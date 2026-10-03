from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import os
import uuid

from mugithi_engine import reference_notes, render_song

app = FastAPI(title="Kikuyu AI Music Studio API", version="0.1.0")

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin, "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rendered songs are written here and served back to the web app.
GENERATED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")

# Topic-based lyric templates, kept in sync with music/services/prompt_engine.py.
LYRIC_TEMPLATES = {
    "gikuyu": "[Verse 1]\n{theme}, ngoro yakwa ĩrĩ na gĩkeno\nTũrĩ hamwe, tũigue rũĩmbo rũrĩa rwega\n\n[Chorus]\nŨcio nĩ wega, tũinage hamwe\nWendo na thayũ, thĩinĩ wa ngoro ciitũ\n\n[Interlude - Guitar Solo]\n\n[Verse 2]\nRũciinĩ rũothe, tũcooke hamwe\n{theme}, rũĩmbo rũitũ rũikarage\n\n[Chorus]\nŨcio nĩ wega, tũinage hamwe\nWendo na thayũ, thĩinĩ wa ngoro ciitũ\n\n[Outro]\nTũinage hamwe, tũinage hamwe",
    "swahili": "[Verse 1]\n{theme}, furaha iko moyoni\nTuko pamoja, tusikie wimbo mzuri\n\n[Chorus]\nTuimbe pamoja, kwa upendo na amani\nTusherehekee maisha, kwa sauti moja\n\n[Interlude - Guitar Solo]\n\n[Verse 2]\nKila siku mpya, tumaini linatuchanua\n{theme}, wimbo wetu utaendelea\n\n[Chorus]\nTuimbe pamoja, kwa upendo na amani\nTusherehekee maisha, kwa sauti moja\n\n[Outro]\nTuimbe pamoja, tuimbe pamoja",
    "english": "[Verse 1]\n{theme}, let the good days find us here\nEvery voice together, every heartbeat clear\n\n[Chorus]\nWe sing as one, we dance as one\nOur story carries on and on\n\n[Interlude - Guitar Solo]\n\n[Verse 2]\nThrough every turning, hope will lead the way\n{theme}, we make a brighter day\n\n[Chorus]\nWe sing as one, we dance as one\nOur story carries on and on\n\n[Outro]\nWe sing as one, we sing as one",
}


def generate_lyrics_from_topic(topic: str, language: str = "gikuyu", genre: str = "mugithi") -> str:
    """Generate structured lyrics from a topic using the template catalog."""
    theme = topic.strip().rstrip(".!?。") or "Wendo witũ"
    template = LYRIC_TEMPLATES.get(language.lower(), LYRIC_TEMPLATES["gikuyu"])
    lyrics = template.format(theme=theme)
    if genre.lower() == "mugithi":
        lyrics = lyrics.replace("[Outro]", "[Mũgithi Tempo Switch]\n\n[Outro]", 1)
    return lyrics


# In-memory job output store. In production this lives in Redis / the database.
jobs: Dict[str, dict] = {}


class GenerateSongRequest(BaseModel):
    prompt: str = Field(..., description="Natural language prompt.")
    lyrics: Optional[str] = Field(default="", description="Song lyrics. Auto-generated from the topic when omitted.")
    language: str = Field(default="gikuyu", description="Language of the lyrics")
    genre: str = Field(default="mugithi", description="Desired music genre")
    mood: str = Field(default="joyful", description="Mood of the song")
    instruments: Optional[List[str]] = Field(default_factory=lambda: ["acoustic guitar", "bass"])
    duration_sec: int = Field(default=120, ge=30, le=300)


class GenerateLyricsRequest(BaseModel):
    topic: str = Field(..., description="Topic or theme to write lyrics about.")
    language: str = Field(default="gikuyu")
    genre: str = Field(default="mugithi")
    mood: str = Field(default="joyful")


class GenerateLyricsResponse(BaseModel):
    lyrics: str
    language: str
    topic: str
    references: List[str] = []


class GenerateSongResponse(BaseModel):
    job_id: str
    status: str = "queued"
    message: str = "Song generation started"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    audio_url: Optional[str] = None
    lyrics: Optional[str] = None
    waveform: List[float] = []
    references: List[str] = []
    detail: str = ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate-lyrics", response_model=GenerateLyricsResponse)
def generate_lyrics(req: GenerateLyricsRequest):
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic is required.")
    if req.language.lower() not in {"gikuyu", "swahili", "english"}:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    return GenerateLyricsResponse(
        lyrics=generate_lyrics_from_topic(req.topic, req.language, req.genre),
        language=req.language,
        topic=req.topic,
        references=reference_notes(req.genre),
    )


@app.post("/generate-song", response_model=GenerateSongResponse)
def generate_song(req: GenerateSongRequest, background_tasks: BackgroundTasks):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required.")
    if req.language.lower() not in {"gikuyu", "swahili", "english"}:
        raise HTTPException(status_code=400, detail="Unsupported language.")

    job_id = str(uuid.uuid4())
    lyrics = (req.lyrics or "").strip() or generate_lyrics_from_topic(req.prompt, req.language, req.genre)
    payload = {
        "job_id": job_id,
        "prompt": req.prompt,
        "lyrics": lyrics,
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
        "lyrics": lyrics,
        "waveform": [],
        "references": reference_notes(req.genre),
        "payload": payload,
    }
    background_tasks.add_task(_render_job, job_id)
    return GenerateSongResponse(
        job_id=job_id,
        status="queued",
        message="Song generation started. The worker will process this job asynchronously.",
    )


def _render_job(job_id: str) -> None:
    """Render a real song with the on-device Mugithi-experience engine."""
    job = jobs.get(job_id)
    if job is None:
        return
    job["status"] = "processing"
    try:
        result = render_song(job["payload"], GENERATED_DIR, job_id)
    except Exception as exc:
        job["status"] = "failed"
        job["detail"] = f"Render failed: {exc}"
        return
    job["status"] = "completed"
    job["audio_url"] = f"/generated/{result['filename']}"
    job["waveform"] = result["waveform"]
    job["references"] = result["references"]


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        audio_url=job["audio_url"],
        lyrics=job.get("lyrics"),
        waveform=job.get("waveform", []),
        references=job.get("references", []),
        detail=job.get("detail") or ("Audio output ready." if job["status"] == "completed" else "Generation in progress."),
    )
