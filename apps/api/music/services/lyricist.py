"""Thematic lyric intelligence backed by external LLMs (DeepSeek, Gemini).

Given a short user prompt, this service writes complete, thematically coherent
song lyrics — real storytelling with an emotional arc instead of the static
templates — while preserving Gĩkũyũ orthography and section structure tags.

Design notes:
  * Backend-agnostic: configuration comes from environment variables so both
    the Django app and the FastAPI engine can share it. `python-dotenv` loads
    the repo-level .env when present.
  * Provider chain: DeepSeek first, then Gemini ("auto"), or pin one with
    LLM_PROVIDER=deepseek|gemini, or disable with LLM_PROVIDER=off.
  * Any provider failure (missing key, network, bad payload) falls through to
    the next provider and finally returns None so callers can use templates.

Environment:
    DEEPSEEK_API_KEY   — https://platform.deepseek.com API key
    GEMINI_API_KEY     — Google AI Studio API key
    LLM_PROVIDER       — auto | deepseek | gemini | off   (default: auto)
    DEEPSEEK_MODEL     — default: deepseek-chat
    GEMINI_MODEL       — default: gemini-2.0-flash
    LLM_TIMEOUT        — request seconds, default: 30
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import requests

try:  # Load the repo-level .env when running outside the Django process.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

logger = logging.getLogger(__name__)

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = """You are "Mũinĩki wa Ngoma" — an award-winning Kenyan songwriter fluent in Gĩkũyũ, Kiswahili, and English, with deep command of Central Kenyan traditions (Mũgithi, Kikuyu Benga, Mwomboko, Kĩrooko gospel, Njanama chants) and modern East African pop (Afro-pop, Gengetone, Amapiano).

Songwriting rules:
1. THEME FIRST: build the whole song around the given theme — concrete imagery, a small story or emotional arc, and a memorable hook. Avoid generic filler lines.
2. LANGUAGE: write entirely in the requested language. For Gĩkũyũ, use correct orthography with diacritics (ĩ, ũ) exactly as printed, natural idioms, and proverbs (thimo) where they fit. Keep lines singable (roughly 6–14 syllables) with musical repetition.
3. STRUCTURE: use these exact section tags, each on its own line: [Verse 1], [Chorus], [Verse 2], [Chorus], [Bridge] or [Interlude - Guitar Solo], [Outro].
4. GROOVE: match the described genre and mood — call-and-response phrasing for Mũgithi, praise refrains for Kĩrooko gospel, lilting triplet feel for Mwomboko.
5. OUTPUT: only the lyrics with section tags. No commentary, no translation, no markdown code fences."""

_USER_TEMPLATE = """Theme / creative direction: {theme}
Language: {language}
Genre style: {genre_style}
Mood: {mood}
Instrumentation: {instruments}

Write the complete lyrics now."""


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails or returns unusable content."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def sanitize_lyrics(text: str) -> str:
    """Normalize raw LLM output into clean, section-tagged lyrics."""
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Drop any chatter before the first section tag.
    match = re.search(r"^\[(Verse|Chorus|Bridge|Interlude|Outro|Intro)", text, re.MULTILINE | re.IGNORECASE)
    if match and match.start() > 0:
        text = text[match.start() :]
    return text


class ThematicLyricist:
    """Generate thematic song lyrics from a prompt via DeepSeek / Gemini."""

    def __init__(
        self,
        provider: str | None = None,
        deepseek_api_key: str | None = None,
        gemini_api_key: str | None = None,
        timeout: int | None = None,
    ):
        self.provider = (provider if provider is not None else _env("LLM_PROVIDER", "auto")).lower()
        self.deepseek_api_key = deepseek_api_key if deepseek_api_key is not None else _env("DEEPSEEK_API_KEY")
        self.gemini_api_key = gemini_api_key if gemini_api_key is not None else _env("GEMINI_API_KEY")
        self.deepseek_model = _env("DEEPSEEK_MODEL", "deepseek-chat")
        self.gemini_model = _env("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout = timeout if timeout is not None else int(_env("LLM_TIMEOUT", "30") or "30")

    # ------------------------------------------------------------ providers

    def _provider_order(self) -> list[str]:
        if self.provider == "off":
            return []
        if self.provider in ("deepseek", "gemini"):
            return [self.provider]
        return ["deepseek", "gemini"]  # auto

    def _call_deepseek(self, system: str, user: str) -> str:
        if not self.deepseek_api_key:
            raise LLMError("DEEPSEEK_API_KEY is not configured.")
        response = requests.post(
            DEEPSEEK_ENDPOINT,
            headers={"Authorization": f"Bearer {self.deepseek_api_key}", "Content-Type": "application/json"},
            json={
                "model": self.deepseek_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.9,
                "max_tokens": 1400,
                "stream": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("DeepSeek returned an unexpected payload shape.") from exc

    def _call_gemini(self, system: str, user: str) -> str:
        if not self.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not configured.")
        response = requests.post(
            GEMINI_ENDPOINT.format(model=self.gemini_model),
            params={"key": self.gemini_api_key},
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1400},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Gemini returned an unexpected payload shape.") from exc

    # ------------------------------------------------------------- generate

    def generate(
        self,
        theme: str,
        language: str = "gikuyu",
        genre_style: str = "",
        mood: str = "joyful",
        instruments: list[str] | None = None,
    ) -> tuple[str, str] | None:
        """Return ``(lyrics, provider_name)`` or None when no LLM is usable.

        Callers should treat None as "fall back to template lyrics".
        """
        theme = (theme or "").strip()
        if not theme:
            return None
        user = _USER_TEMPLATE.format(
            theme=theme,
            language=language,
            genre_style=genre_style or "East African contemporary music with authentic Kikuyu character",
            mood=mood or "joyful",
            instruments=", ".join(instruments or []) or "acoustic guitar, bass",
        )
        for provider in self._provider_order():
            try:
                if provider == "deepseek":
                    raw = self._call_deepseek(SYSTEM_PROMPT, user)
                else:
                    raw = self._call_gemini(SYSTEM_PROMPT, user)
                lyrics = sanitize_lyrics(raw)
                if lyrics and re.search(r"^\[(Verse|Chorus)", lyrics, re.MULTILINE | re.IGNORECASE):
                    return lyrics, provider
                logger.warning("%s returned unusable lyrics; trying next provider", provider)
            except (LLMError, requests.RequestException, ValueError) as exc:
                logger.warning("LLM provider %s failed: %s", provider, exc)
        return None

    def available(self) -> bool:
        """True when at least one provider in the chain has credentials."""
        return any(
            (name == "deepseek" and self.deepseek_api_key) or (name == "gemini" and self.gemini_api_key)
            for name in self._provider_order()
        )
