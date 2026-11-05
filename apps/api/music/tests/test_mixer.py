"""Tests for the multi-track mixer / mastering suite and the render task."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from music.models import Genre, Song, Stem, User
from music.services import audio_mixer
from music.tasks import render_final_song_task

SR = 22050


def _stereo_sine(freq, seconds=1.0, amp=0.5, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    signal = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.vstack([signal, signal])


def _stereo_noise(seconds=1.0, amp=0.3, sr=SR, seed=11):
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal((2, int(sr * seconds)))).astype(np.float32)


def _click_train(seconds=2.0, every=0.25, sr=SR):
    signal = np.zeros(int(sr * seconds), dtype=np.float32)
    t = 0.0
    while t < seconds - 0.02:
        start = int(t * sr)
        length = min(int(0.02 * sr), len(signal) - start)
        signal[start : start + length] = 0.9 * np.hanning(length)
        t += every
    return np.vstack([signal, signal])


class GainStagingTests(TestCase):
    def test_normalize_stem_hits_target_peak(self):
        quiet = _stereo_sine(440, amp=0.05)
        staged = audio_mixer.normalize_stem(quiet, target_peak_dbfs=-12.0)
        self.assertAlmostEqual(float(np.max(np.abs(staged))), 10 ** (-12.0 / 20.0), places=3)

    def test_silence_is_not_amplified(self):
        silent = np.zeros((2, SR // 2), dtype=np.float32)
        self.assertEqual(float(np.max(np.abs(audio_mixer.normalize_stem(silent)))), 0.0)


class ShapeStemTests(TestCase):
    def test_vocals_high_passed_below_100hz(self):
        low_rumble = _stereo_sine(60.0, seconds=2.0)
        shaped = audio_mixer.shape_stem("vocals", low_rumble, SR)
        self.assertLess(float(np.abs(shaped).mean()), float(np.abs(low_rumble).mean()) * 0.2)

    def test_vocals_get_air_and_presence(self):
        noise = _stereo_noise(seconds=1.0)
        shaped = audio_mixer.shape_stem("vocals", noise, SR)
        freqs = np.fft.rfftfreq(noise.shape[1], d=1.0 / SR)

        def band_energy(x, low, high):
            spectrum = np.abs(np.fft.rfft(x, axis=1)) ** 2
            mask = (freqs >= low) & (freqs <= high)
            return float(spectrum[:, mask].mean())

        air_in = band_energy(noise, 10000, 10500)
        air_out = band_energy(shaped, 10000, 10500)
        self.assertGreater(air_out, air_in * 1.5)

    def test_melody_hpf_and_presence_cut(self):
        rumble = _stereo_sine(30.0, seconds=2.0)
        harsh = _stereo_sine(3000.0, seconds=2.0)
        shaped_rumble = audio_mixer.shape_stem("melody", rumble, SR)
        shaped_harsh = audio_mixer.shape_stem("melody", harsh, SR)
        # 4th-order 40 Hz HPF strongly attenuates 30 Hz content
        self.assertLess(float(np.abs(shaped_rumble).mean()), float(np.abs(rumble).mean()) * 0.35)
        # -2.5 dB bell at 3 kHz
        self.assertLess(float(np.abs(shaped_harsh).mean()), float(np.abs(harsh).mean()) * 0.85)

    def test_bass_keeps_low_end(self):
        bass = _stereo_sine(60.0, seconds=2.0)
        shaped = audio_mixer.shape_stem("bass", bass, SR)
        self.assertGreater(float(np.abs(shaped).mean()), float(np.abs(bass).mean()) * 0.9)


class SidechainTests(TestCase):
    def test_kick_ducks_bass(self):
        bass = _stereo_sine(80.0, seconds=2.0, amp=0.5)
        kicks = _click_train(seconds=2.0, every=0.5)
        ducked = audio_mixer.sidechain_duck(bass, kicks, SR, threshold_db=-24.0, ratio=8.0, attack_ms=2.0, release_ms=150.0)
        click_center = int(1.0 * SR)  # click at t=1.0s
        during = float(np.abs(ducked[:, click_center : click_center + int(0.05 * SR)]).mean())
        between = float(np.abs(ducked[:, int(1.3 * SR) : int(1.35 * SR)]).mean())
        self.assertLess(during, between * 0.7)


class PanWidthSumTests(TestCase):
    def test_stereo_balance_pan(self):
        signal = _stereo_sine(440, seconds=0.25)
        left = audio_mixer.apply_pan(signal, -1.0)
        self.assertAlmostEqual(float(np.abs(left[1]).max()), 0.0, places=4)
        self.assertGreater(float(np.abs(left[0]).max()), 0.4)
        center = audio_mixer.apply_pan(signal, 0.0)
        np.testing.assert_allclose(center, signal, atol=1e-6)

    def test_width_zero_is_mono(self):
        noise = _stereo_noise(seconds=0.5)
        mono = audio_mixer.stereo_width(noise, width=0.0)
        np.testing.assert_allclose(mono[0], mono[1], atol=1e-6)

    def test_sum_stems_mute_solo_and_volume(self):
        a = _stereo_sine(200.0, seconds=0.25)
        b = _stereo_sine(800.0, seconds=0.25)
        out = audio_mixer.sum_stems([
            {"samples": a, "volume": 1.0, "pan": 0.0, "is_solo": True},
            {"samples": b, "volume": 1.0, "pan": 0.0},
        ])
        np.testing.assert_allclose(out, a, atol=1e-3)


class MasterChainTests(TestCase):
    def test_limiter_respects_ceiling(self):
        loud = _stereo_sine(440, seconds=0.5, amp=1.5)
        limited = audio_mixer.brickwall_limiter(loud, SR, ceiling_dbfs=-1.0)
        self.assertLessEqual(float(np.max(np.abs(limited))), 10 ** (-1.0 / 20.0) + 1e-4)

    def test_multiband_compressor_reduces_dynamic_range(self):
        sustained = _stereo_sine(100.0, seconds=2.0, amp=0.05)
        bursts = np.zeros((2, 2 * SR), dtype=np.float32)
        burst_t = np.arange(int(0.08 * SR)) / SR
        burst_tone = (0.9 * np.sin(2 * np.pi * 100.0 * burst_t)).astype(np.float32)
        for t in (0.25, 1.25):
            start = int(t * SR)
            bursts[:, start : start + len(burst_tone)] += burst_tone
        signal = sustained + bursts

        def windowed_range_db(x):
            mono = x.mean(axis=0)
            block = int(0.1 * SR)
            levels = [
                20 * np.log10(np.sqrt(np.mean(mono[i : i + block] ** 2)) + 1e-9)
                for i in range(0, len(mono) - block, block)
            ]
            return max(levels) - min(levels)

        compressed = audio_mixer.multiband_compress(signal, SR)
        self.assertLess(windowed_range_db(compressed), windowed_range_db(signal) - 2.0)
        # Makeup may overshoot modestly on sparse band transients; the
        # brickwall limiter in master_chain is the peak authority.
        self.assertLessEqual(float(np.max(np.abs(compressed))), float(np.max(np.abs(signal))) * 1.2)

    def test_master_chain_hits_loudness_target(self):
        mix = _stereo_sine(110.0, seconds=3.0, amp=0.1) + _stereo_noise(seconds=3.0, amp=0.03)
        mastered, report = audio_mixer.master_chain(mix, SR, target_lufs=-14.0)
        self.assertAlmostEqual(report["integrated_lufs"], -14.0, delta=2.0)
        self.assertLessEqual(report["output_peak_dbfs"], -0.9)
        self.assertEqual(mastered.shape, mix.shape)

    def test_mix_and_master_report(self):
        stems = [
            {"kind": "drums", "samples": _click_train(seconds=1.5), "volume": 1.0, "pan": 0.0},
            {"kind": "bass", "samples": _stereo_sine(70.0, seconds=1.5, amp=0.4), "volume": 0.9, "pan": 0.0},
            {"kind": "vocals", "samples": _stereo_noise(seconds=1.5, amp=0.15), "volume": 1.0, "pan": 0.1},
        ]
        mastered, report = audio_mixer.mix_and_master(stems, SR)
        self.assertEqual(mastered.shape[0], 2)
        self.assertEqual(len(report["stems"]), 3)
        self.assertIn("integrated_lufs", report)
        self.assertTrue(np.all(np.isfinite(mastered)))


class RenderFinalSongTaskTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(username="mixer", password="test-password")
        self.genre = Genre.objects.create(name="Mũgithi", slug="mugithi")

    def _song(self):
        song = Song.objects.create(
            user=self.user, title="Mix me", user_prompt="p", compiled_ai_prompt="c",
            genre=self.genre, status=Song.Status.COMPLETED,
        )
        song.audio_file.save("raw.wav", ContentFile(b"RIFF-raw"))
        return song

    @staticmethod
    def _fake_save(path, samples, sample_rate):
        Path(path).write_bytes(b"RIFF-mastered")
        return Path(path)

    def test_auto_split_mix_master_completes(self):
        song = self._song()
        fake_audio = _stereo_sine(220.0, seconds=1.0) + _stereo_noise(seconds=1.0, amp=0.05)
        with patch("music.services.dj_tools.load_audio", return_value=(fake_audio, SR)), patch(
            "music.services.dj_tools.save_audio", side_effect=self._fake_save
        ):
            result = render_final_song_task(song.pk)
        song.refresh_from_db()
        self.assertEqual(result["status"], Song.Status.COMPLETED)
        self.assertEqual(song.status, Song.Status.COMPLETED)
        self.assertTrue(song.mastered_file.name.endswith(".wav"))
        self.assertEqual(Path(song.mastered_file.path).read_bytes(), b"RIFF-mastered")
        self.assertIn("integrated_lufs", song.mastering_report)
        self.assertEqual(len(song.mastering_report["stems"]), 4)

    def test_uses_existing_stem_mix_state(self):
        song = self._song()
        vocals = Stem.objects.create(song=song, kind=Stem.Kind.VOCALS, volume=0.8)
        vocals.audio_file.save("vocals.wav", ContentFile(b"RIFF-v"))
        bass = Stem.objects.create(song=song, kind=Stem.Kind.BASS, is_muted=True)
        bass.audio_file.save("bass.wav", ContentFile(b"RIFF-b"))

        fake_audio = _stereo_sine(330.0, seconds=1.0, amp=0.2)
        with patch("music.services.dj_tools.load_audio", return_value=(fake_audio, SR)), patch(
            "music.services.dj_tools.save_audio", side_effect=self._fake_save
        ):
            result = render_final_song_task(song.pk)
        song.refresh_from_db()
        self.assertEqual(result["status"], Song.Status.COMPLETED)
        kinds = {entry["kind"] for entry in song.mastering_report["stems"]}
        self.assertEqual(kinds, {"vocals", "bass"})
        muted = next(entry for entry in song.mastering_report["stems"] if entry["kind"] == "bass")
        self.assertTrue(muted["muted"])

    def test_no_audio_returns_early(self):
        song = Song.objects.create(
            user=self.user, title="Empty", user_prompt="p", compiled_ai_prompt="c", genre=self.genre
        )
        self.assertEqual(render_final_song_task(song.pk)["status"], "no_audio")

    def test_failure_marks_song_failed(self):
        song = self._song()
        with patch("music.services.dj_tools.load_audio", side_effect=RuntimeError("decode boom")), self.assertRaises(RuntimeError):
            render_final_song_task(song.pk)
        song.refresh_from_db()
        self.assertEqual(song.status, Song.Status.FAILED)
