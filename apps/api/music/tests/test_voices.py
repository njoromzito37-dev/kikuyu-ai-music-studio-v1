"""Tests for voice profiles (male/female/child/choir) and voice cloning."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from music.models import Genre, Song, User, VoiceCloneJob, VoiceProfile
from music.services import voice_clone
from music.services.voice_clone import RVCVoiceCloner, VoiceCloneError
from music.services.voices import VOICE_CATALOG, VOICE_TYPES, get_voice, voice_prompt_tags
from music.services.prompt_engine import KikuyuPromptEngine
from music.tasks import clone_vocals_task


class VoiceCatalogTests(TestCase):
    def test_catalog_integrity(self):
        slugs = [voice["slug"] for voice in VOICE_CATALOG]
        self.assertEqual(len(slugs), len(set(slugs)))
        for voice in VOICE_CATALOG:
            self.assertIn(voice["vocal_type"], VOICE_TYPES)
            self.assertTrue(voice["prompt_tags"].strip())
            self.assertTrue(voice["name"].strip())
        # The requested singer types must all exist.
        covered = {voice["vocal_type"] for voice in VOICE_CATALOG}
        for required in ("male_lead", "female_lead", "child", "children_choir", "male_choir", "female_choir", "mixed_choir"):
            self.assertIn(required, covered)

    def test_lookup_helpers(self):
        self.assertEqual(get_voice("MUGITHI-MALE-LEAD")["vocal_type"], "male_lead")
        self.assertIsNone(get_voice("nope"))
        self.assertIn("male lead vocalist", voice_prompt_tags("mugithi-male-lead"))
        self.assertEqual(voice_prompt_tags(None), "")


class PromptEngineVoiceTests(TestCase):
    def test_voice_tags_injected_into_compiled_prompt(self):
        composition = KikuyuPromptEngine().compose(
            text_prompt="Kĩrooko praise song",
            genre="gospel",
            voice_tags="harmonized male choir, deep basses",
        )
        self.assertIn("Vocals: harmonized male choir, deep basses.", composition["compiled_ai_prompt"])

    def test_no_voice_tags_no_vocals_line(self):
        composition = KikuyuPromptEngine().compose(text_prompt="Benga instrumental", genre="benga")
        self.assertNotIn("Vocals:", composition["compiled_ai_prompt"])


class VoiceApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="singer2", password="test-password")
        self.other = User.objects.create_user(username="stranger", password="test-password")
        self.genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
        self.voice = VoiceProfile.objects.create(
            name="Mũgithi Male Lead",
            slug="mugithi-male-lead",
            vocal_type=VoiceProfile.VocalType.MALE_LEAD,
            prompt_tags="powerful male lead vocalist, warm tenor range",
        )
        self.client.force_authenticate(self.user)

    def _completed_song(self, owner, title="Ready"):
        song = Song.objects.create(
            user=owner,
            title=title,
            user_prompt="p",
            compiled_ai_prompt="c",
            genre=self.genre,
            status=Song.Status.COMPLETED,
        )
        song.audio_file = f"generated/test/{song.pk}.wav"
        song.save(update_fields=["audio_file"])
        return song

    def test_voice_list(self):
        response = self.client.get("/api/voices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["slug"], "mugithi-male-lead")

    def test_generate_with_voice_sets_profile_and_prompt_tags(self):
        with patch("music.views.generate_song_task.delay"):
            response = self.client.post(
                "/api/generate/",
                {"title": "Kĩrĩra", "prompt": "Mũgithi praise jam", "genre": "mugithi", "voice": "mugithi-male-lead"},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        song = Song.objects.get(pk=response.data["id"])
        self.assertEqual(song.voice, self.voice)
        self.assertIn("Vocals: powerful male lead vocalist", song.compiled_ai_prompt)
        self.assertEqual(response.data["voice"]["slug"], "mugithi-male-lead")

    def test_generate_with_unknown_voice_rejected(self):
        response = self.client.post(
            "/api/generate/",
            {"title": "X", "prompt": "Mũgithi jam", "genre": "mugithi", "voice": "ghost-voice"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clone_job_creation_and_dispatch(self):
        song = self._completed_song(self.user)
        with patch("music.views.clone_vocals_task.delay") as dispatch:
            response = self.client.post(
                "/api/voices/clone/", {"source_song": song.pk, "voice": self.voice.pk}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = VoiceCloneJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.status, VoiceCloneJob.Status.PENDING)
        dispatch.assert_called_once_with(job.pk)

    def test_clone_job_validates_ownership_and_readiness(self):
        foreign = self._completed_song(self.other, "Foreign")
        response = self.client.post(
            "/api/voices/clone/", {"source_song": foreign.pk, "voice": self.voice.pk}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        pending = Song.objects.create(
            user=self.user, title="Pending", user_prompt="p", compiled_ai_prompt="c", genre=self.genre
        )
        response = self.client.post(
            "/api/voices/clone/", {"source_song": pending.pk, "voice": self.voice.pk}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clone_list_scoped_to_owner(self):
        song = self._completed_song(self.user)
        job = VoiceCloneJob.objects.create(user=self.user, source_song=song, voice=self.voice)
        other_song = self._completed_song(self.other, "Other")
        other_job = VoiceCloneJob.objects.create(user=self.other, source_song=other_song, voice=self.voice)
        response = self.client.get("/api/voices/clone/")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get(f"/api/voices/clone/{job.pk}/").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(f"/api/voices/clone/{other_job.pk}/").status_code, status.HTTP_404_NOT_FOUND)


class VoiceClonerTests(TestCase):
    @override_settings(VOICE_CLONER="off")
    def test_disabled_by_default(self):
        with self.assertRaises(VoiceCloneError):
            voice_clone.get_voice_cloner()

    @override_settings(VOICE_CLONER="bogus")
    def test_unknown_cloner(self):
        with self.assertRaises(ImproperlyConfigured):
            voice_clone.get_voice_cloner()

    def test_missing_repo_and_model_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            cloner = RVCVoiceCloner(repo_dir=str(Path(tmp) / "no-repo"), model_dir=tmp)
            with self.assertRaises(VoiceCloneError) as ctx:
                cloner.convert(Path("in.wav"), "female-lead", Path(tmp))
            self.assertIn("RVC_REPO_DIR", str(ctx.exception))

            repo = Path(tmp) / "rvc"
            (repo / "tools").mkdir(parents=True)
            (repo / "tools" / "infer_cli.py").write_text("# stub")
            cloner = RVCVoiceCloner(repo_dir=str(repo), model_dir=tmp)
            with self.assertRaises(VoiceCloneError) as ctx:
                cloner.convert(Path("in.wav"), "female-lead", Path(tmp))
            self.assertIn("No trained RVC model", str(ctx.exception))

    def test_convert_invokes_rvc_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "rvc"
            (repo / "tools").mkdir(parents=True)
            (repo / "tools" / "infer_cli.py").write_text("# stub")
            model_dir = Path(tmp) / "models"
            model_dir.mkdir()
            (model_dir / "female-lead.pth").write_bytes(b"model")
            (model_dir / "female-lead.index").write_bytes(b"index")

            def fake_run(cmd, **kwargs):
                Path(cmd[cmd.index("--opt_path") + 1]).write_bytes(b"RIFF-cloned")
                return MagicMock(returncode=0)

            with patch.object(voice_clone.subprocess, "run", side_effect=fake_run) as run:
                cloner = RVCVoiceCloner(repo_dir=str(repo), model_dir=str(model_dir))
                out = cloner.convert(Path(tmp) / "in.wav", "female-lead", Path(tmp) / "out", "clone-1")
            self.assertEqual(out.read_bytes(), b"RIFF-cloned")
            cmd = run.call_args[0][0]
            self.assertIn("--model_name", cmd)
            self.assertIn("--index_path", cmd)
            self.assertTrue(any("female-lead.pth" in str(part) for part in cmd))

    def test_cli_failure_wrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "rvc"
            (repo / "tools").mkdir(parents=True)
            (repo / "tools" / "infer_cli.py").write_text("# stub")
            (Path(tmp) / "child-solo.pth").write_bytes(b"model")
            with patch.object(
                voice_clone.subprocess, "run",
                side_effect=subprocess.CalledProcessError(1, "cmd", stderr=b"shape mismatch"),
            ):
                cloner = RVCVoiceCloner(repo_dir=str(repo), model_dir=tmp)
                with self.assertRaises(VoiceCloneError) as ctx:
                    cloner.convert(Path("in.wav"), "child-solo", Path(tmp) / "out")
            self.assertIn("RVC conversion failed", str(ctx.exception))


class CloneVocalsTaskTests(TestCase):
    def test_task_completes_with_fake_cloner(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            user = User.objects.create_user(username="cloner", password="test-password")
            genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
            song = Song.objects.create(
                user=user, title="Src", user_prompt="p", compiled_ai_prompt="c",
                genre=genre, status=Song.Status.COMPLETED,
            )
            song.audio_file.save("src.wav", ContentFile(b"RIFF-source"))
            voice = VoiceProfile.objects.create(
                name="Female Lead", slug="female-lead",
                vocal_type=VoiceProfile.VocalType.FEMALE_LEAD, prompt_tags="female lead",
            )
            job = VoiceCloneJob.objects.create(user=user, source_song=song, voice=voice)

            class FakeCloner:
                def convert(self, source_audio, voice_slug, out_dir, filename_hint="clone"):
                    assert Path(source_audio).read_bytes() == b"RIFF-source"
                    assert voice_slug == "female-lead"
                    out = Path(out_dir) / f"{filename_hint}.wav"
                    out.write_bytes(b"RIFF-cloned")
                    return out

            with patch("music.tasks.voice_clone.get_voice_cloner", return_value=FakeCloner()):
                result = clone_vocals_task(job.pk)

            job.refresh_from_db()
            self.assertEqual(result["status"], VoiceCloneJob.Status.COMPLETED)
            self.assertEqual(job.status, VoiceCloneJob.Status.COMPLETED)
            self.assertTrue(job.output_file.name.endswith(".wav"))
            self.assertEqual(Path(job.output_file.path).read_bytes(), b"RIFF-cloned")

    def test_task_marks_failed_when_cloner_unavailable(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            user = User.objects.create_user(username="cloner2", password="test-password")
            genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
            song = Song.objects.create(
                user=user, title="Src2", user_prompt="p", compiled_ai_prompt="c",
                genre=genre, status=Song.Status.COMPLETED,
            )
            song.audio_file.save("src2.wav", ContentFile(b"RIFF"))
            voice = VoiceProfile.objects.create(
                name="Male Choir", slug="male-choir",
                vocal_type=VoiceProfile.VocalType.MALE_CHOIR, prompt_tags="male choir",
            )
            job = VoiceCloneJob.objects.create(user=user, source_song=song, voice=voice)
            with patch("music.tasks.voice_clone.get_voice_cloner", side_effect=VoiceCloneError("disabled")), self.assertRaises(VoiceCloneError):
                clone_vocals_task(job.pk)
            job.refresh_from_db()
            self.assertEqual(job.status, VoiceCloneJob.Status.FAILED)
