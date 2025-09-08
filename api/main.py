from fastapi import FastAPI
import os

# Import all route modules at the top
from api.routes import security, ingest_x, dex, signals_topic, onchain
from api import routes_signals
from api import routes_expert_onchain

app = FastAPI(title="GUIDS API")

SQLALCHEMY_DATABASE_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost/dbname")

# Register all routers
app.include_router(security.router)  # Security routes
app.include_router(ingest_x.router)  # X ingestion routes (Day8)
app.include_router(dex.router)      # DEX routes (Day9)
app.include_router(signals_topic.router)  # Topic signals (Day9.1)
app.include_router(onchain.router)  # Onchain routes (Day10)
app.include_router(routes_signals.router, prefix="/signals", tags=["signals"])
app.include_router(routes_expert_onchain.router)  # Expert routes

@app.get("/")
def root():
    return {"message": "API root"}

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}