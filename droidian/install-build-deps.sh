#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Run inside the pinned Droidian builder container, before build.sh.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ $(id -u) == 0 ]] || { echo 'Run this inside the builder container as root' >&2; exit 1; }
mapfile -t packages < <(python3 - "$repo/droidian/sources.lock.json" <<'PY'
import json, sys
for name, version in json.load(open(sys.argv[1]))['build_packages'].items():
    print(name + '=' + version)
PY
)
[[ ${#packages[@]} -gt 0 ]]
apt-get update
apt-get install -y --no-install-recommends "${packages[@]}"
