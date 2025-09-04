from fastapi import FastAPI
import os

# Import all route modules at the top
from api.routes import security, ingest_x, dex, signals_topic

app = FastAPI(title="GUIDS API")

SQLALCHEMY_DATABASE_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost/dbname")

# Register all routers
app.include_router(security.router)  # Security routes
app.include_router(ingest_x.router)  # X ingestion routes (Day8)
app.include_router(dex.router)      # DEX routes (Day9)
app.include_router(signals_topic.router)  # Topic signals (Day9.1)

@app.get("/")
def root():
    return {"message": "API root"}

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}