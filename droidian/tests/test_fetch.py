# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch import verify_archive


class ToolchainVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        manifest = {
            "bin/compiler": {"type": "file", "mode": 0o755, "size": 4,
                             "sha256": hashlib.sha256(b"good").hexdigest()},
            "bin/cc": {"type": "symlink", "mode": 0o777, "target": "compiler"},
        }
        data = json.dumps(manifest).encode()
        (self.root / "files.json").write_bytes(data)
        self.item = {"name": "test compiler", "manifest": "files.json",
                     "manifest_sha256": hashlib.sha256(data).hexdigest()}

    def archive(self, timestamp=1, payload=b"good", extra=False, target="compiler"):
        path = self.root / "input.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            member = tarfile.TarInfo("bin/compiler")
            member.mode, member.mtime, member.size = 0o755, timestamp, len(payload)
            tar.addfile(member, io.BytesIO(payload))
            link = tarfile.TarInfo("bin/cc")
            link.type, link.mode, link.linkname = tarfile.SYMTYPE, 0o777, target
            tar.addfile(link)
            if extra:
                unexpected = tarfile.TarInfo("../outside")
                tar.addfile(unexpected)
        return path

    def test_timestamp_changes_are_allowed(self):
        verify_archive(self.item, self.archive(timestamp=1), self.root)
        verify_archive(self.item, self.archive(timestamp=987654321), self.root)

    def test_changed_file_rejected(self):
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_archive(self.item, self.archive(payload=b"evil"), self.root)

    def test_unexpected_path_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected toolchain entry"):
            verify_archive(self.item, self.archive(extra=True), self.root)

    def test_changed_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError, "symlink mismatch"):
            verify_archive(self.item, self.archive(target="/etc/passwd"), self.root)

    def test_manifest_tampering_rejected(self):
        (self.root / "files.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "manifest checksum mismatch"):
            verify_archive(self.item, self.archive(), self.root)


if __name__ == "__main__":
    unittest.main()
