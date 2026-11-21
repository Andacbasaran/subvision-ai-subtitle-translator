"""
SubVision AI — Otomatik Birim ve Entegrasyon Test Paketi (Unit & Integration Tests)
Çalıştırmak için:
    python -m unittest test_pipeline.py -v
"""

import os
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from benchmark import make_synthetic_subtitle_frame
from glossary import (
    clean_ocr_text,
    extract_speaker_and_body,
    is_plausible_subtitle_text,
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
        # İlk çağrıda ONNX Runtime soğuk başlangıç/JIT ısınması tamamlanır
        self.ocr_engine.read_image_fast(frame)
        text, ocr_ms = self.ocr_engine.read_image_fast(frame)
        self.assertIn("signal", text.lower())
        # Donanım profiline göre makul gecikme üst sınırı (paylaşımlı CI/sanal CPU'larda da kararlı)
        max_ocr_ms = 350.0 if self.tuning.effective_profile == PROFILE_ECO else 180.0
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

    def test_08_plausible_subtitle_anti_gibberish(self) -> None:
        """Gerçek kısa altyazıları kabul edip hayalet/anlamsız OCR çıktılarını reddettiğini doğrular."""
        for valid in ("No!", "Hey!", "Wait.", "MJ", "OK", "Stop right there!"):
            self.assertTrue(
                is_plausible_subtitle_text(valid, avg_confidence=0.82),
                f"Geçerli altyazı reddedildi: {valid}",
            )
        for junk in ("", "...", "IIII", "rrrt", "11--@", "x", "zzzzz", "|||///"):
            self.assertFalse(
                is_plausible_subtitle_text(junk, avg_confidence=0.65),
                f"Hayalet/gürültü metin kabul edildi: {junk}",
            )

    def test_09_zero_phantom_on_noisy_empty_game_scene(self) -> None:
        """Altyazısız karmaşık/parlak oyun arka planında 0 hayalet altyazı üretildiğini doğrular."""
        h, w = 110, 960
        rng = np.random.default_rng(42)
        scene = np.zeros((h, w, 3), dtype=np.uint8)
        # Parlak gündüz gökyüzü + bina kenarı + beyaz araç farı bloğu + hafif doku
        scene[:, :480] = (235, 205, 165)
        scene[:, 480:] = (42, 48, 55)
        cv2.circle(scene, (620, 55), 18, (250, 250, 250), -1)
        cv2.rectangle(scene, (180, 20), (310, 95), (25, 28, 32), -1)
        noise = rng.integers(-8, 9, size=scene.shape, dtype=np.int16)
        scene = np.clip(scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        for mode in ("fast_mask", "hybrid"):
            self.ocr_engine.set_mode(mode)
            text, _ = self.ocr_engine.read_image_fast(scene)
            self.assertEqual(
                text,
                "",
                f"{mode} modunda altyazısız oyun sahnesinde hayalet metin üretildi: {text!r}",
            )
        self.ocr_engine.set_mode("fast_mask")

    def test_10_spiderman2_colored_speaker_over_bright_sky(self) -> None:
        """Parlak gökyüzü + yarı saydam bant + renkli konuşmacı adı (Miles:) senaryosunu doğrular."""
        h, w = 110, 960
        frame = np.full((h, w, 3), (240, 212, 175), dtype=np.uint8)
        # Yarı saydam koyu altyazı arka plan bandı (~%60 koyuluk)
        overlay = frame.copy()
        cv2.rectangle(overlay, (140, 24), (820, 86), (18, 20, 26), -1)
        frame = cv2.addWeighted(overlay, 0.62, frame, 0.38, 0)

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.95
        speaker_txt = "Miles: "
        body_txt = "We have to stop him now!"
        (sw, sh), _ = cv2.getTextSize(speaker_txt, font, scale, 2)
        (bw, _), _ = cv2.getTextSize(body_txt, font, scale, 2)
        start_x = (w - (sw + bw)) // 2
        base_y = 66

        # İnce koyu kontür + mercan-kırmızı (BGR) konuşmacı adı + beyaz diyalog
        cv2.putText(frame, speaker_txt, (start_x, base_y), font, scale, (10, 10, 10), 4, cv2.LINE_AA)
        cv2.putText(frame, speaker_txt, (start_x, base_y), font, scale, (95, 115, 250), 2, cv2.LINE_AA)
        cv2.putText(frame, body_txt, (start_x + sw, base_y), font, scale, (10, 10, 10), 4, cv2.LINE_AA)
        cv2.putText(frame, body_txt, (start_x + sw, base_y), font, scale, (245, 245, 245), 2, cv2.LINE_AA)

        self.ocr_engine.set_mode("fast_mask")
        text, _ = self.ocr_engine.read_image_fast(frame)
        self.assertIn("miles", text.lower())
        self.assertIn("stop", text.lower())
        self.assertGreater(self.ocr_engine.last_line_height_px, 12)

    def test_11_short_one_word_subtitle_in_wide_roi(self) -> None:
        """Geniş 960x110 ROI içindeki tek kelimelik kısa altyazının ('Wait!') kaçırılmadığını doğrular."""
        frame = make_synthetic_subtitle_frame(["Wait!"], width=960, height=110)
        self.ocr_engine.set_mode("fast_mask")
        text, _ = self.ocr_engine.read_image_fast(frame)
        self.assertIn("wait", text.lower())

    def test_12_dynamic_decoding_limit_and_fast_lookup(self) -> None:
        """Dinamik max_decoding_length hesabını ve sıfır-beklemeli önbellek/sözlük dönüşünü doğrular."""
        short_limit = LocalEnTrTranslator.compute_dynamic_max_length([["▁No", "!"]])
        long_limit = LocalEnTrTranslator.compute_dynamic_max_length([["▁word"] * 50])
        self.assertLessEqual(short_limit, 35)
        self.assertGreaterEqual(short_limit, 20)
        self.assertEqual(long_limit, 88)

        # Sözlük hit'i model çağrısı olmadan anında dönmeli
        fast_hit = self.translator.try_fast_lookup("To be continued...")
        self.assertIsNotNone(fast_hit)
        self.assertEqual(fast_hit[0], "Devam edecek...")

        # Önbellekte olmayan yeni cümle None döndürmeli
        self.translator.clear_cache()
        self.assertIsNone(self.translator.try_fast_lookup("Unique untested orbital telemetry signal."))

    def test_13_latest_text_slot_latest_frame_wins(self) -> None:
        """Asenkron LatestTextSlot kuyruğunun eski cümleleri atıp daima en günceli verdiğini doğrular."""
        from main import LatestTextSlot

        slot = LatestTextSlot()
        g1 = slot.submit("First line", 15.0, 28)
        g2 = slot.submit("Second line", 16.0, 28)
        g3 = slot.submit("Third latest line", 17.0, 30)
        self.assertEqual(slot.dropped_count, 2)
        self.assertTrue(slot.is_current(g3))
        self.assertFalse(slot.is_current(g1))
        self.assertFalse(slot.is_current(g2))

        item = slot.take(timeout=0.1)
        self.assertIsNotNone(item)
        gen, text, ocr_ms, line_h = item
        self.assertEqual(gen, g3)
        self.assertEqual(text, "Third latest line")
        self.assertEqual(line_h, 30)

        slot.invalidate()
        self.assertFalse(slot.is_current(g3))

    def test_14_autofit_overlay_font_sizing(self) -> None:
        """Auto-Fit font hesabının uzun Türkçe cümleyi kutuya sığdıracak şekilde otomatik küçülttüğünü doğrular."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from overlay_ui import compute_autofit_font_size

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        short_pt = compute_autofit_font_size(
            tr_text="Bekle!",
            en_text="",
            avail_w=760,
            avail_h=78,
            max_pt=24,
            min_pt=12,
            orig_line_h=30,
            show_bilingual=False,
        )
        long_pt = compute_autofit_font_size(
            tr_text=(
                "Şehrin diğer ucundaki araştırma laboratuvarında bulduğumuz tüm veriler "
                "bunun çok daha büyük ve tehlikeli bir komplonun parçası olduğunu gösteriyor."
            ),
            en_text="",
            avail_w=760,
            avail_h=78,
            max_pt=24,
            min_pt=12,
            orig_line_h=30,
            show_bilingual=False,
        )
        self.assertGreaterEqual(short_pt, 12)
        self.assertLessEqual(short_pt, 24)
        self.assertGreaterEqual(long_pt, 12)
        self.assertLess(long_pt, short_pt)

    def test_15_installer_uninstaller_and_signing_config(self) -> None:
        """Kurulum yardımcısı, opsiyonel kaldırıcı (Uninstaller) ve dijital imzalama yapılandırmasını doğrular."""
        import build_exe

        cs_src = build_exe.LauncherCSharpSource
        self.assertIn("SetupWizardForm", cs_src)
        self.assertIn("UninstallWizardForm", cs_src)
        self.assertIn("SubVisionAI-Uninstaller.exe", cs_src)
        self.assertNotIn("DownloadFileAsync", cs_src)
        self.assertNotIn(".Kill()", cs_src)
        self.assertTrue(callable(build_exe.ensure_publisher_certificate_and_sign))

        iss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "installer.iss")
        with open(iss_path, "rb") as f:
            raw_iss = f.read()
        self.assertTrue(raw_iss.startswith(b"\xef\xbb\xbf"), "installer.iss UTF-8 BOM içermeli")
        iss_text = raw_iss.decode("utf-8-sig")
        self.assertIn("CurUninstallStepChanged", iss_text)
        self.assertIn("DeleteModelsAndRuntime", iss_text)
        self.assertIn("DeleteUserSettings", iss_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
