"""
Unit tests for SubVision AI Multi-Language Pack Manager & Apple Silicon MPS Acceleration.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from subvision.language_packs import (
    DEFAULT_LANG_PAIR,
    LANGUAGE_PACKS,
    LanguagePack,
    LanguagePackManager,
)
from subvision.translator import (
    LocalEnTrTranslator,
    LocalSubtitleTranslator,
    detect_mps_available,
)


def _create_sized_file(path: str, size_bytes: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(b"\x00")


class TestLanguagePackManager(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.models_root = os.path.join(self._tmpdir.name, "models")
        os.makedirs(self.models_root, exist_ok=True)
        self.manager = LanguagePackManager(models_root=self.models_root)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_01_registry_and_listing(self) -> None:
        self.assertEqual(DEFAULT_LANG_PAIR, "en-tr")
        packs = self.manager.list_packs()
        self.assertEqual(len(packs), len(LANGUAGE_PACKS))
        pair_ids = {p.pair_id for p in packs}
        for expected in ("en-tr", "en-es", "en-de", "en-fr", "en-pt", "en-ru", "en-it", "ja-en"):
            self.assertIn(expected, pair_ids)

        en_tr = self.manager.get_pack("EN-TR")
        self.assertIsInstance(en_tr, LanguagePack)
        self.assertEqual(en_tr.hf_repo, "VoragoStudios/gct-opus-mt-tc-big-en-tr-ct2")
        self.assertEqual(en_tr.dir_name, "opus-en-tr-ct2")
        self.assertIsNone(self.manager.get_pack("xx-yy"))

    def test_02_directory_resolution_and_traversal_guard(self) -> None:
        de_dir = self.manager.get_pack_dir("en-de")
        self.assertEqual(de_dir, os.path.join(self.models_root, "opus-en-de-ct2"))

        tr_dir = self.manager.get_pack_dir("en-tr")
        self.assertEqual(tr_dir, os.path.join(self.models_root, "opus-en-tr-ct2"))

        with self.assertRaises(ValueError):
            self.manager.get_pack_dir("../escape")

    def test_03_install_detection_and_size_calculation(self) -> None:
        self.assertFalse(self.manager.is_installed("en-de"))
        self.assertEqual(self.manager.installed_size_mb("en-de"), 0.0)
        self.assertEqual(self.manager.list_installed_pair_ids(), [])

        pack = self.manager.get_pack("en-de")
        pack_dir = self.manager.get_pack_dir("en-de")

        # Undersized files must NOT count as installed
        for fname, min_bytes in pack.min_files.items():
            _create_sized_file(os.path.join(pack_dir, fname), max(1, min_bytes - 10))
        self.assertFalse(self.manager.is_installed("en-de"))

        # Exact/above minimum sizes must count as installed
        for fname, min_bytes in pack.min_files.items():
            _create_sized_file(os.path.join(pack_dir, fname), min_bytes)
        self.assertTrue(self.manager.is_installed("en-de"))
        self.assertEqual(self.manager.list_installed_pair_ids(), ["en-de"])

        size_mb = self.manager.installed_size_mb("en-de")
        expected_mb = round(sum(pack.min_files.values()) / (1024 * 1024), 2)
        self.assertAlmostEqual(size_mb, expected_mb, places=2)

    def test_04_safe_deletion(self) -> None:
        pack_dir = self.manager.get_pack_dir("en-fr")
        _create_sized_file(os.path.join(pack_dir, "model.bin"), 1024)
        self.assertTrue(os.path.isdir(pack_dir))

        self.assertTrue(self.manager.delete_pack("en-fr"))
        self.assertFalse(os.path.exists(pack_dir))
        # Deleting again returns False cleanly
        self.assertFalse(self.manager.delete_pack("en-fr"))

        # Invalid/traversal pair_id never deletes anything
        self.assertFalse(self.manager.delete_pack("../models"))
        self.assertTrue(os.path.isdir(self.models_root))


class TestTranslatorMultiLangAndMPS(unittest.TestCase):
    def test_01_alias_and_default_cpu_backwards_compatibility(self) -> None:
        self.assertIs(LocalSubtitleTranslator, LocalEnTrTranslator)
        tr = LocalEnTrTranslator(cpu_threads=1)
        self.assertEqual(tr.lang_pair, "en-tr")
        self.assertEqual(tr.requested_device, "cpu")
        self.assertEqual(tr.active_device, "cpu")
        self.assertTrue(tr.model_dir.endswith(os.path.join("models", "opus-en-tr-ct2")))

    def test_02_custom_lang_pair_en_de_cpu(self) -> None:
        tr = LocalEnTrTranslator(lang_pair="en-de", device="cpu", cpu_threads=1)
        self.assertEqual(tr.lang_pair, "en-de")
        self.assertEqual(tr.requested_device, "cpu")
        self.assertEqual(tr.active_device, "cpu")
        self.assertTrue(tr.model_dir.endswith(os.path.join("models", "opus-en-de-ct2")))
        self.assertEqual(tr.model_repo, LANGUAGE_PACKS["en-de"].hf_repo)

    def test_03_mps_runtime_error_falls_back_to_cpu(self) -> None:
        tr = LocalEnTrTranslator(
            lang_pair="en-de",
            device="mps",
            cpu_threads=1,
            compute_type_candidates=("int8", "float32"),
        )
        attempts = []

        class _FakeTranslator:
            def __init__(self, path, device, compute_type, intra_threads, inter_threads):
                attempts.append((device, compute_type))
                if device == "mps":
                    raise RuntimeError("MPS backend failed to initialize")

        with (
            patch("subvision.translator.detect_mps_available", return_value=True),
            patch("subvision.translator.ctranslate2.Translator", side_effect=_FakeTranslator),
        ):
            engine, active_type = tr._create_ct2_translator("/fake/model")

        self.assertIsNotNone(engine)
        self.assertEqual(tr.active_device, "cpu")
        self.assertEqual(active_type, "int8")
        self.assertEqual(
            attempts,
            [("mps", "float16"), ("mps", "default"), ("cpu", "int8")],
        )

    def test_04_mps_succeeds_when_available(self) -> None:
        tr = LocalEnTrTranslator(
            lang_pair="en-tr",
            device="mps",
            cpu_threads=1,
            compute_type_candidates=("int8", "float32"),
        )
        attempts = []

        class _FakeTranslator:
            def __init__(self, path, device, compute_type, intra_threads, inter_threads):
                attempts.append((device, compute_type))

        with (
            patch("subvision.translator.detect_mps_available", return_value=True),
            patch("subvision.translator.ctranslate2.Translator", side_effect=_FakeTranslator),
        ):
            engine, active_type = tr._create_ct2_translator("/fake/model")

        self.assertIsNotNone(engine)
        self.assertEqual(tr.active_device, "mps")
        self.assertEqual(active_type, "float16")
        self.assertEqual(attempts, [("mps", "float16")])

    def test_05_detect_mps_available_guards(self) -> None:
        with patch("subvision.translator.sys.platform", "win32"):
            self.assertFalse(detect_mps_available())

        with (
            patch("subvision.translator.sys.platform", "darwin"),
            patch("subvision.translator.platform.machine", return_value="x86_64"),
        ):
            self.assertFalse(detect_mps_available())

        with (
            patch("subvision.translator.sys.platform", "darwin"),
            patch("subvision.translator.platform.machine", return_value="arm64"),
            patch(
                "subvision.translator.ctranslate2.get_supported_compute_types",
                side_effect=RuntimeError("no mps"),
            ),
        ):
            self.assertFalse(detect_mps_available())

        with (
            patch("subvision.translator.sys.platform", "darwin"),
            patch("subvision.translator.platform.machine", return_value="arm64"),
            patch(
                "subvision.translator.ctranslate2.get_supported_compute_types",
                return_value={"float16", "float32"},
            ),
        ):
            self.assertTrue(detect_mps_available())


if __name__ == "__main__":
    unittest.main()
