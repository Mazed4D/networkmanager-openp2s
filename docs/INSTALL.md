# Installing networkmanager-openp2s

## Requirements

- x86_64 Linux with NetworkManager.
- A graphical session with a web browser: sign-in happens in the browser on the
  same machine.
- An Azure Point-to-Site VPN profile (`azurevpnconfig.xml`) that uses Microsoft
  Entra ID authentication. In the Azure portal: *VPN gateway → Point-to-site
  configuration → Download VPN client*, then unpack the zip.
- glibc 2.38 or newer, required by the bundled OpenVPN build.

There are two packages:

- **networkmanager-openp2s**: the VPN itself. Required everywhere.
- **plasma-nm-openp2s**: KDE Plasma 6 support. Plasma refuses to connect a VPN
  type it has no plugin for ("Plasma is missing support for 'openp2s' VPN
  connections"), so on Plasma install both. It also adds the settings page and
  lets System Settings import the Azure profile.

| Distribution | VPN | Plasma support | Status |
| --- | --- | --- | --- |
| Arch Linux, CachyOS, EndeavourOS, Manjaro | yes | yes | tested on KDE Plasma 6 |
| Debian 13 (trixie) | yes | yes | installs in CI |
| Ubuntu 26.04 / Kubuntu 26.04 | yes | yes | installs in CI |
| Ubuntu 24.04 / Kubuntu 24.04 | yes | no (Plasma 5) | installs in CI; connect with `nmcli` |
| Debian 12, Ubuntu 22.04 | no | no | glibc too old |

Desktops other than KDE Plasma may list the connection if they use
NetworkManager, but they have not been tested.

## 1. Install the package

Packages are attached to each
[release](https://github.com/Mazed4D/networkmanager-openp2s/releases), along
with a `SHA256SUMS` file.

### Arch Linux and derivatives

```sh
VERSION=0.1.2-1
base=https://github.com/Mazed4D/networkmanager-openp2s/releases/download/v${VERSION%-*}
curl -LO "$base/networkmanager-openp2s-$VERSION-x86_64.pkg.tar.zst" \
     -LO "$base/plasma-nm-openp2s-$VERSION-x86_64.pkg.tar.zst" -LO "$base/SHA256SUMS"
sha256sum --check --ignore-missing SHA256SUMS
sudo pacman -U "./networkmanager-openp2s-$VERSION-x86_64.pkg.tar.zst" "./plasma-nm-openp2s-$VERSION-x86_64.pkg.tar.zst"
```

Leave out the `plasma-nm-openp2s` file if you do not use KDE Plasma.

Or build both from source (builds the Plasma plugin against your installed
plasma-nm):

```sh
git clone https://github.com/Mazed4D/networkmanager-openp2s.git
cd networkmanager-openp2s/packaging
makepkg -si
```

### Debian and Ubuntu

```sh
VERSION=0.1.2-1
base=https://github.com/Mazed4D/networkmanager-openp2s/releases/download/v${VERSION%-*}
curl -LO "$base/networkmanager-openp2s_${VERSION}_amd64.deb" \
     -LO "$base/plasma-nm-openp2s_${VERSION}_amd64.deb" -LO "$base/SHA256SUMS"
sha256sum --check --ignore-missing SHA256SUMS
sudo apt install "./networkmanager-openp2s_${VERSION}_amd64.deb" "./plasma-nm-openp2s_${VERSION}_amd64.deb"
```

Leave out the `plasma-nm-openp2s` file on Ubuntu 24.04 or if you do not use
KDE Plasma.

Or build the packages from a checkout with `packaging/debian/build-deb.sh` and
`packaging/debian/build-plasma-deb.sh`.

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

On KDE Plasma: *System Settings → Wi-Fi & Networking*, click **+** (Add new
connection), choose **Import VPN Connection…**, and pick the
`azurevpnconfig.xml` file.

Or from a terminal:

```sh
nm-openp2s import ~/Downloads/azurevpnconfig.xml
```

The connection is named after the profile; use `--name` to choose another.
It is private to your user. On Plasma you can change the gateway, DNS servers
and DNS domains later on the connection's VPN tab.

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
