"""Song-generation provider seam.

The Celery generation task renders audio through a pluggable provider so the
product layer never cares whether songs come from a hosted API or a
self-hosted model:

* ``HttpSongProvider`` — POSTs the generation payload to
  ``GENERATION_BACKEND_URL`` (any synchronous text-to-music service that
  returns audio bytes or JSON with an ``audio_url``). This is the historical
  default.
* ``YuESongProvider`` — self-hosted full-song rendering with YuE
  (https://github.com/multimodal-art-projection/YuE): lyrics + genre tags in,
  a sung .wav out. Requires a CUDA GPU worker, the YuE repo cloned to
  ``YUE_REPO_DIR``, and the stage-1/stage-2 checkpoints downloaded.

Select with ``GENERATION_PROVIDER=http|yue``. Provider payloads include a
``phonemes`` field (Gĩkũyũ G2P output from services.g2p) which phoneme-aware
backends can use for lyric alignment; the YuE wrapper writes it next to the
lyrics file for Kikuyu-adapted forks to consume.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

DOWNLOAD_CHUNK_BYTES = 64 * 1024


class SongRenderError(RuntimeError):
    """Raised when a generation provider fails to produce audio."""


class HttpSongProvider:
    """Hosted backend: POST the payload, stream back audio (current behavior)."""

    name = "http"

    def __init__(self, endpoint: str, api_key: str = "", timeout: int = 600, max_bytes: int = 100 * 1024 * 1024):
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self.max_bytes = max_bytes

    def render(self, payload: Mapping, out_dir: Path, filename_hint: str = "song") -> Path:
        if not self.endpoint:
            raise SongRenderError("GENERATION_BACKEND_URL is not configured.")
        headers = {"Accept": "audio/*, application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = requests.post(
            self.endpoint,
            json=dict(payload),
            headers=headers,
            stream=True,
            timeout=(30, self.timeout),
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/json" in content_type:
            body = response.json()
            audio_url = body.get("audio_url")
            if not audio_url:
                raise SongRenderError("Generation provider JSON response must include audio_url.")
            response = requests.get(audio_url, stream=True, timeout=(30, self.timeout))
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()

        suffix = ".mp3" if "mpeg" in content_type or "mp3" in content_type else ".ogg" if "ogg" in content_type else ".wav"
        out_path = Path(out_dir) / f"{filename_hint}{suffix}"
        size = 0
        with open(out_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_bytes:
                    raise SongRenderError("Generated audio exceeds the configured size limit.")
                handle.write(chunk)
        if size == 0:
            raise SongRenderError("Generation provider returned an empty audio stream.")
        return out_path


class YuESongProvider:
    """Self-hosted YuE renderer (open-source lyrics+style -> sung song).

    Setup on the GPU worker:
        git clone https://github.com/multimodal-art-projection/YuE $YUE_REPO_DIR
        huggingface-cli download m-a-p/YuE-s1-7B-anneal-en-cot  # stage 1
        huggingface-cli download m-a-p/YuE-s2-1B-general        # stage 2
    """

    name = "yue"

    def __init__(
        self,
        repo_dir: str,
        stage1_model: str,
        stage2_model: str,
        max_new_tokens: int = 4800,
        cuda_idx: str = "0",
        timeout: int = 3600,
        python_bin: str | None = None,
    ):
        self.repo_dir = repo_dir
        self.stage1_model = stage1_model
        self.stage2_model = stage2_model
        self.max_new_tokens = max_new_tokens
        self.cuda_idx = cuda_idx
        self.timeout = timeout
        self.python_bin = python_bin or shutil.which("python") or "python"

    def render(self, payload: Mapping, out_dir: Path, filename_hint: str = "song") -> Path:
        repo = Path(self.repo_dir)
        infer_script = repo / "src" / "yue" / "infer.py"
        if not infer_script.exists():
            raise SongRenderError(
                f"YuE is not installed at {repo} (expected {infer_script}). Clone the YuE repo and set "
                "YUE_REPO_DIR, or switch GENERATION_PROVIDER back to 'http'."
            )
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        genre_txt = out_dir / f"{filename_hint}-genre.txt"
        lyrics_txt = out_dir / f"{filename_hint}-lyrics.txt"
        genre_txt.write_text(str(payload.get("prompt", "")), encoding="utf-8")
        lyrics_txt.write_text(str(payload.get("lyrics", "")), encoding="utf-8")
        # Phoneme conditioning: written alongside the lyrics for
        # Kikuyu-adapted YuE forks; stock YuE simply ignores the file.
        phonemes = str(payload.get("phonemes") or "")
        if phonemes:
            (out_dir / f"{filename_hint}-phonemes.txt").write_text(phonemes, encoding="utf-8")

        cmd = [
            self.python_bin,
            str(infer_script),
            "--cuda_idx", str(self.cuda_idx),
            "--stage1_model", self.stage1_model,
            "--stage2_model", self.stage2_model,
            "--genre_txt", str(genre_txt),
            "--lyrics_txt", str(lyrics_txt),
            "--output_dir", str(out_dir),
            "--max_new_tokens", str(self.max_new_tokens),
        ]
        logger.info("Rendering song with YuE: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=self.timeout)
        except subprocess.CalledProcessError as exc:
            raise SongRenderError(f"YuE inference failed: {exc.stderr.decode(errors='replace')[-500:]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SongRenderError("YuE inference timed out.") from exc

        candidates = sorted(out_dir.glob("*.wav"), key=lambda path: path.stat().st_mtime)
        if not candidates:
            raise SongRenderError("YuE produced no audio output.")
        return candidates[-1]


def get_provider(kind: str | None = None):
    """Build the configured song-generation provider from Django settings."""
    kind = (kind or getattr(settings, "GENERATION_PROVIDER", "http")).lower()
    if kind == "yue":
        return YuESongProvider(
            repo_dir=settings.YUE_REPO_DIR,
            stage1_model=settings.YUE_STAGE1_MODEL,
            stage2_model=settings.YUE_STAGE2_MODEL,
            max_new_tokens=settings.YUE_MAX_NEW_TOKENS,
            cuda_idx=settings.YUE_CUDA_IDX,
            timeout=settings.YUE_TIMEOUT,
        )
    if kind == "http":
        return HttpSongProvider(
            endpoint=settings.GENERATION_BACKEND_URL,
            api_key=settings.GENERATION_BACKEND_API_KEY,
            timeout=settings.GENERATION_BACKEND_TIMEOUT,
            max_bytes=settings.GENERATION_MAX_AUDIO_BYTES,
        )
    raise ImproperlyConfigured(f"Unknown GENERATION_PROVIDER {kind!r}; expected 'http' or 'yue'.")
