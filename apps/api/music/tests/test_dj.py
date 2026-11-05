"""Tests for the DJ / live-mixing features (dj_tools DSP + API endpoints)."""

import numpy as np
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from music.models import DjMixJob, DjRenderJob, Genre, Song, Stem, User
from music.services import dj_tools

SR = 22050


def _tone(freq, seconds=2.0, sr=SR, amp=0.5):
    t = np.arange(int(sr * seconds)) / sr
    signal = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.vstack([signal, signal])


def _click_track(bpm, seconds=8.0, sr=SR):
    n = int(sr * seconds)
    signal = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    t = 0.0
    while t < seconds - 0.05:
        start = int(t * sr)
        length = min(int(0.03 * sr), n - start)
        signal[start : start + length] += 0.9 * np.hanning(length)
        t += beat
    return np.vstack([signal, signal])


class DspToolsTests(TestCase):
    def test_db_to_gain(self):
        self.assertAlmostEqual(dj_tools.db_to_gain(0.0), 1.0)
        self.assertAlmostEqual(dj_tools.db_to_gain(6.0), 1.995, places=2)
        self.assertAlmostEqual(dj_tools.db_to_gain(-60.0), 0.001, places=3)

    def test_butterworth_response_shapes(self):
        freqs = np.fft.rfftfreq(4096, d=1.0 / SR)
        low = dj_tools.butterworth_response(freqs, 200.0, order=4, kind="lowpass")
        high = dj_tools.butterworth_response(freqs, 2000.0, order=4, kind="highpass")
        self.assertGreater(low[10], 0.99)  # deep in the passband
        self.assertLess(low[-1], 0.01)  # deep in the stopband
        self.assertLess(high[1], 0.01)
        self.assertGreater(high[-1], 0.99)

    def test_three_band_eq_reconstructs_and_boosts(self):
        signal = _tone(120.0, seconds=1.0, amp=0.08) + _tone(3000.0, seconds=1.0, amp=0.03)
        flat = dj_tools.three_band_eq(signal, SR, 0.0, 0.0, 0.0)
        np.testing.assert_allclose(flat, signal, atol=2e-2)
        boosted = dj_tools.three_band_eq(signal, SR, low_db=12.0, mid_db=0.0, high_db=-60.0)
        low_in = dj_tools.butter_filter(signal, SR, 250.0, kind="lowpass")
        low_out = dj_tools.butter_filter(boosted, SR, 250.0, kind="lowpass")
        self.assertGreater(np.abs(low_out).mean(), np.abs(low_in).mean() * 2.5)

    def test_time_stretch_changes_length_not_shape(self):
        signal = _tone(440.0, seconds=1.0)
        faster = dj_tools.time_stretch(signal, 1.5)
        slower = dj_tools.time_stretch(signal, 0.75)
        self.assertEqual(faster.shape[0], 2)
        self.assertAlmostEqual(faster.shape[1] / signal.shape[1], 1 / 1.5, delta=0.05)
        self.assertAlmostEqual(slower.shape[1] / signal.shape[1], 1 / 0.75, delta=0.05)

    def test_pitch_shift_preserves_duration(self):
        signal = _tone(220.0, seconds=1.0)
        shifted = dj_tools.pitch_shift(signal, SR, 3.0)
        self.assertEqual(shifted.shape[0], 2)
        self.assertAlmostEqual(shifted.shape[1] / signal.shape[1], 1.0, delta=0.05)

    def test_echo_adds_delayed_energy(self):
        impulse = np.zeros((2, SR // 2), dtype=np.float32)
        impulse[:, 0] = 0.9
        echoed = dj_tools.apply_echo(impulse, SR, delay_ms=100.0, feedback=0.8, mix=0.9)
        delay = int(SR * 0.1)
        self.assertGreater(np.abs(echoed[:, delay : delay + 64]).max(), 0.2)

    def test_reverb_extends_tail(self):
        impulse = np.zeros((2, SR), dtype=np.float32)
        impulse[:, 0] = 0.8
        wet = dj_tools.apply_reverb(impulse, SR, room_size=0.8, wet=0.6)
        self.assertGreater(np.abs(wet[:, SR // 2 :]).max(), 0.01)

    def test_flanger_and_sweep_preserve_shape(self):
        signal = _tone(500.0, seconds=0.5)
        flanged = dj_tools.apply_flanger(signal, SR)
        swept = dj_tools.filter_sweep(signal, SR, mode="lowpass", start_cutoff=18000.0, end_cutoff=300.0)
        self.assertEqual(flanged.shape, signal.shape)
        self.assertEqual(swept.shape, signal.shape)
        self.assertTrue(np.all(np.isfinite(swept)))

    def test_estimate_bpm_on_click_track(self):
        bpm = dj_tools.estimate_bpm(_click_track(120.0), SR)
        self.assertIsNotNone(bpm)
        self.assertAlmostEqual(bpm, 120.0, delta=3.0)

    def test_estimate_key_on_major_triad(self):
        chord = _tone(261.63, seconds=3.0) + _tone(329.63, seconds=3.0) + _tone(392.0, seconds=3.0)
        key = dj_tools.estimate_key(chord, SR)
        self.assertIsNotNone(key)
        self.assertEqual(key["root"], "C")
        self.assertEqual(key["mode"], "major")
        self.assertTrue(key["camelot"].endswith("B"))

    def test_key_semitone_offset_wraps(self):
        c_major = {"root": "C", "mode": "major"}
        a_minor = {"root": "A", "mode": "minor"}
        self.assertEqual(dj_tools.key_semitone_offset(c_major, c_major), 0)
        self.assertEqual(dj_tools.key_semitone_offset(c_major, a_minor), -3)
        self.assertEqual(dj_tools.key_semitone_offset(a_minor, c_major), 3)

    def test_auto_cue_points_finds_breakdown_and_drop(self):
        loud = _click_track(120.0, seconds=10.0) * 0.8
        quiet = (np.random.default_rng(7).standard_normal((2, 5 * SR)) * 0.01).astype(np.float32)
        # A realistic drop: sustained broadband burst + bass thump, not a single impulse.
        t = np.arange(int(1.0 * SR)) / SR
        burst = (0.6 * np.random.default_rng(3).standard_normal(int(1.0 * SR)) * np.exp(-3 * t)
                 + 0.9 * np.sin(2 * np.pi * 55 * t)).astype(np.float32)
        drop = np.vstack([burst, burst])
        tail = _click_track(120.0, seconds=9.0) * 0.8
        track = np.concatenate([loud, quiet, drop, tail], axis=1)
        cues = dj_tools.auto_cue_points(track, SR, bpm=None)
        labels = {cue["label"] for cue in cues}
        self.assertIn("intro", labels)
        self.assertIn("breakdown", labels)
        self.assertIn("drop", labels)
        breakdown = next(c for c in cues if c["label"] == "breakdown")
        drop_cue = next(c for c in cues if c["label"] == "drop")
        self.assertTrue(9.0 <= breakdown["time"] <= 15.0)
        self.assertTrue(13.0 <= drop_cue["time"] <= 18.0)

    def test_placeholder_stems_reconstruct_input(self):
        signal = _tone(100.0, seconds=1.0) + _tone(1000.0, seconds=1.0) + _tone(8000.0, seconds=1.0, amp=0.2)
        stems = dj_tools.split_stems_placeholder(signal, SR)
        self.assertEqual(set(stems), {"vocals", "bass", "drums", "melody"})
        rebuilt = sum(stems.values())
        np.testing.assert_allclose(rebuilt, signal, atol=1e-4)

    def test_mix_stems_mute_and_solo(self):
        a = _tone(200.0, seconds=0.25)
        b = _tone(800.0, seconds=0.25)
        both = dj_tools.mix_stems([
            {"samples": a, "volume": 1.0},
            {"samples": b, "volume": 1.0},
        ])
        muted = dj_tools.mix_stems([
            {"samples": a, "volume": 1.0, "is_muted": True},
            {"samples": b, "volume": 1.0},
        ])
        soloed = dj_tools.mix_stems([
            {"samples": a, "volume": 1.0, "is_solo": True},
            {"samples": b, "volume": 1.0},
        ])
        self.assertGreater(np.abs(both).mean(), np.abs(muted).mean())
        np.testing.assert_allclose(soloed, a, atol=1e-3)

    def test_render_transition_styles(self):
        a = _tone(300.0, seconds=4.0)
        b = _tone(600.0, seconds=4.0)
        cut = dj_tools.render_transition(a, b, SR, style="cut", transition_bars=2, bpm=120.0)
        self.assertEqual(cut.shape[1], a.shape[1] + b.shape[1])
        cross = dj_tools.render_transition(a, b, SR, style="crossfade", transition_bars=2, bpm=120.0)
        self.assertLess(cross.shape[1], a.shape[1] + b.shape[1])
        for style in ("drop_swap", "echo_out"):
            out = dj_tools.render_transition(a, b, SR, style=style, transition_bars=2, bpm=120.0)
            self.assertEqual(out.shape[0], 2)
            self.assertTrue(np.all(np.isfinite(out)))
        with self.assertRaises(ValueError):
            dj_tools.render_transition(a, b, SR, style="bogus")

    def test_run_chain_applies_operations_in_order(self):
        signal = _tone(440.0, seconds=1.0)
        out = dj_tools.run_chain(signal, SR, [
            {"op": "pitch_shift", "semitones": 2},
            {"op": "eq", "low_db": 3.0, "mid_db": 0.0, "high_db": -3.0},
            {"op": "echo", "delay_ms": 120, "feedback": 0.3, "mix": 0.2},
            {"op": "normalize"},
        ])
        self.assertEqual(out.shape[0], 2)
        self.assertLessEqual(float(np.abs(out).max()), 0.99)
        with self.assertRaises(ValueError):
            dj_tools.run_chain(signal, SR, [{"op": "explode"}])


class DjApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="deejay", password="test-password")
        self.other = User.objects.create_user(username="fan", password="test-password")
        self.genre = Genre.objects.create(name="Mũgithi", slug="mugithi")
        self.client.force_authenticate(self.user)

    def _song(self, owner, title, with_audio=True, song_status=Song.Status.COMPLETED):
        song = Song.objects.create(
            user=owner,
            title=title,
            user_prompt="prompt",
            compiled_ai_prompt="compiled",
            genre=self.genre,
            status=song_status,
            tempo_bpm=120,
        )
        if with_audio:
            song.audio_file = f"generated/test/{song.pk}.wav"
            song.save(update_fields=["audio_file"])
        return song

    def test_create_mix_dispatches_task(self):
        track_a = self._song(self.user, "Ngoma ya Mbere")
        track_b = self._song(self.user, "Ngoma ya Keeri")
        with patch("music.views.mix_tracks_task.delay") as dispatch:
            response = self.client.post("/api/dj/mix/", {
                "track_a": track_a.pk,
                "track_b": track_b.pk,
                "transition": "crossfade",
                "transition_bars": 8,
            }, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = DjMixJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.status, DjMixJob.Status.PENDING)
        self.assertEqual(job.user, self.user)
        dispatch.assert_called_once_with(job.pk)

    def test_mix_rejects_same_track_and_foreign_tracks(self):
        track = self._song(self.user, "Solo")
        foreign = self._song(self.other, "Not yours")
        response = self.client.post("/api/dj/mix/", {"track_a": track.pk, "track_b": track.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post("/api/dj/mix/", {"track_a": track.pk, "track_b": foreign.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mix_requires_completed_audio(self):
        track_a = self._song(self.user, "Done")
        track_b = self._song(self.user, "Pending", song_status=Song.Status.PENDING, with_audio=False)
        response = self.client.post("/api/dj/mix/", {"track_a": track_a.pk, "track_b": track_b.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mix_list_and_detail_are_scoped_to_owner(self):
        track_a = self._song(self.user, "A")
        track_b = self._song(self.user, "B")
        job = DjMixJob.objects.create(user=self.user, track_a=track_a, track_b=track_b)
        other_job_track = self._song(self.other, "C")
        other_job = DjMixJob.objects.create(user=self.other, track_a=other_job_track, track_b=self._song(self.other, "D"))

        response = self.client.get("/api/dj/mix/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get(f"/api/dj/mix/{job.pk}/").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(f"/api/dj/mix/{other_job.pk}/").status_code, status.HTTP_404_NOT_FOUND)

    def test_dsp_render_validates_operations_and_dispatches(self):
        song = self._song(self.user, "Source")
        bad = self.client.post("/api/dj/process/", {
            "source_song": song.pk,
            "operations": [{"op": "explode"}],
        }, format="json")
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        with patch("music.views.process_audio_task.delay") as dispatch:
            good = self.client.post("/api/dj/process/", {
                "source_song": song.pk,
                "operations": [
                    {"op": "time_stretch", "rate": 1.05},
                    {"op": "pitch_shift", "semitones": 2},
                    {"op": "eq", "low_db": 3, "mid_db": -1, "high_db": 2},
                    {"op": "filter_sweep", "mode": "highpass", "start_cutoff": 60, "end_cutoff": 9000},
                ],
            }, format="json")
        self.assertEqual(good.status_code, status.HTTP_202_ACCEPTED)
        job = DjRenderJob.objects.get(pk=good.data["id"])
        self.assertEqual(job.status, DjRenderJob.Status.PENDING)
        dispatch.assert_called_once_with(job.pk)

    def test_analyze_and_autosplit_require_audio(self):
        silent = self._song(self.user, "No audio", with_audio=False)
        self.assertEqual(self.client.post(f"/api/songs/{silent.pk}/analyze/").status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self.client.post(f"/api/songs/{silent.pk}/stems/auto-split/").status_code, status.HTTP_409_CONFLICT)

        ready = self._song(self.user, "Ready")
        with patch("music.views.analyze_song_task.delay") as analyze, patch("music.views.split_song_stems_task.delay") as split:
            self.assertEqual(self.client.post(f"/api/songs/{ready.pk}/analyze/").status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(self.client.post(f"/api/songs/{ready.pk}/stems/auto-split/").status_code, status.HTTP_202_ACCEPTED)
        analyze.assert_called_once_with(ready.pk)
        split.assert_called_once_with(ready.pk)

    def test_stem_mix_state_update_and_scoping(self):
        song = self._song(self.user, "Stemmed")
        stem = Stem.objects.create(song=song, kind=Stem.Kind.VOCALS, audio_file="stems/test/vocals.wav")
        foreign_stem = Stem.objects.create(
            song=self._song(self.other, "Foreign"), kind=Stem.Kind.BASS, audio_file="stems/test/bass.wav"
        )

        response = self.client.get(f"/api/songs/{song.pk}/stems/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        patch_response = self.client.patch(
            f"/api/stems/{stem.pk}/",
            {"volume": 0.5, "is_solo": True, "pan": -0.25},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        stem.refresh_from_db()
        self.assertEqual(stem.volume, 0.5)
        self.assertTrue(stem.is_solo)
        self.assertEqual(stem.pan, -0.25)

        forbidden = self.client.patch(f"/api/stems/{foreign_stem.pk}/", {"volume": 0.1}, format="json")
        self.assertEqual(forbidden.status_code, status.HTTP_404_NOT_FOUND)

    def test_dj_endpoints_require_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/dj/mix/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post("/api/dj/process/", {}, format="json").status_code, status.HTTP_403_FORBIDDEN)
