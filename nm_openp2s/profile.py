from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .entra import ENTRA_LOGIN_HOSTS

_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z0-9-]{1,63}$")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9_-]{1,63}\.)*[a-zA-Z0-9_-]{1,63}$")


class ProfileError(Exception):
    pass


@dataclass
class Profile:
    name: str
    gateways: list[str]
    authority: str
    audience: str
    server_secret: str
    port: int = 443
    dns_servers: list[str] = field(default_factory=list)
    dns_domains: list[str] = field(default_factory=list)

    @property
    def client_id(self) -> str:
        return self.audience

    @property
    def scope(self) -> str:
        return f"{self.audience}/.default"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _find_all(root: ET.Element, *path: str) -> list[ET.Element]:
    nodes = [root]
    for part in path:
        nodes = [child for node in nodes for child in node if _local(child.tag) == part.lower()]
    return nodes


def _text(root: ET.Element, *path: str) -> str | None:
    nodes = _find_all(root, *path)
    if not nodes or nodes[0].text is None:
        return None
    return nodes[0].text.strip()


def is_ipv4(value: str) -> bool:
    match = _IPV4.match(value)
    return bool(match) and all(int(octet) <= 255 for octet in match.groups())


def validate_server_secret(value: str) -> str:
    secret = value.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{512}", secret):
        raise ProfileError("<serversecret> must be exactly 512 hex characters")
    return secret.lower()


def validate_domain(value: str) -> str:
    domain = value.strip().lstrip(".").lower()
    if not _DOMAIN.match(domain):
        raise ProfileError(f"invalid DNS domain: {value!r}")
    return domain


def validate_authority(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in ENTRA_LOGIN_HOSTS:
        raise ProfileError(f"tenant URL is not a Microsoft Entra login host: {value!r}")
    tenant = parsed.path.strip("/").split("/")[0]
    if not _GUID.match(tenant):
        raise ProfileError(f"tenant URL does not name a tenant id: {value!r}")
    return f"https://{parsed.hostname}/{tenant.lower()}"


def parse(xml: str | bytes) -> Profile:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ProfileError(f"not a valid XML profile: {error}") from None

    if _local(root.tag) != "azvpnprofile":
        raise ProfileError("not an Azure VPN Client profile (expected <AzVpnProfile>)")

    auth_type = (_text(root, "clientauth", "type") or "").lower()
    if auth_type != "aad":
        raise ProfileError(f"only Entra ID (aad) profiles are supported, this one is {auth_type or 'unknown'!r}")

    transport = (_text(root, "protocolconfig", "sslprotocolConfig", "transportprotocol") or "tcp").lower()
    if transport != "tcp":
        raise ProfileError(f"unsupported transport {transport!r}; Azure P2S OpenVPN uses tcp")

    gateways = [
        fqdn
        for entry in _find_all(root, "serverlist", "ServerEntry")
        if (fqdn := (_text(entry, "fqdn") or "").lower())
    ]
    if not gateways:
        raise ProfileError("profile has no <serverlist> gateway")
    for gateway in gateways:
        if not _HOSTNAME.match(gateway):
            raise ProfileError(f"invalid gateway hostname: {gateway!r}")

    tenant = _text(root, "clientauth", "aad", "tenant")
    audience = _text(root, "clientauth", "aad", "audience")
    secret = _text(root, "servervalidation", "serversecret")
    if not tenant or not audience or not secret:
        raise ProfileError("profile is missing <tenant>, <audience> or <serversecret>")
    if not _GUID.match(audience):
        raise ProfileError(f"<audience> is not an application id: {audience!r}")

    dns_servers = [node.text.strip() for node in _find_all(root, "clientconfig", "dnsservers", "dnsserver") if node.text]
    for server in dns_servers:
        if not is_ipv4(server):
            raise ProfileError(f"only IPv4 DNS servers are supported: {server!r}")
    dns_domains = [
        validate_domain(node.text)
        for node in _find_all(root, "clientconfig", "dnssuffixes", "dnssuffix")
        if node.text and node.text.strip()
    ]

    name = _text(root, "name") or gateways[0]
    return Profile(
        name=name,
        gateways=gateways,
        authority=validate_authority(tenant),
        audience=audience.lower(),
        server_secret=validate_server_secret(secret),
        dns_servers=dns_servers,
        dns_domains=dns_domains,
    )
