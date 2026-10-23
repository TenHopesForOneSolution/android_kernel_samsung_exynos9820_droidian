# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release import ASSETS, next_build_number, publish, validate_bundle


class FakeGitHub:
    def __init__(self, releases=None, fail_upload=False):
        self.releases = releases or []
        self.fail_upload = fail_upload
        self.created = []

    def pages(self, path):
        return self.releases if path == "/releases" else [{"name": "build-2"}]

    def request(self, path, method="GET", payload=None, binary=False):
        if path == "/releases":
            r = dict(payload, id=10, upload_url="https://uploads.github.com/test{?name}", assets=[])
            self.created.append(r)
            return r
        if path.startswith("https://"):
            if self.fail_upload:
                raise RuntimeError("Simulated upload failure")
            return {}
        if method == "DELETE":
            return None
        return {"name": "Build 3", "html_url": "https://example.invalid/build-3"}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        for name in ASSETS:
            (self.path / name).write_bytes(b"test artifact")
        (self.path / "build-info.json").write_text(json.dumps({"kernel_commit": "a" * 40, "kernel_release": "test"}))
        (self.path / "SHA256SUMS").write_text("".join(
            hashlib.sha256((self.path / n).read_bytes()).hexdigest() + "  " + n + "\n" for n in sorted(ASSETS)))

    def test_build_numbers_ignore_unrelated_tags(self):
        self.assertEqual(next_build_number([]), 1)
        self.assertEqual(next_build_number(["v1.0.0", "build-2", "build-10", "build-x", "build-01"]), 11)

    def test_wrong_commit_rejected_before_publishing(self):
        api = FakeGitHub()
        with self.assertRaisesRegex(RuntimeError, "workflow commit"):
            publish(api, self.path, "b" * 40, "run")
        self.assertEqual(api.created, [])

    def test_corrupted_artifact_rejected(self):
        (self.path / "Image").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            validate_bundle(self.path, "a" * 40)

    def test_successful_release_uses_next_number(self):
        api = FakeGitHub()
        publish(api, self.path, "a" * 40, "run")
        self.assertEqual(api.created[0]["name"], "Build 3")
        self.assertEqual(api.created[0]["tag_name"], "build-3")
        self.assertTrue(api.created[0]["prerelease"])

    def test_rerun_does_not_duplicate_published_release(self):
        api = FakeGitHub([{"tag_name": "build-2", "target_commitish": "a" * 40,
                           "draft": False, "html_url": "https://example.invalid/build-2"}])
        publish(api, self.path, "a" * 40, "run")
        self.assertEqual(api.created, [])

    def test_upload_failure_keeps_draft_for_retry(self):
        api = FakeGitHub(fail_upload=True)
        with self.assertRaisesRegex(RuntimeError, "upload failure"):
            publish(api, self.path, "a" * 40, "run")
        draft = api.created[0]
        self.assertTrue(draft["draft"])
        retry = FakeGitHub([draft])
        publish(retry, self.path, "a" * 40, "run")
        self.assertEqual(retry.created, [])


if __name__ == "__main__":
    unittest.main()
