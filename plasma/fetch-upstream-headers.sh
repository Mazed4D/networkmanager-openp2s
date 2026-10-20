#!/usr/bin/env bash
set -euo pipefail

version="$1"
out="$2"
base="https://invent.kde.org/plasma/plasma-nm/-/raw/v${version}"
mkdir -p "$out"
curl -fsSL -o "$out/vpnuiplugin.h" "$base/libs/editor/vpnuiplugin.h"
curl -fsSL -o "$out/settingwidget.h" "$base/libs/editor/widgets/settingwidget.h"
