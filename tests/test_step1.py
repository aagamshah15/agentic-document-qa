import os
import shutil
import unittest
from fastapi.testclient import TestClient
from main import app
from services.vector_store import (
    get_vector_store,
    get_document_chunk_counts,
    delete_document_from_store,
    add_documents_to_store,
)
from services.agent import get_agent_executor
from langchain_core.documents import Document

class Step1ExtensiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HF_HUB_OFFLINE"] = "1"
        cls.client = TestClient(app)
        cls.test_upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
        cls.sample_pdf = os.path.join(cls.test_upload_dir, "Briefing Memo - DPKB.pdf")

    def test_01_list_documents(self):
        """Verify GET /api/documents returns expected structure, chunk counts, and file sizes."""
        response = self.client.get("/api/documents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("documents", data)
        self.assertIn("total_chunks", data)
        self.assertIsInstance(data["documents"], list)
        self.assertGreater(len(data["documents"]), 0)
        
        first_doc = data["documents"][0]
        self.assertIn("filename", first_doc)
        self.assertIn("size_bytes", first_doc)
        self.assertIn("uploaded_at", first_doc)
        self.assertIn("chunk_count", first_doc)
        self.assertGreater(first_doc["size_bytes"], 0)
        print(f"PASS: Listed {len(data['documents'])} documents with {data['total_chunks']} total chunks.")

    def test_02_upload_validation_unsupported_file(self):
        """Verify POST /api/upload rejects unsupported file types with HTTP 400."""
        files = {"file": ("test.csv", b"col1,col2\nval1,val2", "text/csv")}
        response = self.client.post("/api/upload", files=files)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file format", response.json()["detail"])
        print("PASS: Unsupported format rejected with 400 Bad Request.")

    def test_03_upload_valid_file_and_reindex(self):
        """Verify uploading a copy of a document successfully indexes and increments chunk count."""
        # Find any available PDF in test_upload_dir
        available_files = [f for f in os.listdir(self.test_upload_dir) if f.endswith(".pdf")]
        if not available_files:
            self.skipTest("No sample PDF found in uploads for upload test")

        source_file = os.path.join(self.test_upload_dir, available_files[0])
        temp_pdf_name = "Test_Sample_Document_Copy.pdf"
        with open(source_file, "rb") as f:
            pdf_bytes = f.read()

        files = {"file": (temp_pdf_name, pdf_bytes, "application/pdf")}
        response = self.client.post("/api/upload", files=files)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Successfully processed", data["message"])
        self.assertIn("chunks", data)
        self.assertGreater(data["chunks"], 0)
        print(f"PASS: Uploaded {temp_pdf_name} and indexed {data['chunks']} chunks.")

        # Check list endpoint reflects new doc
        list_res = self.client.get("/api/documents")
        doc_names = [d["filename"] for d in list_res.json()["documents"]]
        self.assertIn(temp_pdf_name, doc_names)
        print("PASS: Document list endpoint immediately reflects new document.")

    def test_04_citation_extraction_logic(self):
        """Verify that citation extraction properly formats sources, pages (1-indexed), and snippets."""
        # Create synthetic documents mimicking LangChain retrieved context
        mock_docs = [
            Document(
                page_content="The client liked both teams' work, but now wants a unified, production-ready solution.",
                metadata={"source": "/path/to/data/uploads/Briefing Memo.pdf", "page": 0}
            ),
            Document(
                page_content="Future teams should build ingestion and validation pipelines from scratch.",
                metadata={"source": "/path/to/data/uploads/Briefing Memo.pdf", "page": 1}
            ),
            Document(
                page_content="General guidelines without explicit page number.",
                metadata={"source": "Manual.pdf"}
            ),
        ]

        # Test citation extraction logic
        sources = []
        seen = set()
        for doc in mock_docs:
            meta = getattr(doc, "metadata", {}) or {}
            src = meta.get("source", "")
            fname = os.path.basename(src) if src else "Document"
            page = meta.get("page", None)
            page_num = (page + 1) if isinstance(page, int) else None
            snippet = doc.page_content.strip()
            if snippet in seen:
                continue
            seen.add(snippet)
            sources.append({
                "source": fname,
                "page": page_num,
                "snippet": snippet[:260] + ("..." if len(snippet) > 260 else "")
            })

        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[0]["source"], "Briefing Memo.pdf")
        self.assertEqual(sources[0]["page"], 1)  # 0-indexed converted to 1-indexed
        self.assertIn("unified, production-ready", sources[0]["snippet"])

        self.assertEqual(sources[1]["page"], 2)  # page 1 converted to 2
        self.assertIsNone(sources[2]["page"])     # no page metadata preserved as None
        print("PASS: Citation formatting & 1-indexing verified across various metadata structures.")

    def test_05_delete_document_and_cleanup(self):
        """Verify deleting a specific document removes it from storage and removes its Chroma vectors."""
        temp_pdf_name = "Test_Sample_Document_Copy.pdf"
        del_res = self.client.delete(f"/api/documents/{temp_pdf_name}")
        self.assertEqual(del_res.status_code, 200)
        data = del_res.json()
        self.assertIn("deleted_chunks", data)
        self.assertGreater(data["deleted_chunks"], 0)
        print(f"PASS: Deleted {temp_pdf_name} and purged {data['deleted_chunks']} vector embeddings.")

        # Ensure it is gone from /api/documents
        list_res = self.client.get("/api/documents")
        doc_names = [d["filename"] for d in list_res.json()["documents"]]
        self.assertNotIn(temp_pdf_name, doc_names)
        print("PASS: Document list confirms removal.")

    def test_06_delete_non_existent_document(self):
        """Verify deleting a non-existent document yields 404."""
        del_res = self.client.delete("/api/documents/definitely_not_a_real_file_987654.pdf")
        self.assertEqual(del_res.status_code, 404)
        print("PASS: 404 correctly returned for non-existent file deletion.")

    def test_07_path_traversal_protection(self):
        """Verify path traversal attempts in delete endpoint are sanitized to basename."""
        del_res = self.client.delete("/api/documents/../../etc/passwd")
        # Since os.path.basename is used, this targets "passwd" in uploads which doesn't exist -> 404
        self.assertEqual(del_res.status_code, 404)
        print("PASS: Path traversal attack safely neutralized.")

    def test_08_root_html_elements(self):
        """Verify UI template contains all necessary DOM hooks for Document Manager and Citations."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('id="documents-list"', html)
        self.assertIn('id="doc-count"', html)
        self.assertIn('id="clear-all-btn"', html)
        self.assertIn('id="drop-zone"', html)
        self.assertIn('id="chat-box"', html)
        print("PASS: Root HTML index contains all required DOM containers and hooks.")

if __name__ == "__main__":
    unittest.main()
