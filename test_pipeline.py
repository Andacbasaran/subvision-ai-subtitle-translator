"""
SubVision AI — Otomatik Birim ve Entegrasyon Test Paketi (Unit & Integration Tests)
Çalıştırmak için:
    python -m unittest test_pipeline.py -v
"""

import unittest

from benchmark import make_synthetic_subtitle_frame
from glossary import (
    clean_ocr_text,
    extract_speaker_and_body,
    lookup_exact_phrase,
    normalize_all_caps_text,
    normalize_slang_for_nmt,
)
from ocr_engine import SubtitleOCREngine
from translator import LocalEnTrTranslator


class TestSubVisionPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ocr_engine = SubtitleOCREngine(use_color_mask=True, ocr_mode="fast_mask")
        cls.translator = LocalEnTrTranslator(cpu_threads=4)
        cls.translator.load()

    def test_01_ocr_noise_and_sdh_cleanup(self) -> None:
        raw = "[dramatic music] H0LD 0N! l'm coming with you | (sighs)"
        cleaned = clean_ocr_text(raw)
        self.assertEqual(cleaned, "HOLD ON! I'm coming with you I")

    def test_02_all_caps_normalization(self) -> None:
        raw_caps = "EVERYTHING WE FOUND POINTS TO A CONSPIRACY. I'M SURE OF IT."
        norm = normalize_all_caps_text(raw_caps)
        self.assertEqual(norm, "Everything we found points to a conspiracy. I'm sure of it.")

    def test_03_speaker_prefix_extraction(self) -> None:
        sp1, body1 = extract_speaker_and_body("DETECTIVE: EVERYTHING POINTS TO A CONSPIRACY.")
        self.assertEqual(sp1, "Detective")
        self.assertEqual(body1, "Everything points to a conspiracy.")

        sp2, body2 = extract_speaker_and_body("[Arthur] Stay close to me!")
        self.assertEqual(sp2, "Arthur")
        self.assertEqual(body2, "Stay close to me!")

    def test_04_slang_and_exact_glossary(self) -> None:
        self.assertEqual(lookup_exact_phrase("What are you talking about?"), "Sen neden bahsediyorsun?")
        self.assertEqual(lookup_exact_phrase("To be continued..."), "Devam edecek...")
        norm_slang = normalize_slang_for_nmt("I'm gonna tell 'em what happened.")
        self.assertIn("going to", norm_slang)
        self.assertIn("them", norm_slang)

    def test_05_fast_line_projection_ocr(self) -> None:
        frame = make_synthetic_subtitle_frame(["Stay behind me, the signal is getting stronger."])
        text, ocr_ms = self.ocr_engine.read_image_fast(frame)
        self.assertIn("signal", text.lower())
        self.assertLess(ocr_ms, 85.0)

    def test_06_ctranslate2_int8_and_lru_cache(self) -> None:
        self.translator.clear_cache()
        sample = "DETECTIVE: EVERYTHING WE FOUND IN THAT ROOM POINTS TO A CONSPIRACY."
        tr_cold, cold_ms, is_cached_cold = self.translator.translate_with_metrics(sample)
        self.assertFalse(is_cached_cold)
        self.assertTrue(tr_cold.startswith("Detective:"))
        self.assertIn("komplo", tr_cold.lower())

        tr_warm, warm_ms, is_cached_warm = self.translator.translate_with_metrics(sample)
        self.assertTrue(is_cached_warm)
        self.assertEqual(tr_cold, tr_warm)
        self.assertLess(warm_ms, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
