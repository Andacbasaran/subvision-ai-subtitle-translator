"""
SubVision AI — Otomatik Birim ve Entegrasyon Test Paketi (Unit & Integration Tests)
Çalıştırmak için:
    python -m unittest test_pipeline.py -v
"""

import unittest
from unittest.mock import patch

import numpy as np

from benchmark import make_synthetic_subtitle_frame
from glossary import (
    clean_ocr_text,
    extract_speaker_and_body,
    lookup_exact_phrase,
    normalize_all_caps_text,
    normalize_slang_for_nmt,
)
from hardware import (
    HardwareProfile,
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    classify_hardware_tier,
    compute_runtime_tuning,
    detect_hardware_profile,
    get_ct2_safe_path,
    select_compute_type_candidates,
)
from ocr_engine import SubtitleOCREngine
from translator import LocalEnTrTranslator


class TestHardwareCompatibility(unittest.TestCase):
    """Farklı işlemci, çekirdek sayısı, SIMD/ISA ve işletim sistemi senaryolarını doğrular."""

    def test_01_old_dual_core_no_avx2_classified_as_eco(self) -> None:
        tier = classify_hardware_tier(
            logical_cores=2,
            physical_cores=2,
            isa_features=("sse2", "sse4_2"),
            arch="x86_64",
        )
        self.assertEqual(tier, PROFILE_ECO)

        hw = HardwareProfile(
            os_name="Windows",
            os_version="10",
            windows_build=19045,
            arch="x86_64",
            cpu_name="Intel(R) Celeron(R) N4020",
            logical_cores=2,
            physical_cores=2,
            isa_features=("sse2", "sse4_2"),
            supported_ct2_types=("float32",),
            capture_exclude_supported=True,
            recommended_tier=tier,
        )
        tuning = compute_runtime_tuning(hw, PROFILE_AUTO)
        self.assertEqual(tuning.effective_profile, PROFILE_ECO)
        # 2 mantıksal çekirdekte OS/arayüz için en az 1 çekirdek boşta kalmalı
        self.assertEqual(tuning.nmt_threads, 1)
        self.assertEqual(tuning.ocr_intra_threads, 1)
        self.assertEqual(tuning.cv_threads, 1)
        self.assertEqual(tuning.scan_fps, 15)
        self.assertEqual(tuning.default_ocr_mode, "fast_mask")
        self.assertEqual(tuning.compute_type_candidates[0], "float32")

    def test_02_quad_core_without_avx2_classified_as_eco(self) -> None:
        tier = classify_hardware_tier(
            logical_cores=4,
            physical_cores=4,
            isa_features=("sse2", "sse4_1", "sse4_2", "avx"),
            arch="x86_64",
        )
        self.assertEqual(tier, PROFILE_ECO)

    def test_03_modern_midrange_and_high_end_cpu_tuning(self) -> None:
        hw_mid = HardwareProfile(
            os_name="Windows",
            os_version="11",
            windows_build=22631,
            arch="x86_64",
            cpu_name="Intel Core i5-11400H",
            logical_cores=8,
            physical_cores=4,
            isa_features=("sse4_2", "avx", "avx2"),
            supported_ct2_types=("int8", "int8_float32", "float32"),
            capture_exclude_supported=True,
            recommended_tier=classify_hardware_tier(8, 4, ("avx2",), "x86_64"),
        )
        self.assertEqual(hw_mid.recommended_tier, PROFILE_BALANCED)
        t_mid = compute_runtime_tuning(hw_mid, PROFILE_AUTO)
        self.assertEqual(t_mid.nmt_threads, 4)
        self.assertEqual(t_mid.scan_fps, 24)
        self.assertEqual(t_mid.compute_type_candidates[0], "int8")

        hw_high = HardwareProfile(
            os_name="Darwin",
            os_version="24.0",
            windows_build=0,
            arch="arm64",
            cpu_name="Apple M3 Pro",
            logical_cores=12,
            physical_cores=12,
            isa_features=("neon", "dotprod"),
            supported_ct2_types=("int8", "float32"),
            capture_exclude_supported=False,
            recommended_tier=classify_hardware_tier(12, 12, ("neon", "dotprod"), "arm64"),
        )
        self.assertEqual(hw_high.recommended_tier, PROFILE_PERFORMANCE)
        t_high = compute_runtime_tuning(hw_high, PROFILE_AUTO)
        self.assertEqual(t_high.nmt_threads, 6)
        self.assertEqual(t_high.scan_fps, 30)
        self.assertFalse(hw_high.capture_exclude_supported)

    def test_04_compute_type_fallback_order_when_int8_missing(self) -> None:
        candidates = select_compute_type_candidates(("float32", "int16"))
        self.assertEqual(candidates[0], "int16")
        self.assertEqual(candidates[1], "float32")
        self.assertIn("default", candidates)
        self.assertIn("auto", candidates)

        candidates_fp32_only = select_compute_type_candidates(("float32",))
        self.assertEqual(candidates_fp32_only[0], "float32")

    def test_05_single_core_safety_and_path_helper(self) -> None:
        hw_1c = HardwareProfile(
            os_name="Linux",
            os_version="6.0",
            windows_build=0,
            arch="x86_64",
            cpu_name="Single Core VM",
            logical_cores=1,
            physical_cores=1,
            isa_features=("sse2",),
            supported_ct2_types=("float32",),
            capture_exclude_supported=False,
            recommended_tier=PROFILE_ECO,
        )
        tuning = compute_runtime_tuning(hw_1c, PROFILE_PERFORMANCE)
        self.assertEqual(tuning.nmt_threads, 1)
        self.assertEqual(tuning.ocr_intra_threads, 1)
        self.assertEqual(get_ct2_safe_path("/tmp/subvision_ascii_path"), "/tmp/subvision_ascii_path")

    def test_06_runtime_hardware_detection_succeeds(self) -> None:
        hw = detect_hardware_profile(query_ct2=True)
        self.assertGreaterEqual(hw.logical_cores, 1)
        self.assertGreaterEqual(hw.physical_cores, 1)
        self.assertLessEqual(hw.physical_cores, hw.logical_cores)
        self.assertTrue(bool(hw.cpu_name))
        self.assertFalse(hw.cpu_name.isdigit())

    def test_07_ct2_compute_type_fallback_on_runtime_error(self) -> None:
        """İlk hesaplama tipi (int8) işlemcide hata verirse otomatik sonraki tipe düştüğünü doğrular."""
        tr = LocalEnTrTranslator(
            cpu_threads=1,
            compute_type_candidates=("int8", "float32"),
        )
        attempts = []

        class _FakeTranslator:
            def __init__(self, path, device, compute_type, intra_threads, inter_threads):
                attempts.append(compute_type)
                if compute_type == "int8":
                    raise ValueError("int8 unsupported on this CPU")

        with patch("translator.ctranslate2.Translator", side_effect=_FakeTranslator):
            engine, active_type = tr._create_ct2_translator("/fake/model")

        self.assertIsNotNone(engine)
        self.assertEqual(active_type, "float32")
        self.assertEqual(attempts, ["int8", "float32"])


class TestSubVisionPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hw = detect_hardware_profile(query_ct2=True)
        cls.tuning = compute_runtime_tuning(cls.hw)
        cls.ocr_engine = SubtitleOCREngine(
            use_color_mask=True,
            ocr_mode="fast_mask",
            tuning=cls.tuning,
        )
        cls.translator = LocalEnTrTranslator(
            cpu_threads=cls.tuning.nmt_threads,
            compute_type_candidates=cls.tuning.compute_type_candidates,
        )
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

    def test_05_two_stage_frame_diff_lock(self) -> None:
        self.ocr_engine.reset_state()
        frame = make_synthetic_subtitle_frame(["Stay behind me, the signal is getting stronger."])
        self.assertTrue(self.ocr_engine._has_raw_frame_changed(frame))
        # Aynı karede 1. aşama ham kilit maskeleme yapmadan False döndürmeli
        self.assertFalse(self.ocr_engine._has_raw_frame_changed(frame))
        # Farklı karede True döndürmeli
        frame2 = make_synthetic_subtitle_frame(["Move quickly to the extraction point!"])
        self.assertTrue(self.ocr_engine._has_raw_frame_changed(frame2))

    def test_06_fast_line_projection_ocr(self) -> None:
        frame = make_synthetic_subtitle_frame(["Stay behind me, the signal is getting stronger."])
        text, ocr_ms = self.ocr_engine.read_image_fast(frame)
        self.assertIn("signal", text.lower())
        # Donanım profiline göre makul gecikme üst sınırı (düşük çekirdekli/sanal CPU'larda da geçer)
        max_ocr_ms = 250.0 if self.tuning.effective_profile == PROFILE_ECO else 120.0
        self.assertLess(ocr_ms, max_ocr_ms)

    def test_07_ctranslate2_adaptive_and_lru_cache(self) -> None:
        self.translator.clear_cache()
        sample = "DETECTIVE: EVERYTHING WE FOUND IN THAT ROOM POINTS TO A CONSPIRACY."
        tr_cold, cold_ms, is_cached_cold = self.translator.translate_with_metrics(sample)
        self.assertFalse(is_cached_cold)
        self.assertTrue(tr_cold.startswith("Detective:"))
        self.assertIn("komplo", tr_cold.lower())

        tr_warm, warm_ms, is_cached_warm = self.translator.translate_with_metrics(sample)
        self.assertTrue(is_cached_warm)
        self.assertEqual(tr_cold, tr_warm)
        self.assertLess(warm_ms, 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
