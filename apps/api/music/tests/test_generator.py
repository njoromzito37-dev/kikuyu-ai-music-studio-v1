"""Tests for the G2P conditioning module and the song-generation provider seam."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from music.models import Genre, Song, User
from music.services import g2p, song_generator
from music.services.song_generator import HttpSongProvider, SongRenderError, YuESongProvider
from music.tasks import generate_song_task


class G2PTests(TestCase):
    def test_core_mappings(self):
        self.assertEqual(g2p.gikuyu_g2p("thayũ"), "ðaju")
        self.assertEqual(g2p.gikuyu_g2p("ng'ombe"), "ŋɔᵐbɛ")
        self.assertEqual(g2p.gikuyu_g2p("Mũgithi"), "muɣɪðɪ")
        self.assertEqual(g2p.gikuyu_g2p("Gĩkũyũ"), "ɣikuju")

    def test_preserves_punctuation_and_spacing(self):
        self.assertEqual(g2p.gikuyu_g2p("Wendo witũ, ngoro yakwa!"), "wɛⁿdɔ wɪtu, ᵑɡɔrɔ jakwa!")

    def test_normalizes_decomposed_unicode(self):
        decomposed = "mũgithi"  # u + combining tilde == ũ
        self.assertEqual(g2p.gikuyu_g2p(decomposed), g2p.gikuyu_g2p("mũgithi"))

    def test_phonemize_lyrics_keeps_section_tags(self):
        out = g2p.phonemize_lyrics("[Chorus]\nThayũ nĩ wega")
        lines = out.splitlines()
        self.assertEqual(lines[0], "[Chorus]")
        self.assertIn("ðaju", lines[1])

    def test_lyric_phonemes_language_gate(self):
        lyrics = "[Verse 1]\nThayũ"
        self.assertIn("ðaju", g2p.lyric_phonemes(lyrics, "gikuyu"))
        self.assertEqual(g2p.lyric_phonemes(lyrics, "english"), "")


def _stream_response(chunks, content_type="audio/wav", payload=None):
    response = MagicMock()
    response.headers = {"Content-Type": content_type}
    response.raise_for_status.return_value = None
    if payload is not None:
        response.json.return_value = payload
    response.iter_content = lambda chunk_size=1: iter(chunks)
    return response


class HttpSongProviderTests(TestCase):
    def test_streams_audio_to_file(self):
        provider = HttpSongProvider(endpoint="http://gen.test/render", max_bytes=1024)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                song_generator.requests, "post", return_value=_stream_response([b"RIFF", b"data"])
            ) as post:
                out = provider.render({"prompt": "x", "lyrics": "y", "phonemes": "z"}, Path(tmp), "song-7")
            self.assertEqual(out.read_bytes(), b"RIFFdata")
            self.assertEqual(out.suffix, ".wav")
            _, kwargs = post.call_args
            self.assertEqual(kwargs["json"]["phonemes"], "z")

    def test_json_audio_url_path(self):
        provider = HttpSongProvider(endpoint="http://gen.test/render")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                song_generator.requests, "post",
                return_value=_stream_response([], "application/json", payload={"audio_url": "http://cdn.test/a.mp3"}),
            ), patch.object(
                song_generator.requests, "get",
                return_value=_stream_response([b"mp3bytes"], "audio/mpeg"),
            ):
                out = provider.render({}, Path(tmp), "song-9")
            self.assertEqual(out.suffix, ".mp3")
            self.assertEqual(out.read_bytes(), b"mp3bytes")

    def test_size_cap_and_empty_stream(self):
        provider = HttpSongProvider(endpoint="http://gen.test/render", max_bytes=4)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(song_generator.requests, "post", return_value=_stream_response([b"123456"])):
                with self.assertRaises(SongRenderError):
                    provider.render({}, Path(tmp), "big")
        provider = HttpSongProvider(endpoint="http://gen.test/render")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(song_generator.requests, "post", return_value=_stream_response([])):
                with self.assertRaises(SongRenderError):
                    provider.render({}, Path(tmp), "empty")

    def test_missing_endpoint(self):
        with self.assertRaises(SongRenderError):
            HttpSongProvider(endpoint="").render({}, Path(tempfile.gettempdir()), "x")


class YuESongProviderTests(TestCase):
    def _provider(self, repo_dir):
        return YuESongProvider(
            repo_dir=str(repo_dir),
            stage1_model="m-a-p/YuE-s1-7B-anneal-en-cot",
            stage2_model="m-a-p/YuE-s2-1B-general",
        )

    def test_missing_repo_raises_setup_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = self._provider(Path(tmp) / "no-such-repo")
            with self.assertRaises(SongRenderError) as ctx:
                provider.render({}, Path(tmp), "song-1")
        self.assertIn("YUE_REPO_DIR", str(ctx.exception))

    def test_render_invokes_infer_and_returns_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "YuE"
            (repo / "src" / "yue").mkdir(parents=True)
            (repo / "src" / "yue" / "infer.py").write_text("# stub")
            out_dir = Path(tmp) / "out"

            def fake_run(cmd, **kwargs):
                target = Path(cmd[cmd.index("--output_dir") + 1])
                target.mkdir(parents=True, exist_ok=True)
                (target / "mix.wav").write_bytes(b"RIFF-yue")
                return MagicMock(returncode=0)

            with patch.object(song_generator.subprocess, "run", side_effect=fake_run) as run:
                provider = self._provider(repo)
                result = provider.render(
                    {"prompt": "mugithi style", "lyrics": "[Verse 1]\nThayũ", "phonemes": "ðaju"},
                    out_dir,
                    "song-3",
                )
            self.assertEqual(result.name, "mix.wav")
            cmd = run.call_args[0][0]
            self.assertIn("--genre_txt", cmd)
            self.assertIn("--lyrics_txt", cmd)
            self.assertIn("--stage1_model", cmd)
            # Genre/lyrics/phoneme scratch files were written for the renderer.
            self.assertTrue((out_dir / "song-3-genre.txt").exists())
            self.assertEqual((out_dir / "song-3-lyrics.txt").read_text(), "[Verse 1]\nThayũ")
            self.assertEqual((out_dir / "song-3-phonemes.txt").read_text(), "ðaju")

    def test_infer_failure_is_wrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "YuE"
            (repo / "src" / "yue").mkdir(parents=True)
            (repo / "src" / "yue" / "infer.py").write_text("# stub")
            with patch.object(
                song_generator.subprocess, "run",
                side_effect=subprocess.CalledProcessError(1, "cmd", stderr=b"cuda oom"),
            ):
                with self.assertRaises(SongRenderError) as ctx:
                    self._provider(repo).render({}, Path(tmp) / "out", "song-4")
            self.assertIn("YuE inference failed", str(ctx.exception))


class ProviderSelectionTests(TestCase):
    @override_settings(GENERATION_PROVIDER="http")
    def test_http_default(self):
        self.assertIsInstance(song_generator.get_provider(), HttpSongProvider)

    @override_settings(GENERATION_PROVIDER="yue", YUE_REPO_DIR="/tmp/yue", YUE_STAGE1_MODEL="s1", YUE_STAGE2_MODEL="s2")
    def test_yue_selection(self):
        provider = song_generator.get_provider()
        self.assertIsInstance(provider, YuESongProvider)
        self.assertEqual(provider.repo_dir, "/tmp/yue")

    @override_settings(GENERATION_PROVIDER="bogus")
    def test_unknown_provider(self):
        with self.assertRaises(ImproperlyConfigured):
            song_generator.get_provider()


class GenerateSongTaskProviderTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(
            MEDIA_ROOT=self.tmp.name,
            GENERATION_PROVIDER="http",
            GENERATION_BACKEND_URL="http://gen.test/render",
        )
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(username="composer", password="test-password")
        self.genre = Genre.objects.create(name="Mũgithi", slug="mugithi")

    def _song(self, language="gikuyu"):
        return Song.objects.create(
            user=self.user,
            title="Thayũ",
            user_prompt="p",
            compiled_ai_prompt="compiled",
            generated_lyrics="[Verse 1]\nThayũ nĩ wega",
            language=language,
            genre=self.genre,
        )

    def test_task_renders_via_provider_and_sends_phonemes(self):
        song = self._song()
        with patch.object(
            song_generator.requests, "post", return_value=_stream_response([b"RIFF", b"-audio"])
        ) as post:
            result = generate_song_task(song.pk)
        song.refresh_from_db()
        self.assertEqual(result["status"], Song.Status.COMPLETED)
        self.assertEqual(song.status, Song.Status.COMPLETED)
        self.assertTrue(song.audio_file.name.endswith(".wav"))
        self.assertEqual(Path(song.audio_file.path).read_bytes(), b"RIFF-audio")
        payload = post.call_args[1]["json"]
        self.assertEqual(payload["genre"], "mugithi")
        self.assertIn("ðaju", payload["phonemes"])

    def test_non_gikuyu_song_sends_empty_phonemes(self):
        song = self._song(language="english")
        with patch.object(song_generator.requests, "post", return_value=_stream_response([b"RIFF"])) as post:
            generate_song_task(song.pk)
        self.assertEqual(post.call_args[1]["json"]["phonemes"], "")

    def test_provider_failure_marks_song_failed(self):
        song = self._song()
        with patch.object(
            song_generator.requests, "post", side_effect=requests.ConnectionError("down")
        ), self.assertRaises(requests.ConnectionError):
            generate_song_task(song.pk)
        song.refresh_from_db()
        self.assertEqual(song.status, Song.Status.FAILED)
