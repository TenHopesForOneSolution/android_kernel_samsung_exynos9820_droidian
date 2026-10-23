#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo"
work=${S10E_BUILD_ROOT:-$repo/.build/droidian}
cache=${S10E_DOWNLOAD_CACHE:-$repo/.cache/droidian}
dist=${S10E_DIST_DIR:-$repo/dist}
jobs=${S10E_JOBS:-$(getconf _NPROCESSORS_ONLN)}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo 'S10E_JOBS must be positive' >&2; exit 1; }
mkdir -p "$work/kernel" "$dist"
work=$(cd "$work" && pwd)
dist=$(cd "$dist" && pwd)
python3 droidian/fetch.py --cache "$cache" --work "$work"

export PATH="$work/toolchain/bin:$PATH"
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
commit=$(git rev-parse HEAD)
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)
export KBUILD_BUILD_USER=s10e KBUILD_BUILD_HOST=droidian-builder
export KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_TIMESTAMP
KBUILD_BUILD_TIMESTAMP=$(date -u -d "@$SOURCE_DATE_EPOCH" '+%a %b %d %T UTC %Y')
# Explicit LOCALVERSION avoids tag/dirty-tree dependent '+' suffixes.
export LOCALVERSION="-g${commit:0:12}"
make_args=(O="$work/kernel" LLVM=1 LLVM_IAS=1 READELF=llvm-readelf)

scripts/kconfig/merge_config.sh -m -O "$work/kernel" \
    arch/arm64/configs/exynos9820-beyond0lte_defconfig \
    droidian/configs/halium.config droidian/configs/droidian.config \
    droidian/configs/beyond0lte.config
make "${make_args[@]}" olddefconfig
for setting in FHANDLE VT VT_CONSOLE DEVTMPFS DEVTMPFS_MOUNT USER_NS EROFS_FS MODULES BLK_DEV_DM CRYPTO_XTS; do
    grep -qx "CONFIG_${setting}=y" "$work/kernel/.config" || { echo "Missing CONFIG_${setting}" >&2; exit 1; }
done
grep -qx 'CONFIG_DM_CRYPT=m' "$work/kernel/.config"
grep -qx '# CONFIG_FRAMEBUFFER_CONSOLE is not set' "$work/kernel/.config"
make "${make_args[@]}" -j"$jobs" Image dtbs modules

patch_file="$repo/droidian/patches/v4l2loopback-capture-clients.patch"
if patch -d "$work/v4l2loopback" -p1 --dry-run --batch --forward < "$patch_file" >/dev/null 2>&1; then
    patch -d "$work/v4l2loopback" -p1 --batch --forward < "$patch_file"
else
    patch -d "$work/v4l2loopback" -p1 --dry-run --batch --reverse < "$patch_file"
fi
make "${make_args[@]}" M="$work/v4l2loopback" -j"$jobs" modules

staging="$work/module-staging"
mkdir -p "$staging"
release=$(cat "$work/kernel/include/config/kernel.release")
make "${make_args[@]}" INSTALL_MOD_PATH="$staging" DEPMOD=/bin/true modules_install
install -D -m 644 "$work/v4l2loopback/v4l2loopback.ko" \
    "$staging/lib/modules/$release/extra/v4l2loopback.ko"
rm -f "$staging/lib/modules/$release/build" "$staging/lib/modules/$release/source"
test -s "$staging/lib/modules/$release/kernel/drivers/md/dm-crypt.ko"
for module in "$staging/lib/modules/$release/kernel/drivers/md/dm-crypt.ko" \
              "$staging/lib/modules/$release/extra/v4l2loopback.ko"; do
    llvm-readelf -p .modinfo "$module" | grep -F "vermagic=$release "
done

install -m 644 "$work/kernel/arch/arm64/boot/Image" "$dist/Image"
install -m 644 "$work/kernel/.config" "$dist/kernel.config"
install -m 644 "$work/kernel/Module.symvers" "$dist/Module.symvers"
install -m 644 droidian/sources.lock.json "$dist/sources.lock.json"
tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
    -C "$staging" -cf - "lib/modules/$release" | gzip -n > "$dist/modules.tar.gz"
(
    cd "$work/kernel/arch/arm64/boot/dts"
    find . -type f \( -name '*.dtb' -o -name '*.dtbo' \) -print0 | LC_ALL=C sort -z > "$work/dtbs.list"
    test -s "$work/dtbs.list"
    tar --null -T "$work/dtbs.list" --mtime="@$SOURCE_DATE_EPOCH" \
        --owner=0 --group=0 --numeric-owner -cf - | gzip -n > "$dist/dtbs.tar.gz"
)
python3 droidian/verify-build.py --work "$work" --dist "$dist"
printf 'Kernel bundle ready: %s (%s)\n' "$dist" "$release"
