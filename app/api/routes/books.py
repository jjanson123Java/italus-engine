from fastapi import APIRouter, HTTPException

from app.registry import load_books

router = APIRouter(tags=["Books"])


@router.get("/api/books")
def get_books():
    try:
        return {
            "status": "ok",
            "books": load_books(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/books")
def get_books_compat():
    return get_books()
