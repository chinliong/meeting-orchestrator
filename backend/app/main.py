import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import projects, stakeholders, tasks, transcripts
from app.db import Base, engine
from app.models import models  # noqa: F401  (ensures models are registered before create_all)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI-Powered Meeting and Workflow Orchestrator")

# Comma-separated list of allowed frontend origins. Defaults to "*" (allow any origin),
# which is fine for this public, cookie-less demo API. Set CORS_ORIGINS to lock it down.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
allow_all = CORS_ORIGINS == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # Credentials can't be combined with a wildcard origin; this API uses neither.
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1")
app.include_router(stakeholders.router, prefix="/api/v1")
app.include_router(transcripts.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}
