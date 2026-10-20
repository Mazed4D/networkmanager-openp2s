# networkmanager-openp2s

A NetworkManager VPN plugin for Azure Point-to-Site VPNs that use Microsoft
Entra ID sign-in. Connections show up in the Plasma network applet and System
Settings and connect with one click, like any other VPN.

It runs the OpenVPN build shipped by [OpenP2S](https://github.com/wyruweso/openp2s)
(stock OpenVPN truncates the Entra token) and follows OpenP2S's approach: the
token goes to OpenVPN over a private management socket, never to disk.

## How it works

| Part | Runs as | Job |
| --- | --- | --- |
| `nm-openp2s-service` | root, started by NetworkManager | runs OpenVPN, reports IP/routes/DNS to NetworkManager |
| `nm-openp2s-helper` | root, OpenVPN `route-up` hook | forwards the pushed config to the service |
| `nm-openp2s-agent` | you, socket-activated user service | Entra sign-in in your browser (PKCE); refresh token kept in KWallet |
| `nm-openp2s` | you | `import` a profile, `login`, `logout` |
| `plasmanetworkmanagement_openp2sui` | you, inside Plasma | lets the Plasma applet and System Settings connect, edit and import this VPN type |

NetworkManager applies addresses, routes and DNS itself, so there is no sudo
prompt and DNS is handled by systemd-resolved through NetworkManager.

## Install

Packages for Arch Linux (and derivatives), Debian 13 and Ubuntu 24.04+ are on
the [releases page](https://github.com/Mazed4D/networkmanager-openp2s/releases).
`networkmanager-openp2s` is the VPN itself; on KDE Plasma 6 also install
`plasma-nm-openp2s`, without which Plasma refuses to connect this VPN type.
See **[docs/INSTALL.md](docs/INSTALL.md)** for the full guide. In short:

```sh
sudo pacman -U ./networkmanager-openp2s-*.pkg.tar.zst ./plasma-nm-openp2s-*.pkg.tar.zst
systemctl --user start nm-openp2s-agent.socket          # once; later logins start it automatically
nm-openp2s import ~/Downloads/azurevpnconfig.xml        # or System Settings → Import VPN Connection…
```

Options for `import`:

- `--dns-domain SUFFIX` (repeatable): resolve names under SUFFIX through the VPN.
- `--dns-all`: resolve every name through the VPN while connected.
- `--name NAME`, `--replace`.

Then connect from the network applet. The first connection opens a browser
sign-in; later ones are silent until the session expires.

## Private hostnames do not resolve

Many Azure profiles list a DNS server but no DNS suffixes. NetworkManager only
hands a VPN's DNS server to systemd-resolved for the VPN's domains, so with
none the server is never used: the tunnel and routes work, but private names
(Private Link, internal hosts) resolve through your normal DNS, or not at all.
`resolvectl status tun0` then shows no DNS server on the link.

Tell NetworkManager which names belong to the VPN, either when importing:

```sh
nm-openp2s import --replace --dns-domain corp.example --dns-domain privatelink.database.windows.net azurevpnconfig.xml
nm-openp2s import --replace --dns-all azurevpnconfig.xml   # every name, while connected
```

or on an existing connection:

```sh
nmcli connection modify "<connection name>" ipv4.dns-search "~corp.example,~privatelink.database.windows.net"
nmcli connection modify "<connection name>" ipv4.dns-search "~." ipv4.dns-priority -50   # every name
```

Reconnect afterwards. `--dns-all` sends all lookups to the VPN's resolver while
connected, so only use it if that resolver also answers public names.

## Troubleshooting

```sh
journalctl -b -u NetworkManager | grep -E 'openp2s|openvpn'   # service + OpenVPN
journalctl --user -u nm-openp2s-agent                         # sign-in
nm-openp2s login "<connection name>"                          # test sign-in alone
nm-openp2s logout                                             # forget the stored sign-in
```

## Limitations

- IPv4 only; TCP gateways only (all Azure P2S OpenVPN gateways today).
- The sign-in needs a logged-in desktop session, so the VPN cannot come up
  before login.
- KDE support is for Plasma 6. Plasma 5 (Kubuntu 24.04) can use the VPN with
  `nmcli`, but its network applet will not connect it.

## Development

`python -m unittest discover -s tests`. The service can run unprivileged on the
session bus against `dev null` (`--session-bus --dev null`) for end-to-end
testing against a real gateway without creating a tunnel.

The Plasma plugin in `plasma/` builds with CMake against the installed
plasma-nm (`cmake -S plasma -B build && cmake --build build && ctest --test-dir build`).
plasma-nm does not install its plugin headers, so `plasma/compat/` declares the
plugin interface itself; `plasma/check-interface.py` verifies those declarations
against a plasma-nm release, and CI runs it against the plasma-nm each package
is built with.

## License

GPL-2.0-only. Not affiliated with Microsoft or with the OpenP2S project.
