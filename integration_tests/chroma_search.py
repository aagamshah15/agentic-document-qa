"""Real Chroma integration, synthetic vectors, temporary storage, no downloads.

Run: venv/bin/python -m unittest integration_tests.chroma_search -v
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chromadb.config import Settings
from chromadb.errors import NotFoundError
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from services.document_catalog import UPLOAD_DIR
from services.document_search import search_documents
from services import vector_store


class SyntheticEmbeddings(Embeddings):
    """Known vectors test database ranking/filtering, not semantic model quality."""

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        if "scholarship" in text.lower():
            return [1.0, 0.0, 0.0]
        if "deadline" in text.lower():
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def local_chroma(**kwargs):
    return Chroma(client_settings=Settings(anonymized_telemetry=False), **kwargs)


class ChromaSearchTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = local_chroma(
            collection_name="agentic_qa_collection",
            embedding_function=SyntheticEmbeddings(),
            persist_directory=str(self.root / "index"),
        )

    def seed(self):
        self.store.add_documents([
            Document(page_content="Scholarship eligibility requires enrollment.", metadata={
                "source": str(UPLOAD_DIR / "scholarships.pdf"), "page": 0,
            }),
            Document(page_content="The deadline is March 15.", metadata={
                "source": str(UPLOAD_DIR / "scholarships.pdf"), "page": 1,
            }),
            Document(page_content="Cafeteria hours start at 8 AM.", metadata={
                "source": str(UPLOAD_DIR / "campus.pdf"), "page": 2,
            }),
        ])

    def test_real_chroma_ranks_and_preserves_citation_metadata(self):
        self.seed()
        result = search_documents("scholarship", limit=1, backend=self.store)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "scholarships.pdf")
        self.assertEqual(result[0]["page"], 1)
        self.assertIn("enrollment", result[0]["excerpt"])
        self.assertAlmostEqual(result[0]["distance"], 0.0)

    def test_filter_happens_before_top_k_selection(self):
        self.seed()
        # The global closest match is in scholarships.pdf. A scoped query must
        # still return campus.pdf; filtering global top-1 afterwards would fail.
        result = search_documents("scholarship", filename="campus.pdf", limit=1, backend=self.store)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "campus.pdf")

    def test_unknown_filename_returns_no_matches(self):
        self.seed()
        self.assertEqual(search_documents("scholarship", filename="missing.pdf", backend=self.store), [])

    def test_empty_collection_returns_empty_list(self):
        self.assertEqual(search_documents("scholarship", backend=self.store), [])

    def test_limit_larger_than_collection_returns_available_chunks(self):
        self.seed()
        self.assertEqual(len(search_documents("scholarship", limit=8, backend=self.store)), 3)

    def test_existing_only_factory_reopens_index_with_same_embedding_model(self):
        self.seed()
        with patch.object(vector_store, "CHROMA_PERSIST_DIR", str(self.root / "index")), \
                patch.object(vector_store, "HuggingFaceEmbeddings", return_value=SyntheticEmbeddings()) as embeddings, \
                patch.object(vector_store, "Chroma", side_effect=local_chroma):
            result = search_documents("deadline", limit=1)
        embeddings.assert_called_once_with(model_name="all-MiniLM-L6-v2")
        self.assertEqual(result[0]["page"], 2)
        self.assertIn("March 15", result[0]["excerpt"])

    def test_missing_index_fails_before_loading_embedding_model(self):
        missing = self.root / "missing"
        with patch.object(vector_store, "CHROMA_PERSIST_DIR", str(missing)), \
                patch.object(vector_store, "HuggingFaceEmbeddings") as embeddings:
            with self.assertRaises(FileNotFoundError):
                search_documents("scholarship")
        embeddings.assert_not_called()
        self.assertFalse(missing.exists())

    def test_missing_collection_is_not_silently_created(self):
        other = local_chroma(
            collection_name="unrelated_collection", embedding_function=SyntheticEmbeddings(),
            persist_directory=str(self.root / "other"),
        )
        with patch.object(vector_store, "CHROMA_PERSIST_DIR", str(self.root / "other")), \
                patch.object(vector_store, "HuggingFaceEmbeddings", return_value=SyntheticEmbeddings()), \
                patch.object(vector_store, "Chroma", side_effect=local_chroma):
            with self.assertRaises(NotFoundError):
                search_documents("scholarship")
        # Reopening the expected collection must still fail after the search.
        with self.assertRaises(NotFoundError):
            local_chroma(
                collection_name="agentic_qa_collection", embedding_function=SyntheticEmbeddings(),
                persist_directory=str(self.root / "other"), create_collection_if_not_exists=False,
            )
        self.assertEqual(other.get()["ids"], [])

    def test_default_factory_still_creates_storage_for_uploads(self):
        location = self.root / "new-upload-store"
        with patch.object(vector_store, "CHROMA_PERSIST_DIR", str(location)), \
                patch.object(vector_store, "HuggingFaceEmbeddings", return_value=SyntheticEmbeddings()), \
                patch.object(vector_store, "Chroma", side_effect=local_chroma):
            store = vector_store.get_vector_store()
        self.assertTrue((location / "chroma.sqlite3").is_file())
        self.assertEqual(store.get()["ids"], [])


if __name__ == "__main__":
    unittest.main()
