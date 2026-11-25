"""
SubVision AI — Multi-Language Pack Registry & Storage Manager.

Manages downloadable CTranslate2/OPUS-MT neural translation language packs
under the user's writable application data directory.
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from subvision.hardware import get_writable_data_dir

DEFAULT_LANG_PAIR = "en-tr"

# Default minimum file sizes (bytes) for standard OPUS-MT CTranslate2 packs
_DEFAULT_CT2_MIN_FILES: Dict[str, int] = {
    "config.json": 200,
    "shared_vocabulary.json": 100_000,
    "source.spm": 100_000,
    "target.spm": 100_000,
    "model.bin": 10_000_000,
}

# Exact integrity thresholds for the primary EN -> TR big model (~227 MB)
_EN_TR_MIN_FILES: Dict[str, int] = {
    "config.json": 200,
    "shared_vocabulary.json": 500_000,
    "source.spm": 400_000,
    "target.spm": 400_000,
    "model.bin": 210_000_000,
}


def has_valid_ct2_vocabulary(pack_dir: str, shared_min_bytes: int = 100_000) -> bool:
    """
    Validates CTranslate2 vocabulary files inside `pack_dir`.
    Accepts either `shared_vocabulary.json` or the split pair
    `source_vocabulary.json` + `target_vocabulary.json`.
    """
    shared_path = os.path.join(pack_dir, "shared_vocabulary.json")
    try:
        if os.path.isfile(shared_path) and os.path.getsize(shared_path) >= shared_min_bytes:
            return True
    except OSError:
        pass

    split_min = max(1, min(50_000, shared_min_bytes // 2))
    src_vocab = os.path.join(pack_dir, "source_vocabulary.json")
    tgt_vocab = os.path.join(pack_dir, "target_vocabulary.json")
    try:
        if (
            os.path.isfile(src_vocab)
            and os.path.isfile(tgt_vocab)
            and os.path.getsize(src_vocab) >= split_min
            and os.path.getsize(tgt_vocab) >= split_min
        ):
            return True
    except OSError:
        pass
    return False


@dataclass(frozen=True)
class LanguagePack:
    """Metadata and integrity requirements for an offline translation model pack."""

    pair_id: str
    source_lang: str
    target_lang: str
    display_name: str
    hf_repo: str
    dir_name: str
    approx_size_mb: int
    min_files: Dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_CT2_MIN_FILES))


LANGUAGE_PACKS: Dict[str, LanguagePack] = {
    "en-tr": LanguagePack(
        pair_id="en-tr",
        source_lang="en",
        target_lang="tr",
        display_name="English → Turkish (Türkçe)",
        hf_repo="VoragoStudios/gct-opus-mt-tc-big-en-tr-ct2",
        dir_name="opus-en-tr-ct2",
        approx_size_mb=227,
        min_files=dict(_EN_TR_MIN_FILES),
    ),
    "en-es": LanguagePack(
        pair_id="en-es",
        source_lang="en",
        target_lang="es",
        display_name="English → Spanish (Español)",
        hf_repo="Helsinki-NLP/opus-mt-en-es",
        dir_name="opus-en-es-ct2",
        approx_size_mb=155,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
    "en-de": LanguagePack(
        pair_id="en-de",
        source_lang="en",
        target_lang="de",
        display_name="English → German (Deutsch)",
        hf_repo="Helsinki-NLP/opus-mt-en-de",
        dir_name="opus-en-de-ct2",
        approx_size_mb=150,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
    "en-fr": LanguagePack(
        pair_id="en-fr",
        source_lang="en",
        target_lang="fr",
        display_name="English → French (Français)",
        hf_repo="Helsinki-NLP/opus-mt-en-fr",
        dir_name="opus-en-fr-ct2",
        approx_size_mb=150,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
    "en-pt": LanguagePack(
        pair_id="en-pt",
        source_lang="en",
        target_lang="pt",
        display_name="English → Portuguese (Português)",
        hf_repo="Helsinki-NLP/opus-mt-tc-big-en-pt",
        dir_name="opus-en-pt-ct2",
        approx_size_mb=220,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
    "en-ru": LanguagePack(
        pair_id="en-ru",
        source_lang="en",
        target_lang="ru",
        display_name="English → Russian (Русский)",
        hf_repo="Helsinki-NLP/opus-mt-en-ru",
        dir_name="opus-en-ru-ct2",
        approx_size_mb=155,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
    "en-it": LanguagePack(
        pair_id="en-it",
        source_lang="en",
        target_lang="it",
        display_name="English → Italian (Italiano)",
        hf_repo="Helsinki-NLP/opus-mt-en-it",
        dir_name="opus-en-it-ct2",
        approx_size_mb=150,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
    "ja-en": LanguagePack(
        pair_id="ja-en",
        source_lang="ja",
        target_lang="en",
        display_name="Japanese → English (日本語 → EN)",
        hf_repo="Helsinki-NLP/opus-mt-ja-en",
        dir_name="opus-ja-en-ct2",
        approx_size_mb=155,
        min_files=dict(_DEFAULT_CT2_MIN_FILES),
    ),
}

_SAFE_PAIR_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class LanguagePackManager:
    """Discovers, validates, measures, and safely manages local language packs."""

    def __init__(self, models_root: Optional[str] = None):
        if models_root is not None:
            self.models_root = os.path.abspath(models_root)
        else:
            self.models_root = os.path.join(get_writable_data_dir(), "models")

    @staticmethod
    def _normalize_pair_id(pair_id: str) -> str:
        return (pair_id or "").strip().lower()

    def list_packs(self) -> List[LanguagePack]:
        """Returns all registered language packs."""
        return list(LANGUAGE_PACKS.values())

    def get_pack(self, pair_id: str) -> Optional[LanguagePack]:
        """Looks up a language pack by pair_id (case-insensitive)."""
        return LANGUAGE_PACKS.get(self._normalize_pair_id(pair_id))

    def get_pack_dir(self, pair_id: str) -> str:
        """Resolves the local storage directory for a given language pair."""
        norm = self._normalize_pair_id(pair_id)
        pack = LANGUAGE_PACKS.get(norm)
        if pack is not None:
            return os.path.join(self.models_root, pack.dir_name)

        if not _SAFE_PAIR_RE.match(norm):
            raise ValueError(f"Invalid language pair id: {pair_id!r}")
        return os.path.join(self.models_root, f"opus-{norm}-ct2")

    def is_installed(self, pair_id: str) -> bool:
        """Returns True if model.bin and all required pack files exist and meet min sizes."""
        try:
            pack_dir = self.get_pack_dir(pair_id)
        except ValueError:
            return False

        if not os.path.isdir(pack_dir):
            return False

        pack = self.get_pack(pair_id)
        required_files = pack.min_files if (pack and pack.min_files) else {"model.bin": 1}
        if "model.bin" not in required_files:
            required_files = {**required_files, "model.bin": 1}

        for fname, min_bytes in required_files.items():
            if fname == "shared_vocabulary.json":
                if not has_valid_ct2_vocabulary(pack_dir, shared_min_bytes=min_bytes):
                    return False
                continue
            fpath = os.path.join(pack_dir, fname)
            if not os.path.isfile(fpath):
                return False
            try:
                if os.path.getsize(fpath) < min_bytes:
                    return False
            except OSError:
                return False
        return True

    def installed_size_mb(self, pair_id: str) -> float:
        """Calculates total on-disk size in MB for the given language pack directory."""
        try:
            pack_dir = self.get_pack_dir(pair_id)
        except ValueError:
            return 0.0

        if not os.path.isdir(pack_dir):
            return 0.0

        total_bytes = 0
        for root, _dirs, files in os.walk(pack_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    if not os.path.islink(fpath):
                        total_bytes += os.path.getsize(fpath)
                except OSError:
                    continue
        return round(total_bytes / (1024 * 1024), 2)

    def delete_pack(self, pair_id: str) -> bool:
        """Safely deletes a language pack directory inside models_root."""
        try:
            pack_dir = self.get_pack_dir(pair_id)
        except ValueError:
            return False

        if not os.path.isdir(pack_dir):
            return False

        root_real = os.path.realpath(self.models_root)
        pack_real = os.path.realpath(pack_dir)
        try:
            common = os.path.commonpath([root_real, pack_real])
        except ValueError:
            return False

        if common != root_real or pack_real == root_real:
            return False

        shutil.rmtree(pack_real)
        return True

    def list_installed_pair_ids(self) -> List[str]:
        """Returns pair_ids of all registered language packs currently installed."""
        return [pack.pair_id for pack in self.list_packs() if self.is_installed(pack.pair_id)]
