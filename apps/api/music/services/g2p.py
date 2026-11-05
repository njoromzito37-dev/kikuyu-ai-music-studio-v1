"""Rule-based grapheme-to-phoneme (G2P) conditioning for Gĩkũyũ lyrics.

Gĩkũyũ orthography is near-phonemic — seven vowels (a, e, i, ĩ, o, u, ũ) and a
compact consonant inventory with a few digraphs — so deterministic rules yield
a reliable IPA-ish phoneme stream for lyric-conditioned audio models (a
YuE-style generator, or an HTTP backend that accepts phoneme hints).

Tone is phonemic in Gĩkũyũ but unmarked in standard orthography, so tone is
intentionally not transcribed; statistical G2P/ASR models can refine this
later without changing the interface.
"""

from __future__ import annotations

import re
import unicodedata

# Order matters: longest (digraph) matches must be tried before single letters.
_G2P_RULES = (
    ("ng'", "ŋ"),   # velar nasal, as in ng'ombe
    ("ng", "ᵑɡ"),   # prenasalized voiced velar stop
    ("ny", "ɲ"),    # palatal nasal
    ("nd", "ⁿd"),
    ("mb", "ᵐb"),
    ("nj", "ᶮdʒ"),
    ("th", "ð"),    # voiced dental fricative, as in thayũ
    ("ĩ", "i"),     # close front vowel (vs. i = /ɪ/)
    ("ũ", "u"),     # close back vowel (vs. u = /ʊ/)
    ("e", "ɛ"),
    ("i", "ɪ"),
    ("o", "ɔ"),
    ("u", "ʊ"),
    ("b", "ɓ"),     # implosive bilabial
    ("c", "ʃ"),     # as in gũcookia
    ("g", "ɣ"),     # voiced velar fricative
    ("y", "j"),
    # Identity by design: a k m n t r h w
)

_PATTERN = re.compile("|".join(re.escape(source) for source, _ in _G2P_RULES))
_MAP = dict(_G2P_RULES)
_SEPARATOR = re.compile(r"([^\w']+)")  # keep apostrophes inside words for ng'
_SECTION_TAG = re.compile(r"^\s*\[[^\]]+\]\s*$")


def gikuyu_g2p(text: str) -> str:
    """Convert a Gĩkũyũ string to a phoneme string (whitespace preserved)."""
    normalized = unicodedata.normalize("NFC", text or "").lower()
    parts = []
    for part in _SEPARATOR.split(normalized):
        if not part or _SEPARATOR.fullmatch(part):
            parts.append(part)
        else:
            parts.append(_PATTERN.sub(lambda match: _MAP[match.group(0)], part))
    return "".join(parts)


def phonemize_lyrics(lyrics: str) -> str:
    """Phonemize lyric lines while keeping [Verse]/[Chorus] section tags intact."""
    lines = []
    for line in (lyrics or "").splitlines():
        lines.append(line if _SECTION_TAG.match(line) else gikuyu_g2p(line))
    return "\n".join(lines)


def lyric_phonemes(lyrics: str, language: str) -> str:
    """Phoneme conditioning string for the generation payload ('' when n/a)."""
    if (language or "").strip().lower() != "gikuyu":
        return ""
    return phonemize_lyrics(lyrics)
