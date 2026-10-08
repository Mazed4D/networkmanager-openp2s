from __future__ import annotations

import argparse
import logging
import os
import pwd
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from . import CA_PATH, HELPER_BINARY, OPENVPN_BINARY, SERVICE_NAME, agent
from .helper import HELPER_INTERFACE, PLUGIN_PATH
from .openvpn import ManagementSession, render_config
from .profile import is_ipv4

log = logging.getLogger("nm-openp2s")

PLUGIN_INTERFACE = "org.freedesktop.NetworkManager.VPN.Plugin"
ERROR_PREFIX = "org.freedesktop.NetworkManager.VPN.Error"
RUNTIME_ROOT = "/run/nm-openp2s"

STATE_INIT, STATE_SHUTDOWN, STATE_STARTING, STATE_STARTED, STATE_STOPPING, STATE_STOPPED = 1, 2, 3, 4, 5, 6
FAILURE_LOGIN, FAILURE_CONNECT, FAILURE_BAD_IP_CONFIG = 0, 1, 2

IDLE_QUIT_SECONDS = 20
STOP_GRACE_SECONDS = 5


class VpnError(dbus.DBusException):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message, name=f"{ERROR_PREFIX}.{kind}")


def ip4_to_u32(address: str) -> dbus.UInt32:
    return dbus.UInt32(struct.unpack("=I", socket.inet_aton(address))[0])


def netmask_to_prefix(netmask: str) -> int:
    value = struct.unpack("!I", socket.inet_aton(netmask))[0]
    prefix = bin(value).count("1")
    if value != ((0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF):
        raise ValueError(f"non-contiguous netmask {netmask}")
    return prefix


def build_ip_config(env: dict[str, str], dns_servers: list[str], dns_domains: list[str]) -> tuple[dict, dict]:
    dev = env.get("dev")
    local = env.get("ifconfig_local")
    if not dev or not local or not is_ipv4(local):
        raise ValueError("OpenVPN did not report a tunnel device and IPv4 address")

    config = {
        "tundev": dbus.String(dev),
        "has-ip4": dbus.Boolean(True),
        "has-ip6": dbus.Boolean(False),
    }
    if is_ipv4(env.get("trusted_ip", "")):
        config["gateway"] = ip4_to_u32(env["trusted_ip"])
    if env.get("tun_mtu", "").isdigit():
        config["mtu"] = dbus.UInt32(int(env["tun_mtu"]))

    netmask = env.get("ifconfig_netmask")
    ip4 = {
        "address": ip4_to_u32(local),
        "prefix": dbus.UInt32(netmask_to_prefix(netmask) if netmask else 32),
        "never-default": dbus.Boolean(env.get("redirect_gateway", "0") in ("", "0")),
    }
    vpn_gateway = env.get("route_vpn_gateway", "")
    if is_ipv4(vpn_gateway):
        ip4["internal-gateway"] = ip4_to_u32(vpn_gateway)
    elif env.get("ifconfig_remote") and is_ipv4(env["ifconfig_remote"]):
        ip4["ptp"] = ip4_to_u32(env["ifconfig_remote"])

    routes = []
    index = 1
    while f"route_network_{index}" in env:
        network = env[f"route_network_{index}"]
        mask = env.get(f"route_netmask_{index}", "255.255.255.255")
        gateway = env.get(f"route_gateway_{index}", vpn_gateway)
        metric = env.get(f"route_metric_{index}", "0")
        if is_ipv4(network) and is_ipv4(mask):
            routes.append(
                dbus.Array(
                    [
                        ip4_to_u32(network),
                        dbus.UInt32(netmask_to_prefix(mask)),
                        ip4_to_u32(gateway) if is_ipv4(gateway) else dbus.UInt32(0),
                        dbus.UInt32(int(metric) if metric.isdigit() else 0),
                    ],
                    signature="u",
                )
            )
        index += 1
    if routes:
        ip4["routes"] = dbus.Array(routes, signature="au")

    servers, domains = list(dns_servers), list(dns_domains)
    index = 1
    while f"foreign_option_{index}" in env:
        parts = env[f"foreign_option_{index}"].split()
        if len(parts) == 3 and parts[0] == "dhcp-option":
            if parts[1] == "DNS" and is_ipv4(parts[2]):
                servers.append(parts[2])
            elif parts[1] in ("DOMAIN", "DOMAIN-SEARCH"):
                domains.append(parts[2])
        index += 1
    servers = list(dict.fromkeys(servers))
    domains = list(dict.fromkeys(domains))
    if servers:
        ip4["dns"] = dbus.Array([ip4_to_u32(s) for s in servers], signature="u")
    if domains:
        ip4["domains"] = dbus.Array([dbus.String(d) for d in domains], signature="s")

    return config, ip4


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").replace(";", ",").split(",") if part.strip()]


class Plugin(dbus.service.Object):
    def __init__(self, bus: dbus.Bus, bus_name: str, loop: GLib.MainLoop, options: argparse.Namespace) -> None:
        self._bus_name = dbus.service.BusName(bus_name, bus, do_not_queue=True)
        super().__init__(bus, PLUGIN_PATH)
        self.bus_name = bus_name
        self.loop = loop
        self.options = options
        self.state = STATE_INIT
        self.process: subprocess.Popen | None = None
        self.session: ManagementSession | None = None
        self.runtime_dir: str | None = None
        self.dns_servers: list[str] = []
        self.dns_domains: list[str] = []
        self.failure: int | None = None
        self.auth_failures = 0
        self._idle_quit = GLib.timeout_add_seconds(IDLE_QUIT_SECONDS, self._quit_if_idle)


    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sa{sv}}", out_signature="")
    def Connect(self, connection):
        self._start(connection)

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sa{sv}}a{sv}", out_signature="")
    def ConnectInteractive(self, connection, details):
        self._start(connection)

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sa{sv}}", out_signature="s")
    def NeedSecrets(self, settings):
        secrets = settings.get("vpn", {}).get("secrets", {})
        return "" if secrets.get("tls-auth") else "vpn"

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="", out_signature="")
    def Disconnect(self):
        if self.state in (STATE_STOPPING, STATE_STOPPED):
            raise VpnError("AlreadyStopped", "already stopped")
        self._stop()

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sv}", out_signature="")
    def SetConfig(self, config):
        self.Config(config)

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sv}", out_signature="")
    def SetIp4Config(self, config):
        self.Ip4Config(config)

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sv}", out_signature="")
    def SetIp6Config(self, config):
        self.Ip6Config(config)

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="s", out_signature="")
    def SetFailure(self, reason):
        log.error("failure reported: %s", reason)
        self._fail(FAILURE_BAD_IP_CONFIG)

    @dbus.service.method(PLUGIN_INTERFACE, in_signature="a{sa{sv}}", out_signature="")
    def NewSecrets(self, connection):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="u")
    def StateChanged(self, state):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="sas")
    def SecretsRequired(self, message, secrets):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="a{sv}")
    def Config(self, config):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="a{sv}")
    def Ip4Config(self, config):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="a{sv}")
    def Ip6Config(self, config):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="s")
    def LoginBanner(self, banner):
        pass

    @dbus.service.signal(PLUGIN_INTERFACE, signature="u")
    def Failure(self, reason):
        pass

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        if interface == PLUGIN_INTERFACE and name == "State":
            return dbus.UInt32(self.state)
        raise dbus.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return {"State": dbus.UInt32(self.state)} if interface == PLUGIN_INTERFACE else {}


    @dbus.service.method(HELPER_INTERFACE, in_signature="a{ss}", out_signature="", sender_keyword="sender")
    def RouteUp(self, env, sender=None):
        if not self._sender_is_trusted(sender):
            raise dbus.DBusException("not allowed", name="org.freedesktop.DBus.Error.AccessDenied")
        try:
            config, ip4 = build_ip_config({str(k): str(v) for k, v in env.items()}, self.dns_servers, self.dns_domains)
        except ValueError as error:
            log.error("bad tunnel configuration: %s", error)
            self._fail(FAILURE_BAD_IP_CONFIG)
            return
        log.info("tunnel up on %s, %d routes", config["tundev"], len(ip4.get("routes", [])))
        self.Config(dbus.Dictionary(config, signature="sv"))
        self.Ip4Config(dbus.Dictionary(ip4, signature="sv"))
        self._set_state(STATE_STARTED)

    def _sender_is_trusted(self, sender: str | None) -> bool:
        if self.options.session_bus:
            return True
        try:
            uid = dbus.Interface(
                self.connection.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"),
                "org.freedesktop.DBus",
            ).GetConnectionUnixUser(sender)
        except dbus.DBusException:
            return False
        return int(uid) == 0


    def _set_state(self, state: int) -> None:
        if state != self.state:
            self.state = state
            self.StateChanged(dbus.UInt32(state))

    def _quit_if_idle(self) -> bool:
        if self.state in (STATE_INIT, STATE_STOPPED):
            log.info("no active connection, exiting")
            self.loop.quit()
        self._idle_quit = 0
        return False

    def _start(self, connection) -> None:
        if self.state in (STATE_STARTING, STATE_STARTED):
            raise VpnError("AlreadyStarted", "already connected")
        if self._idle_quit:
            GLib.source_remove(self._idle_quit)
            self._idle_quit = 0

        vpn = connection.get("vpn", {})
        data = {str(k): str(v) for k, v in vpn.get("data", {}).items()}
        secrets = {str(k): str(v) for k, v in vpn.get("secrets", {}).items()}
        conn = connection.get("connection", {})

        gateways = _split(data.get("gateways"))
        authority, client_id, scope = data.get("authority"), data.get("client-id"), data.get("scope")
        tls_auth = secrets.get("tls-auth")
        if not gateways or not authority or not client_id or not scope:
            raise VpnError("BadArguments", "connection is missing gateways, authority, client-id or scope")
        if not tls_auth:
            raise VpnError("BadArguments", "connection is missing the tls-auth secret")
        uid = self._activating_uid(data, conn)

        self.dns_servers = [s for s in _split(data.get("dns-servers")) if is_ipv4(s)]
        self.dns_domains = _split(data.get("dns-domains"))
        self.client = {"authority": authority, "client_id": client_id, "scope": scope}
        self.uid = uid

        name = str(conn.get("uuid", os.getpid()))
        self.runtime_dir = os.path.join(self.options.runtime_root, name)
        os.makedirs(self.options.runtime_root, mode=0o700, exist_ok=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        os.mkdir(self.runtime_dir, 0o700)
        socket_path = os.path.join(self.runtime_dir, "mgmt.sock")
        config_path = os.path.join(self.runtime_dir, "openvpn.conf")

        helper = [*self.options.helper, "--bus-name", self.bus_name]
        if self.options.session_bus:
            helper.append("--session-bus")
        try:
            config = render_config(
                gateways=gateways,
                port=int(data.get("port", "443")),
                server_secret=tls_auth,
                ca_path=data.get("ca", self.options.ca),
                management_socket=socket_path,
                helper_command=helper,
                dev=self.options.dev,
                verify_name=data.get("verify-name") or None,
            )
        except ValueError as error:
            raise VpnError("BadArguments", str(error)) from None
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(config)

        try:
            self.session = ManagementSession(
                socket_path,
                get_token=self._get_token,
                on_auth_failed=lambda: GLib.idle_add(self._on_auth_failed),
                on_error=lambda message: GLib.idle_add(self._on_mgmt_error, message),
            )
        except OSError as error:
            self._cleanup()
            raise VpnError("LaunchFailed", f"could not create the management socket {socket_path}: {error}") from None
        threading.Thread(target=self.session.run, daemon=True).start()

        log.info("starting OpenVPN for %s", conn.get("id", name))
        try:
            self.process = subprocess.Popen(
                [self.options.openvpn, "--config", config_path],
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            self._cleanup()
            raise VpnError("LaunchFailed", f"could not start {self.options.openvpn}: {error}") from None
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self.process.pid, self._on_exit)
        self._set_state(STATE_STARTING)

    def _activating_uid(self, data: dict[str, str], conn) -> int:
        user = data.get("user")
        if not user:
            permitted = [str(p).split(":")[1] for p in conn.get("permissions", []) if str(p).startswith("user:")]
            user = permitted[0] if len(permitted) == 1 else None
        if self.options.session_bus and not user:
            return os.getuid()
        if not user:
            raise VpnError("BadArguments", "connection names no user to sign in as (vpn.data user=...)")
        try:
            return pwd.getpwnam(user).pw_uid
        except KeyError:
            raise VpnError("BadArguments", f"unknown user {user!r}") from None

    def _get_token(self, force_refresh: bool) -> str:
        uid = None if self.options.session_bus else self.uid
        response = agent.request({"op": "token", **self.client, "force_refresh": force_refresh}, uid=uid)
        if not response.get("ok"):
            raise RuntimeError(f"sign-in failed: {response.get('error')}")
        log.info("got an access token for %s", response.get("account") or "the user")
        return response["token"]

    def _on_auth_failed(self) -> bool:
        self.auth_failures += 1
        if self.auth_failures == 1 and self.session:
            self.session.mark_failed()
        else:
            self._fail(FAILURE_LOGIN)
        return False

    def _on_mgmt_error(self, message: str) -> bool:
        log.error("%s", message)
        self._fail(FAILURE_LOGIN if "sign-in" in message else FAILURE_CONNECT)
        return False

    def _fail(self, reason: int) -> None:
        if self.failure is None and self.state not in (STATE_STOPPING, STATE_STOPPED):
            self.failure = reason
            self.Failure(dbus.UInt32(reason))
        self._stop()

    def _stop(self) -> None:
        if self.state in (STATE_STOPPING, STATE_STOPPED):
            return
        self._set_state(STATE_STOPPING)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            pid = self.process.pid
            GLib.timeout_add_seconds(STOP_GRACE_SECONDS, self._kill_if_running, pid)
        else:
            self._finish()

    def _kill_if_running(self, pid: int) -> bool:
        if self.process and self.process.pid == pid and self.process.poll() is None:
            log.warning("OpenVPN did not stop, killing it")
            self.process.kill()
        return False

    def _on_exit(self, pid: int, status: int) -> None:
        code = os.waitstatus_to_exitcode(status)
        if self.state not in (STATE_STOPPING, STATE_STOPPED):
            log.error("OpenVPN exited unexpectedly (%s)", code)
            self.failure = self.failure if self.failure is not None else FAILURE_CONNECT
            self.Failure(dbus.UInt32(self.failure))
        self._finish()

    def _finish(self) -> None:
        self._cleanup()
        self._set_state(STATE_STOPPED)
        GLib.timeout_add_seconds(1, self._quit)

    def _quit(self) -> bool:
        self.loop.quit()
        return False

    def _cleanup(self) -> None:
        if self.session:
            self.session.close()
            self.session = None
        if self.runtime_dir:
            shutil.rmtree(self.runtime_dir, ignore_errors=True)
            self.runtime_dir = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nm-openp2s-service")
    parser.add_argument("--bus-name", default=SERVICE_NAME)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--session-bus", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dev", default="tun", help=argparse.SUPPRESS)
    parser.add_argument("--runtime-root", default=RUNTIME_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--openvpn", default=os.environ.get("NM_OPENP2S_OPENVPN", OPENVPN_BINARY), help=argparse.SUPPRESS)
    parser.add_argument("--ca", default=CA_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--helper", nargs="+", default=[HELPER_BINARY], help=argparse.SUPPRESS)
    options = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if options.debug else logging.INFO,
        format="nm-openp2s[%(process)d]: %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    if not options.bus_name.startswith(SERVICE_NAME):
        parser.error(f"--bus-name must start with {SERVICE_NAME}")

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus() if options.session_bus else dbus.SystemBus()
    loop = GLib.MainLoop()
    try:
        plugin = Plugin(bus, options.bus_name, loop, options)
    except dbus.DBusException as error:
        log.error("could not claim %s: %s", options.bus_name, error)
        return 1

    def on_signal() -> bool:
        if plugin.state in (STATE_STARTING, STATE_STARTED):
            plugin._stop()
            GLib.timeout_add_seconds(STOP_GRACE_SECONDS + 1, plugin._quit)
        else:
            loop.quit()
        return True

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, on_signal)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, on_signal)
    loop.run()
    plugin._cleanup()
    return 0
