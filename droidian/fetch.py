#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Download and verify pinned build inputs; never uses a phone or credentials."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def verify_archive(item, archive, metadata):
    checksum = digest(archive)
    if "manifest" not in item:
        if checksum != item["sha256"]:
            raise ValueError("Archive checksum mismatch: " + item["name"])
        return
    manifest_path = metadata / item["manifest"]
    if digest(manifest_path) != item["manifest_sha256"]:
        raise ValueError("Toolchain file manifest checksum mismatch")
    # Gitiles regenerates tar mtimes, so archive bytes alone are not stable.
    # The original verified snapshot is a fast path; all other snapshots must
    # contain exactly the same files, bytes, sizes, modes and symlink targets.
    if checksum == item.get("bootstrap_archive_sha256"):
        return
    entries = json.loads(manifest_path.read_text())
    directories = {str(parent) for name in entries for parent in Path(name).parents}
    seen = set()
    with tarfile.open(archive, mode="r|gz") as tar:
        for member in tar:
            if member.isdir():
                if member.name.rstrip("/") not in directories:
                    raise ValueError("Unexpected toolchain directory: " + member.name)
                continue
            expected = entries.get(member.name)
            if expected is None or member.name in seen or member.mode != expected["mode"]:
                raise ValueError("Unexpected toolchain entry: " + member.name)
            seen.add(member.name)
            if expected["type"] == "symlink":
                if not member.issym() or member.linkname != expected["target"]:
                    raise ValueError("Toolchain symlink mismatch: " + member.name)
            else:
                if not member.isfile() or member.size != expected["size"]:
                    raise ValueError("Toolchain file type/size mismatch: " + member.name)
                h = hashlib.sha256()
                with tar.extractfile(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(chunk)
                if h.hexdigest() != expected["sha256"]:
                    raise ValueError("Toolchain file checksum mismatch: " + member.name)
    if seen != set(entries):
        raise ValueError("Toolchain archive is incomplete")


def fetch(item, cache, destination, metadata):
    identity = item.get("manifest_sha256", item.get("sha256"))
    archive = cache / (identity + ".tar.gz")
    valid = False
    if archive.exists():
        try:
            verify_archive(item, archive, metadata)
            valid = True
        except (ValueError, tarfile.TarError):
            print("Cached input failed verification; downloading again", flush=True)
    if not valid:
        partial = archive.with_suffix(".part")
        for attempt in range(3):
            try:
                print("Downloading " + item["name"], flush=True)
                request = urllib.request.Request(item["url"], headers={"User-Agent": "droidian-s10e-builder"})
                with urllib.request.urlopen(request, timeout=120) as source, partial.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                verify_archive(item, partial, metadata)
                partial.replace(archive)
                break
            except Exception as exc:
                print(f"Download attempt {attempt + 1} failed: {exc}", flush=True)
                partial.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
    marker = destination / ".verified-source"
    if marker.exists() and marker.read_text().strip() == identity:
        return
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    # Extraction follows successful archive or complete member verification.
    subprocess.run(["tar", "-xzf", str(archive), "--no-same-owner",
                    "--strip-components=" + str(item["strip_components"]),
                    "-C", str(destination)], check=True)
    marker.write_text(identity + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    metadata = Path(__file__).parent
    lock = json.loads((metadata / "sources.lock.json").read_text())
    for name in ("toolchain", "v4l2loopback"):
        fetch(lock[name], args.cache.resolve(), args.work.resolve() / name, metadata)


if __name__ == "__main__":
    main()
