import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tiktok"))
from archive_links import ArchiveLinkError, ensure_archive_link, repair_archive


class ArchiveLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "tiktok/alice/media/1_01.mp4"
        self.target = self.root / "tiktok/alice/posts/1/01.mp4"
        self.source.parent.mkdir(parents=True)
        self.target.parent.mkdir(parents=True)
        self.source.write_bytes(b"original media bytes")
        self.target.write_bytes(self.source.read_bytes())

    def test_repair_keeps_paths_bytes_and_existing_shared_aliases(self):
        alias = self.source.with_name("2_01.mp4")
        os.link(self.source, alias)
        before = self.source.stat().st_ino
        self.assertEqual(ensure_archive_link(self.root, self.source, self.target), "repaired")
        self.assertEqual(self.source.stat().st_ino, before)
        self.assertTrue(self.target.samefile(alias))
        self.assertEqual(self.target.read_bytes(), b"original media bytes")
        with patch("archive_links.fingerprint", side_effect=AssertionError("must not rehash")):
            self.assertEqual(ensure_archive_link(self.root, self.source, self.target), "shared")

    def test_same_size_different_content_is_preserved(self):
        self.target.write_bytes(b"X" * self.source.stat().st_size)
        before = self.target.stat().st_ino
        self.assertEqual(ensure_archive_link(self.root, self.source, self.target), "different")
        self.assertEqual(self.target.stat().st_ino, before)
        self.assertEqual(self.target.read_bytes(), b"X" * self.source.stat().st_size)

    def test_missing_target_is_hardlinked(self):
        self.target.unlink()
        self.assertEqual(ensure_archive_link(self.root, self.source, self.target), "linked")
        self.assertTrue(self.target.samefile(self.source))

    def test_dry_run_preserves_inode(self):
        before = self.target.stat().st_ino
        self.assertEqual(ensure_archive_link(self.root, self.source, self.target, apply=False), "would_repair")
        self.assertEqual(self.target.stat().st_ino, before)

    def test_stale_plan_digest_does_not_replace_target(self):
        before = self.target.stat().st_ino
        with self.assertRaisesRegex(ArchiveLinkError, "CHANGED"):
            ensure_archive_link(self.root, self.source, self.target, expected_digest="stale")
        self.assertEqual(self.target.stat().st_ino, before)

    def test_replace_failure_preserves_original_and_cleans_temporary_link(self):
        before = self.target.stat().st_ino
        with patch("archive_links.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                ensure_archive_link(self.root, self.source, self.target)
        self.assertEqual(self.target.stat().st_ino, before)
        self.assertEqual(list(self.target.parent.glob(".hardlink-*")), [])
        self.assertEqual(self.source.stat().st_nlink, 1)

    def test_concurrent_target_change_is_not_overwritten(self):
        original = os.link

        def changed(source, destination):
            original(source, destination)
            self.target.write_bytes(b"new archive content")

        with patch("archive_links.os.link", side_effect=changed):
            with self.assertRaisesRegex(ArchiveLinkError, "CHANGED"):
                ensure_archive_link(self.root, self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"new archive content")
        self.assertEqual(list(self.target.parent.glob(".hardlink-*")), [])

    def test_symlink_and_outside_root_are_rejected(self):
        self.target.unlink()
        self.target.symlink_to(self.source)
        with self.assertRaisesRegex(ArchiveLinkError, "SYMLINK"):
            ensure_archive_link(self.root, self.source, self.target)
        with self.assertRaisesRegex(ArchiveLinkError, "PATH_INVALID"):
            ensure_archive_link(self.root, Path("/outside.mp4"), self.target)

    def test_parent_symlink_is_rejected(self):
        parent = self.root / "alias"
        parent.symlink_to(self.source.parent, target_is_directory=True)
        with self.assertRaisesRegex(ArchiveLinkError, "SYMLINK"):
            ensure_archive_link(self.root, parent / self.source.name, self.target)

    def test_scan_repair_is_idempotent_and_excludes_metadata_and_other_platforms(self):
        unrelated = self.root / "x/media/1.mp4"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(self.source.read_bytes())
        metadata = self.target.with_name("metadata.json")
        metadata.write_bytes(self.source.read_bytes())
        report = self.root / "report.jsonl"
        with report.open("w") as stream:
            result = repair_archive(self.root, True, stream)
        self.assertEqual(result["repaired"], 1)
        self.assertEqual(result["unlinked_copy_bytes"], self.source.stat().st_size)
        self.assertTrue(self.target.samefile(self.source))
        self.assertFalse(unrelated.samefile(self.source))
        self.assertFalse(metadata.samefile(self.source))
        second = repair_archive(self.root, False, io.StringIO())
        self.assertEqual(second.get("would_repair", 0), 0)
        self.assertEqual(second["shared"], 1)

    def test_scan_skips_regular_and_broken_symlinks(self):
        alias = self.source.with_name("alias.mp4")
        broken = self.source.with_name("broken.mp4")
        alias.symlink_to(self.source)
        broken.symlink_to(self.root / "absent")
        preview = repair_archive(self.root, False, io.StringIO())
        self.assertEqual(preview["would_repair"], 1)
        self.assertTrue(alias.is_symlink())
        self.assertTrue(broken.is_symlink())


if __name__ == "__main__":
    unittest.main()
