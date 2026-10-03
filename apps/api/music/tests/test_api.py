from unittest.mock import patch

from rest_framework.test import APITestCase

from music.models import Genre, Instrument, Song, User


class SongApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="singer", password="test-password")
        self.other_user = User.objects.create_user(username="listener", password="test-password")
        self.genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
        self.instrument = Instrument.objects.create(
            name="Acoustic Steel-String Guitar",
            slug="acoustic-steel-string-guitar",
            category=Instrument.Category.MODERN,
        )
        self.client.force_authenticate(self.user)

    def test_generate_creates_song_and_dispatches_task(self):
        payload = {
            "title": "Wendo Wakwa",
            "prompt": "Fast live Mũgithi dance song",
            "language": "gikuyu",
            "genre": "mugithi",
            "mood": "joyful",
            "instruments": [self.instrument.pk],
            "duration": 120,
        }
        with patch("music.views.generate_song_task.delay") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post("/api/generate/", payload, format="json")

        self.assertEqual(response.status_code, 202)
        song = Song.objects.get(pk=response.data["id"])
        self.assertEqual(song.user, self.user)
        self.assertEqual(song.status, Song.Status.PENDING)
        self.assertIn("[Mũgithi Tempo Switch]", song.generated_lyrics)
        self.assertEqual(list(song.chosen_instruments.all()), [self.instrument])
        dispatch.assert_called_once_with(song.pk)

    def test_generation_infers_genre_when_omitted(self):
        with patch("music.views.generate_song_task.delay"):
            response = self.client.post(
                "/api/generate/",
                {"title": "A dance", "prompt": "Mũgithi with acoustic guitar"},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["genre"]["slug"], "mugithi")

    def test_song_lists_and_details_are_scoped_to_authenticated_user(self):
        owned_song = Song.objects.create(
            user=self.user,
            title="Mine",
            user_prompt="A song",
            compiled_ai_prompt="Music",
            genre=self.genre,
        )
        Song.objects.create(
            user=self.other_user,
            title="Not mine",
            user_prompt="A song",
            compiled_ai_prompt="Music",
            genre=self.genre,
        )

        response = self.client.get("/api/songs/")
        detail = self.client.get(f"/api/songs/{owned_song.pk}/")
        hidden_detail = self.client.get(f"/api/songs/{owned_song.pk + 1}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(hidden_detail.status_code, 404)

    def test_queue_failure_returns_503_and_marks_song_failed(self):
        with patch("music.views.generate_song_task.delay", side_effect=ConnectionError):
            response = self.client.post(
                "/api/generate/",
                {"title": "Queued", "prompt": "Mũgithi", "genre": "mugithi"},
                format="json",
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Song.objects.get().status, Song.Status.FAILED)