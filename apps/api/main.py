from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import os
import time
import uuid

app = FastAPI(title="Kikuyu AI Music Studio API", version="0.1.0")

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin, "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Demo audio used to simulate a finished render until the worker pipeline is wired in.
DEMO_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"

# In-memory job output store. In production this lives in Redis / the database.
jobs: Dict[str, dict] = {}


class GenerateSongRequest(BaseModel):
    prompt: str = Field(..., description="Natural language prompt.")
    lyrics: str = Field(..., description="Song lyrics in Gĩkũyũ, Swahili, or English.")
    language: str = Field(default="gikuyu", description="Language of the lyrics")
    genre: str = Field(default="mugithi", description="Desired music genre")
    mood: str = Field(default="joyful", description="Mood of the song")
    instruments: Optional[List[str]] = Field(default_factory=lambda: ["acoustic guitar", "bass"])
    duration_sec: int = Field(default=120, ge=30, le=300)


class GenerateSongResponse(BaseModel):
    job_id: str
    status: str = "queued"
    message: str = "Song generation started"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    audio_url: Optional[str] = None
    detail: str = ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate-song", response_model=GenerateSongResponse)
def generate_song(req: GenerateSongRequest, background_tasks: BackgroundTasks):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required.")
    if not req.lyrics.strip():
        raise HTTPException(status_code=400, detail="Lyrics are required.")
    if req.language.lower() not in {"gikuyu", "swahili", "english"}:
        raise HTTPException(status_code=400, detail="Unsupported language.")

    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "prompt": req.prompt,
        "lyrics": req.lyrics,
        "language": req.language,
        "genre": req.genre,
        "mood": req.mood,
        "instruments": req.instruments,
        "duration_sec": req.duration_sec,
    }

    # In production, this would publish to Celery / Redis.
    # For demo purposes, we track the job in memory and simulate a finished render
    # so the frontend can poll for its audio output.
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "audio_url": None,
        "payload": payload,
    }
    background_tasks.add_task(_render_job, job_id)
    return GenerateSongResponse(
        job_id=job_id,
        status="queued",
        message="Song generation started. The worker will process this job asynchronously.",
    )


def _render_job(job_id: str) -> None:
    """Simulated render pipeline; replace with worker/Redis result handling."""
    job = jobs.get(job_id)
    if job is None:
        return
    job["status"] = "processing"
    time.sleep(6)
    job["status"] = "completed"
    job["audio_url"] = DEMO_AUDIO_URL


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        audio_url=job["audio_url"],
        detail="Audio output ready." if job["status"] == "completed" else "Generation in progress.",
    )
