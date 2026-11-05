"""Formant singing-voice synthesizer for Gĩkũyũ lyrics.

Turns structured lyrics into audible singing — locally, with no external
model — by exploiting two facts:

1. Gĩkũyũ is strictly CV-syllabic with a 7-vowel system, so deterministic
   syllabification + per-vowel formant targets produce intelligible sung
   vowels with consonant onsets (nasal murmurs, plosive bursts, fricatives).
2. A buzzy glottal source (harmonic series with vibrato) shaped by three
   Lorentzian formant resonances reads to the ear as a human singing voice.

The selected voice profile's vocal_type sets the register (f0 range),
formant scaling, ensemble size and detune — male/female leads, child
soloist, children's/male/female/mixed choirs, and male–female duet.

This replaces the old single-sine "guide vocal". For production-grade sung
vocals use Suno/YuE via the provider seam + RVC cloning; this synth keeps
local renders singable.
"""

from __future__ import annotations

import math
import unicodedata

import numpy as np

# --- The 7-vowel Gĩkũyũ formant map (F1, F2, F3 Hz at male formant scale) ---
VOWEL_FORMANTS = {
    "a": (750.0, 1250.0, 2600.0),
    "e": (530.0, 1850.0, 2500.0),   # /ɛ/
    "i": (400.0, 2000.0, 2650.0),   # /ɪ/
    "o": (520.0, 1000.0, 2450.0),   # /ɔ/
    "u": (420.0, 1050.0, 2450.0),   # /ʊ/
    "ĩ": (300.0, 2250.0, 2900.0),   # /i/
    "ũ": (300.0, 900.0, 2350.0),    # /u/
}

# Voice-profile vocal registers and ensemble character.
VOICE_PARAMS = {
    "male_lead": {"min_f0": 90.0, "max_f0": 330.0, "scale": 1.00, "members": 1, "detune_cents": 0.0, "timing_ms": 0.0, "octave_spread": False, "breath": 0.02},
    "female_lead": {"min_f0": 175.0, "max_f0": 520.0, "scale": 1.15, "members": 1, "detune_cents": 0.0, "timing_ms": 0.0, "octave_spread": False, "breath": 0.03},
    "child": {"min_f0": 240.0, "max_f0": 620.0, "scale": 1.30, "members": 1, "detune_cents": 0.0, "timing_ms": 0.0, "octave_spread": False, "breath": 0.05},
    "children_choir": {"min_f0": 230.0, "max_f0": 600.0, "scale": 1.28, "members": 6, "detune_cents": 10.0, "timing_ms": 22.0, "octave_spread": False, "breath": 0.05},
    "male_choir": {"min_f0": 80.0, "max_f0": 340.0, "scale": 1.00, "members": 6, "detune_cents": 9.0, "timing_ms": 18.0, "octave_spread": True, "breath": 0.03},
    "female_choir": {"min_f0": 170.0, "max_f0": 540.0, "scale": 1.15, "members": 6, "detune_cents": 9.0, "timing_ms": 18.0, "octave_spread": True, "breath": 0.04},
    "mixed_choir": {"min_f0": 90.0, "max_f0": 560.0, "scale": 1.08, "members": 8, "detune_cents": 12.0, "timing_ms": 26.0, "octave_spread": True, "breath": 0.04},
    "duet": {"min_f0": 95.0, "max_f0": 520.0, "scale": 1.05, "members": 2, "detune_cents": 4.0, "timing_ms": 8.0, "octave_spread": False, "breath": 0.03, "member_ratios": (1.0, 1.86), "member_scales": (1.00, 1.15)},
}

# --- Gĩkũyũ CV syllabification ----------------------------------------------
_ONSET_CLUSTERS = ("ng'", "ndw", "njw", "ngw", "th", "mb", "nd", "nj", "ng", "ny", "mw", "kw", "gw", "rw", "tw")
_ONSET_SINGLE = "mnkgcrthwyb"
_VOWEL_SET = frozenset("aeiouĩũ")
_NASALS = frozenset({"m", "n", "ny", "ng'", "ng"})
_PLOSIVES = frozenset({"b", "t", "k", "g", "mb", "nd", "nj", "ndw", "njw", "ngw"})
_FRICATIVES = frozenset({"th", "c", "h"})


def syllabify_gikuyu(word: str) -> list[tuple[str, str]]:
    """Split a word into (onset, nucleus) CV syllables; punctuation drops,
    apostrophes survive (ng' is a phoneme)."""
    w = unicodedata.normalize("NFC", word or "").lower()
    w = "".join(ch for ch in w if ch.isalpha() or ch == "'")
    syllables: list[tuple[str, str]] = []
    i = 0
    while i < len(w):
        onset = ""
        if w[i] not in _VOWEL_SET:
            for cluster in _ONSET_CLUSTERS:
                if w.startswith(cluster, i):
                    onset = cluster
                    break
            else:
                if w[i] in _ONSET_SINGLE:
                    onset = w[i]
            if not onset:
                i += 1
                continue
            i += len(onset)
        if i < len(w) and w[i] in _VOWEL_SET:
            syllables.append((onset, w[i]))
            i += 1
    return syllables


def syllabify_lines(lines: list[str]) -> list[tuple[str, str]]:
    """Flatten lyric lines into one syllable stream."""
    syllables: list[tuple[str, str]] = []
    for line in lines:
        for word in line.split():
            syllables.extend(syllabify_gikuyu(word))
    return syllables


# --- Synthesis internals ------------------------------------------------------

def _register_freq(note_midi: float, params: dict) -> float:
    """Wrap the melody note into the voice's sung register by octaves."""
    freq = 440.0 * 2.0 ** ((note_midi - 69) / 12.0)
    while freq < params["min_f0"]:
        freq *= 2.0
    while freq > params["max_f0"]:
        freq *= 0.5
    return freq


def _glottal_source(f0: float, dur: float, sr: int, intensity: float, rng) -> np.ndarray:
    """Harmonic-series glottal buzz with vibrato and a slight rising bend."""
    n = int(sr * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n) / sr
    vib_depth = 0.006 + 0.004 * min(intensity, 1.6)
    vibrato = 1.0 + vib_depth * np.sin(2 * np.pi * 5.4 * t + rng.uniform(0, 2 * np.pi))
    bend = 1.0 + 0.003 * intensity * (t / max(dur, 1e-6))
    phase = 2 * np.pi * np.cumsum(f0 * vibrato * bend) / sr
    n_harmonics = max(1, min(24, int((sr * 0.45) / f0)))
    sig = np.zeros(n)
    for harmonic in range(1, n_harmonics + 1):
        sig += (1.0 / harmonic) * np.sin(harmonic * phase)
    return sig


def _formant_shape(sig: np.ndarray, sr: int, formants: tuple, scale: float, breath: float, rng) -> np.ndarray:
    """Shape the glottal source with three formant resonances + aspiration."""
    if len(sig) == 0:
        return sig
    spectrum = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(len(sig), 1.0 / sr)
    gain = 1.0 / np.sqrt(np.maximum(freqs, 20.0) / 100.0)  # glottal spectral tilt
    for formant, bandwidth in zip(formants, (90.0, 110.0, 150.0)):
        center = formant * scale
        gain = gain + 6.0 / (1.0 + ((freqs - center) / bandwidth) ** 2)
    out = np.fft.irfft(spectrum * gain, len(sig))
    if breath > 0:
        noise = rng.standard_normal(len(sig))
        airy = np.fft.irfft(np.fft.rfft(noise) * ((freqs > 2000.0) & (freqs < 8000.0)), len(sig))
        airy /= max(float(np.max(np.abs(airy))), 1e-9)
        out = out + breath * (float(np.max(np.abs(out))) or 1.0) * airy
    return out


def _bandpass_noise(dur: float, sr: int, low: float, high: float, rng, level: float) -> np.ndarray:
    n = int(sr * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    noise = rng.standard_normal(n)
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spectrum *= ((freqs >= low) & (freqs <= high))
    sig = np.fft.irfft(spectrum, n)
    sig /= max(float(np.max(np.abs(sig))), 1e-9)
    env = np.exp(-np.arange(n) / max(1.0, n / 3.0))
    return (level * sig * env).astype(np.float32)


def _consonant(onset: str, sr: int, rng) -> np.ndarray:
    """Consonant onset: nasal murmur, plosive burst, fricative noise, or glide."""
    if not onset:
        return np.zeros(0, dtype=np.float32)
    if onset in _NASALS:
        n = int(0.05 * sr)
        t = np.arange(n) / sr
        freq = 210.0 + rng.uniform(-15.0, 15.0)
        sig = (np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(4 * np.pi * freq * t)) * np.exp(-t * 18.0)
        return (0.30 * sig).astype(np.float32)
    if onset in _PLOSIVES:
        burst = _bandpass_noise(0.028, sr, 1200.0, 4200.0, rng, level=0.30)
        return np.concatenate([burst, np.zeros(int(0.012 * sr), dtype=np.float32)])
    if onset in _FRICATIVES:
        bands = {"th": (1100.0, 2600.0), "c": (1800.0, 4500.0), "h": (500.0, 1500.0)}
        low, high = bands[onset]
        return _bandpass_noise(0.06, sr, low, high, rng, level=0.18)
    # Glides / liquids: brief low formant hum sliding into the vowel.
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    return (np.sin(2 * np.pi * 650.0 * t) * np.linspace(0.10, 0.35, n)).astype(np.float32)


def _synthesize_vowel(f0: float, dur: float, formants: tuple, scale: float, breath: float, intensity: float, rng, sr: int) -> np.ndarray:
    sig = _glottal_source(f0, dur, sr, intensity, rng)
    out = _formant_shape(sig, sr, formants, scale, breath, rng)
    n = len(out)
    if n == 0:
        return out.astype(np.float32)
    out = out / max(float(np.max(np.abs(out))), 1e-9)
    env = np.minimum(1.0, np.arange(n) / max(1, int(0.025 * sr)))
    release = max(1, int(0.12 * dur * sr))
    env[-release:] *= np.linspace(1.0, 0.0, release)
    crescendo = 0.75 + 0.5 * intensity * (np.arange(n) / max(n, 1))
    return (out * env * crescendo).astype(np.float32)


def _member_ratios(params: dict) -> tuple:
    if "member_ratios" in params:
        return params["member_ratios"]
    members = params["members"]
    if params.get("octave_spread"):
        # Every third chorister sings an octave down (basses/tenors anchor).
        return tuple(0.5 if i % 3 == 0 else 1.0 for i in range(members))
    return (1.0,) * members


def sing_syllable(
    onset: str,
    nucleus: str,
    note_midi: float,
    dur: float,
    intensity: float = 1.0,
    vocal_type: str = "male_lead",
    rng=None,
    sample_rate: int = 22050,
) -> np.ndarray:
    """Render one sung syllable (consonant onset + voiced vowel) at a note.

    Ensembles (choirs) sum detuned, timing-jittered ensemble members; the duet
    pairs a male- and female-scaled voice.
    """
    rng = rng if rng is not None else np.random.default_rng()
    params = VOICE_PARAMS.get(vocal_type, VOICE_PARAMS["male_lead"])
    base_freq = _register_freq(note_midi, params)
    formants = VOWEL_FORMANTS.get(nucleus, VOWEL_FORMANTS["a"])
    ratios = _member_ratios(params)
    member_scales = params.get("member_scales") or (params["scale"],) * params["members"]

    attack = _consonant(onset, sample_rate, rng)
    members: list[tuple[np.ndarray, int]] = []
    max_len = 0
    for member in range(params["members"]):
        detune = 2.0 ** (rng.uniform(-params["detune_cents"], params["detune_cents"]) / 1200.0)
        f0 = base_freq * ratios[member % len(ratios)] * detune
        vowel = _synthesize_vowel(f0, dur, formants, member_scales[member % len(member_scales)], params["breath"], intensity, rng, sample_rate)
        audio = np.concatenate([attack, vowel])
        offset = int(rng.uniform(0.0, params["timing_ms"]) * sample_rate / 1000.0)
        members.append((audio, offset))
        max_len = max(max_len, offset + len(audio))

    out = np.zeros(max_len, dtype=np.float32)
    member_gain = 1.0 / math.sqrt(params["members"])
    for audio, offset in members:
        out[offset : offset + len(audio)] += audio * member_gain
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.85).astype(np.float32)
