#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="${1:-$root/dist}"

source "$root/packaging/PKGBUILD"
openvpn_sha256="${sha256sums[0]}"
version="${pkgver}-${pkgrel}"
package="${pkgname}_${version}_amd64"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stage="$work/$package"
lib="$stage/usr/lib/nm-openp2s"

curl -fsSL -o "$work/openvpn" "https://github.com/wyruweso/openp2s/releases/download/v${_openp2s}/openvpn-openp2s"
curl -fsSL -o "$work/BUILDINFO" "https://github.com/wyruweso/openp2s/releases/download/v${_openp2s}/BUILDINFO"
echo "$openvpn_sha256  $work/openvpn" | sha256sum --check --quiet

cd "$root"
install -Dm0644 -t "$lib/nm_openp2s" nm_openp2s/*.py
install -Dm0755 -t "$lib/bin" bin/nm-openp2s bin/nm-openp2s-agent bin/nm-openp2s-helper bin/nm-openp2s-service
install -Dm0755 "$work/openvpn" "$lib/openvpn"
install -Dm0644 "$work/BUILDINFO" "$lib/openvpn.BUILDINFO"
install -dm0755 "$stage/usr/bin"
ln -s /usr/lib/nm-openp2s/bin/nm-openp2s "$stage/usr/bin/nm-openp2s"
install -Dm0644 data/nm-openp2s-service.name "$stage/usr/lib/NetworkManager/VPN/nm-openp2s-service.name"
install -Dm0644 data/nm-openp2s-service.conf "$stage/usr/share/dbus-1/system.d/nm-openp2s-service.conf"
install -Dm0644 -t "$stage/usr/lib/systemd/user" data/nm-openp2s-agent.socket data/nm-openp2s-agent.service
install -Dm0644 LICENSE "$stage/usr/share/doc/$pkgname/copyright"
install -Dm0644 README.md "$stage/usr/share/doc/$pkgname/README.md"

install -dm0755 "$stage/DEBIAN"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: $pkgname
Version: $version
Architecture: amd64
Maintainer: Milan Paunović <70447612+Mazed4D@users.noreply.github.com>
Section: net
Priority: optional
Homepage: https://github.com/Mazed4D/networkmanager-openp2s
Depends: network-manager, python3, python3-dbus, python3-gi, gir1.2-nm-1.0, gir1.2-secret-1, libsecret-1-0, ca-certificates, xdg-utils, libc6 (>= 2.38), libssl3t64 | libssl3, libcap-ng0
Installed-Size: $(du -sk "$stage/usr" | cut -f1)
Description: $pkgdesc
 Adds an Azure Point-to-Site VPN type to NetworkManager that signs in with
 Microsoft Entra ID in the browser, so the VPN can be managed from the
 desktop network settings. Ships the OpenP2S build of OpenVPN.
CONTROL

cat > "$stage/DEBIAN/postinst" <<'SCRIPT'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  systemctl --global enable nm-openp2s-agent.socket >/dev/null 2>&1 || true
  systemctl reload dbus.service >/dev/null 2>&1 || true
fi
SCRIPT

cat > "$stage/DEBIAN/prerm" <<'SCRIPT'
#!/bin/sh
set -e
if [ "$1" = remove ]; then
  systemctl --global disable nm-openp2s-agent.socket >/dev/null 2>&1 || true
fi
find /usr/lib/nm-openp2s -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
SCRIPT
chmod 0755 "$stage/DEBIAN/postinst" "$stage/DEBIAN/prerm"

mkdir -p "$out"
dpkg-deb --root-owner-group -Zxz --build "$stage" "$out/$package.deb"
echo "$out/$package.deb"
