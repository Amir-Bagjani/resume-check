from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .routes_runs import router as runs_router

app = FastAPI(title="Resume Screening API")

app.include_router(runs_router, prefix="/api")

frontend_dir = Path(__file__).parent.parent.parent / "frontend"


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ponytail: static mount last at root; html=True serves index.html at /,
# and styles.css / js/*.js resolve relatively. API routes take precedence.
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")