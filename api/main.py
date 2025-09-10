from fastapi import FastAPI

# Import all route modules at the top
from api.routes import security, ingest_x, dex, signals_heat, signals_topic, onchain
from api.routes import signals_summary
from api import routes_expert_onchain

app = FastAPI(title="GUIDS API")

# Register all routers
app.include_router(security.router)  # Security routes
app.include_router(ingest_x.router)  # X ingestion routes (Day8)
app.include_router(dex.router)      # DEX routes (Day9)
app.include_router(signals_topic.router)  # Topic signals (Day9.1)
app.include_router(onchain.router)  # Onchain routes (Day10)
app.include_router(signals_heat.router)  # Heat signals (Day15&16-CardC)
app.include_router(signals_summary.router)  # Signals summary routes（day14？）
app.include_router(routes_expert_onchain.router)  # Expert routes（day14）

@app.get("/")
def root():
    return {"message": "API root"}

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}