"""Professional multi-track stem mixer & mastering suite.

Summing engine + master bus chain used by ``render_final_song_task``:

* Gain staging — every stem is normalized to a consistent peak reference so
  the sum cannot clip before processing.
* Per-stem tone shaping ("frequency pockets") — high-pass non-bass elements,
  tame harsh high-mids on traditional strings/melodics, presence + air-band
  lift on vocals so Gĩkũyũ phonemes and cloned voices sit above the mix.
* Sidechain compression — drums duck bass/melody; lead vocals duck the
  melodic bed (envelope-followed, attack/release shaped).
* Automated leveling, stereo-balance panning and mid/side stereo width.
* Master bus: multiband compression → gentle saturation → ITU-R BS.1770
  loudness normalization (-14 LUFS streaming target) → brickwall limiter.

All processing is float32 numpy on (channels, samples), reusing the
frequency-domain Butterworth tools from services.dj_tools (ffmpeg only
touches files at the task boundary, never inside the mixer).
"""

from __future__ import annotations

import math

import numpy as np

from . import dj_tools

_EPS = 1e-9


# ---------------------------------------------------------------------------
# metering primitives
# ---------------------------------------------------------------------------

def _mono(samples: np.ndarray) -> np.ndarray:
    return np.asarray(samples, dtype=np.float32).mean(axis=0)


def _peak_dbfs(samples: np.ndarray) -> float:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    return 20.0 * math.log10(max(peak, _EPS))


def _rms_dbfs(samples: np.ndarray) -> float:
    rms = math.sqrt(float(np.mean(samples ** 2))) if samples.size else 0.0
    return 20.0 * math.log10(max(rms, _EPS))


def _envelope(signal: np.ndarray, sample_rate: int, attack_ms: float, release_ms: float, hop_ms: float = 5.0, mode: str = "rms") -> np.ndarray:
    """Block-domain attack/release envelope follower, upsampled to per-sample gain length."""
    n = len(signal)
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    hop = max(1, int(sample_rate * hop_ms / 1000.0))
    n_frames = max(1, n // hop)
    trimmed = signal[: n_frames * hop]
    blocks = trimmed.reshape(n_frames, hop)
    levels = np.max(np.abs(blocks), axis=1) if mode == "peak" else np.sqrt(np.mean(blocks ** 2, axis=1))

    blocks_per_second = sample_rate / hop
    attack = math.exp(-1.0 / max(_EPS, (attack_ms / 1000.0) * blocks_per_second))
    release = math.exp(-1.0 / max(_EPS, (release_ms / 1000.0) * blocks_per_second))
    smoothed = np.empty(n_frames, dtype=np.float64)
    previous = 0.0
    for index, value in enumerate(levels):
        coefficient = attack if value > previous else release
        previous = coefficient * previous + (1.0 - coefficient) * float(value)
        smoothed[index] = previous
    full = np.repeat(smoothed, hop)
    if len(full) < n:
        full = np.pad(full, (0, n - len(full)), mode="edge")
    return full[:n].astype(np.float32)


# ---------------------------------------------------------------------------
# gain staging
# ---------------------------------------------------------------------------

def normalize_stem(samples: np.ndarray, target_peak_dbfs: float = -12.0) -> np.ndarray:
    """Gain-stage a stem so its peak hits the reference (never amplifies silence)."""
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < _EPS:
        return samples
    target = 10.0 ** (target_peak_dbfs / 20.0)
    return (samples * (target / peak)).astype(np.float32)


def gain_stage(stems: list[dict], target_peak_dbfs: float = -12.0) -> list[dict]:
    """Normalize every stem's samples in place-copy; returns new stem dicts."""
    return [{**stem, "samples": normalize_stem(stem["samples"], target_peak_dbfs)} for stem in stems]


# ---------------------------------------------------------------------------
# tone shaping — frequency pockets (zero-phase RBJ biquads in the freq domain)
# ---------------------------------------------------------------------------

def _biquad_magnitude(freqs: np.ndarray, sample_rate: int, b: tuple, a: tuple) -> np.ndarray:
    w = 2.0 * np.pi * freqs / sample_rate
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    numerator = b[0] + b[1] * z1 + b[2] * z2
    denominator = a[0] + a[1] * z1 + a[2] * z2
    return np.abs(numerator / np.maximum(np.abs(denominator), _EPS))


def peaking_magnitude(freqs: np.ndarray, sample_rate: int, f0: float, gain_db: float, q: float = 1.0) -> np.ndarray:
    """RBJ peaking-EQ magnitude curve."""
    amplitude = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / sample_rate
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)
    b = (1.0 + alpha * amplitude, -2.0 * cos_w0, 1.0 - alpha * amplitude)
    a = (1.0 + alpha / amplitude, -2.0 * cos_w0, 1.0 - alpha / amplitude)
    return _biquad_magnitude(freqs, sample_rate, b, a)


def high_shelf_magnitude(freqs: np.ndarray, sample_rate: int, f0: float, gain_db: float, slope: float = 0.8) -> np.ndarray:
    """RBJ high-shelf magnitude curve (air band, K-weighting, etc.)."""
    amplitude = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / sample_rate
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((amplitude + 1.0 / amplitude) * (1.0 / slope - 1.0) + 2.0)
    two_sqrt_a_alpha = 2.0 * math.sqrt(amplitude) * alpha
    b0 = amplitude * ((amplitude + 1) + (amplitude - 1) * cos_w0 + two_sqrt_a_alpha)
    b1 = -2 * amplitude * ((amplitude - 1) + (amplitude + 1) * cos_w0)
    b2 = amplitude * ((amplitude + 1) + (amplitude - 1) * cos_w0 - two_sqrt_a_alpha)
    a0 = (amplitude + 1) - (amplitude - 1) * cos_w0 + two_sqrt_a_alpha
    a1 = 2 * ((amplitude - 1) - (amplitude + 1) * cos_w0)
    a2 = (amplitude + 1) - (amplitude - 1) * cos_w0 - two_sqrt_a_alpha
    return _biquad_magnitude(freqs, sample_rate, (b0, b1, b2), (a0, a1, a2))


def _apply_magnitude(samples: np.ndarray, sample_rate: int, magnitude: np.ndarray) -> np.ndarray:
    n = samples.shape[1]
    spectrum = np.fft.rfft(samples, axis=1)
    spectrum *= magnitude.reshape(1, -1)
    return np.fft.irfft(spectrum, n=n, axis=1).astype(np.float32)


def _peaking(samples: np.ndarray, sample_rate: int, f0: float, gain_db: float, q: float = 1.0) -> np.ndarray:
    freqs = np.fft.rfftfreq(samples.shape[1], d=1.0 / sample_rate)
    return _apply_magnitude(samples, sample_rate, peaking_magnitude(freqs, sample_rate, f0, gain_db, q))


def _high_shelf(samples: np.ndarray, sample_rate: int, f0: float, gain_db: float) -> np.ndarray:
    freqs = np.fft.rfftfreq(samples.shape[1], d=1.0 / sample_rate)
    return _apply_magnitude(samples, sample_rate, high_shelf_magnitude(freqs, sample_rate, f0, gain_db))


def shape_stem(kind: str, samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Carve the frequency pocket for a stem kind.

    * bass:    subsonic cleanup only (keeps the 808/guitar low end intact).
    * drums:   subsonic cleanup below 30 Hz.
    * vocals:  40 Hz high-pass, +2 dB presence at 3 kHz, +3 dB air shelf above
               10 kHz — cloned Gĩkũyũ vocals stay articulate on top.
    * melody/other (traditional strings, synths, guitars): 40 Hz high-pass and
               a -2.5 dB bell at 3 kHz to clear the vocal pocket.
    """
    kind = (kind or "").lower()
    if kind == "bass":
        return dj_tools.butter_filter(samples, sample_rate, 25.0, order=2, kind="highpass")
    if kind == "drums":
        return dj_tools.butter_filter(samples, sample_rate, 30.0, order=4, kind="highpass")
    if kind == "vocals":
        shaped = dj_tools.butter_filter(samples, sample_rate, 40.0, order=4, kind="highpass")
        shaped = _peaking(shaped, sample_rate, 3000.0, 2.0, q=0.9)
        return _high_shelf(shaped, sample_rate, 10000.0, 3.0)
    # melody / other
    shaped = dj_tools.butter_filter(samples, sample_rate, 40.0, order=4, kind="highpass")
    shaped = _peaking(shaped, sample_rate, 3000.0, -2.5, q=1.2)
    return shaped


# ---------------------------------------------------------------------------
# sidechain compression
# ---------------------------------------------------------------------------

def sidechain_duck(
    target: np.ndarray,
    side: np.ndarray,
    sample_rate: int,
    threshold_db: float = -24.0,
    ratio: float = 6.0,
    max_reduction_db: float = 12.0,
    attack_ms: float = 3.0,
    release_ms: float = 120.0,
) -> np.ndarray:
    """Duck ``target`` whenever ``side`` exceeds ``threshold_db`` (compressor law)."""
    if not side.size or not target.size:
        return target
    envelope = _envelope(_mono(side), sample_rate, attack_ms, release_ms)
    envelope = envelope[: target.shape[1]]
    if len(envelope) < target.shape[1]:
        envelope = np.pad(envelope, (0, target.shape[1] - len(envelope)), mode="edge")
    level_db = 20.0 * np.log10(envelope + _EPS)
    over_db = np.clip(level_db - threshold_db, 0.0, None)
    reduction_db = np.minimum(over_db * (1.0 - 1.0 / ratio), max_reduction_db)
    gain = 10.0 ** (-reduction_db / 20.0)
    return (target * gain.reshape(1, -1)).astype(np.float32)


# ---------------------------------------------------------------------------
# leveling, panning, width
# ---------------------------------------------------------------------------

def apply_pan(samples: np.ndarray, pan: float) -> np.ndarray:
    """Stereo balance control, -1 (left) .. +1 (right); unity gain at center.

    Stems are stereo program material, so panning attenuates the opposite
    channel rather than re-summing with a power law (which would drop 3 dB
    at center).
    """
    pan = float(np.clip(pan, -1.0, 1.0))
    out = samples.copy()
    if pan < 0.0:
        out[1] *= 1.0 + pan
    elif pan > 0.0:
        out[0] *= 1.0 - pan
    return out


def stereo_width(samples: np.ndarray, width: float = 1.15) -> np.ndarray:
    """Mid/side width control; 1.0 = unchanged, 0 = mono, >1 = wider."""
    if samples.shape[0] != 2 or abs(width - 1.0) < 1e-6:
        return samples
    mid = (samples[0] + samples[1]) * 0.5
    side = (samples[0] - samples[1]) * 0.5 * float(width)
    return np.stack([mid + side, mid - side]).astype(np.float32)


def sum_stems(stems: list[dict]) -> np.ndarray:
    """Sum staged stems honoring volume / pan / mute / solo."""
    active = [s for s in stems if not s.get("is_muted")]
    if any(s.get("is_solo") for s in stems):
        active = [s for s in stems if s.get("is_solo") and not s.get("is_muted")]
    if not active:
        length = max((s["samples"].shape[1] for s in stems), default=0)
        return np.zeros((2, length), dtype=np.float32)
    length = max(s["samples"].shape[1] for s in active)
    out = np.zeros((2, length), dtype=np.float32)
    for stem in active:
        data = stem["samples"]
        if data.shape[1] < length:
            data = np.pad(data, ((0, 0), (0, length - data.shape[1])))
        data = apply_pan(data, float(stem.get("pan", 0.0)))
        out += data * float(stem.get("volume", 1.0))
    return out


# ---------------------------------------------------------------------------
# master bus: multiband compression, saturation, loudness, limiting
# ---------------------------------------------------------------------------

def _compressor_gain(envelope: np.ndarray, threshold_db: float, ratio: float, makeup_db: float = 0.0) -> np.ndarray:
    level_db = 20.0 * np.log10(envelope + _EPS)
    over_db = level_db - threshold_db
    reduction_db = np.where(over_db > 0.0, over_db * (1.0 - 1.0 / ratio), 0.0)
    return (10.0 ** ((makeup_db - reduction_db) / 20.0)).astype(np.float32)


def multiband_compress(
    samples: np.ndarray,
    sample_rate: int,
    crossovers: tuple[float, float] = (150.0, 2500.0),
    ratio: float = 2.5,
) -> np.ndarray:
    """3-band bus compressor.

    Each band is compressed against a threshold placed 4 dB above its own RMS
    (auto-threshold keeps the tonal balance). Auto-makeup restores the band's
    RMS but is capped so the band's peak never exceeds its input peak —
    glue without level jumps or transient overshoot.
    """
    low_x, high_x = crossovers
    bands = [
        dj_tools.butter_filter(samples, sample_rate, low_x, order=3, kind="lowpass"),
        dj_tools.butter_filter(samples, sample_rate, (low_x, high_x), order=3, kind="bandpass"),
        dj_tools.butter_filter(samples, sample_rate, high_x, order=3, kind="highpass"),
    ]
    out = np.zeros_like(samples)
    for band in bands:
        band_rms_db = _rms_dbfs(band)
        if band_rms_db < -80.0:
            out += band
            continue
        peak_signal = np.max(np.abs(band), axis=0)
        envelope = _envelope(peak_signal, sample_rate, attack_ms=3.0, release_ms=120.0, hop_ms=2.0, mode="peak")
        gain = _compressor_gain(envelope, threshold_db=band_rms_db + 4.0, ratio=ratio)
        compressed = band * gain.reshape(1, -1)
        # Auto makeup to the band's original RMS, capped at the input peak.
        restore_db = _rms_dbfs(band) - _rms_dbfs(compressed)
        peak_headroom_db = _peak_dbfs(band) - _peak_dbfs(compressed)
        makeup_db = min(restore_db, max(0.0, peak_headroom_db))
        out += (compressed * (10.0 ** (makeup_db / 20.0))).astype(np.float32)
    return out.astype(np.float32)


def soft_saturate(samples: np.ndarray, drive: float = 1.3, mix: float = 0.18) -> np.ndarray:
    """Gentle tanh bus saturation blended under the dry signal."""
    driven = np.tanh(samples * drive) / math.tanh(drive)
    return ((1.0 - mix) * samples + mix * driven).astype(np.float32)


def brickwall_limiter(samples: np.ndarray, sample_rate: int, ceiling_dbfs: float = -1.0) -> np.ndarray:
    """Envelope-following peak limiter; nothing exceeds the ceiling."""
    ceiling = 10.0 ** (ceiling_dbfs / 20.0)
    peak_signal = np.max(np.abs(samples), axis=0)
    envelope = _envelope(peak_signal, sample_rate, attack_ms=0.5, release_ms=80.0, hop_ms=1.0, mode="peak")
    gain = np.minimum(1.0, ceiling / np.maximum(envelope, _EPS))
    limited = samples * gain.reshape(1, -1)
    # absolute safety clip at the ceiling
    return np.clip(limited, -ceiling, ceiling).astype(np.float32)


def measure_lufs(samples: np.ndarray, sample_rate: int) -> float:
    """Integrated loudness, ITU-R BS.1770-style (K-weighted, gated).

    Approximation suitable for targeting streaming loudness: K pre-filter
    (+4 dB shelf at 1.68 kHz, 38 Hz high-pass), 400 ms blocks at 100 ms hop,
    absolute gate at -70 LUFS and relative gate at -10 LU.
    """
    if not samples.size:
        return -70.0
    weighted = _high_shelf(samples, sample_rate, 1680.0, 4.0)
    weighted = dj_tools.butter_filter(weighted, sample_rate, 38.0, order=2, kind="highpass")

    block = int(0.400 * sample_rate)
    hop = int(0.100 * sample_rate)
    energies = []
    for start in range(0, samples.shape[1] - block + 1, hop):
        window = weighted[:, start : start + block]
        z = float(np.sum(np.mean(window ** 2, axis=1)))
        energies.append(max(z, _EPS))
    if not energies:
        return -70.0
    block_lufs = -0.691 + 10.0 * np.log10(np.array(energies))
    gated = block_lufs[block_lufs > -70.0]
    if gated.size == 0:
        return -70.0
    relative_threshold = (-0.691 + 10.0 * np.log10(np.mean(10.0 ** ((gated + 0.691) / 10.0)))) - 10.0
    gated = gated[gated > relative_threshold]
    if gated.size == 0:
        return -70.0
    return float(-0.691 + 10.0 * math.log10(float(np.mean(10.0 ** ((gated + 0.691) / 10.0)))))


def normalize_loudness(samples: np.ndarray, sample_rate: int, target_lufs: float = -14.0) -> tuple[np.ndarray, float, float]:
    """Gain to the target integrated loudness. Returns (audio, before, after_gain_db)."""
    measured = measure_lufs(samples, sample_rate)
    gain_db = target_lufs - measured
    adjusted = (samples * (10.0 ** (gain_db / 20.0))).astype(np.float32)
    return adjusted, measured, gain_db


def master_chain(samples: np.ndarray, sample_rate: int, target_lufs: float = -14.0) -> tuple[np.ndarray, dict]:
    """Master bus: HPF -> multiband comp -> saturation -> -14 LUFS -> limiter."""
    report: dict = {"target_lufs": target_lufs, "ceiling_dbfs": -1.0}
    bus = dj_tools.butter_filter(samples, sample_rate, 25.0, order=2, kind="highpass")
    report["pre_master_peak_dbfs"] = round(_peak_dbfs(bus), 2)
    bus = multiband_compress(bus, sample_rate)
    bus = soft_saturate(bus)
    bus, measured_lufs, gain_db = normalize_loudness(bus, sample_rate, target_lufs)
    bus = brickwall_limiter(bus, sample_rate, ceiling_dbfs=report["ceiling_dbfs"])
    report["measured_lufs_before_gain"] = round(measured_lufs, 2)
    report["loudness_gain_db"] = round(gain_db, 2)
    report["integrated_lufs"] = round(measure_lufs(bus, sample_rate), 2)
    report["output_peak_dbfs"] = round(_peak_dbfs(bus), 2)
    return bus, report


# ---------------------------------------------------------------------------
# top-level: mix + master
# ---------------------------------------------------------------------------

def mix_and_master(
    stems: list[dict],
    sample_rate: int,
    target_lufs: float = -14.0,
    width: float = 1.15,
) -> tuple[np.ndarray, dict]:
    """Full pipeline: gain stage -> tone shape -> sidechain -> sum -> width -> master.

    ``stems`` items: {"samples": (2, n) float32, "kind": str, "volume": float,
    "pan": float, "is_muted": bool, "is_solo": bool}.
    Returns (mastered stereo audio, report dict).
    """
    if not stems:
        raise ValueError("mix_and_master needs at least one stem.")

    report: dict = {"stems": []}
    staged = gain_stage(stems, target_peak_dbfs=-12.0)
    for stem, stem_staged in zip(stems, staged):
        report["stems"].append(
            {
                "kind": stem.get("kind", "other"),
                "input_peak_dbfs": round(_peak_dbfs(stem["samples"]), 2),
                "staged_peak_dbfs": round(_peak_dbfs(stem_staged["samples"]), 2),
                "muted": bool(stem.get("is_muted")),
                "solo": bool(stem.get("is_solo")),
            }
        )

    shaped = [
        {**stem, "samples": shape_stem(stem.get("kind", ""), stem["samples"], sample_rate)}
        for stem in staged
    ]

    # Sidechain buses: drums and lead vocals act as the ducking keys.
    drums = sum_stems([{**s, "volume": 1.0, "pan": 0.0} for s in shaped if s.get("kind") == "drums"])
    vocals = sum_stems([{**s, "volume": 1.0, "pan": 0.0} for s in shaped if s.get("kind") == "vocals"])
    ducked = []
    for stem in shaped:
        kind = stem.get("kind", "")
        data = stem["samples"]
        if kind in ("bass", "melody") and np.any(drums):
            data = sidechain_duck(data, drums, sample_rate, threshold_db=-24.0, ratio=6.0, max_reduction_db=12.0)
        if kind == "melody" and np.any(vocals):
            data = sidechain_duck(data, vocals, sample_rate, threshold_db=-20.0, ratio=3.0, max_reduction_db=6.0)
        ducked.append({**stem, "samples": data})

    mixed = sum_stems(ducked)
    mixed = stereo_width(mixed, width)
    # pre-master headroom
    peak = float(np.max(np.abs(mixed)))
    if peak > 10.0 ** (-2.0 / 20.0):
        mixed = (mixed * ((10.0 ** (-2.0 / 20.0)) / peak)).astype(np.float32)

    mastered, master_report = master_chain(mixed, sample_rate, target_lufs=target_lufs)
    report.update(master_report)
    report["width"] = width
    return mastered, report
