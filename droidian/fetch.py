#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Download and verify pinned build inputs; never uses a phone or credentials."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def fetch(item, cache, destination):
    archive = cache / (item["sha256"] + ".tar.gz")
    if not archive.exists() or digest(archive) != item["sha256"]:
        partial = archive.with_suffix(".part")
        for attempt in range(3):
            try:
                print("Downloading " + item["name"], flush=True)
                request = urllib.request.Request(item["url"], headers={"User-Agent": "droidian-s10e-builder"})
                with urllib.request.urlopen(request, timeout=120) as source, partial.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                if digest(partial) != item["sha256"]:
                    raise RuntimeError("Checksum mismatch: " + item["name"])
                partial.replace(archive)
                break
            except Exception:
                partial.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
    marker = destination / ".verified-source"
    if marker.exists() and marker.read_text().strip() == item["sha256"]:
        return
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    # Extraction is allowed only after checking the pinned archive digest.
    subprocess.run(["tar", "-xzf", str(archive), "--no-same-owner",
                    "--strip-components=" + str(item["strip_components"]),
                    "-C", str(destination)], check=True)
    marker.write_text(item["sha256"] + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    lock = json.loads(Path(__file__).with_name("sources.lock.json").read_text())
    for name in ("toolchain", "v4l2loopback"):
        fetch(lock[name], args.cache.resolve(), args.work.resolve() / name)


if __name__ == "__main__":
    main()
