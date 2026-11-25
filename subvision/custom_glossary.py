"""
SubVision AI — External JSON Custom Glossary & Do-Not-Translate Term Manager.

Allows users and open-source contributors to drop JSON glossary files into `glossaries/`
for specific games, TV shows, or domains. Each pack can define:
  - `exact_phrases`: Instant 0.003 ms exact English -> Turkish overrides
  - `do_not_translate`: Proper nouns / lore terms kept untouched through NMT
  - `term_replacements`: Custom English -> Turkish term mappings preserved via placeholders
"""

import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from subvision.hardware import get_app_base_dir, get_writable_data_dir

# Distinct per-occurrence NMT-safe anchor tokens.
# Each anchor has a unique 3-consonant prefix and non-zero 2-digit suffix so no two
# anchors share a SentencePiece 2-gram or 3-gram prefix (preventing CTranslate2
# `no_repeat_ngram_size=3` corruption such as `SVteroM0X`).
_ANCHOR_POOL: Tuple[str, ...] = (
    "ZXQ91", "KVW82", "JPM73", "BWF64", "QDX55", "VNG46", "YHR37", "KZT28",
    "WQP19", "MXJ15", "TLN63", "HCF84", "PRV25", "GJD56", "NKB77", "FZM38",
    "CXL41", "RQV52", "DWB69", "SJK74", "PFZ86", "MHT94", "BVQ13", "XGN27",
    "LKP35", "WCR48", "ZDY59", "QJB61", "KFX72", "VMN83", "THZ96", "GQP14",
)
_FALLBACK_CONSONANTS = "BCDFGHJKLMNPQRSTVWXZ"


def _make_anchor_token(index: int) -> str:
    if 0 <= index < len(_ANCHOR_POOL):
        return _ANCHOR_POOL[index]
    # Deterministic distinct fallback for sentences with >32 glossary terms
    n = index - len(_ANCHOR_POOL)
    base = len(_FALLBACK_CONSONANTS)
    c1 = _FALLBACK_CONSONANTS[(n * 7 + 3) % base]
    c2 = _FALLBACK_CONSONANTS[(n * 11 + 5) % base]
    c3 = _FALLBACK_CONSONANTS[(n * 13 + 9) % base]
    num = 11 + ((n * 17) % 88)
    return f"{c1}{c2}{c3}{num}"


@dataclass
class GlossaryPack:
    pack_id: str
    name: str
    description: str = ""
    exact_phrases: Dict[str, str] = field(default_factory=dict)
    do_not_translate: List[str] = field(default_factory=list)
    term_replacements: Dict[str, str] = field(default_factory=dict)
    source_path: str = ""


def _load_pack_file(path: str) -> Optional[GlossaryPack]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return None
        pack_id = os.path.splitext(os.path.basename(path))[0]
        name = str(raw.get("name") or pack_id).strip()
        desc = str(raw.get("description") or "").strip()
        exact = {
            str(k).strip().lower(): str(v).strip()
            for k, v in (raw.get("exact_phrases") or {}).items()
            if str(k).strip() and str(v).strip()
        }
        dnt = [
            str(item).strip()
            for item in (raw.get("do_not_translate") or [])
            if str(item).strip()
        ]
        repl = {
            str(k).strip(): str(v).strip()
            for k, v in (raw.get("term_replacements") or {}).items()
            if str(k).strip() and str(v).strip()
        }
        return GlossaryPack(
            pack_id=pack_id,
            name=name,
            description=desc,
            exact_phrases=exact,
            do_not_translate=dnt,
            term_replacements=repl,
            source_path=path,
        )
    except Exception:
        return None


class CustomGlossaryManager:
    """Discovers, loads, and applies external JSON glossary packs (thread-safe)."""

    def __init__(self, extra_dirs: Optional[List[str]] = None):
        self._lock = threading.RLock()
        self.search_dirs: List[str] = []
        candidates = [
            os.path.join(get_app_base_dir(), "glossaries"),
            os.path.join(get_writable_data_dir(), "glossaries"),
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.insert(1, os.path.join(meipass, "glossaries"))
        for d in (*candidates, *(extra_dirs or [])):
            norm = os.path.abspath(d)
            if norm not in self.search_dirs:
                self.search_dirs.append(norm)

        self.packs: Dict[str, GlossaryPack] = {}
        self.active_pack_id: str = "none"  # "none", "all", or specific pack_id
        self._compiled_pattern: Optional[re.Pattern] = None
        self._replacement_map: Dict[str, str] = {}
        self.reload()

    def _rebuild_compiled_terms_locked(self) -> None:
        """
        Precompiles a single longest-first alternation regex for the active pack(s).
        Must be called while holding `self._lock`.
        """
        active = self._get_active_packs_locked()
        if not active:
            self._compiled_pattern = None
            self._replacement_map = {}
            return

        mapping_pairs: List[Tuple[str, str]] = []
        replacement_map: Dict[str, str] = {}
        for pack in active:
            for src_term, dst_term in pack.term_replacements.items():
                low = src_term.lower()
                if low not in replacement_map:
                    replacement_map[low] = dst_term
                    mapping_pairs.append((src_term, dst_term))
            for term in pack.do_not_translate:
                low = term.lower()
                if low not in replacement_map:
                    replacement_map[low] = term
                    mapping_pairs.append((term, term))

        if not mapping_pairs:
            self._compiled_pattern = None
            self._replacement_map = {}
            return

        # Longest terms first to avoid partial shadowing (e.g. "Night City" before "Night")
        mapping_pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        alternation = "|".join(re.escape(src_term) for src_term, _ in mapping_pairs)
        self._compiled_pattern = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)
        self._replacement_map = replacement_map

    def _get_active_packs_locked(self) -> List[GlossaryPack]:
        if self.active_pack_id == "none":
            return []
        if self.active_pack_id == "all":
            return list(self.packs.values())
        pack = self.packs.get(self.active_pack_id)
        return [pack] if pack else []

    def reload(self) -> Dict[str, GlossaryPack]:
        with self._lock:
            self.packs.clear()
            for folder in self.search_dirs:
                if not os.path.isdir(folder):
                    continue
                for fname in sorted(os.listdir(folder)):
                    if not fname.lower().endswith(".json"):
                        continue
                    pack = _load_pack_file(os.path.join(folder, fname))
                    if pack is not None:
                        self.packs[pack.pack_id] = pack
            if self.active_pack_id not in ("none", "all") and self.active_pack_id not in self.packs:
                self.active_pack_id = "none"
            self._rebuild_compiled_terms_locked()
            return dict(self.packs)

    def set_active_pack(self, pack_id: str) -> None:
        with self._lock:
            if pack_id in ("none", "all") or pack_id in self.packs:
                self.active_pack_id = pack_id
            else:
                self.active_pack_id = "none"
            self._rebuild_compiled_terms_locked()

    def get_active_packs(self) -> List[GlossaryPack]:
        with self._lock:
            return self._get_active_packs_locked()

    def lookup_exact(self, text: str) -> Optional[str]:
        if not text:
            return None
        key = text.strip().lower()
        key_no_punct = key.rstrip(".!?")
        with self._lock:
            for pack in self._get_active_packs_locked():
                if key in pack.exact_phrases:
                    return pack.exact_phrases[key]
                if key_no_punct in pack.exact_phrases:
                    return pack.exact_phrases[key_no_punct]
        return None

    def protect_terms(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Replaces `do_not_translate` and `term_replacements` occurrences with
        distinct NMT-safe anchor tokens before translation so the NMT model does
        not mangle lore names or hit CTranslate2 `no_repeat_ngram_size=3` collisions.
        """
        if not text:
            return text, {}

        with self._lock:
            pattern = self._compiled_pattern
            replacement_map = self._replacement_map

        if pattern is None or not replacement_map:
            return text, {}

        placeholders: Dict[str, str] = {}
        text_lower = text.lower()
        idx_box = [0]

        def _alloc_anchor() -> str:
            while True:
                cand = _make_anchor_token(idx_box[0])
                idx_box[0] += 1
                if cand.lower() not in text_lower and cand not in placeholders:
                    return cand

        def _replace_match(match: re.Match) -> str:
            matched_lower = match.group(0).lower()
            replacement = replacement_map.get(matched_lower)
            if replacement is None:
                return match.group(0)
            token = _alloc_anchor()
            placeholders[token] = replacement
            return token

        protected = pattern.sub(_replace_match, text)
        return protected, placeholders

    @staticmethod
    def restore_terms(translated_text: str, placeholders: Dict[str, str]) -> str:
        """
        Restores placeholder anchors safely using a callable replacement so
        backreferences (e.g. `\\1`, `\\g<0>`) in custom glossary values never crash
        or corrupt output.
        """
        if not translated_text or not placeholders:
            return translated_text
        if len(placeholders) == 1:
            token, replacement = next(iter(placeholders.items()))
            return re.sub(
                re.escape(token),
                lambda _m, r=replacement: r,
                translated_text,
                flags=re.IGNORECASE,
            )

        lower_map = {tok.lower(): rep for tok, rep in placeholders.items()}
        alternation = "|".join(
            re.escape(tok) for tok in sorted(placeholders.keys(), key=len, reverse=True)
        )
        return re.sub(
            alternation,
            lambda m: lower_map[m.group(0).lower()],
            translated_text,
            flags=re.IGNORECASE,
        )
