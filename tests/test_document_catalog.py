"""Contract tests for document inventory; no models or databases are needed."""

import errno
import json
import os
from pathlib import Path
from stat import S_IFREG
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services.document_catalog import UPLOAD_DIR, list_documents


class ListDocumentsTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.upload_dir = Path(temporary.name) / "uploads"
        self.upload_dir.mkdir()

    def write_file(self, name, content=b"Example document"):
        path = self.upload_dir / name
        path.write_bytes(content)
        return path

    def test_empty_directory_returns_empty_list(self):
        self.assertEqual(list_documents(self.upload_dir), [])

    def test_missing_directory_returns_empty_list_without_creating_it(self):
        missing = self.upload_dir / "missing" / "uploads"
        self.assertEqual(list_documents(missing), [])
        self.assertFalse(missing.parent.exists())

    def test_returns_exact_public_metadata_with_size_in_bytes(self):
        content = "Résumé".encode("utf-8")
        self.write_file("report.pdf", content)

        self.assertEqual(
            list_documents(self.upload_dir),
            [{
                "filename": "report.pdf",
                "size_bytes": len(content),
                "indexing_status": "unknown",
            }],
        )

    def test_pdf_extension_is_case_insensitive(self):
        names = ["first.pdf", "second.PDF", "third.PdF"]
        for name in names:
            self.write_file(name)

        self.assertEqual(
            [item["filename"] for item in list_documents(self.upload_dir)], names
        )

    def test_ignores_non_pdf_extensions_and_misleading_suffixes(self):
        self.write_file("keep.pdf")
        for name in ["notes.txt", "pdf", "report.pdf.exe", "report.pdf.backup", "report.pdf "]:
            self.write_file(name)

        self.assertEqual(
            [item["filename"] for item in list_documents(self.upload_dir)], ["keep.pdf"]
        )

    def test_lists_empty_and_invalid_pdfs_without_claiming_they_are_indexed(self):
        # Inventory checks filenames and metadata, not PDF validity or readiness.
        self.write_file("empty.pdf", b"")
        self.write_file("invalid.pdf", b"This is not a PDF")

        documents = list_documents(self.upload_dir)

        self.assertEqual([item["filename"] for item in documents], ["empty.pdf", "invalid.pdf"])
        self.assertEqual(documents[0]["size_bytes"], 0)
        self.assertTrue(all(item["indexing_status"] == "unknown" for item in documents))

    def test_preserves_spaces_unicode_and_hidden_filenames(self):
        names = ["Quarter 1 report.pdf", "résumé-日本語.pdf", ".draft.pdf"]
        for name in names:
            self.write_file(name)
        # Read back filesystem spelling: some filesystems normalize Unicode names.
        stored_names = {path.name for path in self.upload_dir.iterdir()}

        self.assertEqual(
            {item["filename"] for item in list_documents(self.upload_dir)}, stored_names
        )

    def test_sorts_filenames_case_insensitively(self):
        for name in ["zebra.pdf", "Beta.pdf", "alpha.pdf"]:
            self.write_file(name)

        self.assertEqual(
            [item["filename"] for item in list_documents(self.upload_dir)],
            ["alpha.pdf", "Beta.pdf", "zebra.pdf"],
        )

    def test_casefold_ties_have_a_stable_order(self):
        # Simulate names differing only by case; they cannot coexist on all disks.
        names = ["a.pdf", "A.pdf"]
        paths = [self.upload_dir / name for name in names]
        metadata = SimpleNamespace(st_mode=S_IFREG, st_size=10)
        for order in [paths, list(reversed(paths))]:
            with self.subTest(order=[path.name for path in order]):
                with patch.object(Path, "iterdir", return_value=iter(order)), patch.object(
                    Path, "lstat", return_value=metadata
                ):
                    self.assertEqual(
                        [item["filename"] for item in list_documents(self.upload_dir)],
                        ["A.pdf", "a.pdf"],
                    )

    def test_ignores_directories_even_when_named_pdf_and_does_not_recurse(self):
        for name in ["nested", "folder.pdf"]:
            directory = self.upload_dir / name
            directory.mkdir()
            (directory / "hidden.pdf").write_bytes(b"Nested document")
        self.write_file("visible.pdf")

        self.assertEqual(
            [item["filename"] for item in list_documents(self.upload_dir)], ["visible.pdf"]
        )

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks are unavailable")
    def test_ignores_symlinks_to_files_directories_and_missing_targets(self):
        target = self.write_file("actual.pdf")
        outside = self.upload_dir.parent / "outside.pdf"
        outside.write_bytes(b"Outside document")
        directory = self.upload_dir.parent / "other"
        directory.mkdir()
        targets = [target, outside, directory, self.upload_dir.parent / "missing.pdf"]
        for index, destination in enumerate(targets):
            try:
                (self.upload_dir / f"link-{index}.pdf").symlink_to(
                    destination, target_is_directory=destination.is_dir()
                )
            except OSError as error:
                if error.errno in (errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP):
                    self.skipTest(f"Symlink creation is unavailable: {error}")
                raise

        self.assertEqual(
            [item["filename"] for item in list_documents(self.upload_dir)], ["actual.pdf"]
        )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Named pipes are unavailable")
    def test_ignores_named_pipes_with_pdf_extension(self):
        os.mkfifo(self.upload_dir / "pipe.pdf")

        self.assertEqual(list_documents(self.upload_dir), [])

    def test_regular_file_as_root_raises_instead_of_reporting_empty_library(self):
        path = self.write_file("report.pdf")

        with self.assertRaises(NotADirectoryError):
            list_documents(path)

    def test_directory_read_errors_propagate(self):
        # chmod-based tests can pass unexpectedly when run with elevated rights.
        for error in [PermissionError("Access denied"), OSError(errno.EIO, "I/O failure")]:
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, "iterdir", side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        list_documents(self.upload_dir)
                self.assertIs(raised.exception, error)

    def test_error_partway_through_directory_iteration_propagates(self):
        def interrupted_listing():
            yield self.upload_dir / "report.pdf"
            raise PermissionError("Directory read interrupted")

        with patch.object(Path, "iterdir", return_value=interrupted_listing()):
            with self.assertRaises(PermissionError):
                list_documents(self.upload_dir)

    def test_file_metadata_errors_propagate(self):
        self.write_file("report.pdf")
        for error in [PermissionError("Access denied"), OSError(errno.EIO, "I/O failure")]:
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, "lstat", side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        list_documents(self.upload_dir)
                self.assertIs(raised.exception, error)

    def test_file_deleted_during_listing_is_skipped_and_other_files_remain(self):
        removed = self.write_file("removed.pdf")
        kept = self.write_file("kept.pdf")
        original_lstat = Path.lstat

        def remove_before_inspection(path):
            if path == removed:
                path.unlink()
            return original_lstat(path)

        with patch.object(Path, "lstat", remove_before_inspection):
            documents = list_documents(self.upload_dir)

        self.assertEqual([item["filename"] for item in documents], [kept.name])
        self.assertFalse(removed.exists())

    def test_directory_removed_during_listing_yields_no_stale_entries(self):
        self.write_file("report.pdf")
        original_iterdir = Path.iterdir

        def remove_after_enumeration(path):
            entries = list(original_iterdir(path))
            for entry in entries:
                entry.unlink()
            path.rmdir()
            return iter(entries)

        with patch.object(Path, "iterdir", remove_after_enumeration):
            self.assertEqual(list_documents(self.upload_dir), [])

    def test_file_replaced_by_directory_during_listing_is_skipped(self):
        replaced = self.write_file("report.pdf")
        original_lstat = Path.lstat

        def replace_before_inspection(path):
            if path == replaced:
                path.unlink()
                path.mkdir()
            return original_lstat(path)

        with patch.object(Path, "lstat", replace_before_inspection):
            self.assertEqual(list_documents(self.upload_dir), [])

    def test_handles_file_sizes_larger_than_32_bit_integer(self):
        self.write_file("large.pdf")
        # No need to allocate a multi-gigabyte fixture to test metadata handling.
        size = 2**32 + 123
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=S_IFREG, st_size=size)):
            self.assertEqual(list_documents(self.upload_dir)[0]["size_bytes"], size)

    def test_output_is_json_serializable(self):
        self.write_file("report.pdf")
        documents = list_documents(self.upload_dir)

        self.assertEqual(json.loads(json.dumps(documents)), documents)

    def test_listing_does_not_modify_files_or_create_storage(self):
        path = self.write_file("report.pdf", b"Unchanged contents")
        before = path.stat()
        entries_before = set(self.upload_dir.parent.rglob("*"))

        list_documents(self.upload_dir)

        self.assertEqual(set(self.upload_dir.parent.rglob("*")), entries_before)
        self.assertEqual(path.read_bytes(), b"Unchanged contents")
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_each_call_reflects_additions_and_removals(self):
        self.assertEqual(list_documents(self.upload_dir), [])
        path = self.write_file("new.pdf")
        self.assertEqual(len(list_documents(self.upload_dir)), 1)
        path.unlink()
        self.assertEqual(list_documents(self.upload_dir), [])

    def test_mutating_a_result_does_not_affect_later_calls(self):
        self.write_file("report.pdf")
        first = list_documents(self.upload_dir)
        first[0]["filename"] = "edited.pdf"
        first.append({"filename": "fake.pdf", "size_bytes": 0, "indexing_status": "unknown"})

        self.assertEqual(
            [item["filename"] for item in list_documents(self.upload_dir)], ["report.pdf"]
        )

    def test_default_uses_project_upload_directory_without_reading_real_uploads(self):
        inspected = []

        def record_directory(path):
            inspected.append(path)
            return iter(())

        with patch.object(Path, "iterdir", record_directory):
            self.assertEqual(list_documents(), [])

        expected = Path(__file__).resolve().parent.parent / "data" / "uploads"
        self.assertEqual(UPLOAD_DIR, expected)
        self.assertEqual(inspected, [expected])


if __name__ == "__main__":
    unittest.main()
