from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import projects, stakeholders, tasks, transcripts
from app.db import Base, engine
from app.models import models  # noqa: F401  (ensures models are registered before create_all)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI-Powered Meeting and Workflow Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
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
