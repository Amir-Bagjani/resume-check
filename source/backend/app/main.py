import mimetypes

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .paths import frontend_dir
from .routes_runs import router as runs_router

# Windows registry MIME registrations can label modules as text/plain.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")

app = FastAPI(title="Resume Screening API")

app.include_router(runs_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.middleware("http")
async def loopback_guard(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host not in ("127.0.0.1", "localhost", "::1", "testserver"):
            return JSONResponse(status_code=403, content={"detail": "دسترسی مجاز نیست."})
        origin = request.headers.get("origin")
        if origin:
            o = origin.lower()
            if not (o.startswith("http://127.0.0.1") or o.startswith("http://localhost")):
                return JSONResponse(status_code=403, content={"detail": "دسترسی مجاز نیست."})
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


_frontend = frontend_dir()
if not _frontend.is_dir():
    raise RuntimeError(f"پوشه رابط کاربری یافت نشد: {_frontend}")

# ponytail: static mount last at root; html=True serves index.html at /,
# and styles.css / js/*.js resolve relatively. API routes take precedence.
app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
