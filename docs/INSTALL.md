# Installing networkmanager-openp2s

## Requirements

- x86_64 Linux with NetworkManager.
- A graphical session with a web browser: sign-in happens in the browser on the
  same machine.
- An Azure Point-to-Site VPN profile (`azurevpnconfig.xml`) that uses Microsoft
  Entra ID authentication. In the Azure portal: *VPN gateway → Point-to-site
  configuration → Download VPN client*, then unpack the zip.
- glibc 2.38 or newer, required by the bundled OpenVPN build.

| Distribution | Package | Status |
| --- | --- | --- |
| Arch Linux, CachyOS, EndeavourOS, Manjaro | `.pkg.tar.zst` | tested on KDE Plasma 6 |
| Debian 13 (trixie) | `.deb` | installs in CI |
| Ubuntu 24.04 and newer | `.deb` | installs in CI |
| Debian 12, Ubuntu 22.04 | — | not supported (glibc too old) |

Desktops other than KDE Plasma should list the connection too if they use
NetworkManager, but they have not been tested.

## 1. Install the package

Packages are attached to each
[release](https://github.com/Mazed4D/networkmanager-openp2s/releases), along
with a `SHA256SUMS` file.

### Arch Linux and derivatives

```sh
VERSION=0.1.1-1
base=https://github.com/Mazed4D/networkmanager-openp2s/releases/download/v${VERSION%-*}
curl -LO "$base/networkmanager-openp2s-$VERSION-x86_64.pkg.tar.zst" -LO "$base/SHA256SUMS"
sha256sum --check --ignore-missing SHA256SUMS
sudo pacman -U "./networkmanager-openp2s-$VERSION-x86_64.pkg.tar.zst"
```

Or build it from source:

```sh
git clone https://github.com/Mazed4D/networkmanager-openp2s.git
cd networkmanager-openp2s/packaging
makepkg -si
```

### Debian and Ubuntu

```sh
VERSION=0.1.1-1
base=https://github.com/Mazed4D/networkmanager-openp2s/releases/download/v${VERSION%-*}
curl -LO "$base/networkmanager-openp2s_${VERSION}_amd64.deb" -LO "$base/SHA256SUMS"
sha256sum --check --ignore-missing SHA256SUMS
sudo apt install "./networkmanager-openp2s_${VERSION}_amd64.deb"
```

Or build the `.deb` from a checkout with `packaging/debian/build-deb.sh`.

Replace `VERSION` with the release you want. The package includes the patched
OpenVPN from [OpenP2S](https://github.com/wyruweso/openp2s), installed as
`/usr/lib/nm-openp2s/openvpn`. Your system's OpenVPN is not touched.

## 2. Start the sign-in agent

The package enables the agent for every new login. For the session you are
already in, start it once:

```sh
systemctl --user start nm-openp2s-agent.socket
```

## 3. Add your VPN profile

```sh
nm-openp2s import ~/Downloads/azurevpnconfig.xml
```

The connection is named after the profile; use `--name` to choose another.
It is private to your user.

If your profile lists a DNS server but no DNS suffixes (`import` prints a note
when it does), private hostnames will not resolve over the VPN until you tell
NetworkManager which names to send there. Add `--dns-domain <suffix>` for each
internal domain, or `--dns-all` to send every lookup through the VPN while
connected. See
[Private hostnames do not resolve](../README.md#private-hostnames-do-not-resolve).

## 4. Connect

Click the connection in the network applet (or *System Settings → Wi-Fi &
Networking*), or run:

```sh
nmcli connection up "<connection name>"
```

The first connection opens a Microsoft sign-in page in your browser. Later
connections reuse the session stored in your keyring (KWallet or GNOME Keyring)
and connect without prompting, until your organisation's policy requires you to
sign in again.

To connect automatically, open your Wi-Fi or wired connection in System
Settings and choose this VPN under *Automatically connect to VPN*. It can only
connect once you are logged in, because sign-in needs your session.

## Updating

Install the newer package the same way. Existing connections and your stored
sign-in are kept.

## Uninstalling

```sh
nm-openp2s logout
nmcli connection delete "<connection name>"
sudo pacman -R networkmanager-openp2s     # Arch
sudo apt remove networkmanager-openp2s    # Debian / Ubuntu
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Connection fails immediately | `journalctl -b -u NetworkManager \| grep -E 'openp2s\|openvpn'` |
| No browser opens / sign-in fails | `journalctl --user -u nm-openp2s-agent`, then `nm-openp2s login "<connection name>"` |
| "sign-in agent is not reachable" | `systemctl --user start nm-openp2s-agent.socket` |
| Connected, but private names do not resolve | `resolvectl status tun0`; see step 3 |
| Wrong account signed in | `nm-openp2s logout`, then connect again |
