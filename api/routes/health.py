"""Health check route module"""
from fastapi import APIRouter

router = APIRouter()

@router.get("/healthz")
def healthz():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy"}

@router.get("/health")
def health():
    """Alternative health check endpoint"""
    return {"status": "healthy"}