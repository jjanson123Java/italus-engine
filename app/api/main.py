from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.health import router as health_router
from app.api.routes.project import router as project_router
from app.api.routes.books import router as books_router


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(title="Narrative Studio API", version="0.1.0")

app.include_router(health_router)
app.include_router(project_router)
app.include_router(books_router)

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")


@app.get("/", include_in_schema=False)
def landing_page():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/styles.css", include_in_schema=False)
def styles():
    return FileResponse(FRONTEND_DIR / "styles.css")


@app.get("/script.js", include_in_schema=False)
def script():
    return FileResponse(FRONTEND_DIR / "script.js")


@app.get("/workspace", include_in_schema=False)
def workspace_page():
    return FileResponse(FRONTEND_DIR / "workspace.html")
    

@app.get("/help", include_in_schema=False)
def help_page():
    return FileResponse(FRONTEND_DIR / "pages" / "help.html")



@app.get("/workspace.css", include_in_schema=False)
def workspace_styles():
    return FileResponse(FRONTEND_DIR / "workspace.css")


@app.get("/workspace.js", include_in_schema=False)
def workspace_script():
    return FileResponse(FRONTEND_DIR / "workspace.js")
