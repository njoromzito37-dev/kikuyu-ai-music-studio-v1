import logging
import os
import shutil
import subprocess
import tempfile
from array import array

import requests
from celery import shared_task
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import transaction

from .models import Song

logger = logging.getLogger(__name__)
WAVEFORM_BUCKETS = 256
DOWNLOAD_CHUNK_BYTES = 64 * 1024


def _provider_audio(response, song):
    content_type = response.headers.get("Content-Type", "").lower()
    if "application/json" in content_type:
        payload = response.json()
        audio_url = payload.get("audio_url")
        if not audio_url:
            raise ValueError("Generation provider JSON response must include audio_url.")
        audio_response = requests.get(audio_url, stream=True, timeout=(30, settings.GENERATION_BACKEND_TIMEOUT))
        audio_response.raise_for_status()
        response = audio_response
        content_type = response.headers.get("Content-Type", "").lower()

    suffix = ".mp3" if "mpeg" in content_type or "mp3" in content_type else ".ogg" if "ogg" in content_type else ".wav"
    maximum = settings.GENERATION_MAX_AUDIO_BYTES
    output = bytearray()
    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
        if not chunk:
            continue
        output.extend(chunk)
        if len(output) > maximum:
            raise ValueError("Generated audio exceeds the configured size limit.")
    if not output:
        raise ValueError("Generation provider returned an empty audio stream.")
    filename = f"song-{song.pk}{suffix}"
    return ContentFile(bytes(output), name=filename)


def _waveform(path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg is not installed; saving generated audio without waveform data")
        return []
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-i", path, "-ac", "1", "-ar", "8000", "-f", "f32le", "pipe:1"],
        check=True,
        capture_output=True,
        timeout=90,
    )
    samples = array("f")
    samples.frombytes(result.stdout[: len(result.stdout) - (len(result.stdout) % samples.itemsize)])
    if not samples:
        return []
    if os.sys.byteorder != "little":
        samples.byteswap()
    bucket_size = max(1, len(samples) // WAVEFORM_BUCKETS)
    peaks = []
    for start in range(0, len(samples), bucket_size):
        bucket = samples[start : start + bucket_size]
        peaks.append(round(max((abs(value) for value in bucket), default=0.0), 4))
        if len(peaks) >= WAVEFORM_BUCKETS:
            break
    return peaks


@shared_task(bind=True, max_retries=2, default_retry_delay=30, name="music.generate_song")
def generate_song_task(self, song_id):
    try:
        with transaction.atomic():
            song = Song.objects.select_for_update().select_related("genre").get(pk=song_id)
            if song.status == Song.Status.COMPLETED:
                return {"song_id": song.pk, "status": song.status}
            song.status = Song.Status.PROCESSING
            song.failure_reason = ""
            song.generation_task_id = self.request.id or ""
            song.save(update_fields=["status", "failure_reason", "generation_task_id", "updated_at"])

        endpoint = settings.GENERATION_BACKEND_URL
        if not endpoint:
            raise RuntimeError("GENERATION_BACKEND_URL is not configured.")
        headers = {"Accept": "audio/*, application/json"}
        if settings.GENERATION_BACKEND_API_KEY:
            headers["Authorization"] = f"Bearer {settings.GENERATION_BACKEND_API_KEY}"
        payload = {
            "prompt": song.compiled_ai_prompt,
            "lyrics": song.generated_lyrics,
            "language": song.language,
            "genre": song.genre.slug,
            "mood": song.mood,
            "instruments": list(song.chosen_instruments.values_list("slug", flat=True)),
            "duration_seconds": song.duration,
            "tempo_bpm": song.tempo_bpm,
        }
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            stream=True,
            timeout=(30, settings.GENERATION_BACKEND_TIMEOUT),
        )
        response.raise_for_status()
        audio_content = _provider_audio(response, song)

        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(audio_content.name)[1]) as temporary_audio:
            for chunk in audio_content.chunks():
                temporary_audio.write(chunk)
            temporary_audio.flush()
            waveform = _waveform(temporary_audio.name)
            temporary_audio.seek(0)
            with transaction.atomic():
                song = Song.objects.select_for_update().get(pk=song_id)
                song.audio_file.save(audio_content.name, File(temporary_audio), save=False)
                song.audio_waveform_data = waveform
                song.status = Song.Status.COMPLETED
                song.failure_reason = ""
                song.save(update_fields=["audio_file", "audio_waveform_data", "status", "failure_reason", "updated_at"])
        return {"song_id": song.pk, "status": song.status, "audio": song.audio_file.name}
    except Song.DoesNotExist:
        logger.info("Song %s disappeared before its generation task ran", song_id)
        return {"song_id": song_id, "status": "missing"}
    except Exception as exc:
        logger.exception("Song generation failed for song %s", song_id)
        Song.objects.filter(pk=song_id).update(
            status=Song.Status.FAILED,
            failure_reason="Generation failed. Please retry later.",
        )
        raise