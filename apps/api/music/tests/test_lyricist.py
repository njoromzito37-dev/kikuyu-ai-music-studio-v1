"""Tests for the LLM thematic lyricist (DeepSeek / Gemini) integration."""

from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase
from rest_framework.test import APITestCase

from music.models import Genre, Song, User
from music.services.lyricist import ThematicLyricist, sanitize_lyrics
from music.services.prompt_engine import KikuyuPromptEngine

LLM_LYRICS = (
    "[Verse 1]\nGũkũya kwa rũciũ, njuĩra ĩrĩa njũrũ\nWendo wa mũciĩ, ũrĩa ũtũmĩte hamwe\n\n"
    "[Chorus]\nTũinage hamwe, tũinage hamwe\nNgai nĩ mũmbi wa maundu mothe\n\n"
    "[Verse 2]\nRũrĩmĩ rwakwa, rwĩtaga wega wa Ngai\n\n[Outro]\nTũinage hamwe"
)


def _response(payload):
    fake = MagicMock()
    fake.raise_for_status.return_value = None
    fake.json.return_value = payload
    return fake


def _lyricist(**overrides):
    """Hermetic lyricist: no ambient env keys unless explicitly passed."""
    base = {"deepseek_api_key": "", "gemini_api_key": "", "timeout": 5}
    base.update(overrides)
    return ThematicLyricist(**base)


class SanitizeTests(TestCase):
    def test_strips_markdown_fences_and_chatter(self):
        raw = "Sure! Here are your lyrics:\n```text\n[Verse 1]\nMbete cia rũciũ\n\n\n\n[Chorus]\nTwĩ hamwe\n```"
        cleaned = sanitize_lyrics(raw)
        self.assertTrue(cleaned.startswith("[Verse 1]"))
        self.assertTrue(cleaned.endswith("Twĩ hamwe"))
        self.assertNotIn("```", cleaned)
        self.assertNotIn("\n\n\n", cleaned)

    def test_empty_input(self):
        self.assertEqual(sanitize_lyrics(""), "")


class ThematicLyricistTests(TestCase):
    def test_no_keys_returns_none(self):
        self.assertIsNone(_lyricist().generate(theme="Wendo wa mũciĩ"))
        self.assertFalse(_lyricist().available())

    def test_provider_off_short_circuits(self):
        lyricist = _lyricist(provider="off", deepseek_api_key="x")
        self.assertIsNone(lyricist.generate(theme="test theme"))
        self.assertFalse(lyricist.available())

    def test_blank_theme_returns_none(self):
        self.assertIsNone(_lyricist(deepseek_api_key="x").generate(theme="   "))

    def test_deepseek_success(self):
        payload = {"choices": [{"message": {"content": LLM_LYRICS}}]}
        with patch("music.services.lyricist.requests.post", return_value=_response(payload)) as post:
            result = _lyricist(deepseek_api_key="ds-key").generate(theme="Gũcookia kwao", language="gikuyu")
        self.assertIsNotNone(result)
        lyrics, provider = result
        self.assertEqual(provider, "deepseek")
        self.assertIn("[Chorus]", lyrics)
        args, kwargs = post.call_args
        self.assertIn("api.deepseek.com", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ds-key")
        self.assertEqual(kwargs["json"]["messages"][0]["role"], "system")

    def test_gemini_fallback_after_deepseek_failure(self):
        gemini_payload = {"candidates": [{"content": {"parts": [{"text": LLM_LYRICS}]}}]}

        def router(url, **kwargs):
            if "deepseek" in url:
                raise requests.ConnectionError("deepseek unreachable")
            return _response(gemini_payload)

        with patch("music.services.lyricist.requests.post", side_effect=router):
            result = _lyricist(deepseek_api_key="ds-key", gemini_api_key="gm-key").generate(theme="Thayũ")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "gemini")

    def test_all_providers_failing_returns_none(self):
        with patch(
            "music.services.lyricist.requests.post",
            side_effect=requests.Timeout("slow"),
        ):
            result = _lyricist(deepseek_api_key="a", gemini_api_key="b").generate(theme="Kĩroko")
        self.assertIsNone(result)

    def test_unstructured_llm_output_is_rejected(self):
        payload = {"choices": [{"message": {"content": "just some prose without tags"}}]}
        with patch("music.services.lyricist.requests.post", return_value=_response(payload)):
            self.assertIsNone(_lyricist(deepseek_api_key="x").generate(theme="test theme"))

    def test_pinned_provider_skips_others(self):
        payload = {"candidates": [{"content": {"parts": [{"text": LLM_LYRICS}]}}]}
        with patch("music.services.lyricist.requests.post", return_value=_response(payload)) as post:
            result = _lyricist(provider="gemini", gemini_api_key="gm-key").generate(theme="Ngai nĩ wega")
        self.assertEqual(result[1], "gemini")
        self.assertIn("generativelanguage.googleapis.com", post.call_args[0][0])
        self.assertEqual(post.call_args[1]["params"]["key"], "gm-key")


class PromptEngineLyricistTests(TestCase):
    def test_compose_falls_back_to_template_without_providers(self):
        with patch("music.services.prompt_engine.ThematicLyricist") as lyricist_cls:
            lyricist_cls.return_value.generate.return_value = None
            composition = KikuyuPromptEngine().compose(
                text_prompt="Mũgithi dance song", genre="mugithi", language="gikuyu",
            )
        self.assertEqual(composition["lyrics_engine"], "template")
        self.assertIn("[Mũgithi Tempo Switch]", composition["generated_lyrics"])

    def test_compose_uses_llm_lyrics_when_available(self):
        with patch("music.services.prompt_engine.ThematicLyricist") as lyricist_cls:
            lyricist_cls.return_value.generate.return_value = (LLM_LYRICS, "deepseek")
            composition = KikuyuPromptEngine().compose(
                text_prompt="Ngoma ya gũcookia kwao", genre="mugithi", language="gikuyu",
            )
        self.assertEqual(composition["lyrics_engine"], "deepseek")
        self.assertIn("Ngai nĩ mũmbi", composition["generated_lyrics"])
        # structure_lyrics still injects the Mũgithi tempo switch for the genre
        self.assertIn("[Mũgithi Tempo Switch]", composition["generated_lyrics"])

    def test_user_supplied_lyrics_take_precedence(self):
        with patch("music.services.prompt_engine.ThematicLyricist") as lyricist_cls:
            composition = KikuyuPromptEngine().compose(
                text_prompt="anything",
                genre="benga",
                language="gikuyu",
                lyrics="[Verse 1]\nRũĩmbo rwakwa",
            )
        lyricist_cls.return_value.generate.assert_not_called()
        self.assertEqual(composition["lyrics_engine"], "user")


class GenerateApiLyricsEngineTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mũinĩki", password="test-password")
        self.genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
        self.client.force_authenticate(self.user)

    def test_generate_records_lyrics_engine(self):
        with patch("music.views.generate_song_task.delay"), patch(
            "music.services.prompt_engine.ThematicLyricist"
        ) as lyricist_cls:
            lyricist_cls.return_value.generate.return_value = (LLM_LYRICS, "gemini")
            response = self.client.post(
                "/api/generate/",
                {"title": "Gũcookia Kwao", "prompt": "Mũgithi homecoming song", "genre": "mugithi"},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        song = Song.objects.get(pk=response.data["id"])
        self.assertEqual(song.lyrics_engine, "gemini")
        self.assertEqual(response.data["lyrics_engine"], "gemini")

    def test_generate_without_providers_uses_template_engine(self):
        with patch("music.views.generate_song_task.delay"), patch(
            "music.services.prompt_engine.ThematicLyricist"
        ) as lyricist_cls:
            lyricist_cls.return_value.generate.return_value = None
            response = self.client.post(
                "/api/generate/",
                {"title": "Template", "prompt": "Mũgithi song", "genre": "mugithi"},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["lyrics_engine"], "template")
