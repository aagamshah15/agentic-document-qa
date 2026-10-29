import os
import unittest
import json
from fastapi.testclient import TestClient
from main import app
import services.session_store as session_store

class TestMultiChatModelStop(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_session_id = "test_session_step5"
        # Ensure clean state for test session
        session_store.delete_session(self.test_session_id)

    def tearDown(self):
        session_store.delete_session(self.test_session_id)

    def test_01_models_discovery_endpoint(self):
        """Verify GET /api/models returns installed models or fallback models."""
        response = self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("models", data)
        self.assertIn("default_model", data)
        self.assertIsInstance(data["models"], list)
        self.assertGreater(len(data["models"]), 0)
        print(f"PASS: /api/models returned {len(data['models'])} models (default: {data['default_model']}).")

    def test_02_create_and_list_sessions(self):
        """Verify POST /api/sessions creates a session and GET /api/sessions lists it."""
        # Create session
        res = self.client.post(
            "/api/sessions",
            json={
                "session_id": self.test_session_id,
                "title": "New Chat",
                "model": "llama3.1:8b",
                "effort": "high"
            }
        )
        self.assertEqual(res.status_code, 200)
        session_data = res.json()
        self.assertEqual(session_data["id"], self.test_session_id)
        self.assertEqual(session_data["model"], "llama3.1:8b")
        self.assertEqual(session_data["effort"], "high")

        # List sessions
        list_res = self.client.get("/api/sessions")
        self.assertEqual(list_res.status_code, 200)
        sessions = list_res.json()["sessions"]
        session_ids = [s["id"] for s in sessions]
        self.assertIn(self.test_session_id, session_ids)
        print("PASS: Session creation and listing verified.")

    def test_03_query_persists_to_session_memory_and_auto_titles(self):
        """Verify querying updates SQLite session memory and auto-names 'New Chat'."""
        # First ensure session exists with default title
        self.client.post(
            "/api/sessions",
            json={"session_id": self.test_session_id, "title": "New Chat"}
        )

        # Send a query with model and effort specified
        query_text = "What is the capital of Japan?"
        res = self.client.post(
            "/api/query",
            json={
                "query": query_text,
                "session_id": self.test_session_id,
                "model": "llama3",
                "effort": "low",
                "history": []
            }
        )
        self.assertEqual(res.status_code, 200)
        answer_data = res.json()
        self.assertIn("answer", answer_data)

        # Retrieve session details
        detail_res = self.client.get(f"/api/sessions/{self.test_session_id}")
        self.assertEqual(detail_res.status_code, 200)
        details = detail_res.json()
        
        # Verify title auto-naming
        self.assertIn("What is the capital", details["session"]["title"])

        # Verify messages persisted (user + assistant)
        messages = details["messages"]
        self.assertGreaterEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], query_text)
        self.assertEqual(messages[1]["role"], "assistant")
        print("PASS: Persistent SQLite message storage and auto-titling verified.")

    def test_04_patch_session_settings(self):
        """Verify PATCH /api/sessions/{session_id} updates title, model, and effort."""
        self.client.post(
            "/api/sessions",
            json={"session_id": self.test_session_id, "title": "Old Title", "model": "llama3", "effort": "low"}
        )

        patch_res = self.client.patch(
            f"/api/sessions/{self.test_session_id}",
            json={
                "title": "Updated Custom Research Thread",
                "model": "qwen3:4b",
                "effort": "high"
            }
        )
        self.assertEqual(patch_res.status_code, 200)
        updated = patch_res.json()
        self.assertEqual(updated["title"], "Updated Custom Research Thread")
        self.assertEqual(updated["model"], "qwen3:4b")
        self.assertEqual(updated["effort"], "high")
        print("PASS: PATCH /api/sessions updates title, model, and effort.")

    def test_05_stop_chat_partial_persistence(self):
        """Verify POST /api/chat/stop correctly preserves partial response on cancellation."""
        self.client.post(
            "/api/sessions",
            json={"session_id": self.test_session_id}
        )

        stop_res = self.client.post(
            "/api/chat/stop",
            json={
                "session_id": self.test_session_id,
                "role": "assistant",
                "content": "This is a partial answer that was stopped by the user mid-stream...",
                "route": "local_context",
                "sources": [
                    {"source": "Sample.pdf", "page": 1, "snippet": "Sample snippet"}
                ]
            }
        )
        self.assertEqual(stop_res.status_code, 200)

        # Check that it appears in session messages
        detail_res = self.client.get(f"/api/sessions/{self.test_session_id}")
        self.assertEqual(detail_res.status_code, 200)
        messages = detail_res.json()["messages"]
        matching = [m for m in messages if "partial answer that was stopped" in m["content"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["sources"][0]["source"], "Sample.pdf")
        print("PASS: Stream stop partial persistence verified in SQLite.")

    def test_06_delete_and_clear_session(self):
        """Verify session clearing and deletion endpoints."""
        self.client.post(
            "/api/sessions",
            json={"session_id": self.test_session_id}
        )
        session_store.add_message(self.test_session_id, "user", "Hello")
        session_store.add_message(self.test_session_id, "assistant", "Hi there")

        # Clear messages
        clear_res = self.client.post(f"/api/sessions/{self.test_session_id}/clear")
        self.assertEqual(clear_res.status_code, 200)
        
        detail_res = self.client.get(f"/api/sessions/{self.test_session_id}")
        self.assertEqual(len(detail_res.json()["messages"]), 0)

        # Delete session
        del_res = self.client.delete(f"/api/sessions/{self.test_session_id}")
        self.assertEqual(del_res.status_code, 200)

        # Confirm 404 after deletion
        not_found_res = self.client.get(f"/api/sessions/{self.test_session_id}")
        self.assertEqual(not_found_res.status_code, 404)
        print("PASS: Session clear and delete endpoints verified.")

    def test_07_ui_components_for_multichat_model_stop(self):
        """Verify UI contains model dropdown, effort selector, stop button, and chat threads."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('id="model-select"', html)
        self.assertIn('id="effort-select"', html)
        self.assertIn('id="sessions-list"', html)
        self.assertIn('id="chat-count"', html)
        self.assertIn('id="send-btn"', html)
        self.assertIn('stop-icon', html)
        print("PASS: UI contains all necessary hooks for multi-chat, model/effort, and stop button.")

if __name__ == "__main__":
    unittest.main()
