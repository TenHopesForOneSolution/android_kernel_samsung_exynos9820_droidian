#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Publish Build N after a successful main-branch build (serialized by CI)."""
import argparse
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


ASSETS = {"Image", "kernel.config", "Module.symvers", "sources.lock.json",
          "modules.tar.gz", "dtbs.tar.gz", "build-info.json"}


def next_build_number(tags):
    numbers = [int(m[1]) for tag in tags if (m := re.fullmatch(r"build-([1-9][0-9]*)", tag))]
    return max(numbers, default=0) + 1


def validate_bundle(directory, expected_commit):
    entries = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        checksum, filename = line.split("  ", 1)
        if filename not in ASSETS or filename in entries or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise RuntimeError("Invalid checksum manifest entry")
        entries[filename] = checksum
    if set(entries) != ASSETS:
        raise RuntimeError("Incomplete release bundle")
    for name, expected in entries.items():
        checksum = hashlib.sha256()
        with (directory / name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        if checksum.hexdigest() != expected:
            raise RuntimeError("Artifact checksum mismatch: " + name)
    info = json.loads((directory / "build-info.json").read_text())
    if info["kernel_commit"] != expected_commit:
        raise RuntimeError("Artifact does not belong to this workflow commit")
    return info


class GitHub:
    def __init__(self, repository, token):
        self.base = "https://api.github.com/repos/" + repository
        self.token = token

    def request(self, path, method="GET", payload=None, binary=False):
        url = path if path.startswith("https://") else self.base + path
        # Never forward a release token to an arbitrary upload host.
        if urllib.parse.urlparse(url).hostname not in {"api.github.com", "uploads.github.com"}:
            raise RuntimeError("Unexpected GitHub API/upload host")
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "s10e-kernel-release"}
        body = payload if binary else (json.dumps(payload).encode() if payload is not None else None)
        if body is not None:
            headers["Content-Type"] = "application/octet-stream" if binary else "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
        return json.loads(data) if data else None

    def pages(self, path):
        result = []
        for page in range(1, 1001):
            items = self.request(path + f"?per_page=100&page={page}")
            result.extend(items)
            if len(items) < 100:
                return result
        raise RuntimeError("Unexpectedly many GitHub API pages")


def publish(api, directory, commit, run_url):
    info = validate_bundle(directory, commit)
    releases = api.pages("/releases")
    existing = [r for r in releases if re.fullmatch(r"build-[1-9][0-9]*", r["tag_name"])
                and r["target_commitish"] == commit]
    if len(existing) > 1:
        raise RuntimeError("Multiple Build releases already exist for this commit")
    release = existing[0] if existing else None
    if release and not release["draft"]:
        print("Already published: " + release["html_url"])
        return release
    if release is None:
        tags = [r["tag_name"] for r in releases] + [t["name"] for t in api.pages("/tags")]
        number = next_build_number(tags)
        body = (f"Samsung Galaxy S10e (beyond0lte), Droidian/Halium Android 12 vendor.\n\n"
                f"Source: `{commit}`\nKernel: `{info['kernel_release']}`\n"
                f"Workflow: {run_url}\n\n"
                "Includes Image, compiled device trees, matching dm-crypt/v4l2loopback modules, "
                "configuration, symbol versions, pinned inputs and SHA256SUMS.\n\n"
                "CI checks passed; physical-device boot/hardware validation is pending. "
                "This is a kernel component bundle, not a flashable boot image. "
                "The OS build must supply a matching initramfs and run depmod for the module tree.\n")
        release = api.request("/releases", "POST", {
            "tag_name": f"build-{number}", "target_commitish": commit,
            "name": f"Build {number}", "body": body, "draft": True, "prerelease": True,
        })
    # A failed upload leaves a draft. A rerun repairs that same draft/number.
    for asset in release.get("assets", []):
        api.request("/releases/assets/" + str(asset["id"]), "DELETE")
    upload = release["upload_url"].split("{", 1)[0]
    for name in sorted(ASSETS | {"SHA256SUMS"}):
        print("Uploading " + name, flush=True)
        api.request(upload + "?" + urllib.parse.urlencode({"name": name}),
                    "POST", (directory / name).read_bytes(), binary=True)
    release = api.request("/releases/" + str(release["id"]), "PATCH", {"draft": False})
    print("Published " + release["name"] + ": " + release["html_url"])
    return release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}:
        raise RuntimeError("Publishing is only allowed from main push/manual builds")
    repository = os.environ["GITHUB_REPOSITORY"]
    api = GitHub(repository, os.environ["GH_TOKEN"])
    run_url = f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    release = publish(api, args.directory, os.environ["GITHUB_SHA"], run_url)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as stream:
            stream.write(f"[{release['name']}]({release['html_url']})\n")


if __name__ == "__main__":
    main()
