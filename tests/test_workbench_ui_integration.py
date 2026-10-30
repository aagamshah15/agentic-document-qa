"""
Dimension — Autonomous Data & Schema Studio
Workbench UI Integration & Verification Suite.
Validates the 6-View Studio Architecture, HTML assets, static resources, and v2 REST endpoints.
"""

import unittest
from fastapi.testclient import TestClient
from main import app


class TestWorkbenchUIIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Entering the client runs the startup hook, which seeds the demo stores
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_root_index_html_renders_all_6_views_and_modals(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 1. Navigation Tabs
        self.assertIn('class="studio-view-tabs"', html)
        self.assertIn('data-view="chat"', html)
        self.assertIn('data-view="map"', html)
        self.assertIn('data-view="findings"', html)
        self.assertIn('data-view="changes"', html)
        self.assertIn('data-view="glossary"', html)
        self.assertIn('data-view="seeds"', html)

        # 2. Connection Selector
        self.assertIn('id="active-connection-select"', html)
        self.assertIn('id="conn-tier-indicator"', html)

        # 3. View Containers
        self.assertIn('id="view-chat"', html)
        self.assertIn('id="view-map"', html)
        self.assertIn('id="view-findings"', html)
        self.assertIn('id="view-changes"', html)
        self.assertIn('id="view-glossary"', html)
        self.assertIn('id="view-seeds"', html)

        # 4. Modals
        self.assertIn('id="db-modal"', html)
        self.assertIn('id="new-proposal-modal"', html)
        self.assertIn('id="approval-modal"', html)
        self.assertIn('id="new-glossary-modal"', html)
        self.assertIn('id="code-viewer-modal"', html)

        # 5. Script Tags
        self.assertIn('src="/static/studio_workbench.js"', html)
        self.assertIn('src="/static/app.js"', html)

    def test_static_workbench_script_served(self):
        res = self.client.get("/static/studio_workbench.js")
        self.assertEqual(res.status_code, 200)
        js = res.text
        self.assertIn("DimensionStudioWorkbench", js)
        self.assertIn("switchView", js)
        self.assertIn("loadMap", js)
        self.assertIn("loadFindings", js)
        self.assertIn("loadProposals", js)
        self.assertIn("loadGlossary", js)
        self.assertIn("loadSeedPlan", js)

    def test_static_styles_contain_studio_design_tokens(self):
        res = self.client.get("/static/styles.css")
        self.assertEqual(res.status_code, 200)
        css = res.text
        self.assertIn(".studio-view-tabs", css)
        self.assertIn(".studio-tab-btn", css)
        self.assertIn(".erd-table-card", css)
        self.assertIn(".finding-card", css)
        self.assertIn(".proposal-card", css)
        self.assertIn(".glossary-card", css)
        self.assertIn(".dag-step-node", css)

    def test_connections_api_returns_seeded_demo_stores(self):
        res = self.client.get("/api/v2/connections")
        self.assertEqual(res.status_code, 200)
        conns = res.json().get("connections", [])
        self.assertGreater(len(conns), 0)

        # Verify properties
        conn = conns[0]
        self.assertIn("id", conn)
        self.assertIn("name", conn)
        self.assertIn("engine", conn)
        self.assertIn("tier", conn)

    def test_end_to_end_views_api_flow(self):
        # 1. Fetch connection list
        res_conns = self.client.get("/api/v2/connections")
        conns = res_conns.json()["connections"]
        self.assertTrue(len(conns) > 0)
        target_conn = conns[0]["id"]

        # 2. View 2: Map graph
        res_graph = self.client.get(f"/api/v2/connections/{target_conn}/graph")
        self.assertEqual(res_graph.status_code, 200)
        self.assertIn("nodes", res_graph.json()["graph"])
        self.assertIn("edges", res_graph.json()["graph"])

        # 3. View 3: Findings
        res_findings = self.client.get(f"/api/v2/connections/{target_conn}/findings")
        self.assertEqual(res_findings.status_code, 200)
        self.assertIn("findings", res_findings.json())

        # 4. View 4: Proposals
        res_props = self.client.get(f"/api/v2/connections/{target_conn}/proposals")
        self.assertEqual(res_props.status_code, 200)
        self.assertIn("proposals", res_props.json())

        # 5. View 5: Glossary
        res_gloss = self.client.get(f"/api/v2/connections/{target_conn}/glossary")
        self.assertEqual(res_gloss.status_code, 200)
        self.assertIn("entries", res_gloss.json())

        # 6. View 6: Seed Plan
        res_seed = self.client.post(f"/api/v2/connections/{target_conn}/seed-plans", json={})
        self.assertEqual(res_seed.status_code, 200)
        self.assertIn("topological_order", res_seed.json()["plan"])


if __name__ == "__main__":
    unittest.main()
