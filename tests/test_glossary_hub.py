"""
Unit tests for Community Glossary Hub (`subvision/glossary_hub.py`)
and all bundled game glossary packs in `glossaries/`.
"""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from subvision.custom_glossary import CustomGlossaryManager
from subvision.glossary_hub import (
    GITHUB_GLOSSARIES_API,
    MAX_GLOSSARY_BYTES,
    CommunityGlossaryHub,
    RemoteGlossaryItem,
    safe_pack_filename,
    validate_glossary_payload,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GLOSSARIES_DIR = os.path.join(REPO_ROOT, "glossaries")

EXPECTED_ALL_PACKS = {
    "baldurs_gate3",
    "cyberpunk2077",
    "spiderman2",
    "elden_ring",
    "rdr2",
    "witcher3",
    "skyrim",
    "starfield",
    "persona5",
}

NEW_POPULAR_PACKS = {
    "elden_ring",
    "rdr2",
    "witcher3",
    "skyrim",
    "starfield",
    "persona5",
}


class _FakeHTTPResponse(io.BytesIO):
    """Minimal context-manager mock for urllib.request.urlopen."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class TestBundledGlossaryPacks(unittest.TestCase):
    def test_all_nine_packs_exist_and_validate(self):
        json_files = sorted(
            f for f in os.listdir(GLOSSARIES_DIR) if f.lower().endswith(".json")
        )
        self.assertGreaterEqual(len(json_files), 9)

        found_ids = set()
        for fname in json_files:
            self.assertEqual(safe_pack_filename(fname), fname)
            full_path = os.path.join(GLOSSARIES_DIR, fname)
            with open(full_path, "rb") as f:
                raw_bytes = f.read()
            payload = validate_glossary_payload(raw_bytes)
            self.assertIsInstance(payload["name"], str)
            self.assertTrue(payload["name"].strip())
            found_ids.add(os.path.splitext(fname)[0])

        self.assertTrue(EXPECTED_ALL_PACKS.issubset(found_ids))

    def test_all_packs_load_via_custom_glossary_manager(self):
        mgr = CustomGlossaryManager(extra_dirs=[GLOSSARIES_DIR])
        for pack_id in EXPECTED_ALL_PACKS:
            self.assertIn(pack_id, mgr.packs, f"Pack {pack_id!r} failed to load")
            pack = mgr.packs[pack_id]
            self.assertTrue(pack.name)
            self.assertTrue(pack.description)

    def test_six_new_packs_have_rich_turkish_content(self):
        mgr = CustomGlossaryManager(extra_dirs=[GLOSSARIES_DIR])
        for pack_id in NEW_POPULAR_PACKS:
            pack = mgr.packs[pack_id]
            self.assertGreaterEqual(len(pack.exact_phrases), 8, f"{pack_id} exact_phrases too small")
            self.assertLessEqual(len(pack.exact_phrases), 15, f"{pack_id} exact_phrases too large")
            self.assertGreaterEqual(len(pack.do_not_translate), 12, f"{pack_id} do_not_translate too small")
            self.assertLessEqual(len(pack.do_not_translate), 20, f"{pack_id} do_not_translate too large")
            self.assertGreaterEqual(len(pack.term_replacements), 10, f"{pack_id} term_replacements too small")
            self.assertLessEqual(len(pack.term_replacements), 15, f"{pack_id} term_replacements too large")

    def test_new_pack_runtime_lookup_and_term_protection(self):
        mgr = CustomGlossaryManager(extra_dirs=[GLOSSARIES_DIR])
        mgr.set_active_pack("elden_ring")
        self.assertEqual(mgr.lookup_exact("YOU DIED"), "ÖLDÜN")

        protected, placeholders = mgr.protect_terms(
            "The Tarnished rested at the Site of Grace in Limgrave."
        )
        self.assertNotIn("Tarnished", protected)
        self.assertNotIn("Site of Grace", protected)
        self.assertNotIn("Limgrave", protected)

        restored = mgr.restore_terms(protected, placeholders)
        self.assertIn("Lekeli", restored)
        self.assertIn("Lütuf Noktası", restored)
        self.assertIn("Limgrave", restored)


class TestSafePackFilename(unittest.TestCase):
    def test_valid_filenames(self):
        for valid in ("elden_ring.json", "rdr2.json", "cyberpunk-2077.json", "a.json"):
            self.assertEqual(safe_pack_filename(valid), valid)

    def test_rejects_path_traversal_and_invalid_names(self):
        invalid_names = [
            "../evil.json",
            "..\\evil.json",
            "/etc/passwd",
            "/etc/passwd.json",
            "subdir/pack.json",
            "bad name.json",
            "Uppercase.json",
            ".hidden.json",
            "-leadingdash.json",
            "pack.txt",
            "",
            "   ",
            "a" * 65 + ".json",
            "evil\x00.json",
        ]
        for bad in invalid_names:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    safe_pack_filename(bad)


class TestValidateGlossaryPayload(unittest.TestCase):
    def test_valid_minimal_and_full_payload(self):
        minimal = json.dumps({"name": "Test Game"}).encode("utf-8")
        self.assertEqual(validate_glossary_payload(minimal)["name"], "Test Game")

        full = json.dumps(
            {
                "name": "Full Game",
                "description": "Açıklama",
                "exact_phrases": {"hello": "Merhaba"},
                "do_not_translate": ["Hero"],
                "term_replacements": {"Sword": "Kılıç"},
            }
        ).encode("utf-8")
        parsed = validate_glossary_payload(full)
        self.assertEqual(parsed["exact_phrases"]["hello"], "Merhaba")

    def test_rejects_invalid_payloads(self):
        cases = [
            b"",
            b"{" + b" " * MAX_GLOSSARY_BYTES + b"}",
            b"\xff\xfeinvalid-utf8",
            b"not json at all",
            b'["list", "not", "dict"]',
            json.dumps({}).encode("utf-8"),
            json.dumps({"name": "   "}).encode("utf-8"),
            json.dumps({"name": 123}).encode("utf-8"),
            json.dumps({"name": "Ok", "description": 42}).encode("utf-8"),
            json.dumps({"name": "Ok", "exact_phrases": ["not", "dict"]}).encode("utf-8"),
            json.dumps({"name": "Ok", "exact_phrases": {"k": 123}}).encode("utf-8"),
            json.dumps({"name": "Ok", "do_not_translate": "not-a-list"}).encode("utf-8"),
            json.dumps({"name": "Ok", "do_not_translate": ["ok", 99]}).encode("utf-8"),
            json.dumps({"name": "Ok", "term_replacements": ["bad"]}).encode("utf-8"),
            json.dumps({"name": "Ok", "term_replacements": {"k": None}}).encode("utf-8"),
        ]
        for payload in cases:
            with self.subTest(size=len(payload), sample=payload[:40]):
                with self.assertRaises(ValueError):
                    validate_glossary_payload(payload)


class TestCommunityGlossaryHub(unittest.TestCase):
    def test_fetch_catalog_remote_success_and_is_local_marking(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_dir = os.path.join(tmp, "local")
            bundled_dir = os.path.join(tmp, "bundled")
            os.makedirs(local_dir)
            os.makedirs(bundled_dir)

            with open(os.path.join(bundled_dir, "elden_ring.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "Elden Ring"}, f)
            with open(os.path.join(local_dir, "rdr2.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "RDR2"}, f)

            api_entries = [
                {
                    "type": "file",
                    "name": "elden_ring.json",
                    "download_url": "https://raw.githubusercontent.com/example/elden_ring.json",
                    "size": 1234,
                    "sha": "sha1",
                },
                {
                    "type": "file",
                    "name": "rdr2.json",
                    "download_url": "https://raw.githubusercontent.com/example/rdr2.json",
                    "size": 2345,
                    "sha": "sha2",
                },
                {
                    "type": "file",
                    "name": "hades2.json",
                    "download_url": "https://raw.githubusercontent.com/example/hades2.json",
                    "size": 999,
                    "sha": "sha3",
                },
                {
                    "type": "dir",
                    "name": "nested_dir",
                },
                {
                    "type": "file",
                    "name": "../evil.json",
                    "download_url": "https://raw.githubusercontent.com/example/evil.json",
                    "size": 100,
                    "sha": "bad",
                },
            ]
            raw_resp = json.dumps(api_entries).encode("utf-8")

            captured_req = {}

            def fake_urlopen(req, timeout=None):
                captured_req["url"] = req.full_url
                captured_req["user_agent"] = req.get_header("User-agent")
                captured_req["timeout"] = timeout
                return _FakeHTTPResponse(raw_resp)

            hub = CommunityGlossaryHub(local_dir=local_dir, bundled_dir=bundled_dir)
            with patch("subvision.glossary_hub.urllib.request.urlopen", side_effect=fake_urlopen):
                items = hub.fetch_catalog(timeout=4.5)

            self.assertEqual(captured_req["url"], GITHUB_GLOSSARIES_API)
            self.assertEqual(captured_req["user_agent"], "SubVisionAI")
            self.assertEqual(captured_req["timeout"], 4.5)

            by_id = {item.pack_id: item for item in items}
            self.assertEqual(set(by_id.keys()), {"elden_ring", "rdr2", "hades2"})
            self.assertTrue(by_id["elden_ring"].is_local)
            self.assertTrue(by_id["rdr2"].is_local)
            self.assertFalse(by_id["hades2"].is_local)
            self.assertEqual(by_id["hades2"].size_bytes, 999)
            self.assertEqual(by_id["hades2"].sha, "sha3")

    def test_fetch_catalog_offline_and_rate_limit_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_dir = os.path.join(tmp, "local")
            bundled_dir = os.path.join(tmp, "bundled")
            os.makedirs(local_dir)
            os.makedirs(bundled_dir)

            with open(os.path.join(bundled_dir, "skyrim.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "Skyrim"}, f)
            with open(os.path.join(local_dir, "persona5.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "Persona 5"}, f)

            hub = CommunityGlossaryHub(local_dir=local_dir, bundled_dir=bundled_dir)

            with patch(
                "subvision.glossary_hub.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                items = hub.fetch_catalog()

            self.assertEqual([i.pack_id for i in items], ["persona5", "skyrim"])
            self.assertTrue(all(i.is_local for i in items))

            # Rate-limited HTTP 403 also falls back cleanly
            http_err = urllib.error.HTTPError(
                GITHUB_GLOSSARIES_API, 403, "rate limit", hdrs=None, fp=None
            )
            with patch("subvision.glossary_hub.urllib.request.urlopen", side_effect=http_err):
                items_403 = hub.fetch_catalog()
            self.assertEqual([i.pack_id for i in items_403], ["persona5", "skyrim"])

    def test_install_pack_from_item_and_url_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_dir = os.path.join(tmp, "local")
            bundled_dir = os.path.join(tmp, "bundled")
            hub = CommunityGlossaryHub(local_dir=local_dir, bundled_dir=bundled_dir)

            pack_payload = {
                "name": "Hades II",
                "description": "Yeraltı dünyası terimleri.",
                "exact_phrases": {"death to chronos": "Chronos'a ölüm"},
                "do_not_translate": ["Melinoë", "Hecate"],
                "term_replacements": {"Boon": "Lütuf"},
            }
            raw_bytes = json.dumps(pack_payload, ensure_ascii=False).encode("utf-8")

            item = RemoteGlossaryItem(
                pack_id="hades2",
                filename="hades2.json",
                download_url="https://raw.githubusercontent.com/example/hades2.json",
                size_bytes=len(raw_bytes),
                sha="abc123",
                is_local=False,
            )

            with patch(
                "subvision.glossary_hub.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(raw_bytes),
            ):
                installed_path = hub.install_pack(item)

            self.assertEqual(installed_path, os.path.join(local_dir, "hades2.json"))
            self.assertTrue(os.path.isfile(installed_path))
            self.assertFalse(os.path.exists(installed_path + ".tmp"))

            # Verify CustomGlossaryManager loads the newly installed pack
            mgr = CustomGlossaryManager(extra_dirs=[local_dir])
            self.assertIn("hades2", mgr.packs)
            mgr.set_active_pack("hades2")
            self.assertEqual(mgr.lookup_exact("death to chronos"), "Chronos'a ölüm")

            # Also test installing directly via URL string
            with patch(
                "subvision.glossary_hub.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(raw_bytes),
            ):
                url_path = hub.install_pack(
                    "https://raw.githubusercontent.com/example/hades2_alt.json"
                )
            self.assertEqual(url_path, os.path.join(local_dir, "hades2_alt.json"))
            self.assertTrue(os.path.isfile(url_path))

    def test_install_pack_rejects_invalid_json_and_bad_scheme(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_dir = os.path.join(tmp, "local")
            hub = CommunityGlossaryHub(local_dir=local_dir, bundled_dir=tmp)

            with patch(
                "subvision.glossary_hub.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(b"{broken json"),
            ):
                with self.assertRaises(ValueError):
                    hub.install_pack("https://example.com/broken.json")
            self.assertFalse(os.path.exists(os.path.join(local_dir, "broken.json")))
            self.assertFalse(os.path.exists(os.path.join(local_dir, "broken.json.tmp")))

            with self.assertRaises(ValueError):
                hub.install_pack("file:///etc/passwd", filename="passwd.json")

            with self.assertRaises(ValueError):
                hub.install_pack("https://example.com/ok.json", filename="../escape.json")


if __name__ == "__main__":
    unittest.main()
