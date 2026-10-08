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

NetworkManager applies addresses, routes and DNS itself, so there is no sudo
prompt and DNS is handled by systemd-resolved through NetworkManager.

## Install (Arch / CachyOS)

```sh
cd packaging && makepkg -si
systemctl --user start nm-openp2s-agent.socket   # once; later logins start it automatically
nm-openp2s import ~/Downloads/azurevpnconfig.xml
```

Options for `import`:

- `--dns-domain SUFFIX` (repeatable): resolve names under SUFFIX through the VPN.
- `--dns-all`: resolve every name through the VPN while connected.
- `--name NAME`, `--replace`.

Then connect from the network applet. The first connection opens a browser
sign-in; later ones are silent until the session expires.

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
- Plasma has no editor page for this VPN type; change settings with
  `nm-openp2s import --replace` or `nmcli connection modify`.

## Development

`python -m unittest discover -s tests`. The service can run unprivileged on the
session bus against `dev null` (`--session-bus --dev null`) for end-to-end
testing against a real gateway without creating a tunnel.

## License

GPL-2.0-only. Not affiliated with Microsoft or with the OpenP2S project.
