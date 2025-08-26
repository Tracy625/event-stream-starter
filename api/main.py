from fastapi import FastAPI
import os

app = FastAPI()

SQLALCHEMY_DATABASE_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost/dbname")

# Import and register security routes
from api.routes import security
app.include_router(security.router)

@app.get("/")
def root():
    return {"message": "API root"}

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}