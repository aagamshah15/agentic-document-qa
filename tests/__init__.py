"""Automated tests for the document Q&A application."""

import os
import tempfile

# Keep tests out of the real data/studio_app.db: routes_v2 and the services build a
# default StudioAppDB at import time, so this must be set before they are imported.
_TEST_APP_DB_DIR = tempfile.mkdtemp(prefix="studio_test_app_db_")
os.environ.setdefault("STUDIO_APP_DB_PATH", os.path.join(_TEST_APP_DB_DIR, "studio_app.db"))
