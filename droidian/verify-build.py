#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate release components and record the exact source/toolchain identity."""
import argparse
import json
import os
import struct
import subprocess
import tarfile
from pathlib import Path

from fetch import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    kernel = args.work / "kernel"
    dist = args.dist
    image = dist / "Image"
    with image.open("rb") as stream:
        header = stream.read(64)
    if len(header) < 64 or header[56:60] != b"ARM\x64":
        raise RuntimeError("Invalid arm64 Image header")
    image_size = struct.unpack_from("<Q", header, 16)[0]
    if image.stat().st_size >= 55 * 1024 * 1024 or image_size == 0:
        raise RuntimeError("Image cannot fit the S10e boot partition with an initramfs")
    release = (kernel / "include/config/kernel.release").read_text().strip()
    with tarfile.open(dist / "modules.tar.gz") as archive:
        names = archive.getnames()
        for suffix in ("kernel/drivers/md/dm-crypt.ko", "extra/v4l2loopback.ko"):
            member = archive.extractfile("lib/modules/" + release + "/" + suffix)
            if member is None or not member.read(4) == b"\x7fELF":
                raise RuntimeError("Missing/invalid module: " + suffix)
        if any(name.endswith(("/build", "/source")) for name in names):
            raise RuntimeError("Module archive contains build-host symlinks")
    with tarfile.open(dist / "dtbs.tar.gz") as archive:
        trees = [m for m in archive if m.isfile()]
        if not trees:
            raise RuntimeError("No device trees built")
        for member in trees:
            if archive.extractfile(member).read(4) != b"\xd0\x0d\xfe\xed":
                raise RuntimeError("Invalid FDT: " + member.name)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    compiler = subprocess.check_output([str(args.work / "toolchain/bin/clang"), "--version"], text=True).splitlines()[0]
    info = {
        "device": "samsung-beyond0lte",
        "kernel_commit": commit,
        "kernel_release": release,
        "compiler": compiler,
        "source_date_epoch": int(os.environ["SOURCE_DATE_EPOCH"]),
        "config_sha256": digest(dist / "kernel.config"),
        "lock_sha256": digest(dist / "sources.lock.json"),
        "image_bytes": image.stat().st_size,
        "device_tree_count": len(trees),
        "hardware_validation": "pending; CI validation does not boot a physical phone",
    }
    (dist / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    filenames = ["Image", "kernel.config", "Module.symvers", "sources.lock.json", "toolchain-files.json", "modules.tar.gz", "dtbs.tar.gz", "build-info.json"]
    (dist / "SHA256SUMS").write_text("".join(digest(dist / name) + "  " + name + "\n" for name in filenames))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
