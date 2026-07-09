from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "application": "Narrative Studio",
        "version": "0.1.0",
    }


@router.get("/api/health")
def api_health():
    return health()
