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


class TestSubVisionV14Features(unittest.TestCase):
    """v1.4 modüler mimari, bağlamlı çeviri, Whisper VAD, i18n ve güncelleme denetleyici testleri."""

    def test_01_modular_package_backwards_compatibility(self) -> None:
        import main as app_main
        from subvision import __version__
        from subvision.workers import LatestTextSlot

        self.assertTrue(__version__.startswith("1.4"))
        self.assertIs(app_main.LatestTextSlot, LatestTextSlot)

    def test_02_i18n_tr_and_en_switching(self) -> None:
        from subvision.i18n import LanguageManager

        lm = LanguageManager("tr")
        self.assertEqual(lm.t("tab_home"), "Ana Ekran")
        lm.set_language("en")
        self.assertEqual(lm.t("tab_home"), "Home")
        self.assertIn("1.5.0", lm.t("updates_available", latest="1.5.0", current="1.4.0"))

    def test_03_updater_semver_and_mocked_release_check(self) -> None:
        import io
        import json
        from subvision.updater import check_for_updates, is_newer_version, parse_semver

        self.assertTrue(is_newer_version("v1.5.0", "1.4.0"))
        self.assertFalse(is_newer_version("v1.4.0", "1.4.0"))
        self.assertFalse(is_newer_version("1.3.9", "1.4.0"))
        self.assertGreater(parse_semver("1.4.0"), parse_semver("1.4.0-beta.1"))

        fake_payload = json.dumps(
            {
                "tag_name": "v1.5.0",
                "html_url": "https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/tag/v1.5.0",
                "body": "Release notes",
            }
        ).encode("utf-8")

        class _FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("urllib.request.urlopen", return_value=_FakeResp(fake_payload)):
            info = check_for_updates(current_version="1.4.0")
        self.assertTrue(info.is_update_available)
        self.assertEqual(info.latest_version, "1.5.0")
        self.assertIsNone(info.error)

    def test_04_context_aware_translator_and_safe_fallback(self) -> None:
        from subvision.context_translator import (
            BACKEND_OLLAMA,
            ContextAwareTranslator,
            ContextBackendConfig,
        )

        class _DummyLocal:
            is_ready = True
            active_compute_type = "int8"
            cpu_threads = 4
            model_dir = "."
            cache_size = 0
            total_requests = 0
            cache_hits = 0

            def try_fast_lookup(self, text: str):
                return None

            def translate_with_metrics(self, text: str):
                return f"LOCAL:{text}", 5.0, False

            def clear_cache(self):
                pass

        ctx_tr = ContextAwareTranslator(
            local_translator=_DummyLocal(),
            config=ContextBackendConfig(backend=BACKEND_OLLAMA, context_window=3),
        )

        # 1) Mock successful Ollama response & speaker preservation
        with patch.object(
            ctx_tr,
            "_http_post_json",
            return_value={"message": {"content": "Beni takip et, hemen gidiyoruz."}},
        ):
            tr_text, ms, cached = ctx_tr.translate_with_metrics("Arthur: Follow me, we leave now.")
        self.assertEqual(tr_text, "Arthur: Beni takip et, hemen gidiyoruz.")
        self.assertFalse(cached)
        self.assertEqual(ctx_tr.last_provider_used, BACKEND_OLLAMA)
        self.assertEqual(len(ctx_tr.get_context_snapshot()), 1)

        # 2) Mock network error -> must fall back seamlessly to local CT2
        with patch.object(ctx_tr, "_http_post_json", side_effect=TimeoutError("timed out")):
            fb_text, _, _ = ctx_tr.translate_with_metrics("Stay quiet.")
        self.assertEqual(fb_text, "LOCAL:Stay quiet.")
        self.assertEqual(ctx_tr.last_provider_used, "local_ct2_fallback")

    def test_05_whisper_speech_segmenter_vad(self) -> None:
        from subvision.audio_whisper import SpeechSegmenter, detect_audio_capabilities

        caps = detect_audio_capabilities()
        self.assertIsInstance(caps.is_ready, bool)

        seg = SpeechSegmenter(
            sample_rate=16000,
            energy_threshold=0.02,
            silence_duration_sec=0.2,
            min_speech_sec=0.2,
            max_speech_sec=2.0,
        )
        # Silence alone should emit nothing
        quiet = np.zeros(1600, dtype=np.float32)
        self.assertIsNone(seg.push_frame(quiet))

        # Speech frames followed by trailing silence should emit a segment
        loud = np.full(1600, 0.25, dtype=np.float32)
        for _ in range(4):
            self.assertIsNone(seg.push_frame(loud))
        emitted = None
        for _ in range(3):
            res = seg.push_frame(quiet)
            if res is not None:
                emitted = res
                break
        self.assertIsNotNone(emitted)
        self.assertGreaterEqual(emitted.size, 3200)

    def test_06_custom_json_glossary_and_term_protection(self) -> None:
        from subvision.custom_glossary import CustomGlossaryManager

        mgr = CustomGlossaryManager()
        self.assertIn("cyberpunk2077", mgr.packs)
        self.assertIn("spiderman2", mgr.packs)
        self.assertIn("baldurs_gate3", mgr.packs)

        mgr.set_active_pack("cyberpunk2077")
        self.assertEqual(mgr.lookup_exact("preem"), "Harika")

        protected, placeholders = mgr.protect_terms("Welcome to Night City, Choom!")
        self.assertNotIn("Night City", protected)
        self.assertNotIn("Choom", protected)
        restored = mgr.restore_terms(protected, placeholders)
        self.assertIn("Night City", restored)
        self.assertIn("Dostum", restored)

    def test_07_profile_manager_and_process_matching(self) -> None:
        from subvision.profiles import ProfileManager

        pm = ProfileManager()
        pm.save_profile(
            name="Spider-Man 2",
            roi={"left": 100, "top": 800, "width": 900, "height": 110},
            ocr_mode="fast_mask",
            overlay_mode="cover",
            text_color="#FACC15",
            glossary_pack="spiderman2",
            process_name="Spider-Man2.exe",
        )
        self.assertEqual(pm.match_process("spider-man2.exe"), "Spider-Man 2")
        self.assertIsNone(pm.match_process("notepad.exe"))
        self.assertFalse(pm.delete_profile(pm.DEFAULT_PROFILE_NAME))
        self.assertTrue(pm.delete_profile("Spider-Man 2"))

    def test_08_srt_and_anki_csv_exporters(self) -> None:
        import tempfile
        from subvision.exporters import (
            HistoryEntry,
            export_history_to_anki_csv,
            export_history_to_srt,
        )

        entries = [
            HistoryEntry("12:00:01", "Stay with me!", "Benimle kal!", 1.0),
            HistoryEntry("12:00:05", "We are almost there.", "Neredeyse vardık.", 5.0),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            srt_path = os.path.join(tmpdir, "out.srt")
            csv_path = os.path.join(tmpdir, "out.csv")
            self.assertEqual(export_history_to_srt(entries, srt_path, bilingual=True), 2)
            self.assertEqual(export_history_to_anki_csv(entries, csv_path), 2)

            with open(srt_path, "r", encoding="utf-8") as f:
                srt_txt = f.read()
            self.assertIn("00:00:01,000 --> 00:00:04,200", srt_txt)
            self.assertIn("Benimle kal!", srt_txt)

            with open(csv_path, "r", encoding="utf-8-sig") as f:
                csv_txt = f.read()
            self.assertIn("English;Turkish;Timestamp", csv_txt)
            self.assertIn("Stay with me!;Benimle kal!;12:00:01", csv_txt)

    def test_09_roi_selector_paint_no_qfont_float_crash(self) -> None:
        """ROISelectorOverlay çiziminin hem boşta hem sürükleme sırasında QFont float hatası vermediğini doğrular."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QApplication
        from overlay_ui import ROISelectorOverlay

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        selector = ROISelectorOverlay(on_selected=lambda _roi: None)
        selector.resize(1280, 720)
        # Boşta çizim (F7 açılışı — eski 8.8 float crash noktası)
        pix_idle = selector.grab()
        self.assertFalse(pix_idle.isNull())

        # Sürükleme çizimi (eski 8.2 float crash noktası)
        selector.start_pos = QPoint(220, 520)
        selector.end_pos = QPoint(1060, 640)
        selector.is_selecting = True
        pix_drag = selector.grab()
        self.assertFalse(pix_drag.isNull())
        selector.close()

    def test_10_dynamic_tight_overlay_hug_and_tr_overflow(self) -> None:
        """Overlay'in tüm ROI yerine orijinal altyazı kutusunu sıkıca örttüğünü ve uzun TR'de genişlediğini doğrular."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtCore import QRect
        from PyQt6.QtWidgets import QApplication
        from overlay_ui import SubtitleOverlayWindow, compute_dynamic_overlay_plan

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        canvas = QRect(0, 0, 1280, 220)
        local_roi = QRect(140, 60, 1000, 110)
        # 1000 px ROI ortasında yalnızca 180 px genişliğinde dar 1 satırlık orijinal altyazı
        narrow_layout = {
            "bbox": (0.41, 0.36, 0.59, 0.64),
            "lines": [(0.41, 0.36, 0.59, 0.64)],
            "line_h_norm": 0.28,
            "line_count": 1,
        }

        short_plan = compute_dynamic_overlay_plan(
            tr_text="Bekle!",
            en_text="Wait!",
            canvas_rect=canvas,
            local_roi_rect=local_roi,
            layout=narrow_layout,
            overlay_mode="cover",
            font_size_pt=24,
            auto_fit_font=True,
        )
        self.assertIsNotNone(short_plan)
        assert short_plan is not None
        # Tüm 1000 px ROI'yi kaplamak yerine orijinal ~180 px kutuyu sıkıca sarmalı
        self.assertLess(short_plan.backdrop_union.width(), 320.0)
        orig_left = local_roi.left() + 0.41 * local_roi.width()
        orig_right = local_roi.left() + 0.59 * local_roi.width()
        self.assertLessEqual(short_plan.backdrop_union.left(), orig_left)
        self.assertGreaterEqual(short_plan.backdrop_union.right(), orig_right)

        # 2 kelimelik cümle TR'de 5+ kelimeye uzadığında kontrollü biçimde genişlemeli
        long_plan = compute_dynamic_overlay_plan(
            tr_text="Bir saniye bekle, sakın hareket etme!",
            en_text="Hold on!",
            canvas_rect=canvas,
            local_roi_rect=local_roi,
            layout=narrow_layout,
            overlay_mode="cover",
            font_size_pt=24,
            auto_fit_font=True,
        )
        self.assertIsNotNone(long_plan)
        assert long_plan is not None
        self.assertGreater(long_plan.backdrop_union.width(), short_plan.backdrop_union.width() + 80.0)
        self.assertLessEqual(long_plan.backdrop_union.left(), orig_left)
        self.assertGreaterEqual(long_plan.backdrop_union.right(), orig_right)

        # SubtitleOverlayWindow çizimi ve temizlenme doğrulaması
        overlay = SubtitleOverlayWindow()
        overlay.align_to_roi(
            {"left": 100, "top": 700, "width": 1000, "height": 110, "qt_left": 100, "qt_top": 700, "qt_width": 1000, "qt_height": 110}
        )
        overlay.set_subtitle("Bekle!", "Wait!", orig_line_h_px=30, layout=narrow_layout)
        self.assertIsNotNone(overlay._render_plan)
        self.assertFalse(overlay.grab().isNull())
        overlay.set_subtitle("")
        self.assertIsNone(overlay._render_plan)
        overlay.close()

    def test_11_ocr_normalized_bbox_and_outlier_filtering(self) -> None:
        """OCR satır projeksiyonunun sıkı bbox çıkardığını ve kenardaki izole HUD pikselini elediğini doğrular."""
        mask = np.zeros((110, 960), dtype=np.uint8)
        # Ortada 180px genişliğinde gerçek metin bandı (x=390..570, y=40..68)
        for rx in range(390, 570, 6):
            mask[40:68, rx : rx + 3] = 255
        # Sağ köşede küçük izole HUD paraziti (x=935..941, y=42..60)
        mask[42:60, 935:941] = 255

        ocr_ready = np.full((110, 960, 3), 255, dtype=np.uint8)
        crops, boxes, median_h, line_count = SubtitleOCREngine.extract_fast_line_crops_with_boxes(
            ocr_ready, mask
        )
        self.assertEqual(line_count, 1)
        self.assertEqual(len(crops), 1)
        self.assertEqual(len(boxes), 1)
        self.assertGreaterEqual(median_h, 24)

        layout = SubtitleOCREngine._build_normalized_layout(boxes, 960, 110, measured_h=median_h)
        self.assertIsNotNone(layout)
        assert layout is not None
        u1, v1, u2, v2 = layout["bbox"]
        # İzole sağ kenar paraziti elendiği için kutu ortada dar kalmalı
        self.assertGreater(u1, 0.35)
        self.assertLess(u2, 0.65)
        self.assertLess(u2 - u1, 0.30)

        # DBNet satır birleştirme kontrolü
        merged = SubtitleOCREngine._group_dbnet_boxes_into_lines(
            [(100, 20, 220, 44), (235, 22, 360, 46), (180, 60, 310, 84)]
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0], (100, 20, 360, 46))
        self.assertEqual(merged[1], (180, 60, 310, 84))

    def test_12_target_window_lock_and_alt_tab_gating(self) -> None:
        """Hedef uygulama kilidinin Alt+Tab forum metinlerini dışladığını ve oyun odağında devam ettiğini doğrular."""
        from subvision.window_tracker import TargetWindowSpec, WindowInfo, is_target_foreground

        game_win = WindowInfo(hwnd=1001, pid=5000, process_name="gta6.exe", title="Grand Theft Auto VI")
        game_child = WindowInfo(hwnd=1002, pid=5000, process_name="gta6.exe", title="GTA6 Overlay")
        forum_win = WindowInfo(hwnd=2002, pid=6000, process_name="chrome.exe", title="Technopat Sosyal")
        own_win = WindowInfo(hwnd=3003, pid=9999, process_name="python.exe", title="SubVision AI")

        # 1) Kilit yok -> her zaman aktif
        self.assertTrue(is_target_foreground(None, forum_win, own_pid=9999))
        self.assertTrue(is_target_foreground(TargetWindowSpec(), forum_win, own_pid=9999))

        # 2) Oyun kilitli -> oyunda True, forumda ve SubVision'ın kendi penceresinde False
        game_target = TargetWindowSpec(hwnd=1001, process_name="gta6.exe", title="Grand Theft Auto VI")
        self.assertTrue(is_target_foreground(game_target, game_win, own_pid=9999, window_alive_fn=lambda _: True))
        self.assertTrue(is_target_foreground(game_target, game_child, own_pid=9999, window_alive_fn=lambda _: True))
        self.assertFalse(is_target_foreground(game_target, forum_win, own_pid=9999, window_alive_fn=lambda _: True))
        self.assertFalse(is_target_foreground(game_target, own_win, own_pid=9999, window_alive_fn=lambda _: True))

        # 3) Çok pencereli tarayıcı izolasyonu: YouTube penceresi (2001) kilitliyken Forum penceresi (2002) reddedilmeli
        yt_win = WindowInfo(hwnd=2001, pid=6000, process_name="chrome.exe", title="YouTube - Video")
        yt_target = TargetWindowSpec(hwnd=2001, process_name="chrome.exe", title="YouTube - Video")
        self.assertTrue(
            is_target_foreground(
                yt_target, yt_win, own_pid=9999, window_alive_fn=lambda h: h == 2001, root_owner_fn=lambda h: h
            )
        )
        self.assertFalse(
            is_target_foreground(
                yt_target, forum_win, own_pid=9999, window_alive_fn=lambda h: h == 2001, root_owner_fn=lambda h: h
            )
        )

        # 4) Anti-cheat / yükseltilmiş oyun (process_name boş) -> HWND veya başlık ile eşleşmeli
        ac_win = WindowInfo(hwnd=4004, pid=7000, process_name="", title="VALORANT")
        ac_target = TargetWindowSpec(hwnd=4004, process_name="", title="VALORANT")
        self.assertTrue(is_target_foreground(ac_target, ac_win, own_pid=9999, window_alive_fn=lambda _: True))
        self.assertFalse(is_target_foreground(ac_target, forum_win, own_pid=9999, window_alive_fn=lambda _: True))

    def test_13_worker_alt_tab_pause_resume_and_packaging(self) -> None:
        """CaptureTranslateWorker'ın Alt+Tab anında OCR'ı duraklatıp geri dönünce devam ettiğini ve paketlemeyi doğrular."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import time
        from PyQt6.QtWidgets import QApplication
        import build_exe
        import main as app_main
        from subvision.window_tracker import TargetWindowSpec, WindowInfo
        from subvision.workers import CaptureTranslateWorker

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        self.assertTrue(hasattr(app_main, "QCheckBox"))
        self.assertIn(("subvision/window_tracker.py", "subvision/window_tracker.py"), build_exe.EMBEDDED_FILES)
        self.assertIn("res_window_tracker.py", build_exe.LauncherCSharpSource)

        game_win = WindowInfo(hwnd=101, pid=4242, process_name="game.exe", title="Game")
        forum_win = WindowInfo(hwnd=202, pid=5353, process_name="chrome.exe", title="Forum")
        current_fg = {"win": game_win}
        capture_calls = {"count": 0}
        emitted_focus = []
        emitted_subs = []
        emitted_clears = []

        class _FakeOCR:
            last_line_height_px = 28
            last_subtitle_layout = {"bbox": (0.3, 0.3, 0.7, 0.7), "lines": [(0.3, 0.3, 0.7, 0.7)], "line_h_norm": 0.4, "line_count": 1}

            def reset_state(self):
                pass

            def capture_and_read(self, box, sct):
                capture_calls["count"] += 1
                return "NEW_TEXT", "Hold on!", 5.0

        class _FakeTranslator:
            def try_fast_lookup(self, text):
                return "Bekle!", 0.1, True

        class _DummyMSS:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        worker = CaptureTranslateWorker(
            ocr_engine=_FakeOCR(),
            translator=_FakeTranslator(),
            roi={"left": 0, "top": 0, "width": 800, "height": 100},
            scan_interval_sec=0.025,
            idle_scan_interval_sec=0.04,
            target_filter=TargetWindowSpec(hwnd=101, process_name="game.exe", title="Game"),
            foreground_provider=lambda: current_fg["win"],
        )
        worker.target_focus_changed.connect(lambda focused: emitted_focus.append(focused))
        worker.subtitle_updated.connect(lambda *args: emitted_subs.append(args))
        worker.subtitle_cleared.connect(lambda: emitted_clears.append(True))

        with patch("subvision.workers.mss.mss", return_value=_DummyMSS()):
            worker.start()
            # Oyun odaktayken yakalama çalışmalı
            t_end = time.monotonic() + 1.0
            while not emitted_subs and time.monotonic() < t_end:
                app.processEvents()
                time.sleep(0.02)
            self.assertGreaterEqual(len(emitted_subs), 1)
            self.assertIsInstance(emitted_subs[0][6], dict)

            # Alt+Tab ile foruma geç -> focus False & clear gelmeli, OCR durmalı
            current_fg["win"] = forum_win
            t_end = time.monotonic() + 1.0
            while (False not in emitted_focus) and time.monotonic() < t_end:
                app.processEvents()
                time.sleep(0.02)
            self.assertIn(False, emitted_focus)
            self.assertGreaterEqual(len(emitted_clears), 1)
            frozen_count = capture_calls["count"]
            time.sleep(0.18)
            self.assertEqual(capture_calls["count"], frozen_count)

            # Oyuna geri dön -> focus True gelmeli ve OCR devam etmeli
            current_fg["win"] = game_win
            t_end = time.monotonic() + 1.0
            while (True not in emitted_focus) and time.monotonic() < t_end:
                app.processEvents()
                time.sleep(0.02)
            self.assertIn(True, emitted_focus)
            self.assertGreater(capture_calls["count"], frozen_count)

            worker.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
