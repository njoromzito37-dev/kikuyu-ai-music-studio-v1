from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid

app = FastAPI(title="Kikuyu AI Music Studio API", version="0.1.0")


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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate-song", response_model=GenerateSongResponse)
def generate_song(req: GenerateSongRequest):
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
    # For demo purposes, we return the job contract immediately.
    return GenerateSongResponse(
        job_id=job_id,
        status="queued",
        message="Song generation started. The worker will process this job asynchronously.",
    )
