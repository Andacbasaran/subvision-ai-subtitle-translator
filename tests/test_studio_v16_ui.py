"""
SubVision AI v1.6.0 — Studio UI Integration & Offscreen PyQt6 Smoke Tests.
Verifies i18n keys, main.py v1.6.0 version & imports, language pair selector,
Apple Silicon MPS toggle, Glossary Hub button, and VocabNotebook / Anki TSV controls
without requiring network access or model downloads.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main as studio_main
from subvision.exporters import HistoryEntry
from subvision.i18n import TRANSLATIONS, LanguageManager
from subvision.language_packs import LanguagePackManager
from subvision.vocab_learner import VocabNotebook

_REQUIRED_V16_I18N_KEYS = (
    "lang_pair_title",
    "lang_pair_installed",
    "lang_pair_downloadable",
    "lang_pair_restart_hint",
    "mps_accel_label",
    "mps_accel_unavailable_note",
    "mps_accel_tooltip",
    "glossary_hub_btn",
    "glossary_hub_title",
    "glossary_hub_loading",
    "glossary_hub_empty",
    "glossary_hub_installed",
    "glossary_hub_available",
    "glossary_hub_install_btn",
    "glossary_hub_install_ok",
    "glossary_hub_install_err",
    "vocab_save_btn",
    "vocab_export_tsv_btn",
    "vocab_status_label",
    "vocab_saved_msg",
    "vocab_empty_history",
    "vocab_no_words",
    "vocab_empty_notebook",
    "vocab_export_ok",
)


class TestStudioV16I18nAndImports(unittest.TestCase):
    def test_v16_i18n_keys_exist_in_tr_and_en(self) -> None:
        for lang in ("tr", "en"):
            table = TRANSLATIONS[lang]
            mgr = LanguageManager(lang)
            for key in _REQUIRED_V16_I18N_KEYS:
                self.assertIn(key, table, f"Missing i18n key '{key}' in '{lang}'")
                self.assertTrue(
                    isinstance(table[key], str) and table[key].strip(),
                    f"Empty i18n value for '{key}' in '{lang}'",
                )
                self.assertEqual(mgr.t(key), table[key])

        self.assertEqual(LanguageManager("tr").t("vocab_status_label", count=7), "Vocab: 7")
        self.assertEqual(LanguageManager("en").t("vocab_status_label", count=12), "Vocab: 12")

    def test_main_version_and_v16_imports(self) -> None:
        self.assertEqual(studio_main.APP_VERSION, "1.6.0")
        self.assertIn("1.6.0", studio_main.APP_TITLE)
        self.assertIs(studio_main.LanguagePackManager, LanguagePackManager)
        self.assertIs(studio_main.VocabNotebook, VocabNotebook)
        self.assertTrue(callable(studio_main.CommunityGlossaryHub))
        self.assertTrue(callable(studio_main.extract_study_words))
        self.assertTrue(callable(studio_main.detect_mps_available))


class TestStudioV16MainWindowOffscreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_offscreen_mainwindow_v16_widgets_and_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "user_settings.json")
            vocab_path = os.path.join(tmpdir, "vocab_notebook.json")
            tsv_path = os.path.join(tmpdir, "study_deck.tsv")

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
                    # 1. Default settings & LocalEnTrTranslator wiring
                    self.assertEqual(win.settings.get("lang_pair"), "en-tr")
                    self.assertEqual(win.settings.get("nmt_device"), "cpu")
                    self.assertEqual(win._local_translator.lang_pair, "en-tr")
                    self.assertEqual(win._local_translator.requested_device, "cpu")

                    # 2. Language Pair dropdown populated from LanguagePackManager
                    expected_packs = LanguagePackManager().list_packs()
                    self.assertEqual(win.lang_pair_combo.count(), len(expected_packs))
                    self.assertEqual(win.lang_pair_combo.currentData(), "en-tr")

                    # Switch language pair and verify persistence
                    idx_de = win.lang_pair_combo.findData("en-de")
                    self.assertGreaterEqual(idx_de, 0)
                    win.lang_pair_combo.setCurrentIndex(idx_de)
                    self.assertEqual(win.settings["lang_pair"], "en-de")
                    self.assertTrue(os.path.isfile(cfg_path))
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        saved_cfg = json.load(f)
                    self.assertEqual(saved_cfg["lang_pair"], "en-de")
                    self.assertEqual(saved_cfg["nmt_device"], "cpu")

                    # 3. MPS checkbox defaults to CPU (unchecked) and toggles cleanly
                    self.assertFalse(win.chk_mps_accel.isChecked())
                    win._on_mps_accel_toggled(True)
                    self.assertEqual(win.settings["nmt_device"], "mps")
                    win._on_mps_accel_toggled(False)
                    self.assertEqual(win.settings["nmt_device"], "cpu")

                    # 4. Glossary Hub button exists next to combo_glossary_pack
                    self.assertTrue(hasattr(win, "btn_glossary_hub"))
                    self.assertTrue(hasattr(win, "combo_glossary_pack"))

                    # 5. VocabNotebook integration & word extraction from history
                    self.assertEqual(win.lbl_vocab_count.text(), "Vocab: 0")
                    win._history_entries.append(
                        HistoryEntry(
                            timestamp="12:00:00",
                            en_text="Detective: Everything points to a much bigger conspiracy.",
                            tr_text="Dedektif: Her şey çok daha büyük bir komploya işaret ediyor.",
                            elapsed_sec=1.5,
                        )
                    )
                    added = win._save_selected_history_words(silent=True)
                    self.assertGreaterEqual(added, 2)
                    self.assertIn(f"Vocab: {added}", win.lbl_vocab_count.text())

                    # 6. Export Anki TSV directly from the window's vocab_notebook
                    exported = win.vocab_notebook.export_anki_tsv(tsv_path)
                    self.assertEqual(exported, added)
                    self.assertTrue(os.path.isfile(tsv_path))
                    with open(tsv_path, "r", encoding="utf-8-sig") as f:
                        tsv_content = f.read()
                    self.assertIn("#separator:tab", tsv_content)
                    self.assertIn("conspiracy", tsv_content.lower())
                finally:
                    win._force_quit = True
                    win.overlay.close()
                    win.roi_selector.close()
                    win.close()


if __name__ == "__main__":
    unittest.main()
