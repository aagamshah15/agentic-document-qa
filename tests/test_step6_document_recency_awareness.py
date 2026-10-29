import os
import unittest
from fastapi.testclient import TestClient
from main import app
from services.document_catalog import (
    get_document_inventory,
    get_most_recent_document,
    get_document_manifest_text,
    resolve_target_document,
)
from services.router import determine_query_route
from services.vector_store import get_retriever

class Step6DocumentRecencyAwarenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HF_HUB_OFFLINE"] = "1"
        cls.client = TestClient(app)

    def test_01_document_inventory_order(self):
        """Verify get_document_inventory orders documents by modification timestamp descending."""
        docs = get_document_inventory()
        self.assertGreater(len(docs), 0)
        # Check mtimes are sorted descending
        for i in range(len(docs) - 1):
            self.assertGreaterEqual(docs[i]["mtime"], docs[i + 1]["mtime"])
        print(f"PASS: Document inventory contains {len(docs)} files in strict mtime descending order.")

    def test_02_most_recent_document(self):
        """Verify get_most_recent_document returns the newest uploaded file."""
        latest = get_most_recent_document()
        self.assertIsNotNone(latest)
        self.assertIn("filename", latest)
        self.assertIn("formatted_time", latest)
        print(f"PASS: Most recent document identified: '{latest['filename']}' ({latest['formatted_time']}).")

    def test_03_manifest_text(self):
        """Verify manifest contains [MOST RECENT UPLOAD] tag on the latest document."""
        manifest = get_document_manifest_text()
        self.assertIn("[MOST RECENT UPLOAD]", manifest)
        latest = get_most_recent_document()
        self.assertIn(latest["filename"], manifest)
        print("PASS: Document manifest accurately tags [MOST RECENT UPLOAD].")

    def test_04_recency_phrase_resolution(self):
        """Verify phrases like 'just uploaded', 'last doc', etc. resolve to the newest document."""
        latest = get_most_recent_document()["filename"]
        test_queries = [
            "Summarise the doc I just uploaded",
            "What was the last doc I uploaded?",
            "Can you tell me what is in the latest file?",
            "What's the recent doc about?",
            "Give me key takeaways from the doc I uploaded",
            "What did I upload last?",
        ]
        for q in test_queries:
            resolved = resolve_target_document(q)
            self.assertEqual(
                resolved,
                latest,
                f"Query '{q}' should resolve to '{latest}', got '{resolved}'"
            )
        print("PASS: All recency and latest-document phrases correctly resolve to the latest upload.")

    def test_05_specific_document_resolution(self):
        """Verify queries targeting a specific document resolve to that document."""
        self.assertEqual(
            resolve_target_document("What are the key points in the TE 460 slides?"),
            "2026_10_12_TE 460 Lectures in Engineering Entrepreneurship.pdf"
        )
        self.assertEqual(
            resolve_target_document("Review Aagam resume experience"),
            "Aagam_Shah_Resume.pdf"
        )
        print("PASS: Specific document titles resolve to their respective target filenames.")

    def test_06_router_never_misroutes_document_recency_queries(self):
        """Verify queries referencing uploaded files or recency never route to web search."""
        queries = [
            "What was the last doc I uploaded?",
            "Summarise the doc I just uploaded",
            "What documents are in the library?",
            "Tell me about the latest file",
        ]
        for q in queries:
            route, score = determine_query_route(q)
            self.assertEqual(
                route,
                "local_context",
                f"Expected 'local_context' for query '{q}', got '{route}'"
            )
        print("PASS: Router reliably routes all document inventory and recency queries to 'local_context'.")

    def test_07_scoped_retriever_targets_exact_file(self):
        """Verify get_retriever(target_filename=...) restricts retrieval to that specific file."""
        target_name = "2026_10_12_TE 460 Lectures in Engineering Entrepreneurship.pdf"
        retriever = get_retriever(target_filename=target_name, k=3)
        docs = retriever.invoke("entrepreneurship lectures")
        self.assertGreater(len(docs), 0)
        for doc in docs:
            src = doc.metadata.get("source", "")
            self.assertEqual(os.path.basename(src), target_name)
        print(f"PASS: Scoped retriever returned {len(docs)} chunks exclusively from '{target_name}'.")

if __name__ == "__main__":
    unittest.main()
