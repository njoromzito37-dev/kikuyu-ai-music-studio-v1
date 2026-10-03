import tempfile
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from music.models import Genre, Song, User
from music.tasks import generate_song_task


class GenerateSongTaskTests(TestCase):
    def test_provider_audio_is_saved_with_waveform_and_completed_status(self):
        user = User.objects.create_user(username="producer", password="test-password")
        genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
        song = Song.objects.create(
            user=user,
            title="Dance Song",
            user_prompt="A live dance song",
            compiled_ai_prompt="Acoustic Mũgithi with fast dance rhythm",
            generated_lyrics="[Verse 1]\nTũinage hamwe",
            genre=genre,
        )
        provider_response = Mock()
        provider_response.headers = {"Content-Type": "audio/wav"}
        provider_response.iter_content.return_value = [b"test-audio-bytes"]

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, GENERATION_BACKEND_URL="https://provider.test/generate"):
                with patch("music.tasks.requests.post", return_value=provider_response) as request:
                    with patch("music.tasks._waveform", return_value=[0.1, 0.8]):
                        result = generate_song_task.apply(args=[song.pk], throw=True).get()

        song.refresh_from_db()
        request.assert_called_once()
        self.assertEqual(result["status"], Song.Status.COMPLETED)
        self.assertEqual(song.status, Song.Status.COMPLETED)
        self.assertEqual(song.audio_waveform_data, [0.1, 0.8])
        self.assertTrue(song.audio_file.name.endswith(".wav"))