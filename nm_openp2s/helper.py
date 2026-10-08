from __future__ import annotations

import argparse
import os
import re
import sys

from . import SERVICE_NAME

HELPER_INTERFACE = f"{SERVICE_NAME}.Helper"
PLUGIN_PATH = "/org/freedesktop/NetworkManager/VPN/Plugin"

_WANTED = re.compile(
    r"^(dev|tun_mtu|trusted_ip6?|ifconfig_(local|netmask|remote)|route_vpn_gateway"
    r"|route_(network|netmask|gateway|metric)_\d+|foreign_option_\d+|redirect_gateway|script_type)$"
)


def collect(environ: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in environ.items() if _WANTED.match(k)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nm-openp2s-helper")
    parser.add_argument("--bus-name", default=SERVICE_NAME)
    parser.add_argument("--session-bus", action="store_true", help=argparse.SUPPRESS)
    args, _ = parser.parse_known_args(argv)

    import dbus

    if args.session_bus:
        bus = dbus.bus.BusConnection(f"unix:path=/run/user/{os.getuid()}/bus")
    else:
        bus = dbus.SystemBus()
    try:
        proxy = bus.get_object(args.bus_name, PLUGIN_PATH, introspect=False)
        proxy.RouteUp(dbus.Dictionary(collect(dict(os.environ)), signature="ss"), dbus_interface=HELPER_INTERFACE)
    except dbus.DBusException as error:
        print(f"nm-openp2s-helper: could not report to {args.bus_name}: {error}", file=sys.stderr)
        return 1
    return 0
