import logging
import os
import shutil
import subprocess
import tempfile
from array import array
from pathlib import Path

from celery import shared_task
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .models import DjMixJob, DjRenderJob, Song, Stem
from .services import dj_tools, g2p, song_generator

logger = logging.getLogger(__name__)
WAVEFORM_BUCKETS = 256


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

        payload = {
            "prompt": song.compiled_ai_prompt,
            "lyrics": song.generated_lyrics,
            "language": song.language,
            "genre": song.genre.slug,
            "mood": song.mood,
            "instruments": list(song.chosen_instruments.values_list("slug", flat=True)),
            "duration_seconds": song.duration,
            "tempo_bpm": song.tempo_bpm,
            # Phoneme-level lyric conditioning (Gĩkũyũ G2P) for phoneme-aware backends.
            "phonemes": g2p.lyric_phonemes(song.generated_lyrics, song.language),
        }
        provider = song_generator.get_provider()
        with tempfile.TemporaryDirectory() as work_dir:
            audio_path = provider.render(payload, Path(work_dir), filename_hint=f"song-{song.pk}")
            waveform = _waveform(str(audio_path))
            with transaction.atomic():
                song = Song.objects.select_for_update().get(pk=song_id)
                with open(audio_path, "rb") as handle:
                    song.audio_file.save(f"{audio_path.stem}{audio_path.suffix}", File(handle), save=False)
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


# ---------------------------------------------------------------------------
# DJ / live-mixing tasks
# ---------------------------------------------------------------------------

def _load_song_audio(song):
    """Decode a song's stored audio_file to (samples, sample_rate) via dj_tools."""
    suffix = os.path.splitext(song.audio_file.name)[1] or ".wav"
    with song.audio_file.open("rb") as handle:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            shutil.copyfileobj(handle, temporary)
            temporary_path = temporary.name
    try:
        return dj_tools.load_audio(temporary_path)
    finally:
        os.unlink(temporary_path)


def _track_analysis(song, samples, sample_rate):
    """Return (bpm, key_dict) for a track, persisting newly computed values."""
    bpm = float(song.tempo_bpm) if song.tempo_bpm else dj_tools.estimate_bpm(samples, sample_rate)
    if song.musical_key and song.camelot:
        parts = song.musical_key.split()
        key = {
            "key": song.musical_key,
            "camelot": song.camelot,
            "root": parts[0] if parts else "",
            "mode": parts[-1] if len(parts) > 1 else "major",
        }
    else:
        key = dj_tools.estimate_key(samples, sample_rate)
    update_fields = []
    if bpm and not song.tempo_bpm:
        song.tempo_bpm = int(round(bpm))
        update_fields.append("tempo_bpm")
    if key and not song.musical_key:
        song.musical_key = key.get("key", "")
        song.camelot = key.get("camelot", "")
        update_fields += ["musical_key", "camelot"]
    if not song.cue_points:
        song.cue_points = dj_tools.auto_cue_points(samples, sample_rate, bpm=bpm)
        update_fields.append("cue_points")
    if update_fields:
        update_fields.append("updated_at")
        song.save(update_fields=update_fields)
    return bpm, key


@shared_task(bind=True, max_retries=1, name="music.analyze_song")
def analyze_song_task(self, song_id):
    """Detect BPM, musical key and auto-cue markers for a song."""
    try:
        song = Song.objects.get(pk=song_id)
    except Song.DoesNotExist:
        return {"song_id": song_id, "status": "missing"}
    if not song.audio_file:
        return {"song_id": song_id, "status": "no_audio"}
    samples, sample_rate = _load_song_audio(song)
    bpm, key = _track_analysis(song, samples, sample_rate)
    return {"song_id": song.pk, "bpm": bpm, "key": key, "cues": len(song.cue_points)}


@shared_task(bind=True, max_retries=1, name="music.split_song_stems")
def split_song_stems_task(self, song_id):
    """Separate a song into vocals / bass / drums / melody stems."""
    try:
        song = Song.objects.get(pk=song_id)
    except Song.DoesNotExist:
        return {"song_id": song_id, "status": "missing"}
    if not song.audio_file:
        return {"song_id": song_id, "status": "no_audio"}
    try:
        samples, sample_rate = _load_song_audio(song)
        stems = dj_tools.split_stems_placeholder(samples, sample_rate)
        with transaction.atomic():
            song.stems.all().delete()
            for kind, data in stems.items():
                temporary_path = dj_tools.render_to_temp_file(data, sample_rate, ".wav")
                try:
                    with open(temporary_path, "rb") as handle:
                        stem = Stem(song=song, kind=kind)
                        stem.audio_file.save(f"song-{song.pk}-{kind}.wav", File(handle), save=True)
                finally:
                    os.unlink(temporary_path)
        return {"song_id": song.pk, "stems": sorted(stems)}
    except Exception:
        logger.exception("Stem separation failed for song %s", song_id)
        raise


@shared_task(bind=True, max_retries=1, name="music.dj_process")
def process_audio_task(self, job_id):
    """Run a DjRenderJob's DSP chain (tempo, key, EQ, effects) over its source song."""
    try:
        job = DjRenderJob.objects.select_related("source_song").get(pk=job_id)
    except DjRenderJob.DoesNotExist:
        return {"job_id": job_id, "status": "missing"}
    if job.status == DjRenderJob.Status.COMPLETED:
        return {"job_id": job_id, "status": job.status}
    DjRenderJob.objects.filter(pk=job_id).update(
        status=DjRenderJob.Status.PROCESSING,
        task_id=self.request.id or "",
        failure_reason="",
    )
    try:
        samples, sample_rate = _load_song_audio(job.source_song)
        rendered = dj_tools.run_chain(samples, sample_rate, job.operations)
        temporary_path = dj_tools.render_to_temp_file(rendered, sample_rate, ".wav")
        try:
            with open(temporary_path, "rb") as handle:
                with transaction.atomic():
                    job = DjRenderJob.objects.select_for_update().get(pk=job_id)
                    job.output_file.save(f"render-{job.pk}.wav", File(handle), save=False)
                    job.status = DjRenderJob.Status.COMPLETED
                    job.save(update_fields=["output_file", "status", "updated_at"])
        finally:
            os.unlink(temporary_path)
        return {"job_id": job_id, "status": job.status, "output": job.output_file.name}
    except Exception:
        logger.exception("DSP render failed for job %s", job_id)
        DjRenderJob.objects.filter(pk=job_id).update(
            status=DjRenderJob.Status.FAILED,
            failure_reason="DSP render failed. Please retry later.",
        )
        raise


@shared_task(bind=True, max_retries=1, name="music.dj_mix")
def mix_tracks_task(self, job_id):
    """Automated mashup: analyze, tempo/key-match, and transition-mix two tracks."""
    try:
        job = DjMixJob.objects.select_related("track_a", "track_b").get(pk=job_id)
    except DjMixJob.DoesNotExist:
        return {"job_id": job_id, "status": "missing"}
    if job.status == DjMixJob.Status.COMPLETED:
        return {"job_id": job_id, "status": job.status}
    DjMixJob.objects.filter(pk=job_id).update(
        status=DjMixJob.Status.PROCESSING,
        task_id=self.request.id or "",
        failure_reason="",
    )
    try:
        samples_a, sample_rate = _load_song_audio(job.track_a)
        samples_b, _ = _load_song_audio(job.track_b)
        bpm_a, key_a = _track_analysis(job.track_a, samples_a, sample_rate)
        bpm_b, key_b = _track_analysis(job.track_b, samples_b, sample_rate)

        if job.match_tempo:
            samples_b = dj_tools.match_tempo(samples_b, bpm_b, bpm_a)
        if job.match_key:
            samples_b = dj_tools.match_key(samples_b, sample_rate, key_b, key_a)

        mixed = dj_tools.render_transition(
            samples_a,
            samples_b,
            sample_rate,
            style=job.transition,
            transition_bars=job.transition_bars,
            bpm=bpm_a or 120.0,
        )
        temporary_path = dj_tools.render_to_temp_file(mixed, sample_rate, ".wav")
        try:
            waveform = _waveform(temporary_path)
            with open(temporary_path, "rb") as handle:
                with transaction.atomic():
                    job = DjMixJob.objects.select_for_update().get(pk=job_id)
                    job.output_file.save(f"mix-{job.pk}.wav", File(handle), save=False)
                    job.mix_waveform_data = waveform
                    job.analysis = {
                        "track_a": {"bpm": bpm_a, "key": key_a},
                        "track_b": {"bpm": bpm_b, "key": key_b},
                    }
                    job.status = DjMixJob.Status.COMPLETED
                    job.save(update_fields=["output_file", "mix_waveform_data", "analysis", "status", "updated_at"])
        finally:
            os.unlink(temporary_path)
        return {"job_id": job_id, "status": job.status, "output": job.output_file.name}
    except Exception:
        logger.exception("Mix render failed for job %s", job_id)
        DjMixJob.objects.filter(pk=job_id).update(
            status=DjMixJob.Status.FAILED,
            failure_reason="Mix render failed. Please retry later.",
        )
        raise