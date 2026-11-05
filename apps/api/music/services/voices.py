"""Voice catalog for vocal-type selection and voice cloning.

Canonical, backend-agnostic list of vocal profiles (male / female / child /
choirs / duet) shared by the Django API (seeding + serializers) and the
FastAPI engine (/voices endpoint + generation payloads). Each profile carries
``prompt_tags`` — the vocal description injected into style prompts so the
generator renders the requested singer — and acts as the anchor for a trained
voice-clone model (RVC ``<slug>.pth``) when one exists.
"""

from __future__ import annotations

VOICE_TYPES = (
    "male_lead",
    "female_lead",
    "child",
    "children_choir",
    "male_choir",
    "female_choir",
    "mixed_choir",
    "duet",
)

VOICE_CATALOG: list[dict] = [
    {
        "slug": "mugithi-male-lead",
        "name": "Mũgithi Male Lead",
        "vocal_type": "male_lead",
        "description": "Classic Mũgithi frontman — warm tenor, rhythmic delivery, crowd ad-libs.",
        "prompt_tags": "powerful male lead vocalist, warm tenor range, energetic Mũgithi delivery, call-and-response ad-libs",
    },
    {
        "slug": "female-lead",
        "name": "Female Lead (Mũirĩtu)",
        "vocal_type": "female_lead",
        "description": "Expressive female lead with bright alto tone and emotive vibrato.",
        "prompt_tags": "expressive female lead vocalist, bright alto, emotive vibrato, warm midrange presence",
    },
    {
        "slug": "smooth-tenor",
        "name": "Smooth Tenor",
        "vocal_type": "male_lead",
        "description": "Romantic, laid-back male tenor with gentle falsetto runs.",
        "prompt_tags": "smooth romantic male tenor, gentle falsetto runs, intimate close-miked delivery",
    },
    {
        "slug": "child-solo",
        "name": "Child Soloist (Mwana)",
        "vocal_type": "child",
        "description": "Clear child solo voice — bright, innocent, simple melodic phrasing.",
        "prompt_tags": "clear child solo voice, innocent bright timbre, simple melodic phrasing",
    },
    {
        "slug": "children-choir",
        "name": "Children's Choir (Kwaya ya Ciana)",
        "vocal_type": "children_choir",
        "description": "Unison children's choir, playful and bright, simple harmonies.",
        "prompt_tags": "unison children's choir, playful bright tone, simple two-part harmonies",
    },
    {
        "slug": "male-choir",
        "name": "Male Choir (Kwaya ya Arũme)",
        "vocal_type": "male_choir",
        "description": "Harmonized male choir — deep basses and tenors in call-and-response.",
        "prompt_tags": "harmonized male choir, deep basses and rich tenors, powerful call-and-response",
    },
    {
        "slug": "female-choir",
        "name": "Female Choir (Kwaya ya Airĩtu)",
        "vocal_type": "female_choir",
        "description": "Harmonized female choir — soaring sopranos over warm altos.",
        "prompt_tags": "harmonized female choir, soaring sopranos, warm altos, uplifting blend",
    },
    {
        "slug": "mixed-choir",
        "name": "Mixed Choir (Kwaya)",
        "vocal_type": "mixed_choir",
        "description": "Full SATB mixed choir with rich four-part harmony.",
        "prompt_tags": "full SATB mixed choir, rich four-part harmony, majestic dynamics",
    },
    {
        "slug": "praise-leader",
        "name": "Praise Leader & Choir",
        "vocal_type": "mixed_choir",
        "description": "Gospel praise leader trading lines with an answering choir (Kĩrooko style).",
        "prompt_tags": "gospel praise leader with full choir responses, Pentecostal energy, spirit-filled ad-libs",
    },
    {
        "slug": "duet",
        "name": "Male–Female Duet",
        "vocal_type": "duet",
        "description": "Male and female leads trading verses with intertwined harmonies.",
        "prompt_tags": "male and female lead duet, intertwined harmonies, conversational call-and-answer phrasing",
    },
]

_BY_SLUG = {voice["slug"]: voice for voice in VOICE_CATALOG}


def get_voice(slug: str | None) -> dict | None:
    if not slug:
        return None
    return _BY_SLUG.get(str(slug).strip().lower())


def voice_prompt_tags(slug: str | None) -> str:
    voice = get_voice(slug)
    return voice["prompt_tags"] if voice else ""


def voice_options() -> list[dict]:
    """Public listing shape (used by the FastAPI /voices endpoint)."""
    return [
        {
            "slug": voice["slug"],
            "name": voice["name"],
            "vocal_type": voice["vocal_type"],
            "description": voice["description"],
        }
        for voice in VOICE_CATALOG
    ]
