from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routers import auth, business, catalog, clusters, explainer, factories, leaks, onboarding

app = FastAPI(
    title="Induscope API",
    description="Circular Carbon Intelligence backend. Every computed field traces to a "
                "real function call in app/engine, app/intelligence, or ml/ over "
                "real-or-calibrated data (data-pipeline/). Symbiosis matching (ml/symbiosis_model.py) "
                "and the tool-calling explainer (ml/explainer.py, Ollama llama3.1:8b + "
                "deterministic fallback) are live as of Phase 3c/3d.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only — tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal error", "type": type(exc).__name__})


app.include_router(clusters.router)
app.include_router(factories.router)
app.include_router(catalog.router)
app.include_router(onboarding.router)
app.include_router(explainer.router)
app.include_router(explainer.global_router)
app.include_router(business.router)
app.include_router(leaks.router)
app.include_router(auth.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
