"""Tests for the formant singing-voice synthesizer and engine vocal wiring."""

import wave
from pathlib import Path
import tempfile

import numpy as np
from django.test import TestCase

from music.services import vocal_synth

SR = 22050


def _rng():
    return np.random.default_rng(7)


def _band_energy(signal, sr, low, high):
    spectrum = np.abs(np.fft.rfft(signal)) ** 2
    freqs = np.fft.rfftfreq(len(signal), 1.0 / sr)
    mask = (freqs >= low) & (freqs <= high)
    return float(spectrum[mask].mean())


class SyllabifyTests(TestCase):
    def test_cv_syllables(self):
        self.assertEqual(vocal_synth.syllabify_gikuyu("thayũ"), [("th", "a"), ("y", "ũ")])
        self.assertEqual(vocal_synth.syllabify_gikuyu("ng'ombe"), [("ng'", "o"), ("mb", "e")])
        self.assertEqual(vocal_synth.syllabify_gikuyu("Mũgithi"), [("m", "ũ"), ("g", "i"), ("th", "i")])

    def test_labialized_cluster_and_punctuation(self):
        self.assertEqual(vocal_synth.syllabify_gikuyu("hamwe"), [("h", "a"), ("mw", "e")])
        self.assertEqual(vocal_synth.syllabify_gikuyu("Wendo!"), [("w", "e"), ("nd", "o")])

    def test_vowel_initial_and_empty(self):
        self.assertEqual(vocal_synth.syllabify_gikuyu("ĩno"), [("", "ĩ"), ("n", "o")])
        self.assertEqual(vocal_synth.syllabify_gikuyu("123"), [])

    def test_syllabify_lines_flattens_words(self):
        syllables = vocal_synth.syllabify_lines(["Thayũ nĩ", "wega"])
        self.assertEqual(len(syllables), 2 + 1 + 2)


class SingSyllableTests(TestCase):
    def test_produces_voiced_audio_of_expected_length(self):
        out = vocal_synth.sing_syllable("th", "a", 67, 0.4, vocal_type="male_lead", rng=_rng(), sample_rate=SR)
        self.assertGreater(len(out), int(0.4 * SR))
        self.assertLess(len(out), int(0.6 * SR))
        self.assertGreater(float(np.abs(out).max()), 0.5)
        self.assertTrue(np.all(np.isfinite(out)))

    def test_close_vowel_has_low_formant_dominance(self):
        # ũ (/u/): F1 300 Hz, F2 900 Hz — low formant region should dominate.
        out = vocal_synth.sing_syllable("", "ũ", 57, 0.5, vocal_type="male_lead", rng=_rng(), sample_rate=SR)
        low = _band_energy(out, SR, 200, 500)
        high = _band_energy(out, SR, 2000, 3200)
        self.assertGreater(low, high * 2)

    def test_female_register_sits_above_male(self):
        male = vocal_synth.sing_syllable("", "a", 60, 0.4, vocal_type="male_lead", rng=_rng(), sample_rate=SR)
        female = vocal_synth.sing_syllable("", "a", 60, 0.4, vocal_type="female_lead", rng=_rng(), sample_rate=SR)

        def centroid(signal):
            spectrum = np.abs(np.fft.rfft(signal))
            freqs = np.fft.rfftfreq(len(signal), 1.0 / SR)
            return float((spectrum * freqs).sum() / spectrum.sum())

        self.assertGreater(centroid(female), centroid(male))

    def test_choir_is_an_ensemble(self):
        solo = vocal_synth.sing_syllable("", "a", 60, 0.4, vocal_type="male_lead", rng=_rng(), sample_rate=SR)
        choir = vocal_synth.sing_syllable("", "a", 60, 0.4, vocal_type="male_choir", rng=_rng(), sample_rate=SR)
        self.assertGreaterEqual(len(choir), len(solo))
        self.assertTrue(np.all(np.isfinite(choir)))
        # Octave-spread anchoring: choir adds sub-register members, so low-band
        # energy rises versus a single lead voice at the same note.
        self.assertGreater(_band_energy(choir, SR, 60, 150), _band_energy(solo, SR, 60, 150))

    def test_unknown_voice_falls_back_to_male_lead(self):
        out = vocal_synth.sing_syllable("", "e", 64, 0.3, vocal_type="ghost", rng=_rng(), sample_rate=SR)
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertGreater(float(np.abs(out).max()), 0.5)


class EngineVocalIntegrationTests(TestCase):
    """Local renders must actually sing: vocal-band energy rises with vocals on."""

    PAYLOAD = {
        "genre": "mugithi",
        "lyrics": "[Verse 1]\nThayũ nĩ wega tene na tene\nWendo wa Ngai ũrĩa mũingĩ\n\n[Chorus]\nTũinage hamwe ciana ciake\nNĩ wega ũrĩa Ngai atũenda",
        "instruments": ["acoustic guitar"],
        "duration_sec": 14,
        "vocal_type": "male_lead",
    }

    @staticmethod
    def _read_wav(path):
        with wave.open(str(path), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
            return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    def _render(self, tmp, **overrides):
        from mugithi_engine import render_song

        payload = {**self.PAYLOAD, **overrides}
        result = render_song(payload, tmp, "test-song")
        return self._read_wav(Path(tmp) / result["filename"]), result

    def test_vocals_are_audible_in_local_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            sung, _ = self._render(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            band_only, _ = self._render(tmp, instrumental=True)
        vocal_band_sung = _band_energy(sung, SR, 300, 3400)
        vocal_band_band = _band_energy(band_only, SR, 300, 3400)
        self.assertGreater(vocal_band_sung, vocal_band_band * 1.2)

    def test_render_reports_slow_groove_bpm(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self._render(tmp)
        self.assertEqual(result["bpm"], 98)
