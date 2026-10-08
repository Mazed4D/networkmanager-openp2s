from __future__ import annotations

import argparse
import getpass
import sys

from . import SERVICE_NAME, __version__, agent
from .entra import AuthError
from .profile import ProfileError, parse, validate_domain


def _nm():
    import gi

    gi.require_version("NM", "1.0")
    from gi.repository import NM

    return NM


def _run_async(start) -> object:
    from gi.repository import GLib

    loop = GLib.MainLoop()
    outcome: dict = {}

    def done(source, result, finish):
        try:
            outcome["value"] = finish(source, result)
        except GLib.Error as error:
            outcome["error"] = error
        loop.quit()

    start(done)
    loop.run()
    if "error" in outcome:
        raise RuntimeError(outcome["error"].message)
    return outcome.get("value")


def build_connection(profile, *, name: str, user: str, dns_domains: list[str], dns_all: bool):
    NM = _nm()
    connection = NM.SimpleConnection.new()

    s_con = NM.SettingConnection.new()
    s_con.set_property(NM.SETTING_CONNECTION_ID, name)
    s_con.set_property(NM.SETTING_CONNECTION_UUID, NM.utils_uuid_generate())
    s_con.set_property(NM.SETTING_CONNECTION_TYPE, NM.SETTING_VPN_SETTING_NAME)
    s_con.set_property(NM.SETTING_CONNECTION_AUTOCONNECT, False)
    s_con.add_permission("user", user, None)
    connection.add_setting(s_con)

    s_vpn = NM.SettingVpn.new()
    s_vpn.set_property(NM.SETTING_VPN_SERVICE_TYPE, SERVICE_NAME)
    s_vpn.set_property(NM.SETTING_VPN_TIMEOUT, 300)
    data = {
        "gateways": ",".join(profile.gateways),
        "port": str(profile.port),
        "authority": profile.authority,
        "client-id": profile.client_id,
        "scope": profile.scope,
        "user": user,
    }
    if profile.dns_servers:
        data["dns-servers"] = ",".join(profile.dns_servers)
    if profile.dns_domains:
        data["dns-domains"] = ",".join(profile.dns_domains)
    for key, value in data.items():
        s_vpn.add_data_item(key, value)
    s_vpn.add_secret("tls-auth", profile.server_secret)
    s_vpn.set_secret_flags("tls-auth", NM.SettingSecretFlags.NONE)
    connection.add_setting(s_vpn)

    s_ip4 = NM.SettingIP4Config.new()
    s_ip4.set_property(NM.SETTING_IP_CONFIG_METHOD, NM.SETTING_IP4_CONFIG_METHOD_AUTO)
    s_ip4.set_property(NM.SETTING_IP_CONFIG_NEVER_DEFAULT, True)
    if dns_all:
        s_ip4.add_dns_search("~.")
        s_ip4.set_property(NM.SETTING_IP_CONFIG_DNS_PRIORITY, -50)
    for domain in dns_domains:
        s_ip4.add_dns_search(f"~{domain}")
    connection.add_setting(s_ip4)

    s_ip6 = NM.SettingIP6Config.new()
    s_ip6.set_property(NM.SETTING_IP_CONFIG_METHOD, NM.SETTING_IP6_CONFIG_METHOD_IGNORE)
    connection.add_setting(s_ip6)

    connection.verify()
    return connection


def cmd_import(args: argparse.Namespace) -> int:
    try:
        with open(args.profile, "rb") as handle:
            profile = parse(handle.read())
        dns_domains = [validate_domain(d) for d in args.dns_domain]
    except (OSError, ProfileError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    NM = _nm()
    client = NM.Client.new(None)
    name = args.name or profile.name
    existing = [c for c in client.get_connections() if c.get_id() == name]
    if existing and not args.replace:
        print(f"error: a connection named {name!r} already exists (use --replace)", file=sys.stderr)
        return 1

    connection = build_connection(profile, name=name, user=args.user, dns_domains=dns_domains, dns_all=args.dns_all)
    for old in existing:
        _run_async(lambda cb, c=old: c.delete_async(None, cb, NM.RemoteConnection.delete_finish))
    _run_async(lambda cb: client.add_connection_async(connection, True, None, cb, NM.Client.add_connection_finish))

    print(f"Added VPN connection {name!r}.")
    print("It is now listed in the Plasma network applet and in System Settings.")
    if profile.dns_servers and not (profile.dns_domains or dns_domains or args.dns_all):
        print(
            "\nnote: the profile has DNS servers but no DNS domains, so no names are resolved through\n"
            "the VPN. Re-import with --dns-domain <suffix> (repeatable) or --dns-all if internal\n"
            "names do not resolve.",
        )
    return 0


def _client_for(name: str) -> dict:
    NM = _nm()
    client = NM.Client.new(None)
    for connection in client.get_connections():
        s_vpn = connection.get_setting_vpn()
        if connection.get_id() == name and s_vpn and s_vpn.get_service_type() == SERVICE_NAME:
            return {
                "authority": s_vpn.get_data_item("authority"),
                "client_id": s_vpn.get_data_item("client-id"),
                "scope": s_vpn.get_data_item("scope"),
            }
    raise SystemExit(f"error: no nm-openp2s connection named {name!r}")


def cmd_login(args: argparse.Namespace) -> int:
    try:
        response = agent.request({"op": "token", **_client_for(args.connection), "force_refresh": True})
    except AuthError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if not response.get("ok"):
        print(f"error: {response.get('error')}", file=sys.stderr)
        return 1
    print(f"Signed in as {response.get('account') or 'unknown account'}.")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    payload = {"op": "forget", **(_client_for(args.connection) if args.connection else {})}
    try:
        response = agent.request(payload)
    except AuthError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if not response.get("ok"):
        print(f"error: {response.get('error')}", file=sys.stderr)
        return 1
    print("Signed out; the next connection will open the browser.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nm-openp2s", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import", help="add an Azure P2S profile to NetworkManager")
    p.add_argument("profile", help="azurevpnconfig.xml")
    p.add_argument("--name", help="connection name (default: the profile name)")
    p.add_argument("--user", default=getpass.getuser(), help="whose sign-in to use (default: you)")
    p.add_argument("--dns-domain", action="append", default=[], metavar="SUFFIX",
                   help="resolve names under SUFFIX through the VPN (repeatable)")
    p.add_argument("--dns-all", action="store_true", help="resolve every name through the VPN while connected")
    p.add_argument("--replace", action="store_true", help="replace an existing connection with the same name")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("login", help="sign in now, without connecting")
    p.add_argument("connection", help="connection name")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="forget the stored sign-in")
    p.add_argument("connection", nargs="?", help="connection name (default: all)")
    p.set_defaults(func=cmd_logout)

    args = parser.parse_args(argv)
    return args.func(args)
