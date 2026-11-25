"""
Regression tests for SubVision AI v1.6.0 hardening improvements:
- Version parity across package, main.py, pyproject.toml, and build scripts
- Dynamic Windows Online Setup embedding (all subvision/*.py and glossaries/*.json)
- CustomGlossary multi-term NMT placeholder isolation & backreference safety
- ContextAwareTranslator interface delegation, Gemini x-goog-api-key header & error scrubbing,
  URL scheme validation, dynamic source/target language parameterization, and bounded cache
- Unicode/multilingual OCR cleaning & plausibility
- Updater fail-closed SHA-256, URL allowlist, Linux & wrong-arch filtering, SemVer pre-release
- VocabNotebook corrupt seen_count resilience, context_tr search, atomic batch save
- MainWindow stop_translation(), _on_perf_profile_changed(), settings preservation (offscreen)
"""

import io
import json
import os
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main as studio_main
import subvision
from subvision.audio_whisper import LiveAudioTranscriber, _downsample_to_16k
from subvision.context_translator import (
    BACKEND_DEEPL,
    BACKEND_GEMINI,
    BACKEND_OPENAI_COMPAT,
    ContextAwareTranslator,
    ContextBackendConfig,
)
from subvision.custom_glossary import CustomGlossaryManager
from subvision.glossary import clean_ocr_text, is_plausible_subtitle_text
from subvision.glossary_hub import CommunityGlossaryHub
from subvision.updater import (
    UpdateInfo,
    compute_file_sha256,
    download_update_asset,
    is_newer_version,
    is_trusted_update_url,
    parse_semver,
    select_platform_asset,
)
from subvision.vocab_learner import VocabCard, VocabNotebook


class _FakeHTTPResponse(io.BytesIO):
    def __init__(self, data: bytes, headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _DummyLocalTranslator:
    def __init__(self, lang_pair: str = "en-tr"):
        self.lang_pair = lang_pair
        src, tgt = lang_pair.split("-", 1)
        self.source_lang = src
        self.target_lang = tgt
        self.is_ready = True
        self.active_compute_type = "int8"
        self.cpu_threads = 4
        self.model_dir = "/tmp/fake_model"
        self.cache_size = 0
        self.total_requests = 0
        self.cache_hits = 0
        self.unloaded = False
        self.reconfigured_to = None

    def try_fast_lookup(self, text: str):
        return None

    def translate_with_metrics(self, text: str):
        return f"LOCAL:{text}", 2.0, False

    def clear_cache(self) -> None:
        pass

    def reconfigure_threads(self, n: int) -> None:
        self.cpu_threads = int(n)
        self.reconfigured_to = int(n)

    def unload(self) -> None:
        self.unloaded = True
        self.is_ready = False


class TestPackagingAndVersionParity(unittest.TestCase):
    def test_version_parity_across_manifests(self) -> None:
        self.assertEqual(subvision.__version__, "1.6.0")
        self.assertEqual(studio_main.APP_VERSION, subvision.__version__)

        pyproject_path = os.path.join(REPO_ROOT, "pyproject.toml")
        with open(pyproject_path, "r", encoding="utf-8") as f:
            pyproject_text = f.read()
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_text)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1), subvision.__version__)

    def test_build_exe_embeds_every_module_and_glossary(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "build_exe_mod", os.path.join(REPO_ROOT, "scripts", "build_exe.py")
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        embedded = mod.discover_embedded_files(REPO_ROOT)
        embedded_paths = {src for src, _ in embedded}

        for fname in os.listdir(os.path.join(REPO_ROOT, "subvision")):
            if fname.endswith(".py"):
                self.assertIn(f"subvision/{fname}", embedded_paths)

        for fname in os.listdir(os.path.join(REPO_ROOT, "glossaries")):
            if fname.endswith(".json"):
                self.assertIn(f"glossaries/{fname}", embedded_paths)

        csharp_map = mod.build_csharp_embedded_map(embedded)
        self.assertIn("res_language_packs.py", csharp_map)
        self.assertIn("res_vocab_learner.py", csharp_map)
        self.assertIn("res_elden_ring.json", csharp_map)


class TestCustomGlossaryAndMultilingual(unittest.TestCase):
    def test_distinct_anchors_and_backreference_safe_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_path = os.path.join(tmpdir, "backref_test.json")
            with open(pack_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": "Backref Test",
                        "term_replacements": {
                            "Alpha": r"Grup \1 Örneği",
                            "Beta": r"Bölüm \g<0>",
                            "Gamma": "Gama",
                        },
                    },
                    f,
                )
            mgr = CustomGlossaryManager(extra_dirs=[tmpdir])
            mgr.set_active_pack("backref_test")

            src = "Alpha met Beta near Gamma."
            protected, placeholders = mgr.protect_terms(src)
            self.assertEqual(len(placeholders), 3)
            # Ensure no two placeholders share a 3-char prefix (no_repeat_ngram_size=3 safety)
            prefixes = {tok[:3] for tok in placeholders}
            self.assertEqual(len(prefixes), 3)
            self.assertNotIn("SVTERM", protected)

            restored = mgr.restore_terms(protected, placeholders)
            self.assertIn(r"Grup \1 Örneği", restored)
            self.assertIn(r"Bölüm \g<0>", restored)
            self.assertIn("Gama", restored)

    def test_unicode_ocr_cleaning_and_plausibility(self) -> None:
        self.assertTrue(is_plausible_subtitle_text("Überraschung! Wir gehen los.", source_lang="de"))
        self.assertTrue(is_plausible_subtitle_text("Привет, как дела?", source_lang="ru"))
        self.assertTrue(is_plausible_subtitle_text("こんにちは、世界！", source_lang="ja"))
        self.assertIn("Überraschung", clean_ocr_text("Überraschung! [SFX]", source_lang="de"))
        self.assertIn("Привет", clean_ocr_text("Привет, мир!", source_lang="ru"))
        self.assertIn("世界", clean_ocr_text("こんにちは世界", source_lang="ja"))


class TestContextAwareTranslatorHardening(unittest.TestCase):
    def test_delegation_cpu_threads_and_unload(self) -> None:
        local = _DummyLocalTranslator()
        ctx = ContextAwareTranslator(local_translator=local)

        ctx.set_cpu_threads(2)
        self.assertEqual(local.reconfigured_to, 2)
        self.assertEqual(ctx.cpu_threads, 2)

        ctx.cpu_threads = 6
        self.assertEqual(local.cpu_threads, 6)

        ctx.unload()
        self.assertTrue(local.unloaded)
        self.assertFalse(ctx.is_ready)

    def test_gemini_uses_header_not_query_and_scrubs_errors(self) -> None:
        secret = "AIzaSySUPER_SECRET_TEST_KEY_999"
        local = _DummyLocalTranslator(lang_pair="en-de")
        ctx = ContextAwareTranslator(
            local_translator=local,
            config=ContextBackendConfig(backend=BACKEND_GEMINI, api_key=secret),
        )

        captured = {}

        def fake_post(url, payload, headers=None):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = dict(headers or {})
            return {"candidates": [{"content": {"parts": [{"text": "Bleib bei mir."}]}}]}

        with patch.object(ctx, "_http_post_json", side_effect=fake_post):
            tr, _, cached = ctx.translate_with_metrics("Stay with me.")
        self.assertEqual(tr, "Bleib bei mir.")
        self.assertFalse(cached)
        self.assertNotIn(secret, captured["url"])
        self.assertNotIn("?key=", captured["url"])
        self.assertEqual(captured["headers"].get("x-goog-api-key"), secret)
        # Dynamic prompt targets German for en-de
        sys_txt = captured["payload"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("German", sys_txt)

        # Error scrubbing ensures secret never leaks into last_error or test_connection
        with patch.object(
            ctx, "_http_post_json", side_effect=RuntimeError(f"HTTP 403 for key={secret}")
        ):
            ok, msg = ctx.test_connection()
        self.assertFalse(ok)
        self.assertNotIn(secret, msg)
        self.assertIn("[REDACTED]", msg)

    def test_deepl_dynamic_lang_and_http_scheme_guard(self) -> None:
        local = _DummyLocalTranslator(lang_pair="ja-en")
        ctx = ContextAwareTranslator(
            local_translator=local,
            config=ContextBackendConfig(backend=BACKEND_DEEPL, api_key="deepl-secret"),
        )
        captured = {}

        def fake_post(url, payload, headers=None):
            captured["payload"] = payload
            return {"translations": [{"text": "Hello world"}]}

        with patch.object(ctx, "_http_post_json", side_effect=fake_post):
            tr, _, _ = ctx.translate_with_metrics("こんにちは")
        self.assertEqual(tr, "Hello world")
        self.assertEqual(captured["payload"]["source_lang"], "JA")
        self.assertEqual(captured["payload"]["target_lang"], "EN-US")

        # Reject insecure non-localhost HTTP endpoints
        ctx_bad = ContextAwareTranslator(
            local_translator=local,
            config=ContextBackendConfig(
                backend=BACKEND_OPENAI_COMPAT,
                endpoint="http://evil.example.com/v1/chat/completions",
                api_key="sk-test",
            ),
        )
        with self.assertRaises(ValueError):
            ctx_bad._http_post_json("http://evil.example.com/v1/chat/completions", {})

        # Reject non-HTTPS glossary hub URLs
        hub = CommunityGlossaryHub(local_dir=tempfile.gettempdir(), bundled_dir=tempfile.gettempdir())
        with self.assertRaises(ValueError):
            hub.install_pack("http://example.com/pack.json")


class TestUpdaterHardening(unittest.TestCase):
    def test_semver_prerelease_and_trusted_urls(self) -> None:
        self.assertEqual(parse_semver("v1.6.0"), (1, 6, 0, 1))
        self.assertTrue(is_newer_version("1.6.0-beta.2", "1.6.0-beta.1"))
        self.assertTrue(is_newer_version("1.6.0", "1.6.0-rc.1"))
        self.assertFalse(is_newer_version("1.6.0-beta.1", "1.6.0-beta.2"))

        self.assertTrue(is_trusted_update_url("https://api.github.com/repos/a/b/releases/latest"))
        self.assertTrue(
            is_trusted_update_url("https://objects.githubusercontent.com/release/pkg.dmg")
        )
        self.assertFalse(is_trusted_update_url("http://github.com/a/b"))
        self.assertFalse(is_trusted_update_url("https://evil.example.com/pkg.exe"))

    def test_linux_asset_selection_and_wrong_arch_rejection(self) -> None:
        assets = [
            {
                "name": "SubVisionAI-v1.6.0-macOS-arm64.dmg",
                "browser_download_url": "https://github.com/x/y/mac-arm64.dmg",
                "size": 100,
            },
            {
                "name": "SubVisionAI-v1.6.0-Linux-x86_64.tar.gz",
                "browser_download_url": "https://github.com/x/y/linux-x64.tar.gz",
                "size": 200,
            },
            {
                "name": "SHA256SUMS-Linux.txt",
                "browser_download_url": "https://github.com/x/y/SHA256SUMS-Linux.txt",
                "size": 50,
            },
        ]
        # Intel macOS must NOT pick arm64 DMG
        mac_intel = select_platform_asset(assets, platform_name="darwin", machine="x86_64")
        self.assertEqual(mac_intel[0], "")

        # Linux x86_64 picks tar.gz and Linux checksums
        lin_name, lin_url, _, lin_cs = select_platform_asset(
            assets, platform_name="linux", machine="x86_64"
        )
        self.assertEqual(lin_name, "SubVisionAI-v1.6.0-Linux-x86_64.tar.gz")
        self.assertEqual(lin_url, "https://github.com/x/y/linux-x64.tar.gz")
        self.assertEqual(lin_cs, "https://github.com/x/y/SHA256SUMS-Linux.txt")

    def test_download_update_asset_fail_closed(self) -> None:
        payload = b"trusted-installer-binary"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_file = os.path.join(tmpdir, "ref.bin")
            with open(tmp_file, "wb") as f:
                f.write(payload)
            good_hash = compute_file_sha256(tmp_file)

            # 1) Missing checksum_url -> fail closed
            info_no_cs = UpdateInfo(
                current_version="1.5.0",
                latest_version="1.6.0",
                is_update_available=True,
                release_url="https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/tag/v1.6.0",
                asset_name="SubVisionAI-Setup-v1.6.0.exe",
                asset_url="https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/download/v1.6.0/SubVisionAI-Setup-v1.6.0.exe",
                asset_size=len(payload),
                checksum_url="",
            )
            with self.assertRaises(RuntimeError):
                download_update_asset(info_no_cs, tmpdir)

            # 2) Checksum download failure -> fail closed
            info_cs = UpdateInfo(
                current_version="1.5.0",
                latest_version="1.6.0",
                is_update_available=True,
                release_url="https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/tag/v1.6.0",
                asset_name="SubVisionAI-Setup-v1.6.0.exe",
                asset_url="https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/download/v1.6.0/SubVisionAI-Setup-v1.6.0.exe",
                asset_size=len(payload),
                checksum_url="https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/download/v1.6.0/SHA256SUMS.txt",
            )

            def fail_cs_open(req, timeout=10.0):
                if "SHA256SUMS" in req.full_url:
                    raise OSError("checksum unreachable")
                return _FakeHTTPResponse(payload)

            with patch("urllib.request.urlopen", side_effect=fail_cs_open):
                with self.assertRaises(RuntimeError):
                    download_update_asset(info_cs, tmpdir)

            # 3) Valid SHA-256 succeeds cleanly
            sums_bytes = f"{good_hash}  SubVisionAI-Setup-v1.6.0.exe\n".encode("utf-8")

            def ok_open(req, timeout=10.0):
                if "SHA256SUMS" in req.full_url:
                    return _FakeHTTPResponse(sums_bytes)
                return _FakeHTTPResponse(payload)

            with patch("urllib.request.urlopen", side_effect=ok_open):
                out_path = download_update_asset(info_cs, tmpdir)
            self.assertTrue(os.path.isfile(out_path))


class TestVocabAndAudioHardening(unittest.TestCase):
    def test_vocab_corrupt_seen_count_batch_and_context_tr_search(self) -> None:
        card = VocabCard.from_dict({"word": "ambush", "seen_count": "not-an-int"})
        self.assertEqual(card.seen_count, 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "vocab.json")
            nb = VocabNotebook(storage_path=path)
            added = nb.add_cards_batch(
                words=["ambush", "canyon"],
                translation="pusu",
                context_en="Watch out for the ambush in the canyon!",
                context_tr="Kanyondaki pusuya dikkat et!",
                source="RDR2",
            )
            self.assertEqual(len(added), 2)
            # Search must match context_tr as well
            hits = nb.search("kanyondaki")
            self.assertEqual(len(hits), 2)

    def test_audio_downsample_and_non_en_whisper_model(self) -> None:
        import numpy as np

        sig_48k = np.sin(np.linspace(0, 20 * np.pi, 4800, dtype=np.float32))
        out_16k = _downsample_to_16k(sig_48k, 48000)
        self.assertEqual(out_16k.size, 1600)
        self.assertEqual(out_16k.dtype, np.float32)

        tr_ja = LiveAudioTranscriber(model_size="tiny.en", source_lang="ja")
        self.assertEqual(tr_ja.model_size, "tiny")
        self.assertEqual(tr_ja.source_lang, "ja")


class TestMainWindowHardeningOffscreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_stop_translation_perf_profile_and_context_window_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "user_settings.json")
            vocab_path = os.path.join(tmpdir, "vocab_notebook.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "context_window": 6,
                        "context_timeout_sec": 7.5,
                        "lang_pair": "en-tr",
                    },
                    f,
                )

            with (
                patch.object(studio_main, "CONFIG_PATH", cfg_path),
                patch.object(studio_main.MainWindow, "_start_model_loading", return_value=None),
                patch.object(studio_main.MainWindow, "check_for_updates_async", return_value=None),
                patch.object(studio_main.MainWindow, "_register_global_hotkeys", return_value=None),
                patch.object(studio_main.MainWindow, "_setup_system_tray", return_value=None),
                patch.object(
                    studio_main,
                    "VocabNotebook",
                    side_effect=lambda: VocabNotebook(storage_path=vocab_path),
                ),
            ):
                win = studio_main.MainWindow()
                try:
                    self.assertTrue(callable(win.stop_translation))
                    win.stop_translation(reset_ui=True)

                    # Changing perf profile must not crash with AttributeError on ContextAwareTranslator
                    idx_eco = win.combo_perf_profile.findData("eco")
                    self.assertGreaterEqual(idx_eco, 0)
                    win.combo_perf_profile.setCurrentIndex(idx_eco)
                    win._on_perf_profile_changed()

                    with open(cfg_path, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    self.assertEqual(saved["context_window"], 6)
                    self.assertAlmostEqual(saved["context_timeout_sec"], 7.5)
                    if os.name != "nt":
                        mode = os.stat(cfg_path).st_mode & 0o777
                        self.assertEqual(mode, 0o600)
                finally:
                    win._force_quit = True
                    win.overlay.close()
                    win.roi_selector.close()
                    win.close()


if __name__ == "__main__":
    unittest.main()
