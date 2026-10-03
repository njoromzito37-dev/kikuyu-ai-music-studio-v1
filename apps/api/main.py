from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import os
import time
import uuid

from mugithi_engine import reference_notes, render_song
from suno_client import SUNO_FUNCTIONS, SunoClient, SunoError

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
    engine: str = "local"
    suno_task_id: Optional[str] = None
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
        "engine": "suno" if SunoClient.from_env() else "local",
        "suno_task_id": None,
        "payload": payload,
    }
    background_tasks.add_task(_render_job, job_id)
    return GenerateSongResponse(
        job_id=job_id,
        status="queued",
        message="Song generation started. The worker will process this job asynchronously.",
    )


def _render_job(job_id: str) -> None:
    """Render via Suno when configured; otherwise the local Mugithi engine."""
    job = jobs.get(job_id)
    if job is None:
        return
    job["status"] = "processing"
    try:
        suno = SunoClient.from_env()
        if suno:
            _render_job_suno(job, suno)
            return
        result = render_song(job["payload"], GENERATED_DIR, job_id)
        job["status"] = "completed"
        job["audio_url"] = f"/generated/{result['filename']}"
        job["waveform"] = result["waveform"]
        job["references"] = result["references"]
    except Exception as exc:
        job["status"] = "failed"
        job["detail"] = f"Render failed: {exc}"


def _render_job_suno(job, suno: SunoClient) -> None:
    """Submit the song to Suno in custom mode and poll until audio is ready."""
    payload = job["payload"]
    style = f"{payload['genre']}, {payload['mood']}, Kikuyu East African, " + ", ".join(
        r.split(": ", 1)[-1] for r in job["references"][:2]
    )
    title = payload["prompt"][:80]
    result = suno.generate_custom(prompt=payload["lyrics"], style=style, title=title)
    task_id = result.get("taskId")
    if not task_id:
        raise SunoError("Suno did not return a taskId.")
    job["suno_task_id"] = task_id

    for _ in range(60):  # poll up to ~5 minutes
        time.sleep(5)
        info = suno.get_status(task_id)
        status = (info.get("status") or "").upper()
        if status == "SUCCESS":
            clips = (info.get("response") or {}).get("sunoData") or []
            if not clips or not clips[0].get("audioUrl"):
                raise SunoError("Suno finished without audio output.")
            job["status"] = "completed"
            job["audio_url"] = clips[0]["audioUrl"]
            job["detail"] = "Generated by Suno AI."
            return
        if "FAILED" in status or status in ("CREATE_TASK_FAILED", "SENSITIVE_WORD_ERROR"):
            raise SunoError(f"Suno generation failed ({status}).")
    raise SunoError("Suno generation timed out.")


# ---------------------------------------------------------------------------
# Suno functions - every Suno capability, proxied (requires SUNO_API_KEY)
# ---------------------------------------------------------------------------


def _suno() -> SunoClient:
    client = SunoClient.from_env()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Suno is not configured. Set SUNO_API_KEY (and optionally SUNO_API_BASE) to enable all Suno functions.",
        )
    return client


@app.get("/suno/enabled")
def suno_enabled():
    """Capability report for the UI: whether Suno is wired and which functions are on."""
    return {"enabled": SunoClient.from_env() is not None, "functions": SUNO_FUNCTIONS}


@app.post("/suno/generate")
def suno_generate(body: Dict[str, Any]):
    """Custom or description-mode generation."""
    try:
        client = _suno()
        if body.get("customMode", True):
            return client.generate_custom(
                prompt=body.get("prompt", ""),
                style=body.get("style", ""),
                title=body.get("title", "Untitled"),
                instrumental=body.get("instrumental", False),
                model=body.get("model", "V4_5"),
                callback_url=body.get("callBackUrl"),
            )
        return client.generate_description(
            description=body.get("prompt", ""),
            instrumental=body.get("instrumental", False),
            model=body.get("model", "V4_5"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/lyrics")
def suno_lyrics(body: Dict[str, Any]):
    try:
        return _suno().generate_lyrics(body.get("prompt", ""), body.get("callBackUrl"))
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/extend")
def suno_extend(body: Dict[str, Any]):
    try:
        return _suno().extend(
            audio_id=body["audioId"],
            prompt=body.get("prompt", ""),
            style=body.get("style", ""),
            title=body.get("title", ""),
            continue_at=body.get("continueAt", 0),
            model=body.get("model", "V4_5"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/cover")
def suno_cover(body: Dict[str, Any]):
    try:
        return _suno().cover(
            audio_id=body["audioId"],
            prompt=body.get("prompt", ""),
            style=body.get("style", ""),
            title=body.get("title", ""),
            model=body.get("model", "V4_5"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/upload-extend")
def suno_upload_extend(body: Dict[str, Any]):
    try:
        return _suno().upload_extend(
            upload_url=body["uploadUrl"],
            prompt=body.get("prompt", ""),
            style=body.get("style", ""),
            title=body.get("title", ""),
            continue_at=body.get("continueAt", 0),
            model=body.get("model", "V4_5"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/upload-cover")
def suno_upload_cover(body: Dict[str, Any]):
    try:
        return _suno().upload_cover(
            upload_url=body["uploadUrl"],
            prompt=body.get("prompt", ""),
            style=body.get("style", ""),
            title=body.get("title", ""),
            model=body.get("model", "V4_5"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/add-vocals")
def suno_add_vocals(body: Dict[str, Any]):
    try:
        return _suno().add_vocals(
            upload_url=body["uploadUrl"],
            prompt=body.get("prompt", ""),
            style=body.get("style", ""),
            title=body.get("title", ""),
            model=body.get("model", "V4_5"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/add-instrumental")
def suno_add_instrumental(body: Dict[str, Any]):
    try:
        return _suno().add_instrumental(
            upload_url=body["uploadUrl"],
            title=body.get("title", ""),
            tags=body.get("tags", ""),
            model=body.get("model", "V4_5"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/stems")
def suno_stems(body: Dict[str, Any]):
    """Vocal/instrumental stem separation."""
    try:
        return _suno().separate_stems(
            task_id=body["taskId"],
            audio_id=body["audioId"],
            stem_type=body.get("type", "vocal"),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/suno/stems/{task_id}")
def suno_stems_status(task_id: str):
    try:
        return _suno().get_stems_status(task_id)
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/convert-wav")
def suno_convert_wav(body: Dict[str, Any]):
    try:
        return _suno().convert_wav(task_id=body["taskId"], audio_id=body["audioId"], callback_url=body.get("callBackUrl"))
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/suno/wav/{task_id}")
def suno_wav_status(task_id: str):
    try:
        return _suno().get_wav_status(task_id)
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/timestamps")
def suno_timestamps(body: Dict[str, Any]):
    """Word/line-aligned timestamped lyrics for a clip."""
    try:
        return _suno().timestamped_lyrics(task_id=body["taskId"], audio_id=body["audioId"])
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/concat")
def suno_concat(body: Dict[str, Any]):
    try:
        return _suno().concat(task_id=body["taskId"], clips=body.get("clips", []))
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/mashup")
def suno_mashup(body: Dict[str, Any]):
    try:
        return _suno().mashup(task_ids=body.get("taskIdList", []), model=body.get("model", "V4_5"), callback_url=body.get("callBackUrl"))
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/persona")
def suno_persona(body: Dict[str, Any]):
    """Create a reusable persona (voice/style) from a clip."""
    try:
        return _suno().create_persona(
            task_id=body["taskId"],
            audio_id=body["audioId"],
            name=body.get("name", ""),
            description=body.get("description", ""),
            callback_url=body.get("callBackUrl"),
        )
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/suno/boost-style")
def suno_boost_style(body: Dict[str, Any]):
    """Enhance a raw style description into rich Suno style tags."""
    try:
        return _suno().boost_style(content=body.get("content", ""))
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/suno/status/{task_id}")
def suno_status(task_id: str):
    try:
        return _suno().get_status(task_id)
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/suno/lyrics/{task_id}")
def suno_lyrics_status(task_id: str):
    try:
        return _suno().get_lyrics_status(task_id)
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/suno/quota")
def suno_quota():
    try:
        return _suno().get_quota()
    except SunoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
        engine=job.get("engine", "local"),
        suno_task_id=job.get("suno_task_id"),
        detail=job.get("detail") or ("Audio output ready." if job["status"] == "completed" else "Generation in progress."),
    )
