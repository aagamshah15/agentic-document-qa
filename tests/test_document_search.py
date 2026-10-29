"""Search contract tests that do not require Chroma, embeddings, or an LLM."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from services.document_catalog import UPLOAD_DIR
from services.document_search import MAX_EXCERPT_CHARS, MAX_QUERY_CHARS, search_documents


def chunk(text="Scholarships open in March.", **metadata):
    return SimpleNamespace(page_content=text, metadata=metadata)


class DocumentSearchTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.similarity_search_with_score.return_value = []

    def search(self, query="scholarships", **kwargs):
        return search_documents(query, backend=self.backend, **kwargs)

    def test_returns_evidence_with_basename_and_one_based_page(self):
        self.backend.similarity_search_with_score.return_value = [
            (chunk(source="/private/uploads/report.pdf", page=0), 0.125)
        ]
        self.assertEqual(self.search(), [{
            "filename": "report.pdf", "page": 1,
            "excerpt": "Scholarships open in March.", "truncated": False, "distance": 0.125,
        }])

    def test_strips_query_whitespace_and_uses_default_limit(self):
        self.search("  eligibility requirements\n")
        self.backend.similarity_search_with_score.assert_called_once_with(
            "eligibility requirements", k=4, filter=None
        )

    def test_filename_filter_is_passed_to_backend_before_ranking(self):
        self.search(filename="Annual Report.PDF", limit=2)
        self.backend.similarity_search_with_score.assert_called_once_with(
            "scholarships", k=2, filter={"source": str(UPLOAD_DIR / "Annual Report.PDF")}
        )

    def test_empty_search_returns_empty_list(self):
        self.assertEqual(self.search(), [])

    def test_backend_errors_are_not_misreported_as_no_results(self):
        for error in [PermissionError("denied"), RuntimeError("index corrupt"), TimeoutError("slow")]:
            with self.subTest(error=type(error).__name__):
                self.backend.similarity_search_with_score.side_effect = error
                with self.assertRaises(type(error)) as raised:
                    self.search()
                self.assertIs(raised.exception, error)

    def test_invalid_query_is_rejected_before_opening_storage(self):
        for query in [None, 42, [], "", " \t\n", "x" * (MAX_QUERY_CHARS + 1)]:
            with self.subTest(query_type=type(query).__name__):
                with patch("services.document_search._open_existing_index") as opener:
                    with self.assertRaises((TypeError, ValueError)):
                        search_documents(query)
                    opener.assert_not_called()

    def test_maximum_query_length_is_accepted(self):
        self.search("x" * MAX_QUERY_CHARS)
        self.backend.similarity_search_with_score.assert_called_once()

    def test_invalid_limits_are_rejected(self):
        for limit in [0, -1, 9, True, False, 1.5, "4", None]:
            with self.subTest(limit=limit):
                with self.assertRaises((TypeError, ValueError)):
                    self.search(limit=limit)
        self.backend.similarity_search_with_score.assert_not_called()

    def test_minimum_and_maximum_limits_are_accepted(self):
        for limit in [1, 8]:
            with self.subTest(limit=limit):
                self.search(limit=limit)
                self.assertEqual(self.backend.similarity_search_with_score.call_args.kwargs["k"], limit)

    def test_paths_and_non_pdf_names_are_rejected(self):
        for filename in [
            "", ".", "..", "../secret.pdf", "/tmp/report.pdf", "nested/report.pdf",
            "..\\secret.pdf", "C:\\report.pdf", "report.pdf\x00", "notes.txt", "report.pdf.bak",
        ]:
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    self.search(filename=filename)
        self.backend.similarity_search_with_score.assert_not_called()

    def test_non_string_filename_is_rejected(self):
        for filename in [12, True, []]:
            with self.subTest(filename=filename), self.assertRaises(TypeError):
                self.search(filename=filename)
        self.backend.similarity_search_with_score.assert_not_called()

    def test_filename_spelling_is_preserved_exactly(self):
        name = "Résumé - 日本語.PDF"
        self.search(filename=name)
        self.assertEqual(
            self.backend.similarity_search_with_score.call_args.kwargs["filter"],
            {"source": str(UPLOAD_DIR / name)},
        )

    def test_missing_metadata_remains_unknown(self):
        self.backend.similarity_search_with_score.return_value = [(chunk(), 0.2)]
        result = self.search()[0]
        self.assertIsNone(result["filename"])
        self.assertIsNone(result["page"])

    def test_malformed_page_metadata_is_not_invented_or_coerced(self):
        for page in [None, -1, True, False, "3", 1.5]:
            with self.subTest(page=page):
                self.backend.similarity_search_with_score.return_value = [(chunk(page=page), 0.2)]
                self.assertIsNone(self.search()[0]["page"])

    def test_physical_page_number_is_independent_of_printed_page_label(self):
        self.backend.similarity_search_with_score.return_value = [(chunk(page=3, page_label="ii"), 0.2)]
        self.assertEqual(self.search()[0]["page"], 4)

    def test_absolute_paths_are_not_exposed_in_source_names(self):
        for source in ["/private/uploads/report.pdf", "C:\\private\\uploads\\report.pdf", "report.pdf"]:
            with self.subTest(source=source):
                self.backend.similarity_search_with_score.return_value = [(chunk(source=source), 0.2)]
                self.assertEqual(self.search()[0]["filename"], "report.pdf")

    def test_invalid_source_metadata_remains_unknown(self):
        for source in [None, "", 123, [], "/"]:
            with self.subTest(source=source):
                self.backend.similarity_search_with_score.return_value = [(chunk(source=source), 0.2)]
                self.assertIsNone(self.search()[0]["filename"])

    def test_backend_ranking_is_preserved(self):
        self.backend.similarity_search_with_score.return_value = [
            (chunk("Best", source="z.pdf"), 0.1), (chunk("Second", source="a.pdf"), 0.4)
        ]
        self.assertEqual([match["excerpt"] for match in self.search()], ["Best", "Second"])

    def test_empty_chunks_are_skipped_without_inventing_replacement_text(self):
        self.backend.similarity_search_with_score.return_value = [
            (chunk(""), 0), (chunk(" \n\t"), 0.1), (chunk("Actual text"), 0.2)
        ]
        self.assertEqual([match["excerpt"] for match in self.search()], ["Actual text"])

    def test_long_excerpts_are_bounded_and_marked_truncated(self):
        text = "x" * (MAX_EXCERPT_CHARS + 50)
        self.backend.similarity_search_with_score.return_value = [(chunk(text), 0.2)]
        result = self.search()[0]
        self.assertEqual(result["excerpt"], text[:MAX_EXCERPT_CHARS])
        self.assertTrue(result["truncated"])

    def test_exact_excerpt_limit_is_not_marked_truncated(self):
        text = "x" * MAX_EXCERPT_CHARS
        self.backend.similarity_search_with_score.return_value = [(chunk(text), 0.2)]
        self.assertFalse(self.search()[0]["truncated"])

    def test_limits_output_even_if_backend_returns_too_many_chunks(self):
        self.backend.similarity_search_with_score.return_value = [(chunk(str(i)), float(i)) for i in range(10)]
        self.assertEqual(len(self.search(limit=2)), 2)

    def test_high_distance_is_returned_without_claiming_answer_confidence(self):
        self.backend.similarity_search_with_score.return_value = [(chunk("Unrelated passage"), 50.0)]
        result = self.search()[0]
        self.assertEqual(result["distance"], 50.0)
        self.assertNotIn("confidence", result)

    def test_nonfinite_distances_fail_instead_of_creating_invalid_json(self):
        for distance in [float("nan"), float("inf"), float("-inf")]:
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                self.backend.similarity_search_with_score.return_value = [(chunk(), distance)]
                self.search()

    def test_result_is_json_serializable_and_does_not_mutate_source(self):
        original = chunk(source="/private/report.pdf", page=0)
        self.backend.similarity_search_with_score.return_value = [(original, 0.2)]
        result = self.search()
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        result[0]["excerpt"] = "edited"
        self.assertEqual(original.page_content, "Scholarships open in March.")
        self.assertEqual(original.metadata, {"source": "/private/report.pdf", "page": 0})

    def test_default_opens_existing_index_only(self):
        with patch("services.document_search._open_existing_index", return_value=self.backend) as opener:
            self.assertEqual(search_documents("eligibility"), [])
            opener.assert_called_once_with()

    def test_missing_index_error_is_propagated(self):
        with patch("services.document_search._open_existing_index", side_effect=FileNotFoundError("No index")):
            with self.assertRaises(FileNotFoundError):
                search_documents("eligibility")

    def test_injected_backend_does_not_open_default_storage(self):
        with patch("services.document_search._open_existing_index") as opener:
            self.search()
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
