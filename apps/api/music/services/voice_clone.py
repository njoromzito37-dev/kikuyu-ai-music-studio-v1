"""Singing-voice cloning seam.

Converts the vocals of a rendered song into a target voice profile
(male / female / child / choir) using a self-hosted RVC
(Retrieval-based Voice Conversion) install — the standard open-source
singing-voice conversion toolchain.

Setup on the GPU worker:
    git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI $RVC_REPO_DIR
    # train or obtain one model per voice profile and drop it in $RVC_MODEL_DIR:
    #   $RVC_MODEL_DIR/mugithi-male-lead.pth   (+ optional .index)
    #   $RVC_MODEL_DIR/female-lead.pth         ...

Select with ``VOICE_CLONER=rvc``; the default ``off`` makes the API return a
clear error instead of silently skipping conversion. RVC CLI argument order
varies slightly across forks — override the script with RVC_INFER_SCRIPT if
your fork differs.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class VoiceCloneError(RuntimeError):
    """Raised when voice conversion cannot run or produced no output."""


class RVCVoiceCloner:
    """Drive RVC's infer_cli for one trained model per voice-profile slug."""

    name = "rvc"

    def __init__(
        self,
        repo_dir: str,
        model_dir: str,
        f0_method: str = "rmvpe",
        f0_up_key: int = 0,
        timeout: int = 1800,
        python_bin: str | None = None,
        infer_script: str | None = None,
    ):
        self.repo_dir = repo_dir
        self.model_dir = model_dir
        self.f0_method = f0_method
        self.f0_up_key = f0_up_key
        self.timeout = timeout
        self.python_bin = python_bin or shutil.which("python") or "python"
        self.infer_script = infer_script

    def _script(self) -> Path:
        if self.infer_script:
            script = Path(self.infer_script)
        else:
            script = Path(self.repo_dir) / "tools" / "infer_cli.py"
        if not script.exists():
            raise VoiceCloneError(
                f"RVC is not installed at {self.repo_dir} (expected {script}). Clone the RVC repo and set "
                "RVC_REPO_DIR / RVC_INFER_SCRIPT, or switch VOICE_CLONER back to 'off'."
            )
        return script

    def _model(self, voice_slug: str) -> Path:
        model = Path(self.model_dir) / f"{voice_slug}.pth"
        if not model.exists():
            raise VoiceCloneError(
                f"No trained RVC model for voice profile '{voice_slug}' at {model}. Train one from the "
                "profile's reference audio (licensed recordings only) and re-run."
            )
        return model

    def convert(self, source_audio: Path, voice_slug: str, out_dir: Path, filename_hint: str = "clone") -> Path:
        """Convert ``source_audio`` vocals to ``voice_slug``; returns the output wav path."""
        script = self._script()
        model = self._model(voice_slug)
        index = Path(self.model_dir) / f"{voice_slug}.index"
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{filename_hint}.wav"

        cmd = [
            self.python_bin,
            str(script),
            "--f0up_key", str(self.f0_up_key),
            "--input_path", str(source_audio),
            "--opt_path", str(out_path),
            "--model_name", str(model),
            "--f0method", self.f0_method,
        ]
        if index.exists():
            cmd += ["--index_path", str(index)]
        logger.info("Converting vocals with RVC model %s", model.name)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=self.timeout)
        except subprocess.CalledProcessError as exc:
            raise VoiceCloneError(f"RVC conversion failed: {exc.stderr.decode(errors='replace')[-500:]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise VoiceCloneError("RVC conversion timed out.") from exc
        if not out_path.exists():
            raise VoiceCloneError("RVC produced no output audio.")
        return out_path


def get_voice_cloner(kind: str | None = None) -> RVCVoiceCloner:
    """Build the configured voice cloner from Django settings."""
    kind = (kind or getattr(settings, "VOICE_CLONER", "off")).lower()
    if kind == "rvc":
        return RVCVoiceCloner(
            repo_dir=settings.RVC_REPO_DIR,
            model_dir=settings.RVC_MODEL_DIR,
            f0_method=settings.RVC_F0_METHOD,
            timeout=settings.RVC_TIMEOUT,
            infer_script=getattr(settings, "RVC_INFER_SCRIPT", "") or None,
        )
    if kind == "off":
        raise VoiceCloneError("Voice cloning is disabled. Set VOICE_CLONER=rvc on a GPU worker to enable it.")
    raise ImproperlyConfigured(f"Unknown VOICE_CLONER {kind!r}; expected 'rvc' or 'off'.")
