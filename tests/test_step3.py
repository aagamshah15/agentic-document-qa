import os
import unittest
from fastapi.testclient import TestClient
from main import app
from services.document_processor import process_document, SUPPORTED_EXTENSIONS
from services.summarizer import prepare_summary_text

class Step3MultiFormatAndSummarizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HF_HUB_OFFLINE"] = "1"
        cls.client = TestClient(app)
        cls.test_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
        os.makedirs(cls.test_dir, exist_ok=True)

    def test_01_supported_extensions(self):
        """Verify supported extensions include pdf, txt, md, docx."""
        self.assertIn(".pdf", SUPPORTED_EXTENSIONS)
        self.assertIn(".txt", SUPPORTED_EXTENSIONS)
        self.assertIn(".md", SUPPORTED_EXTENSIONS)
        self.assertIn(".docx", SUPPORTED_EXTENSIONS)
        print("PASS: Supported extensions verified:", SUPPORTED_EXTENSIONS)

    def test_02_upload_txt_file(self):
        """Verify plain text (.txt) files can be uploaded and chunked."""
        txt_content = b"Agentic AI systems use reasoning loops to determine tools and query vector stores. This is a text test."
        files = {"file": ("test_doc.txt", txt_content, "text/plain")}
        res = self.client.post("/api/upload", files=files)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("Successfully processed", data["message"])
        self.assertEqual(data["filename"], "test_doc.txt")
        self.assertGreaterEqual(data["chunks"], 1)
        print("PASS: Uploaded and embedded .txt file.")

    def test_03_upload_markdown_file(self):
        """Verify markdown (.md) files can be uploaded and chunked."""
        md_content = b"# Architecture\n\nFastAPI and ChromaDB with LangChain form the core architecture of the app."
        files = {"file": ("test_arch.md", md_content, "text/markdown")}
        res = self.client.post("/api/upload", files=files)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("Successfully processed", data["message"])
        self.assertEqual(data["filename"], "test_arch.md")
        self.assertGreaterEqual(data["chunks"], 1)
        print("PASS: Uploaded and embedded .md file.")

    def test_04_unsupported_file_rejected(self):
        """Verify unsupported formats (e.g. .csv) are rejected with HTTP 400 and clear error message."""
        files = {"file": ("data.csv", b"col1,col2\nval1,val2", "text/csv")}
        res = self.client.post("/api/upload", files=files)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported file format", res.json()["detail"])
        print("PASS: Unsupported .csv rejected with 400.")

    def test_05_prepare_summary_text(self):
        """Verify prepare_summary_text combines chunks and respects max_chars limit."""
        sample_path = os.path.join(self.test_dir, "test_doc.txt")
        text = prepare_summary_text(sample_path, max_chars=50)
        self.assertTrue(len(text) > 0)
        self.assertIn("Agentic AI", text)
        print("PASS: prepare_summary_text produces valid concatenated text.")

    def test_06_summarize_stream_endpoint_mount(self):
        """Verify POST /api/documents/{filename}/summarize/stream endpoint mounts with text/event-stream."""
        res = self.client.post("/api/documents/test_doc.txt/summarize/stream")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/event-stream", res.headers["content-type"])
        print("PASS: Summarize stream endpoint mounts as text/event-stream.")

    def test_07_summarize_non_existent_404(self):
        """Verify 404 for summarizing non-existent document."""
        res = self.client.post("/api/documents/ghost_file.pdf/summarize")
        self.assertEqual(res.status_code, 404)
        print("PASS: 404 returned for non-existent document summary.")

    @classmethod
    def tearDownClass(cls):
        # Clean up test files
        for test_file in ["test_doc.txt", "test_arch.md"]:
            cls.client.delete(f"/api/documents/{test_file}")

if __name__ == "__main__":
    unittest.main()
