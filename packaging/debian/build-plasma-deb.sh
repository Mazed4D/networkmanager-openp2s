#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="${1:-$root/dist}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"

source "$root/packaging/PKGBUILD"
name=plasma-nm-openp2s
version="${pkgver}-${pkgrel}"
package="${name}_${version}_amd64"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stage="$work/$package"

cmake -S "$root/plasma" -B "$work/build" -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build "$work/build"
ctest --test-dir "$work/build" --output-on-failure
DESTDIR="$stage" cmake --install "$work/build"
find "$stage" -name '*.so' -exec strip --strip-unneeded {} +
install -Dm0644 "$root/LICENSE" "$stage/usr/share/doc/$name/copyright"

mkdir -p "$work/shlibs/debian"
printf 'Source: %s\n\nPackage: %s\nArchitecture: amd64\n' "$name" "$name" > "$work/shlibs/debian/control"
plugin="$(find "$stage" -name '*.so' | head -1)"
shlibs="$(cd "$work/shlibs" && dpkg-shlibdeps -O --ignore-missing-info -e "$plugin" 2>/dev/null | sed -n 's/^shlibs:Depends=//p')"
plasma_nm_full="$(dpkg-query -W -f='${Version}' plasma-nm)"
plasma_nm_epoch="$(sed -nE 's/^([0-9]+:).*/\1/p' <<<"$plasma_nm_full")"
plasma_nm_major="$(sed -E 's/^[0-9]+://; s/-[^-]*$//' <<<"$plasma_nm_full" | cut -d. -f1)"

install -dm0755 "$stage/DEBIAN"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: $name
Version: $version
Architecture: amd64
Maintainer: Milan Paunović <70447612+Mazed4D@users.noreply.github.com>
Section: net
Priority: optional
Homepage: https://github.com/Mazed4D/networkmanager-openp2s
Depends: networkmanager-openp2s (= $version), plasma-nm (>= ${plasma_nm_epoch}${plasma_nm_major}), ${shlibs}
Installed-Size: $(du -sk "$stage/usr" | cut -f1)
Description: KDE Plasma support for networkmanager-openp2s VPN connections
 Lets the Plasma network applet and System Settings connect, edit and import
 Azure Point-to-Site VPN connections that sign in with Microsoft Entra ID.
CONTROL

dpkg-deb --root-owner-group -Zxz --build "$stage" "$out/$package.deb"
echo "$out/$package.deb"
