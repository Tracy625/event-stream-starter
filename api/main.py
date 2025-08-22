from fastapi import FastAPI
import os

app = FastAPI()

SQLALCHEMY_DATABASE_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost/dbname")

@app.get("/")
def root():
    return {"message": "API root"}

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}