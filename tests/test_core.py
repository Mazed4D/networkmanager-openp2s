import os
import socket
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nm_openp2s.openvpn import render_config, static_key
from nm_openp2s.profile import ProfileError, parse
from nm_openp2s.service import build_ip_config, netmask_to_prefix

SECRET = "ab" * 256
TENANT = "11111111-2222-3333-4444-555555555555"
AUDIENCE = "41b23e61-6c1e-4545-b367-cd054e0ed4b4"

PROFILE = f"""<AzVpnProfile><name>hub</name><serverlist><ServerEntry>
<fqdn>azuregateway-x.vpn.azure.com</fqdn></ServerEntry></serverlist>
<clientauth><type>aad</type><aad><issuer>https://sts.windows.net/{TENANT}/</issuer>
<tenant>https://login.microsoftonline.com/{TENANT}</tenant><audience>{AUDIENCE}</audience></aad></clientauth>
<protocolconfig><sslprotocolConfig><transportprotocol>tcp</transportprotocol></sslprotocolConfig></protocolconfig>
<clientconfig><dnsservers><dnsserver>10.10.0.4</dnsserver></dnsservers></clientconfig>
<servervalidation><serversecret>{SECRET}</serversecret></servervalidation></AzVpnProfile>"""


def u32(ip: str) -> int:
    return struct.unpack("=I", socket.inet_aton(ip))[0]


class ProfileTests(unittest.TestCase):
    def test_parses_entra_profile(self):
        p = parse(PROFILE)
        self.assertEqual(p.name, "hub")
        self.assertEqual(p.gateways, ["azuregateway-x.vpn.azure.com"])
        self.assertEqual(p.authority, f"https://login.microsoftonline.com/{TENANT}")
        self.assertEqual(p.client_id, AUDIENCE)
        self.assertEqual(p.scope, f"{AUDIENCE}/.default")
        self.assertEqual(p.dns_servers, ["10.10.0.4"])

    def test_rejects_non_microsoft_authority(self):
        with self.assertRaises(ProfileError):
            parse(PROFILE.replace("login.microsoftonline.com", "evil.example"))

    def test_rejects_certificate_profiles(self):
        with self.assertRaises(ProfileError):
            parse(PROFILE.replace("<type>aad</type>", "<type>cert</type>"))

    def test_rejects_hostile_gateway(self):
        with self.assertRaises(ProfileError):
            parse(PROFILE.replace("azuregateway-x.vpn.azure.com", "x.com\nscript-security 2"))


class ConfigTests(unittest.TestCase):
    def render(self, **overrides):
        options = dict(
            gateways=["gw.vpn.azure.com"], port=443, server_secret=SECRET, ca_path="/etc/ssl/ca.pem",
            management_socket="/run/nm-openp2s/x/mgmt.sock",
            helper_command=["/usr/lib/nm-openp2s/bin/nm-openp2s-helper", "--bus-name", "org.x.Connection_1"],
        )
        options.update(overrides)
        return render_config(**options)

    def test_hands_networking_to_networkmanager(self):
        config = self.render()
        for directive in ("ifconfig-noexec", "route-noexec", "management-client", "auth-nocache", "reneg-sec 0"):
            self.assertIn(f"\n{directive}\n", config)
        self.assertIn("route-up '/usr/lib/nm-openp2s/bin/nm-openp2s-helper --bus-name org.x.Connection_1'", config)

    def test_static_key_layout(self):
        key = static_key(SECRET).splitlines()
        self.assertEqual(len(key), 18)
        self.assertTrue(all(len(line) == 32 for line in key[1:-1]))

    def test_refuses_directive_injection(self):
        with self.assertRaises(ValueError):
            self.render(ca_path="/x\nscript-security 3")
        with self.assertRaises(ValueError):
            self.render(gateways=["gw.example 443\nup /bin/sh"])


class IpConfigTests(unittest.TestCase):
    ENV = {
        "dev": "tun0",
        "tun_mtu": "1500",
        "trusted_ip": "203.0.113.10",
        "ifconfig_local": "10.200.0.11",
        "ifconfig_netmask": "255.255.255.0",
        "route_vpn_gateway": "10.200.0.1",
        "route_network_1": "10.20.0.0",
        "route_netmask_1": "255.255.255.0",
        "route_gateway_1": "10.200.0.1",
        "route_network_2": "10.32.0.0",
        "route_netmask_2": "255.255.248.0",
        "route_gateway_2": "10.200.0.1",
    }

    def test_builds_config(self):
        config, ip4 = build_ip_config(self.ENV, ["10.10.0.4"], [])
        self.assertEqual(config["tundev"], "tun0")
        self.assertEqual(config["gateway"], u32("203.0.113.10"))
        self.assertEqual(ip4["address"], u32("10.200.0.11"))
        self.assertEqual(ip4["prefix"], 24)
        self.assertTrue(ip4["never-default"])
        self.assertEqual(ip4["internal-gateway"], u32("10.200.0.1"))
        self.assertEqual(
            [list(r) for r in ip4["routes"]],
            [[u32("10.20.0.0"), 24, u32("10.200.0.1"), 0], [u32("10.32.0.0"), 21, u32("10.200.0.1"), 0]],
        )
        self.assertEqual(list(ip4["dns"]), [u32("10.10.0.4")])
        self.assertNotIn("domains", ip4)

    def test_merges_pushed_dns(self):
        env = dict(self.ENV, foreign_option_1="dhcp-option DNS 10.0.0.53", foreign_option_2="dhcp-option DOMAIN corp.example")
        _, ip4 = build_ip_config(env, ["10.10.0.4"], ["azure.example"])
        self.assertEqual(list(ip4["dns"]), [u32("10.10.0.4"), u32("10.0.0.53")])
        self.assertEqual(list(ip4["domains"]), ["azure.example", "corp.example"])

    def test_redirect_gateway_allows_default_route(self):
        _, ip4 = build_ip_config(dict(self.ENV, redirect_gateway="1"), [], [])
        self.assertFalse(ip4["never-default"])

    def test_requires_address(self):
        with self.assertRaises(ValueError):
            build_ip_config({"dev": "tun0"}, [], [])

    def test_netmask(self):
        self.assertEqual(netmask_to_prefix("255.255.252.0"), 22)
        with self.assertRaises(ValueError):
            netmask_to_prefix("255.0.255.0")


if __name__ == "__main__":
    unittest.main()
