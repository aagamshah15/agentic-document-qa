import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import router
from api.routes_db import router as db_router
from api.routes_v2 import router as v2_router

app = FastAPI(
    title="Dimension Data & Schema Studio API",
    description="Autonomous Data & Schema Intelligence Studio with DuckDB, SQLAlchemy, and Agentic Data Toolkits.",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(db_router, prefix="/api")
app.include_router(v2_router, prefix="/api")

# Mount the frontend directory to serve static files (CSS, JS)
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.on_event("startup")
def bootstrap_demo_connections():
    """Ensures demo databases (clean e-commerce and messy retail) are registered in StudioAppDB on launch."""
    try:
        from services.app_db import StudioAppDB
        from services.connector import StudioConnector
        from services.catalog import MetadataCatalog
        from experiments.fixtures.generator import generate_shop_messy_fixture

        app_db = StudioAppDB()
        existing = app_db.list_connections()
        existing_paths = {c.get("dsn_template") for c in existing}

        # 1. Clean E-Commerce
        ecom_path = os.path.abspath("data/sample_datasets/ecommerce.sqlite")
        if os.path.exists(ecom_path) and ecom_path not in existing_paths:
            cid = app_db.create_connection(
                name="Demo E-Commerce Store",
                engine="sqlite",
                dsn_template=ecom_path,
                tier="sandbox",
                privilege_grade="B",
            )
            eng = StudioConnector.create_managed_engine("sqlite", ecom_path, read_only=True)
            MetadataCatalog(app_db=app_db).capture_and_record_snapshot(cid, eng, source="bootstrap")

        # 2. Messy Retail (Planted traps & hygiene benchmark)
        messy_path = os.path.abspath("data/sample_datasets/shop_messy.db")
        if not os.path.exists(messy_path):
            generate_shop_messy_fixture(os.path.dirname(messy_path))

        if os.path.exists(messy_path) and messy_path not in existing_paths:
            cid2 = app_db.create_connection(
                name="Messy Retail (Hygiene Benchmark)",
                engine="sqlite",
                dsn_template=messy_path,
                tier="dev",
                privilege_grade="B",
            )
            eng2 = StudioConnector.create_managed_engine("sqlite", messy_path, read_only=True)
            MetadataCatalog(app_db=app_db).capture_and_record_snapshot(cid2, eng2, source="bootstrap")
    except Exception as e:
        print("[Studio Startup] Demo bootstrap note:", e)
