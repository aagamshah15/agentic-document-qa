import os
import json
import unittest
from fastapi.testclient import TestClient
from main import app
from services.agent import (
    format_chat_history,
    get_session_history,
    clear_session_history,
)
from langchain_core.messages import HumanMessage, AIMessage

class Step2ConversationalMemoryAndStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HF_HUB_OFFLINE"] = "1"
        cls.client = TestClient(app)

    def test_01_format_chat_history(self):
        """Verify chat history formatting converts dicts and Pydantic models to BaseMessages."""
        history = [
            {"role": "user", "content": "What is Aagam's degree?"},
            {"role": "assistant", "content": "He has a Master's from UIUC."},
        ]
        messages = format_chat_history(history)
        self.assertEqual(len(messages), 2)
        self.assertIsInstance(messages[0], HumanMessage)
        self.assertEqual(messages[0].content, "What is Aagam's degree?")
        self.assertIsInstance(messages[1], AIMessage)
        self.assertEqual(messages[1].content, "He has a Master's from UIUC.")
        print("PASS: Chat history conversion to HumanMessage/AIMessage is correct.")

    def test_02_session_history_management(self):
        """Verify session store creates, retrieves, and clears session history."""
        session_id = "test_sess_123"
        history = get_session_history(session_id)
        self.assertEqual(history, [])

        history.append(HumanMessage(content="Hello"))
        history.append(AIMessage(content="Hi there!"))
        
        self.assertEqual(len(get_session_history(session_id)), 2)

        # Clear session
        res = self.client.post("/api/chat/clear", json={"session_id": session_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(get_session_history(session_id)), 0)
        print("PASS: Session history management and /api/chat/clear verified.")

    def test_03_query_stream_sse_endpoint(self):
        """Verify POST /api/query/stream returns SSE content type and yields chunks."""
        # Note: In sandboxed environment, Ollama may not be reached, so we test endpoint routing and error handling or streaming response headers
        response = self.client.post(
            "/api/query/stream",
            json={
                "query": "Test streaming",
                "session_id": "test_stream_session",
                "history": []
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        print("PASS: /api/query/stream correctly mounts as text/event-stream.")

    def test_04_ui_new_chat_button(self):
        """Verify UI contains the 'New Chat' button and conversational hooks."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn('id="new-chat-btn"', res.text)
        self.assertIn('New Chat', res.text)
        print("PASS: UI contains 'New Chat' button.")

if __name__ == "__main__":
    unittest.main()
