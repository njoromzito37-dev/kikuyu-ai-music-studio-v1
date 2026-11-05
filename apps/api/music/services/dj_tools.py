"""DJ audio processing toolbox for the Kikuyu AI Music Studio.

Server-side DSP used by the DJ endpoints and Celery tasks:

* Audio I/O through ffmpeg wrapper functions (decode to float32 PCM, encode back).
* Tempo adjustment via a phase-vocoder time stretcher (no pitch shift).
* Key shifting via resample + compensating time stretch (pitch transpose).
* 3-band EQ with Butterworth filters (frequency-domain, zero-phase).
* Effects rack: flanger, reverb (synthetic-IR convolution), echo/delay and a
  DJ-style high-pass/low-pass filter sweep.
* Analysis: BPM estimation, musical-key estimation (Krumhansl-Schmuckler) with
  Camelot wheel output, and automatic cue-point detection (intro / verse /
  breakdown / drop / outro).
* Mashup helpers: tempo/key matching and transition renderers
  (cut, smooth crossfade, drop swap, echo out).

Everything operates on ``float32`` numpy arrays shaped ``(channels, samples)``.
numpy is a hard dependency; ffmpeg must be installed for file I/O. The design
keeps the heavy math vectorized so it can run inside a Celery worker without
specialist audio libraries; swap individual stages for rubberband/librosa
builds in production if higher fidelity is required.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

DEFAULT_SAMPLE_RATE = 44100
_FFMPEG_TIMEOUT = 300


# ---------------------------------------------------------------------------
# ffmpeg wrapper I/O
# ---------------------------------------------------------------------------

def _ffmpeg_bin() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("ffmpeg is required for DJ audio processing but is not installed.")
    return binary


def load_audio(path: str | Path, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 2) -> tuple[np.ndarray, int]:
    """Decode any ffmpeg-supported audio file to ``(channels, samples)`` float32."""
    binary = _ffmpeg_bin()
    result = subprocess.run(
        [
            binary, "-v", "error", "-i", str(path),
            "-ac", str(channels), "-ar", str(sample_rate),
            "-f", "f32le", "pipe:1",
        ],
        check=True,
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT,
    )
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if samples.size == 0:
        raise ValueError(f"ffmpeg decoded no audio from {path!s}")
    if channels > 1:
        samples = samples.reshape(-1, channels).T.copy()
    else:
        samples = samples.reshape(1, -1)
    return samples, sample_rate


def save_audio(path: str | Path, samples: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Path:
    """Encode ``(channels, samples)`` float32 audio through ffmpeg.

    The output format follows the file suffix (``.wav``/``.mp3``/``.ogg``).
    """
    binary = _ffmpeg_bin()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.ascontiguousarray(_ensure_stereo(samples).T, dtype=np.float32).tobytes()
    suffix = path.suffix.lower()
    codec = {".wav": ["-c:a", "pcm_s16le"], ".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], ".ogg": ["-c:a", "libvorbis", "-q:a", "6"]}.get(suffix)
    if codec is None:
        raise ValueError(f"Unsupported output format {suffix!r}; use .wav, .mp3 or .ogg")
    subprocess.run(
        [
            binary, "-y", "-v", "error",
            "-f", "f32le", "-ac", "2", "-ar", str(sample_rate), "-i", "pipe:0",
            *codec, str(path),
        ],
        input=data,
        check=True,
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT,
    )
    return path


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def _ensure_stereo(samples: np.ndarray) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples.reshape(1, -1)
    if samples.shape[0] == 1:
        samples = np.vstack([samples, samples])
    return samples


def _mono(samples: np.ndarray) -> np.ndarray:
    return np.asarray(samples, dtype=np.float32).mean(axis=0)


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def _normalize_peak(samples: np.ndarray, ceiling: float = 0.98) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > ceiling:
        samples = samples * (ceiling / peak)
    return samples.astype(np.float32)


def _match_length(samples: np.ndarray, length: int) -> np.ndarray:
    if samples.shape[1] == length:
        return samples
    if samples.shape[1] > length:
        return samples[:, :length]
    pad = length - samples.shape[1]
    return np.pad(samples, ((0, 0), (0, pad)))


# ---------------------------------------------------------------------------
# Butterworth filtering (frequency-domain, zero-phase)
# ---------------------------------------------------------------------------

def butterworth_response(freqs: np.ndarray, cutoff: float, order: int = 4, kind: str = "lowpass") -> np.ndarray:
    """Magnitude response of a Butterworth filter evaluated at ``freqs``.

    Applied in the frequency domain (zero-phase), which keeps DJ filter kills
    free of phase smear. ``kind`` is ``lowpass``, ``highpass`` or ``bandpass``
    (``cutoff`` may then be a ``(low, high)`` tuple).
    """
    cutoff = np.asarray(cutoff, dtype=np.float64)
    order = max(1, int(order))
    with np.errstate(divide="ignore", invalid="ignore"):
        if kind == "bandpass":
            low, high = float(cutoff[0]), float(cutoff[1])
            response = butterworth_response(freqs, high, order, "lowpass") * butterworth_response(freqs, low, order, "highpass")
            return response
        ratio = np.where(freqs > 0, freqs / float(cutoff), 0.0)
        if kind == "lowpass":
            response = 1.0 / np.sqrt(1.0 + ratio ** (2 * order))
        elif kind == "highpass":
            ratio = np.where(freqs > 0, float(cutoff) / np.maximum(freqs, 1e-9), np.inf)
            response = 1.0 / np.sqrt(1.0 + ratio ** (2 * order))
            response[0] = 0.0
        else:
            raise ValueError(f"Unknown filter kind {kind!r}")
    return response


def _fft_filter(samples: np.ndarray, sample_rate: int, magnitude: np.ndarray) -> np.ndarray:
    """Apply a zero-phase magnitude curve to ``(channels, samples)`` audio."""
    n = samples.shape[1]
    spectrum = np.fft.rfft(samples, axis=1)
    spectrum *= magnitude.reshape(1, -1).astype(np.float64)
    out = np.fft.irfft(spectrum, n=n, axis=1)
    return out.astype(np.float32)


def butter_filter(samples: np.ndarray, sample_rate: int, cutoff, order: int = 4, kind: str = "lowpass") -> np.ndarray:
    """Static Butterworth low/high/band-pass filter over a whole signal."""
    freqs = np.fft.rfftfreq(samples.shape[1], d=1.0 / sample_rate)
    magnitude = butterworth_response(freqs, cutoff, order=order, kind=kind)
    return _fft_filter(samples, sample_rate, magnitude)


def three_band_eq(
    samples: np.ndarray,
    sample_rate: int,
    low_db: float = 0.0,
    mid_db: float = 0.0,
    high_db: float = 0.0,
    low_cut: float = 250.0,
    high_cut: float = 4000.0,
    order: int = 4,
) -> np.ndarray:
    """DJ-mixer 3-band EQ.

    Splits the signal with Butterworth crossovers at ``low_cut``/``high_cut``
    into low / mid / high bands (perfect reconstruction: the mid band is the
    residual so the three bands always sum back to the input), applies each
    band gain in dB, and re-sums.
    """
    samples = _ensure_stereo(samples)
    low_band = butter_filter(samples, sample_rate, low_cut, order=order, kind="lowpass")
    high_band = butter_filter(samples, sample_rate, high_cut, order=order, kind="highpass")
    mid_band = samples - low_band - high_band
    out = (
        low_band * db_to_gain(low_db)
        + mid_band * db_to_gain(mid_db)
        + high_band * db_to_gain(high_db)
    )
    return _normalize_peak(out)


def dj_filter(samples: np.ndarray, sample_rate: int, mode: str, cutoff: float, order: int = 4) -> np.ndarray:
    """Single DJ filter knob: ``mode`` is ``lowpass`` or ``highpass``."""
    samples = _ensure_stereo(samples)
    return butter_filter(samples, sample_rate, cutoff, order=order, kind=mode).astype(np.float32)


def filter_sweep(
    samples: np.ndarray,
    sample_rate: int,
    mode: str = "lowpass",
    start_cutoff: float = 20000.0,
    end_cutoff: float = 400.0,
    order: int = 4,
    frame_size: int = 2048,
    hop: int = 512,
) -> np.ndarray:
    """Time-varying HP/LP filter sweep (the classic DJ 'knob turn').

    Processes the signal in overlapping frames, interpolating the Butterworth
    cutoff from ``start_cutoff`` to ``end_cutoff`` across the track.
    """
    samples = _ensure_stereo(samples)
    n = samples.shape[1]
    if n == 0:
        return samples
    window = np.hanning(frame_size).astype(np.float32)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)
    out = np.zeros_like(samples)
    norm = np.zeros(n, dtype=np.float32)
    n_frames = max(1, 1 + (n - frame_size) // hop)
    log_start, log_end = math.log10(max(start_cutoff, 20.0)), math.log10(max(end_cutoff, 20.0))
    for frame_index in range(n_frames + 1):
        start = frame_index * hop
        frame = samples[:, start : start + frame_size]
        if frame.shape[1] < frame_size:
            frame = np.pad(frame, ((0, 0), (0, frame_size - frame.shape[1])))
        position = frame_index / max(1, n_frames)
        cutoff = 10.0 ** (log_start + (log_end - log_start) * position)
        magnitude = butterworth_response(freqs, cutoff, order=order, kind=mode)
        spectrum = np.fft.rfft(frame * window.reshape(1, -1), axis=1)
        chunk = np.fft.irfft(spectrum * magnitude.reshape(1, -1), n=frame_size, axis=1) * window.reshape(1, -1)
        end = min(start + frame_size, n)
        out[:, start:end] += chunk[:, : end - start].astype(np.float32)
        norm[start:end] += (window ** 2)[: end - start]
    nz = norm > 1e-8
    out[:, nz] /= norm[nz].reshape(1, -1)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# tempo / pitch
# ---------------------------------------------------------------------------

def time_stretch(samples: np.ndarray, rate: float, frame_size: int = 2048, hop: int | None = None) -> np.ndarray:
    """Phase-vocoder time stretch. ``rate > 1`` is faster (shorter output).

    Pitch is preserved, so this is the tempo-adjustment building block used
    for beatmatching two tracks.
    """
    samples = _ensure_stereo(samples)
    if rate <= 0:
        raise ValueError("rate must be positive")
    if abs(rate - 1.0) < 1e-6:
        return samples.copy()
    hop = hop or frame_size // 4
    window = np.hanning(frame_size).astype(np.float64)
    omega = 2.0 * np.pi * hop * np.arange(frame_size // 2 + 1) / frame_size
    out_channels = []
    for channel in samples:
        padded = np.pad(channel.astype(np.float64), frame_size)
        n_frames = 1 + (len(padded) - frame_size) // hop
        if n_frames < 2:
            out_channels.append(channel.copy())
            continue
        stft = np.empty((frame_size // 2 + 1, n_frames), dtype=np.complex128)
        for index in range(n_frames):
            frame = padded[index * hop : index * hop + frame_size] * window
            stft[:, index] = np.fft.rfft(frame)
        time_steps = np.arange(0, n_frames - 1, rate, dtype=np.float64)
        stretched = np.empty((frame_size // 2 + 1, len(time_steps)), dtype=np.complex128)
        phase = np.angle(stft[:, 0])
        for step_index, step in enumerate(time_steps):
            left = int(step)
            frac = step - left
            right = min(left + 1, n_frames - 1)
            magnitude = (1.0 - frac) * np.abs(stft[:, left]) + frac * np.abs(stft[:, right])
            stretched[:, step_index] = magnitude * np.exp(1j * phase)
            if right > left:
                delta = np.angle(stft[:, right]) - np.angle(stft[:, left]) - omega
                delta -= 2.0 * np.pi * np.round(delta / (2.0 * np.pi))
                phase = phase + omega + delta
        expected = hop * (len(time_steps) - 1) + frame_size
        rebuilt = np.zeros(expected, dtype=np.float64)
        weight = np.zeros(expected, dtype=np.float64)
        for step_index in range(stretched.shape[1]):
            frame = np.fft.irfft(stretched[:, step_index], n=frame_size)
            start = step_index * hop
            rebuilt[start : start + frame_size] += frame * window
            weight[start : start + frame_size] += window ** 2
        nz = weight > 1e-8
        rebuilt[nz] /= weight[nz]
        out_channels.append(rebuilt.astype(np.float32))
    length = min(channel.shape[0] for channel in out_channels)
    result = np.stack([channel[:length] for channel in out_channels])
    target = max(1, int(round(samples.shape[1] / rate)))
    return _match_length(result, target).astype(np.float32)


def pitch_shift(samples: np.ndarray, sample_rate: int, semitones: float) -> np.ndarray:
    """Transpose pitch by ``semitones`` while preserving duration.

    Resampling by ``2 ** (semitones/12)`` transposes pitch (and tempo); a
    compensating phase-vocoder stretch restores the original length. For
    production quality swap the resampler for rubberband.
    """
    samples = _ensure_stereo(samples)
    if abs(semitones) < 1e-3:
        return samples.copy()
    factor = 2.0 ** (semitones / 12.0)
    n = samples.shape[1]
    new_n = max(2, int(round(n / factor)))
    grid = np.arange(n, dtype=np.float64)
    resample_grid = np.linspace(0.0, n - 1.0, new_n)
    resampled = np.stack(
        [np.interp(resample_grid, grid, channel.astype(np.float64)) for channel in samples]
    ).astype(np.float32)
    restored = time_stretch(resampled, 1.0 / factor)
    return _match_length(restored, n).astype(np.float32)


# ---------------------------------------------------------------------------
# effects rack
# ---------------------------------------------------------------------------

def apply_flanger(
    samples: np.ndarray,
    sample_rate: int,
    base_delay_ms: float = 2.0,
    depth_ms: float = 2.0,
    rate_hz: float = 0.5,
    feedback: float = 0.3,
    mix: float = 0.5,
) -> np.ndarray:
    """Sweeping comb 'jet' effect built from an LFO-modulated fractional delay."""
    samples = _ensure_stereo(samples)
    n = samples.shape[1]
    if n == 0:
        return samples
    t = np.arange(n, dtype=np.float64) / sample_rate
    delay = (base_delay_ms + depth_ms * (0.5 + 0.5 * np.sin(2.0 * np.pi * rate_hz * t))) * sample_rate / 1000.0
    grid = np.arange(n, dtype=np.float64)

    def delayed(signal: np.ndarray) -> np.ndarray:
        indices = np.clip(grid - delay, 0.0, n - 1.0)
        return np.stack([np.interp(indices, grid, channel) for channel in signal]).astype(np.float32)

    wet = delayed(samples)
    feedback_term = np.zeros_like(wet)
    feedback_source = wet
    feedback = float(np.clip(feedback, 0.0, 0.9))
    for _ in range(3):
        if feedback <= 0:
            break
        feedback_source = delayed(feedback_source)
        feedback_term = feedback_term * feedback + feedback_source * feedback
    wet = np.clip(wet + feedback_term, -1.0, 1.0)
    mix = float(np.clip(mix, 0.0, 1.0))
    return ((1.0 - mix) * samples + mix * wet).astype(np.float32)


def _fft_convolve(signal: np.ndarray, impulse: np.ndarray) -> np.ndarray:
    n = len(signal) + len(impulse) - 1
    n_fft = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(signal, n_fft) * np.fft.rfft(impulse, n_fft), n_fft)[:n]


def apply_reverb(
    samples: np.ndarray,
    sample_rate: int,
    room_size: float = 0.6,
    damping: float = 0.5,
    wet: float = 0.25,
    pre_delay_ms: float = 20.0,
) -> np.ndarray:
    """Hall-style reverb via convolution with a synthetic decaying-noise IR.

    ``room_size`` controls decay time, ``damping`` progressively darkens the
    tail, ``wet`` is the wet/dry balance. Stereo decorrelation comes from an
    independent impulse response per channel.
    """
    samples = _ensure_stereo(samples)
    n = samples.shape[1]
    if n == 0:
        return samples
    room_size = float(np.clip(room_size, 0.0, 1.0))
    damping = float(np.clip(damping, 0.0, 1.0))
    wet = float(np.clip(wet, 0.0, 1.0))
    decay_s = 0.25 + room_size * 1.75
    ir_length = int(sample_rate * decay_s)
    t = np.arange(ir_length, dtype=np.float64) / sample_rate
    envelope = np.exp(-6.91 * t / decay_s)
    segments = 8
    wet_channels = []
    for channel_index, channel in enumerate(samples):
        rng = np.random.default_rng(20240 + channel_index)
        impulse = rng.standard_normal(ir_length).astype(np.float64) * envelope
        # Progressive damping: later portions of the tail get darker.
        bounds = np.linspace(0, ir_length, segments + 1).astype(int)
        for seg in range(segments):
            seg_slice = impulse[bounds[seg] : bounds[seg + 1]]
            if seg_slice.size == 0:
                continue
            cutoff = max(400.0, 9000.0 * ((1.0 - damping * 0.85) ** seg))
            freqs = np.fft.rfftfreq(seg_slice.size, d=1.0 / sample_rate)
            magnitude = butterworth_response(freqs, cutoff, order=2, kind="lowpass")
            impulse[bounds[seg] : bounds[seg + 1]] = np.fft.irfft(np.fft.rfft(seg_slice) * magnitude, n=seg_slice.size)
        impulse /= max(1e-9, np.max(np.abs(impulse)))
        pre_delay = int(sample_rate * pre_delay_ms / 1000.0)
        impulse = np.concatenate([np.zeros(pre_delay), impulse])
        wet_channel = _fft_convolve(channel.astype(np.float64), impulse)[:n]
        wet_channels.append(wet_channel)
    wet_signal = np.stack(wet_channels).astype(np.float32)
    wet_signal /= max(1e-9, float(np.max(np.abs(wet_signal))))
    out = (1.0 - wet) * samples + wet * wet_signal * 0.9
    return _normalize_peak(out)


def apply_echo(
    samples: np.ndarray,
    sample_rate: int,
    delay_ms: float = 350.0,
    feedback: float = 0.35,
    mix: float = 0.3,
    damping_hz: float = 4000.0,
    max_taps: int = 10,
    floor_db: float = -40.0,
) -> np.ndarray:
    """Tempo-friendly feedback delay with progressively damped repeats."""
    samples = _ensure_stereo(samples)
    n = samples.shape[1]
    delay = max(1, int(sample_rate * delay_ms / 1000.0))
    feedback = float(np.clip(feedback, 0.0, 0.95))
    mix = float(np.clip(mix, 0.0, 1.0))
    wet = np.zeros_like(samples)
    tap_gain = feedback
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    for tap in range(1, max_taps + 1):
        if 20.0 * math.log10(max(tap_gain, 1e-9)) < floor_db:
            break
        shifted = np.zeros_like(samples)
        offset = tap * delay
        if offset >= n:
            break
        shifted[:, offset:] = samples[:, : n - offset]
        cutoff = max(300.0, damping_hz / math.sqrt(tap))
        magnitude = butterworth_response(freqs, cutoff, order=2, kind="lowpass")
        shifted = _fft_filter(shifted, sample_rate, magnitude)
        wet += tap_gain * shifted
        tap_gain *= feedback
    out = (1.0 - mix) * samples + mix * wet
    return _normalize_peak(out)


EFFECT_RACK = {
    "flanger": apply_flanger,
    "reverb": apply_reverb,
    "echo": apply_echo,
    "delay": apply_echo,
    "filter_sweep": filter_sweep,
    "filter": dj_filter,
}


# ---------------------------------------------------------------------------
# analysis: BPM, key, cue points
# ---------------------------------------------------------------------------

def onset_envelope(samples: np.ndarray, sample_rate: int, hop: int = 512, frame_size: int = 1024) -> tuple[np.ndarray, int]:
    """Spectral-flux onset strength envelope."""
    mono = _mono(samples).astype(np.float64)
    if len(mono) < frame_size:
        return np.zeros(1), hop
    window = np.hanning(frame_size)
    n_frames = 1 + (len(mono) - frame_size) // hop
    envelope = np.zeros(n_frames, dtype=np.float64)
    previous = None
    for index in range(n_frames):
        frame = mono[index * hop : index * hop + frame_size] * window
        magnitude = np.abs(np.fft.rfft(frame))
        if previous is not None:
            diff = np.clip(magnitude - previous, 0.0, None)
            envelope[index] = math.sqrt(float(np.mean(diff ** 2)))
        previous = magnitude
    envelope -= envelope.mean()
    return np.clip(envelope, 0.0, None), hop


def estimate_bpm(samples: np.ndarray, sample_rate: int, hop: int = 512) -> float | None:
    """Estimate tempo from onset-envelope autocorrelation (40–240 BPM window)."""
    envelope, hop = onset_envelope(samples, sample_rate, hop=hop)
    if envelope.size < 8 or not np.any(envelope):
        return None
    frame_rate = sample_rate / hop
    autocorr = np.correlate(envelope, envelope, mode="full")[envelope.size - 1 :]
    min_lag = max(1, int(frame_rate * 60.0 / 240.0))
    max_lag = min(len(autocorr) - 1, int(frame_rate * 60.0 / 40.0))
    if max_lag <= min_lag:
        return None
    window = autocorr[min_lag:max_lag]
    if not np.any(window):
        return None
    lag = min_lag + int(np.argmax(window))
    bpm = 60.0 * frame_rate / lag
    while bpm < 80.0:
        bpm *= 2.0
    while bpm > 180.0:
        bpm /= 2.0
    return round(bpm, 1)


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_MAJOR_CAMELOT = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
_MINOR_CAMELOT = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]


def _chroma(samples: np.ndarray, sample_rate: int, frame_size: int = 4096, hop: int = 2048) -> np.ndarray:
    mono = _mono(samples).astype(np.float64)
    if len(mono) < frame_size:
        return np.zeros(12)
    window = np.hanning(frame_size)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)
    valid = (freqs >= 40.0) & (freqs <= 5000.0)
    midi = np.zeros(freqs.size)
    with np.errstate(divide="ignore", invalid="ignore"):
        midi[valid] = 69.0 + 12.0 * np.log2(freqs[valid] / 440.0)
    pitch_class = np.mod(np.round(midi), 12).astype(int)
    chroma = np.zeros(12, dtype=np.float64)
    n_frames = 1 + (len(mono) - frame_size) // hop
    max_frames = min(n_frames, 2000)
    for index in range(max_frames):
        frame = mono[index * hop : index * hop + frame_size] * window
        magnitude = np.abs(np.fft.rfft(frame)) ** 2
        for pc in range(12):
            chroma[pc] += float(magnitude[valid & (pitch_class == pc)].sum())
    total = chroma.sum()
    return chroma / total if total > 0 else chroma


def estimate_key(samples: np.ndarray, sample_rate: int) -> dict | None:
    """Estimate musical key using Krumhansl-Schmuckler profile correlation.

    Returns ``{"key", "root", "mode", "camelot", "confidence"}`` — the Camelot
    code makes harmonic mixing between tracks straightforward.
    """
    chroma = _chroma(samples, sample_rate)
    if not np.any(chroma):
        return None
    chroma = (chroma - chroma.mean()) / (chroma.std() + 1e-9)
    best = None
    for root in range(12):
        for mode, profile, camelot_table in (
            ("major", _MAJOR_PROFILE, _MAJOR_CAMELOT),
            ("minor", _MINOR_PROFILE, _MINOR_CAMELOT),
        ):
            rolled = np.roll(profile, root)
            rolled = (rolled - rolled.mean()) / (rolled.std() + 1e-9)
            score = float(np.corrcoef(chroma, rolled)[0, 1])
            if best is None or score > best[0]:
                best = (score, root, mode, camelot_table[root])
    if best is None:
        return None
    score, root, mode, camelot = best
    return {
        "key": f"{_NOTE_NAMES[root]} {mode}",
        "root": _NOTE_NAMES[root],
        "mode": mode,
        "camelot": camelot,
        "confidence": round(max(0.0, min(1.0, score)), 3),
    }


def key_semitone_offset(source_key: dict | None, target_key: dict | None) -> int:
    """Semitones to transpose ``source_key`` onto ``target_key`` (wrapped ±6)."""
    if not source_key or not target_key:
        return 0
    try:
        source = _NOTE_NAMES.index(source_key["root"])
        target = _NOTE_NAMES.index(target_key["root"])
    except (KeyError, ValueError):
        return 0
    offset = (target - source) % 12
    if offset > 6:
        offset -= 12
    return int(offset)


def _pick_onset_times(envelope: np.ndarray, hop: int, sample_rate: int, min_gap_s: float = 0.25, threshold_ratio: float = 0.3) -> np.ndarray:
    if envelope.size == 0 or not np.any(envelope):
        return np.array([])
    threshold = envelope.max() * threshold_ratio
    min_gap = max(1, int(min_gap_s * sample_rate / hop))
    peaks = []
    last = -min_gap
    for index in range(1, envelope.size - 1):
        if envelope[index] >= threshold and envelope[index] >= envelope[index - 1] and envelope[index] >= envelope[index + 1]:
            if index - last >= min_gap:
                peaks.append(index)
                last = index
    return np.array(peaks) * hop / sample_rate


def auto_cue_points(
    samples: np.ndarray,
    sample_rate: int,
    bpm: float | None = None,
    max_cues: int = 10,
) -> list[dict]:
    """Auto-cue / hot-cue detection.

    Uses onset strength plus a coarse energy contour to tag the cue points a
    DJ would mark by hand: ``intro``, ``verse``, ``breakdown`` (sustained
    low-energy section), ``drop`` (strongest onset after the breakdown) and
    ``outro``. Times are quantized to the beat grid when ``bpm`` is known.
    """
    samples = _ensure_stereo(samples)
    duration = samples.shape[1] / sample_rate
    if duration < 4.0:
        return []
    envelope, hop = onset_envelope(samples, sample_rate)
    onsets = _pick_onset_times(envelope, hop, sample_rate)

    # Coarse RMS energy contour, one value per second.
    mono = _mono(samples)
    window = sample_rate
    n_windows = max(1, int(duration))
    energy = np.array(
        [float(np.sqrt(np.mean(mono[i * window : (i + 1) * window] ** 2))) if (i + 1) * window <= len(mono) else 0.0 for i in range(n_windows)]
    )
    if not np.any(energy):
        return []

    def quantize(t: float) -> float:
        if bpm and bpm > 0:
            beat = 60.0 / bpm
            return round(round(t / beat) * beat, 3)
        return round(float(t), 3)

    cues: list[dict] = []
    cues.append({"time": 0.0, "label": "intro", "kind": "hotcue"})

    # Breakdown: the quietest sustained region in the middle half of the track.
    mid_start, mid_end = int(n_windows * 0.2), max(int(n_windows * 0.8), int(n_windows * 0.2) + 1)
    mid_energy = energy[mid_start:mid_end]
    breakdown_time = None
    if mid_energy.size >= 4:
        smoothed = np.convolve(mid_energy, np.ones(3) / 3.0, mode="same")
        breakdown_index = int(np.argmin(smoothed)) + mid_start
        if energy[breakdown_index] < energy.mean() * 0.7:
            breakdown_time = float(breakdown_index)
            cues.append({"time": quantize(breakdown_time), "label": "breakdown", "kind": "hotcue"})

    # Drop: the onset after the breakdown with the strongest combination of
    # spectral flux and sustained energy uplift (a drop is defined by the
    # energy jump around it, not just the transient).
    def onset_score(t: float) -> float:
        frame = min(int(t * sample_rate / hop), envelope.size - 1)
        flux = float(envelope[frame]) / (float(envelope.max()) + 1e-9)
        sec = int(t)
        before = energy[max(0, sec - 2) : sec]
        after = energy[sec : sec + 2]
        uplift = max(0.0, float(after.mean() if after.size else 0.0) - float(before.mean() if before.size else 0.0))
        return flux + 4.0 * uplift / (float(energy.max()) + 1e-9)

    if onsets.size:
        if breakdown_time is not None:
            after = onsets[(onsets > breakdown_time) & (onsets < breakdown_time + 16.0)]
            if after.size:
                drop_time = float(after[int(np.argmax([onset_score(t) for t in after]))])
                cues.append({"time": quantize(drop_time), "label": "drop", "kind": "hotcue"})
        if not any(c["label"] == "drop" for c in cues):
            strongest = float(onsets[int(np.argmax([onset_score(t) for t in onsets]))])
            cues.append({"time": quantize(strongest), "label": "drop", "kind": "hotcue"})

    # Verse markers: evenly spaced strong onsets between intro and breakdown.
    verse_candidates = onsets[(onsets > 4.0) & (onsets < (breakdown_time or duration * 0.5))]
    if verse_candidates.size:
        step = max(1, verse_candidates.size // 2)
        for t in verse_candidates[::step][:2]:
            cues.append({"time": quantize(float(t)), "label": "verse", "kind": "hotcue"})

    cues.append({"time": quantize(max(0.0, duration - min(16.0, duration * 0.1))), "label": "outro", "kind": "hotcue"})

    unique: dict[str, dict] = {}
    for cue in sorted(cues, key=lambda c: c["time"]):
        unique.setdefault(f"{cue['label']}@{cue['time']}", cue)
    return list(unique.values())[:max_cues]


# ---------------------------------------------------------------------------
# stems (placeholder band-split separation)
# ---------------------------------------------------------------------------

STEM_KINDS = ("vocals", "bass", "drums", "melody")


def split_stems_placeholder(samples: np.ndarray, sample_rate: int) -> dict[str, np.ndarray]:
    """Band-split 'stem' separation placeholder.

    Produces four complementary stems (vocals / bass / drums / melody) whose
    sum reconstructs the input, so mute/solo/volume math behaves correctly in
    the remix deck. Replace with a demucs-based separation service for real
    source isolation; the Stem model and endpoints stay unchanged.
    """
    samples = _ensure_stereo(samples)
    bass = butter_filter(samples, sample_rate, 160.0, order=4, kind="lowpass")
    vocals = butter_filter(samples, sample_rate, (300.0, 3400.0), order=3, kind="bandpass")
    drums = butter_filter(samples, sample_rate, 5000.0, order=4, kind="highpass")
    melody = samples - bass - vocals - drums
    return {
        "bass": bass.astype(np.float32),
        "vocals": vocals.astype(np.float32),
        "drums": drums.astype(np.float32),
        "melody": melody.astype(np.float32),
    }


def mix_stems(stem_mix: list[dict]) -> np.ndarray:
    """Sum stems honoring volume / mute / solo.

    ``stem_mix`` items: ``{"samples": ndarray, "volume": float, "is_muted": bool, "is_solo": bool}``.
    If any stem is soloed, only soloed stems are audible.
    """
    active = [s for s in stem_mix if not s.get("is_muted")]
    if any(s.get("is_solo") for s in stem_mix):
        active = [s for s in stem_mix if s.get("is_solo") and not s.get("is_muted")]
    if not active:
        length = max((s["samples"].shape[1] for s in stem_mix), default=0)
        return np.zeros((2, length), dtype=np.float32)
    length = max(s["samples"].shape[1] for s in active)
    out = np.zeros((2, length), dtype=np.float32)
    for stem in active:
        data = _match_length(_ensure_stereo(stem["samples"]), length)
        out += data * float(stem.get("volume", 1.0))
    return _normalize_peak(out)


# ---------------------------------------------------------------------------
# transitions / mashups
# ---------------------------------------------------------------------------

def equal_power_crossfade(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Equal-power crossfade between two equal-length ``(channels, n)`` blocks."""
    n = min(a.shape[1], b.shape[1])
    a, b = a[:, :n], b[:, :n]
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    fade_out = np.cos(t * np.pi / 2.0).reshape(1, -1)
    fade_in = np.sin(t * np.pi / 2.0).reshape(1, -1)
    return (a * fade_out + b * fade_in).astype(np.float32)


TRANSITION_STYLES = ("cut", "crossfade", "drop_swap", "echo_out")


def render_transition(
    track_a: np.ndarray,
    track_b: np.ndarray,
    sample_rate: int,
    style: str = "crossfade",
    transition_bars: int = 8,
    bpm: float = 120.0,
) -> np.ndarray:
    """Render a DJ transition from track A into track B.

    Styles:
      * ``cut``        – hard cut, A then B.
      * ``crossfade``  – smooth equal-power crossfade over ``transition_bars``.
      * ``drop_swap``  – A stops at the transition point, one-bar gap, B drops in.
      * ``echo_out``   – A tails out through a feedback echo while B fades in.
    """
    track_a = _ensure_stereo(track_a)
    track_b = _ensure_stereo(track_b)
    if style not in TRANSITION_STYLES:
        raise ValueError(f"Unknown transition style {style!r}; expected one of {TRANSITION_STYLES}")
    beat_s = 60.0 / max(30.0, float(bpm))
    seg = int(sample_rate * transition_bars * 4 * beat_s)

    if style == "cut":
        return np.concatenate([track_a, track_b], axis=1).astype(np.float32)

    seg = max(1, min(seg, track_a.shape[1], track_b.shape[1]))
    head_a, tail_a = track_a[:, :-seg], track_a[:, -seg:]
    head_b, tail_b = track_b[:, :seg], track_b[:, seg:]

    if style == "crossfade":
        blended = equal_power_crossfade(tail_a, head_b)
        out = np.concatenate([head_a, blended, tail_b], axis=1)
    elif style == "drop_swap":
        gap = np.zeros((2, int(sample_rate * beat_s * 4)), dtype=np.float32)
        blended = equal_power_crossfade(tail_a, np.zeros_like(head_b))  # fade A out cleanly
        b_in = head_b * np.linspace(0.0, 1.0, head_b.shape[1], dtype=np.float32).reshape(1, -1) ** 0.5
        out = np.concatenate([head_a, blended, gap, b_in, tail_b], axis=1)
    else:  # echo_out
        echo_tail = apply_echo(
            tail_a, sample_rate,
            delay_ms=beat_s * 750.0, feedback=0.55, mix=0.65,
        )
        decay = np.linspace(1.0, 0.0, seg, dtype=np.float32).reshape(1, -1) ** 1.5
        b_in = head_b * np.linspace(0.0, 1.0, seg, dtype=np.float32).reshape(1, -1)
        blended = _normalize_peak(echo_tail * decay + b_in)
        out = np.concatenate([head_a, blended, tail_b], axis=1)
    return _normalize_peak(out)


def match_tempo(samples: np.ndarray, source_bpm: float | None, target_bpm: float | None) -> np.ndarray:
    """Time-stretch ``samples`` from ``source_bpm`` to ``target_bpm`` (pitch-safe)."""
    if not source_bpm or not target_bpm or source_bpm <= 0 or target_bpm <= 0:
        return samples
    rate = float(target_bpm) / float(source_bpm)
    if abs(rate - 1.0) < 0.005:
        return samples
    # Keep stretches musical: halve/double target into a sane ratio window,
    # only when the adjusted ratio actually lands closer to 1.
    while rate > 1.25 and rate / 2.0 >= 0.75:
        target_bpm /= 2.0
        rate = float(target_bpm) / float(source_bpm)
    while rate < 0.75 and rate * 2.0 <= 1.25:
        target_bpm *= 2.0
        rate = float(target_bpm) / float(source_bpm)
    return time_stretch(samples, rate)


def match_key(samples: np.ndarray, sample_rate: int, source_key: dict | None, target_key: dict | None) -> np.ndarray:
    """Transpose ``samples`` so its key matches the target (wrapped ±6 semitones)."""
    semitones = key_semitone_offset(source_key, target_key)
    if semitones == 0:
        return samples
    return pitch_shift(samples, sample_rate, semitones)


# ---------------------------------------------------------------------------
# chain runner (used by the DSP render endpoint/task)
# ---------------------------------------------------------------------------

def run_chain(samples: np.ndarray, sample_rate: int, operations: list[dict]) -> np.ndarray:
    """Apply an ordered list of DSP operations.

    Each operation is a dict with an ``op`` key, e.g.::

        [{"op": "time_stretch", "rate": 1.04},
         {"op": "pitch_shift", "semitones": 2},
         {"op": "eq", "low_db": 3, "mid_db": -2, "high_db": 1},
         {"op": "echo", "delay_ms": 375, "feedback": 0.4, "mix": 0.25},
         {"op": "filter_sweep", "mode": "highpass", "start_cutoff": 40, "end_cutoff": 8000},
         {"op": "reverb", "room_size": 0.7, "wet": 0.3},
         {"op": "flanger", "rate_hz": 0.25, "depth_ms": 3}]
    """
    samples = _ensure_stereo(samples)
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"Operation {index} must be an object")
        op = operation.get("op")
        params = {k: v for k, v in operation.items() if k != "op"}
        if op == "time_stretch":
            samples = time_stretch(samples, float(params.get("rate", 1.0)))
        elif op == "pitch_shift":
            samples = pitch_shift(samples, sample_rate, float(params.get("semitones", 0.0)))
        elif op == "eq":
            samples = three_band_eq(
                samples, sample_rate,
                low_db=float(params.get("low_db", 0.0)),
                mid_db=float(params.get("mid_db", 0.0)),
                high_db=float(params.get("high_db", 0.0)),
            )
        elif op in EFFECT_RACK:
            effect = EFFECT_RACK[op]
            numeric = {k: float(v) for k, v in params.items() if isinstance(v, (int, float))}
            text = {k: str(v) for k, v in params.items() if isinstance(v, str)}
            samples = effect(samples, sample_rate, **numeric, **text)
        elif op == "normalize":
            samples = _normalize_peak(samples, ceiling=float(params.get("ceiling", 0.98)))
        else:
            raise ValueError(f"Unknown DSP operation {op!r} at position {index}")
    return _normalize_peak(samples)


def render_to_temp_file(samples: np.ndarray, sample_rate: int, suffix: str = ".wav") -> Path:
    """Persist audio to a temp file and return its path (caller deletes)."""
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.close()
    path = Path(handle.name)
    try:
        save_audio(path, samples, sample_rate)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
