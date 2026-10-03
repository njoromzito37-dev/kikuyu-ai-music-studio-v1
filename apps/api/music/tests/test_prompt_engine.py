from django.test import SimpleTestCase

from music.services.prompt_engine import KikuyuPromptEngine


class KikuyuPromptEngineTests(SimpleTestCase):
    def setUp(self):
        self.engine = KikuyuPromptEngine()

    def test_infers_supported_styles_from_prompt(self):
        prompts = {
            "Mũgithi live guitar dance": "mugithi",
            "Benga with interlocking guitars": "benga",
            "Kĩrooko praise and worship": "gospel",
            "Mwomboko accordion in 6/8": "mwomboko",
            "Amapiano with Gĩkũyũ lyrics": "afro-pop",
            "Njanama acoustic folk": "acoustic-folk",
            "Traditional chants for a ceremony": "traditional-chants",
        }
        for prompt, expected in prompts.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(self.engine.infer_genre_slug(prompt), expected)

    def test_composition_preserves_gikuyu_diacritics_and_mugithi_markers(self):
        result = self.engine.compose(
            "Mũgithi love song for ũhoro wa wendo",
            "mugithi",
            instruments=["Acoustic Steel-String Guitar"],
        )
        self.assertIn("Mũgithi", result["compiled_ai_prompt"])
        self.assertIn("ĩ, ũ, ã, ẽ, õ", result["compiled_ai_prompt"])
        self.assertIn("[Mũgithi Tempo Switch]", result["generated_lyrics"])
        self.assertIn("[Interlude - Guitar Solo]", result["generated_lyrics"])

    def test_prompt_is_limited_to_512_whitespace_tokens(self):
        result = self.engine.compose("word " * 1000, "mugithi")
        self.assertLessEqual(len(result["compiled_ai_prompt"].split()), 512)

    def test_unstructured_user_lyrics_are_given_sections(self):
        result = self.engine.compose("Mugithi dance", "mugithi", lyrics="Line one\nLine two")
        self.assertTrue(result["generated_lyrics"].startswith("[Verse 1]"))
        self.assertIn("[Chorus]", result["generated_lyrics"])
        self.assertIn("[Outro]", result["generated_lyrics"])