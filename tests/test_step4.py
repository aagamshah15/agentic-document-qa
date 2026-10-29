import os
import unittest
from fastapi.testclient import TestClient
from main import app
from services.router import determine_query_route
from services.web_search import search_web, WEB_SEARCH_NOTICE

class Step4AutonomousRoutingAndWebSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HF_HUB_OFFLINE"] = "1"
        cls.client = TestClient(app)

    def test_01_router_explicit_keywords(self):
        """Verify queries with explicit web keywords route to web_search."""
        queries = [
            "search the web for latest AI models",
            "What is today's weather in Chicago?",
            "What is the stock price of Apple?",
        ]
        for q in queries:
            route, score = determine_query_route(q)
            self.assertEqual(route, "web_search")
            print(f"PASS: Explicit keyword query '{q}' -> route '{route}'")

    def test_02_router_unrelated_query(self):
        """Verify queries unrelated to local document content route to web_search."""
        query = "What is the population and capital of Iceland?"
        route, score = determine_query_route(query)
        self.assertEqual(route, "web_search")
        print(f"PASS: Unrelated query '{query}' -> route '{route}' (score: {score:.3f})")

    def test_03_router_local_context(self):
        """Verify queries matching local indexed documents route to local_context."""
        query = "What is Aagam's educational background and GPA?"
        route, score = determine_query_route(query)
        self.assertEqual(route, "local_context")
        print(f"PASS: Document query '{query}' -> route '{route}' (score: {score:.3f})")

    def test_04_web_search_notice_clarity(self):
        """Verify WEB_SEARCH_NOTICE clearly states that web search is being used instead of local context."""
        self.assertIn("Live Web Search", WEB_SEARCH_NOTICE)
        self.assertIn("not found in your uploaded documents", WEB_SEARCH_NOTICE)
        self.assertIn("live web search instead of local context", WEB_SEARCH_NOTICE)
        print("PASS: Web search notice explicitly and clearly disclaims using web search over local context.")

    def test_05_stream_routing_payload(self):
        """Verify /api/query/stream accepts queries and emits SSE headers."""
        res = self.client.post(
            "/api/query/stream",
            json={
                "query": "search online for fastAPI documentation",
                "session_id": "test_routing_sess",
                "history": []
            }
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/event-stream", res.headers["content-type"])
        print("PASS: Streaming endpoint correctly mounted with autonomous routing.")

if __name__ == "__main__":
    unittest.main()
