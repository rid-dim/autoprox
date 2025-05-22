from fastapi import APIRouter

router = APIRouter(prefix="/v0", tags=["health"])

@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok"} 