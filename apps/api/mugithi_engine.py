"""On-device song generation engine with a Mugithi reference knowledge base.

The "experience" comes from MUGITHI_REFERENCE: distilled traits of classic
Mugithi records (single-guitar groove, alternating bass/strum pattern,
tempo switch, call-and-response hooks, common keys/progressions and themes).
That knowledge steers lyrics, prompts, and the audio arrangement rendered by
render_song(), which synthesizes a real WAV using Karplus-Strong string
physical modelling (acoustic guitar), a bass voice, and kick/shaker/snare.
"""

import os
import re
import unicodedata
import wave
from array import array

import numpy as np

SAMPLE_RATE = 22050
MAX_RENDER_SECONDS = 45

# ---------------------------------------------------------------------------
# Mugithi experience: reference knowledge distilled from the canon
# ---------------------------------------------------------------------------

MUGITHI_REFERENCE = {
    "artists": [
        "Joseph Kamaru",
        "John De'Mathew",
        "Queen Jane",
        "Samidoh",
        "Mighty Salim",
        "Kigia wa Esther",
    ],
    "songs": [
        "Wendo wa Cembe (cembe ya wendo) - hoe-of-love metaphor classics",
        "Tiga Kumute (De'Mathew) - storytelling over a single-guitar groove",
        "Mwendwa KK (Queen Jane) - call-and-response romantic duet phrasing",
        "Mũgithi train performances - nonstop medley with tempo switches",
    ],
    "style": {
        "tempo_bpm": 132,
        "meter": "4/4",
        "groove": "alternating bass-note / chord-stab eighth-note pattern (the 'one-man guitar' band style)",
        "structure": "intro riff -> verse groove -> chorus hook -> Mũgithi tempo switch -> fast outro",
        "harmony": "I-IV-V in a bright major key, pentatonic lead fills",
        "vocals": "call-and-response: solo voice calls, chorus answers",
    },
    "themes": [
        "wendo (love) told through everyday metaphors",
        "gũkũũ / nostalgia for the homeland",
        "dance and celebration (rĩmũ, mũgithi night)",
        "advice and storytelling (thimo na ngano)",
    ],
}

GENRE_KEYS = {
    "mugithi": "G",
    "benga": "A",
    "gospel": "C",
    "mwomboko": "F",
    "afro-pop": "A",
    "acoustic-folk": "G",
}

# Roman progressions per genre (scale degrees, major key)
GENRE_PROGRESSIONS = {
    "mugithi": [(0, "maj"), (3, "maj"), (0, "maj"), (4, "maj")],          # I IV I V
    "benga": [(0, "maj"), (0, "maj"), (3, "maj"), (4, "maj")],            # I I IV V
    "gospel": [(0, "maj"), (5, "min"), (3, "maj"), (4, "maj")],           # I vi IV V
    "mwomboko": [(0, "maj"), (4, "maj"), (0, "maj"), (4, "maj")],         # I V I V
    "afro-pop": [(5, "min"), (3, "maj"), (0, "maj"), (4, "maj")],         # vi IV I V
    "acoustic-folk": [(0, "maj"), (5, "min"), (3, "maj"), (4, "maj")],
}

GENRE_BPM = {"mugithi": 132, "benga": 138, "gospel": 96, "mwomboko": 118, "afro-pop": 104, "acoustic-folk": 92}

# How loud each instrument sits in the blend (mix gain) and its pitch
# offset in semitones relative to its written part.
INSTRUMENT_MIX = {
    "wandĩndĩ": {"gain": 0.9, "pitch": 0},
    "kĩgamba": {"gain": 0.5, "pitch": 0},
    "coro": {"gain": 0.7, "pitch": 0},
    "ndũmũ": {"gain": 0.75, "pitch": 0},
    "mũgũgũmũ": {"gain": 0.85, "pitch": 0},
    "acoustic guitar": {"gain": 1.0, "pitch": 0},
    "electric guitar": {"gain": 0.8, "pitch": 0},
    "bass": {"gain": 1.0, "pitch": 0},
    "accordion": {"gain": 0.55, "pitch": 0},
    "keyboard": {"gain": 0.5, "pitch": 0},
    "synthesizers": {"gain": 0.45, "pitch": 0},
    "brass section": {"gain": 0.6, "pitch": 0},
    "drum kit": {"gain": 0.9, "pitch": 0},
    "djembe": {"gain": 0.8, "pitch": 0},
    "marimba": {"gain": 0.5, "pitch": 0},
    "choir": {"gain": 0.6, "pitch": 0},
}

# Vocal loudness per section - verses intimate, chorus lifts, outro peaks.
VOCAL_SECTION_GAIN = {"verse": 1.0, "chorus": 1.35, "outro": 1.15}

NOTE_SEMITONES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
PENTATONIC = [0, 2, 4, 7, 9]


def reference_notes(genre: str):
    """Style references injected into prompts/jobs - the model's 'experience'."""
    ref = MUGITHI_REFERENCE
    style = ref["style"]
    return [
        f"Mugithi canon: {', '.join(ref['artists'][:4])}",
        f"Groove: {style['groove']}",
        f"Structure: {style['structure']}",
        f"Theme: {ref['themes'][0]}",
    ]


def _freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _midi(note_name: str, octave: int) -> int:
    return 12 * (octave + 1) + NOTE_SEMITONES[note_name]


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------

_pluck_cache = {}


def _ks_pluck(freq: float, dur: float, brightness: float = 0.6, decay: float = 0.996) -> np.ndarray:
    """Karplus-Strong plucked string - the acoustic guitar voice."""
    key = (round(freq, 1), round(dur, 2), brightness)
    if key in _pluck_cache:
        return _pluck_cache[key]
    n_samples = int(SAMPLE_RATE * dur)
    n_delay = max(2, int(SAMPLE_RATE / freq))
    rng = np.random.default_rng(int(freq * 100) % (2**32))
    buf = rng.uniform(-1, 1, n_delay) * brightness + np.linspace(1, -1, n_delay) * (1 - brightness)
    out = np.empty(n_samples, dtype=np.float64)
    for i in range(n_samples):
        out[i] = buf[i % n_delay]
        buf[i % n_delay] = decay * 0.5 * (buf[i % n_delay] + buf[(i + 1) % n_delay])
    # quick attack, natural release
    env = np.minimum(1.0, np.arange(n_samples) / (0.002 * SAMPLE_RATE))
    tail = np.exp(-np.arange(n_samples) / (dur * SAMPLE_RATE * 0.9))
    result = (out * env * tail).astype(np.float32)
    _pluck_cache[key] = result
    return result


def _kick(dur: float = 0.18) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE
    sweep = 110 * np.exp(-t * 22) + 45
    sig = np.sin(2 * np.pi * np.cumsum(sweep) / SAMPLE_RATE)
    return (sig * np.exp(-t * 18)).astype(np.float32)


def _shaker(dur: float = 0.09) -> np.ndarray:
    n = int(SAMPLE_RATE * dur)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    noise = np.diff(noise, prepend=0.0)  # crude highpass -> crisp shaker
    t = np.arange(n) / SAMPLE_RATE
    return (noise * np.exp(-t * 40) * 0.6).astype(np.float32)


def _snare(dur: float = 0.14) -> np.ndarray:
    n = int(SAMPLE_RATE * dur)
    rng = np.random.default_rng(11)
    t = np.arange(n) / SAMPLE_RATE
    noise = rng.standard_normal(n) * np.exp(-t * 26)
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 32)
    return ((noise * 0.7 + body * 0.4)).astype(np.float32)


def _place(mix: np.ndarray, sig: np.ndarray, offset_s: float, gain: float) -> None:
    start = int(offset_s * SAMPLE_RATE)
    end = min(len(mix), start + len(sig))
    if start >= len(mix):
        return
    mix[start:end] += sig[: end - start] * gain


# ---------------------------------------------------------------------------
# Full instrument provision - every instrument in the style catalog can be
# synthesized and layered into the arrangement.
# ---------------------------------------------------------------------------

INSTRUMENT_CATALOG = {
    # Traditional
    "wandĩndĩ": {"name": "Wandĩndĩ (single-string fiddle)", "category": "traditional"},
    "kĩgamba": {"name": "Kĩgamba (leg rattles)", "category": "traditional"},
    "coro": {"name": "Coro (horn)", "category": "traditional"},
    "ndũmũ": {"name": "Ndũmũ (flute)", "category": "traditional"},
    "mũgũgũmũ": {"name": "Mũgũgũmũ (percussion drum)", "category": "traditional"},
    # Modern
    "acoustic guitar": {"name": "Acoustic Guitar", "category": "modern"},
    "electric guitar": {"name": "Electric Guitar", "category": "modern"},
    "bass": {"name": "Bass", "category": "modern"},
    "accordion": {"name": "Accordion", "category": "modern"},
    "keyboard": {"name": "Keyboard", "category": "modern"},
    "synthesizers": {"name": "Synthesizers", "category": "modern"},
    "brass section": {"name": "Brass Section", "category": "modern"},
    "drum kit": {"name": "Drum Kit", "category": "modern"},
    "djembe": {"name": "Djembe", "category": "modern"},
    "marimba": {"name": "Marimba", "category": "modern"},
    "choir": {"name": "Choir", "category": "modern"},
}


def _saw(freq: float, dur: float, gain_env: bool = True) -> np.ndarray:
    """Bright sawtooth voice for reeds/accordion/brass."""
    n = int(SAMPLE_RATE * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n) / SAMPLE_RATE
    sig = np.zeros(n)
    for h in range(1, 10):
        sig += (1.0 / h) * np.sin(2 * np.pi * freq * h * t)
    if gain_env:
        sig *= np.exp(-t / max(dur * 0.7, 0.05))
    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak * 0.5).astype(np.float32)


def _flute(freq: float, dur: float) -> np.ndarray:
    """Airy flute: sine + soft breath noise."""
    n = int(SAMPLE_RATE * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 2 * t)
    rng = np.random.default_rng(int(freq) % (2**32))
    breath = rng.standard_normal(n) * 0.03
    env = np.minimum(1.0, np.arange(n) / (0.05 * SAMPLE_RATE))
    release = max(1, int(0.1 * SAMPLE_RATE))
    env[-release:] *= np.linspace(1.0, 0.0, release)
    out = (tone * 0.5 + breath) * env
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.4).astype(np.float32)


def _horn(freq: float, dur: float) -> np.ndarray:
    """Resonant horn/coro call: strong fundamental + 2nd harmonic swell."""
    n = int(SAMPLE_RATE * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n) / SAMPLE_RATE
    swell = np.minimum(1.0, np.arange(n) / (0.12 * SAMPLE_RATE)) * np.exp(-t / max(dur * 0.8, 0.1))
    sig = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2 * t) + 0.25 * np.sin(2 * np.pi * freq * 3 * t)
    out = sig * swell
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.5).astype(np.float32)


def _marimba(freq: float, dur: float) -> np.ndarray:
    """Marimba: mallet attack with fast-decaying resonant tone."""
    n = int(SAMPLE_RATE * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n) / SAMPLE_RATE
    sig = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 4 * t)
    env = np.exp(-t / max(dur * 0.35, 0.03))
    out = sig * env
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.45).astype(np.float32)


def _drum_hit(dur: float = 0.12, pitch: float = 70.0) -> np.ndarray:
    """Low drum (mũgũgũmũ / djembe body)."""
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n) / SAMPLE_RATE
    sweep = pitch * np.exp(-t * 18) + 40
    sig = np.sin(2 * np.pi * np.cumsum(sweep) / SAMPLE_RATE)
    return (sig * np.exp(-t * 15) * 0.8).astype(np.float32)


def _rattle(dur: float = 0.08) -> np.ndarray:
    """Kĩgamba rattle: cluster of short noise bursts."""
    n = int(SAMPLE_RATE * dur)
    rng = np.random.default_rng(5)
    sig = np.zeros(n)
    for burst in range(0, n, max(1, n // 5)):
        end = min(n, burst + int(0.02 * SAMPLE_RATE))
        sig[burst:end] = rng.standard_normal(end - burst)
    sig = np.diff(sig, prepend=0.0)
    t = np.arange(n) / SAMPLE_RATE
    return (sig * np.exp(-t * 30) * 0.5).astype(np.float32)


def _layer_instruments(mix: np.ndarray, instruments: list, key_root: str, progression: list, sections: list, bpm: float, rng) -> None:
    """Layer each selected instrument into the arrangement, blended by gain
    and pitch per INSTRUMENT_MIX for a balanced, in-tune mix."""
    base = _midi(key_root, 4)
    kick, shaker = _kick(), _shaker()
    t = 0.0
    for section, bars, sec_bpm in sections:
        beat = 60 / sec_bpm
        for bar in range(bars):
            degree, quality = progression[bar % len(progression)]
            chord = _chord_midis(key_root, degree, quality, 3)
            bar_start = t
            for inst in instruments:
                slug = inst.strip().lower()
                blend = INSTRUMENT_MIX.get(slug, {"gain": 0.6, "pitch": 0})
                gain = blend["gain"]
                semitones = blend["pitch"]
                pitch_ratio = 2 ** (semitones / 12)
                if slug == "kĩgamba":
                    for b in range(4):
                        _place(mix, _rattle(), bar_start + b * beat, gain)
                elif slug in ("mũgũgũmũ", "djembe"):
                    _place(mix, _drum_hit(), bar_start, gain)
                    _place(mix, _drum_hit(0.1, 90.0 * pitch_ratio), bar_start + 2 * beat, gain * 0.85)
                elif slug in ("ndũmũ", "flute") and section in ("verse", "chorus"):
                    note = base + PENTATONIC[rng.integers(0, len(PENTATONIC))]
                    _place(mix, _flute(_freq(note) * pitch_ratio, beat * 2), bar_start, gain)
                elif slug == "coro" and section in ("intro", "chorus"):
                    _place(mix, _horn(_freq(base) * pitch_ratio, beat * 1.5), bar_start, gain)
                elif slug in ("wandĩndĩ", "fiddle") and section in ("verse", "chorus"):
                    note = base + 12 + PENTATONIC[rng.integers(0, len(PENTATONIC))]
                    _place(mix, _ks_pluck(_freq(note) * pitch_ratio, beat, brightness=0.9), bar_start + beat, gain)
                elif slug in ("accordion", "keyboard", "synthesizers", "brass section") and section != "intro":
                    for m in chord:
                        _place(mix, _saw(_freq(m + 12) * pitch_ratio, beat * 1.8), bar_start, gain)
                elif slug == "marimba" and section in ("verse", "chorus"):
                    for b in range(4):
                        note = base + PENTATONIC[(bar + b) % len(PENTATONIC)]
                        _place(mix, _marimba(_freq(note + 12) * pitch_ratio, beat * 0.9), bar_start + b * beat, gain)
                elif slug == "drum kit" and section != "intro":
                    for b in range(4):
                        _place(mix, kick, bar_start + b * beat, gain * 0.7)
                        _place(mix, shaker, bar_start + b * beat + beat / 2, gain * 0.5)
            t = bar_start + 4 * beat


# ---------------------------------------------------------------------------
# Arrangement + rendering
# ---------------------------------------------------------------------------

def _chord_midis(key_root: str, degree: int, quality: str, octave: int) -> list:
    root_midi = _midi(key_root, octave) + MAJOR_SCALE[degree]
    third = root_midi + (3 if quality == "min" else 4)
    return [root_midi, third, root_midi + 7]


def _lead_phrase(key_root: str, rng, bars: int, octave: int = 5) -> list:
    """Call-and-response pentatonic phrase; the 'answer' resolves to the root."""
    base = _midi(key_root, octave)
    notes = []
    phrase = [rng.choice(PENTATONIC) for _ in range(bars * 2)]
    for i, deg in enumerate(phrase):
        is_answer_end = i % (bars * 2) == (bars * 2 - 1)
        notes.append(base + (0 if is_answer_end else deg))
    return notes


# ---------------------------------------------------------------------------
# Vocal synthesis - a simple singing voice for the lyrics
# ---------------------------------------------------------------------------

VOWEL_FORMANTS = {
    "a": [730, 1090, 2440],
    "e": [530, 1840, 2480],
    "i": [390, 1990, 2550],
    "o": [570, 840, 2410],
    "u": [300, 870, 2240],
}


def _sing_vowel(freq: float, dur: float, vowel: str, intensity: float = 1.0) -> np.ndarray:
    """Synthesize a sung vowel: glottal pulse source shaped by formant resonances,
    with vibrato and an amplitude envelope - reads as a vocal line.

    intensity drives vocal dynamics: louder, a touch of upward pitch bend,
    deeper vibrato, and a crescendo swell across the note."""
    n = int(SAMPLE_RATE * dur)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n) / SAMPLE_RATE
    vibrato = 1.0 + 0.008 * intensity * np.sin(2 * np.pi * 5.5 * t)  # vibrato deepens with intensity
    bend = 1.0 + 0.004 * intensity * (t / max(dur, 1e-6))  # slight pitch bend up over the note
    phase = 2 * np.pi * np.cumsum(freq * vibrato * bend) / SAMPLE_RATE
    sig = np.zeros(n)
    for harmonic in range(1, 7):
        sig += (1.0 / harmonic) * np.sin(harmonic * phase)
    sig *= 0.6  # stronger glottal source
    # formant resonances give the vowel its character
    out = np.zeros(n)
    for formant in VOWEL_FORMANTS.get(vowel.lower(), VOWEL_FORMANTS["a"]):
        out += _resonate(sig, formant, formant * 0.15)
    peak = float(np.max(np.abs(out))) or 1.0
    out = out / peak * 0.9  # normalize each sung note to a consistent level
    # amplitude envelope: quick attack, sustain, short release
    env = np.minimum(1.0, np.arange(n) / (0.03 * SAMPLE_RATE))
    release = max(1, int(0.08 * SAMPLE_RATE))
    env[-release:] *= np.linspace(1.0, 0.0, release)
    crescendo = 0.7 + 0.6 * intensity * (t / max(dur, 1e-6))  # swell through the note
    return (out * env * crescendo).astype(np.float32)


def _resonate(x: np.ndarray, center: float, bw: float) -> np.ndarray:
    """Fast formant resonator via FFT bandpass around `center` Hz."""
    if len(x) == 0:
        return x
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SAMPLE_RATE)
    gain = 1.0 / (1.0 + ((freqs - center) / max(bw, 1.0)) ** 2)
    return np.fft.irfft(spectrum * gain, len(x))


def _lyrics_sections(lyrics: str) -> dict:
    """Split structured lyrics into {section: [lines]} by [Section] headers."""
    sections: dict = {}
    current = "verse"
    for raw in (lyrics or "").splitlines():
        line = raw.strip()
        match = re.match(r"^\[(.+?)\]", line)
        if match:
            label = match.group(1).lower()
            if "chorus" in label:
                current = "chorus"
            elif "outro" in label or "tempo" in label or "switch" in label:
                current = "outro"
            elif "interlude" in label or "solo" in label:
                current = "_instrumental"
            else:
                current = "verse"
            continue
        if line and current != "_instrumental":
            sections.setdefault(current, []).append(line)
    return sections


def _place_vocals(mix: np.ndarray, key_root: str, lyrics: str, section_times: dict, bpm: float, rng, vocal_energy: float = 1.0) -> None:
    """Sing the lyrics over verse/chorus/outro with dynamics: verses stay
    intimate, the chorus lifts and doubles, phrases swell toward their end.
    vocal_energy widens the expressive range when vocal dynamics call for it."""
    lyrics_sections = _lyrics_sections(lyrics)
    if not any(lyrics_sections.values()):
        return
    base = _midi(key_root, 4)
    beat = 60 / bpm
    for section in ("verse", "chorus", "outro"):
        lines = lyrics_sections.get(section) or []
        if not lines or section not in section_times:
            continue
        start_t, dur_t = section_times[section]
        words = " ".join(lines).split()
        if not words:
            continue
        step = dur_t / len(words)
        section_gain = VOCAL_SECTION_GAIN.get(section, 1.0) * vocal_energy
        for i, word in enumerate(words):
            note = base + PENTATONIC[rng.integers(0, len(PENTATONIC))]
            vowel = next((c for c in word if c.lower() in VOWEL_FORMANTS), "a")
            note_dur = min(max(step * 0.9, beat * 0.35), beat * 1.1)
            phrase_pos = i / max(len(words) - 1, 1)
            intensity = section_gain * (0.85 + 0.3 * phrase_pos)  # phrases swell toward the end
            _place(mix, _sing_vowel(_freq(note), note_dur, vowel, intensity), start_t + i * step, 1.5)
            if section == "chorus":
                # Double the chorus lead a third above for a fuller vocal.
                _place(mix, _sing_vowel(_freq(note + 4), note_dur, vowel, intensity * 0.7), start_t + i * step, 0.6)


def render_song(payload: dict, out_dir: str, stem: str, remaster: bool = False) -> dict:
    """Render a real WAV grounded in the Mugithi reference style."""
    genre = (payload.get("genre") or "mugithi").lower()
    bpm = GENRE_BPM.get(genre, 120)
    key_root = GENRE_KEYS.get(genre, "G")
    progression = GENRE_PROGRESSIONS.get(genre, GENRE_PROGRESSIONS["mugithi"])
    is_mugithi = genre == "mugithi"

    target = max(12, min(int(payload.get("duration_sec") or 120), MAX_RENDER_SECONDS))
    bar_dur = 4 * 60 / bpm
    total_bars = max(10, int(round(target / bar_dur)))
    # Mugithi structure: intro riff | verse | chorus | tempo switch | fast outro
    intro_bars, chorus_bars, switch_bars, outro_bars = 1, 4, (1 if is_mugithi else 0), 3
    verse_bars = max(2, total_bars - intro_bars - chorus_bars - switch_bars - outro_bars)

    fast_bpm = bpm * (1.18 if is_mugithi else 1.0)  # the Mũgithi tempo switch
    sections = [("intro", intro_bars, bpm), ("verse", verse_bars, bpm), ("chorus", chorus_bars, bpm)]
    if switch_bars:
        sections.append(("switch", switch_bars, bpm))
    sections.append(("outro", outro_bars, fast_bpm))

    total_s = sum(bars * 4 * 60 / sec_bpm for _, bars, sec_bpm in sections) + 1.5
    mix = np.zeros(int(SAMPLE_RATE * total_s), dtype=np.float32)
    rng = np.random.default_rng(42)
    swing = float(payload.get("swing") or 0.08)  # eighth-note swing: speeds/slows off-beats

    # Vocal dynamics: "dynamic"/"emotive" widen the expressive range.
    vocal_dynamics = (payload.get("vocal_dynamics") or "").lower()
    vocal_energy = 1.2 if any(k in vocal_dynamics for k in ("dynamic", "emotive", "expressive")) else 1.0

    # Percussion pattern: keywords steer beat emphasis.
    percussion_pattern = (payload.get("percussion_pattern") or "").lower()
    kick_gain = 1.0 if "steady kick" in percussion_pattern or "kick" in percussion_pattern else 0.9
    snare_gain = 1.1 if "snare" in percussion_pattern else 1.0
    extra_syncopation = "syncopat" in percussion_pattern
    lyrics = unicodedata.normalize("NFC", payload.get("lyrics") or "")
    section_times: dict = {}

    kick, shaker, snare = _kick(), _shaker(), _snare()
    lead_notes = _lead_phrase(key_root, rng, 2)

    t = 0.0
    lead_idx = 0
    for section, bars, sec_bpm in sections:
        beat = 60 / sec_bpm
        eighth = beat / 2
        section_start = t
        for bar in range(bars):
            degree, quality = progression[bar % len(progression)]
            chord = _chord_midis(key_root, degree, quality, 3)
            bass_root = chord[0] - 12
            bar_start = t
            # Groove: 8 eighth-note slots -> alternating bass note / chord stab
            for slot in range(8):
                slot_t = bar_start + slot * eighth
                if slot % 2 == 0:
                    bass_note = bass_root if slot % 4 == 0 else bass_root + 7
                    _place(mix, _ks_pluck(_freq(bass_note), eighth * 1.8, brightness=0.3, decay=0.994), slot_t, 0.85)
                else:
                    if section == "intro" and slot < 4:
                        continue
                    for j, m in enumerate(chord):
                        _place(mix, _ks_pluck(_freq(m), eighth * 1.5), slot_t + j * 0.006, 0.38)
            # Percussion: four-on-the-floor kick, swung 8th shakers, snare on 2 & 4
            for b in range(4):
                _place(mix, kick, bar_start + b * beat, (0.9 if section != "intro" else 0.5) * kick_gain)
                _place(mix, shaker, bar_start + b * beat + eighth * (1 + swing), 0.5)
                if section in ("chorus", "outro"):
                    _place(mix, shaker, bar_start + b * beat, 0.3)
                if b in (1, 3) and section not in ("intro",):
                    _place(mix, snare, bar_start + b * beat, 0.55 * snare_gain)
                if extra_syncopation and section != "intro":
                    _place(mix, snare, bar_start + b * beat + eighth * 1.5, 0.3)
            # Call-and-response lead hook in chorus/outro
            if section in ("chorus", "outro"):
                for k in range(2):
                    note = lead_notes[lead_idx % len(lead_notes)]
                    lead_idx += 1
                    _place(mix, _ks_pluck(_freq(note), beat * 1.6, brightness=0.8), bar_start + k * 2 * beat, 0.5)
            t = bar_start + 4 * beat
        section_times[section] = (section_start, t - section_start)

    # Sing the lyrics over the sung sections
    _place_vocals(mix, key_root, lyrics, section_times, bpm, rng, vocal_energy)

    # Layer every selected instrument
    _layer_instruments(mix, payload.get("instruments") or [], key_root, progression, sections, bpm, rng)

    # gentle master: soft clip + normalize
    mix = np.tanh(mix)
    if remaster:
        # Remaster: gentle compression, presence lift, louder output.
        threshold = 0.55
        over = np.abs(mix) > threshold
        mix = np.where(over, np.sign(mix) * (threshold + (np.abs(mix) - threshold) * 0.4), mix)
        mix = mix + 0.15 * np.diff(mix, prepend=mix[0])  # presence / air
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = (mix / peak * (0.98 if remaster else 0.92)).astype(np.float32)
    fade = int(SAMPLE_RATE * 0.8)
    mix[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)

    os.makedirs(out_dir, exist_ok=True)
    filename = f"{stem}.wav"
    path = os.path.join(out_dir, filename)
    pcm = array("h", (mix * 32767).astype(np.int16))
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())

    bucket = max(1, len(mix) // 64)
    peaks = [round(float(np.max(np.abs(mix[i : i + bucket]))), 4) for i in range(0, len(mix), bucket)][:64]
    return {
        "filename": filename,
        "duration": round(len(mix) / SAMPLE_RATE, 2),
        "waveform": peaks,
        "bpm": bpm,
        "tempo_switched": is_mugithi,
        "references": reference_notes(genre),
    }
