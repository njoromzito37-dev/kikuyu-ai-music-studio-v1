"""Master instrument catalog with timbre/role metadata.

Reference data describing how each instrument sounds and what it does in the
arrangement. Used to enrich generation prompts with timbral detail when an
instrument has no entry in the prompt engine's static table.
"""

from __future__ import annotations

import unicodedata

MASTER_INSTRUMENT_CATALOG = {
    "traditional_strings": [
        {"name": "Acoustic Rhythms Guitar (Mũgithi Steel-string)", "timbre": "Bright, percussive rhythmic strumming", "role": "Backbone harmonic driver"},
        {"name": "Nyatiti (Traditional 8-string Lyre)", "timbre": "Warm, resonant wooden plucks", "role": "Melodic counterpoint"},
        {"name": "Luo Orutu (Single-string Fiddle)", "timbre": "Expressive, crying bowed sustain", "role": "Lead melodic hooks"}
    ],
    "percussion_and_rhythm": [
        {"name": "Traditional Djembe / Calabash Drum", "timbre": "Deep low-end thud with crisp slaps", "role": "Groove foundation"},
        {"name": "Shakers & Metal Clackers", "timbre": "High-frequency crisp transient tick", "role": "Polyrhythmic texture"},
        {"name": "Electronic Trap 808 Sub-Bass", "timbre": "Subterranean, sliding low-end weight", "role": "Modern low-end punch"},
        {"name": "Punchy Modern Drum Kit", "timbre": "Gated snares, crisp hats, heavy kicks", "role": "Rhythmic anchor"}
    ],
    "harmonic_and_melodic": [
        {"name": "Grand Piano", "timbre": "Rich, dynamic acoustic chords", "role": "Atmospheric filler"},
        {"name": "Dark Melodic Bell / Pluck Synth", "timbre": "Ethereal, high-register crystalline chime", "role": "Trap/Drill atmosphere"},
        {"name": "Electric Bass Guitar", "timbre": "Warm, finger-picked low-mid growl", "role": "Groove bridge between acoustic and electric"}
    ]
}


def flatten_catalog() -> list[dict]:
    """All catalog entries as flat dicts with their category attached."""
    return [
        {"category": category, **entry}
        for category, entries in MASTER_INSTRUMENT_CATALOG.items()
        for entry in entries
    ]


def _normalize(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name or "").casefold().split())


_LOOKUP = {_normalize(entry["name"]): entry for entry in flatten_catalog()}


def describe_instrument(name: str) -> str:
    """Timbre/role-enriched description for prompts; falls back to the name."""
    entry = _LOOKUP.get(_normalize(name))
    if entry is None:
        return name
    return f"{entry['name']} ({entry['timbre']}; {entry['role']})"
