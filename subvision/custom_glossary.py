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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from subvision.hardware import get_app_base_dir, get_writable_data_dir


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
    """Discovers, loads, and applies external JSON glossary packs."""

    def __init__(self, extra_dirs: Optional[List[str]] = None):
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
        self.reload()

    def reload(self) -> Dict[str, GlossaryPack]:
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
        return self.packs

    def set_active_pack(self, pack_id: str) -> None:
        if pack_id in ("none", "all") or pack_id in self.packs:
            self.active_pack_id = pack_id
        else:
            self.active_pack_id = "none"

    def get_active_packs(self) -> List[GlossaryPack]:
        if self.active_pack_id == "none":
            return []
        if self.active_pack_id == "all":
            return list(self.packs.values())
        pack = self.packs.get(self.active_pack_id)
        return [pack] if pack else []

    def lookup_exact(self, text: str) -> Optional[str]:
        if not text:
            return None
        key = text.strip().lower()
        key_no_punct = key.rstrip(".!?")
        for pack in self.get_active_packs():
            if key in pack.exact_phrases:
                return pack.exact_phrases[key]
            if key_no_punct in pack.exact_phrases:
                return pack.exact_phrases[key_no_punct]
        return None

    def protect_terms(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Replaces `do_not_translate` and `term_replacements` occurrences with
        NMT-safe tokens (`SVTERM0`, `SVTERM1`, ...) before translation so the NMT
        model does not mangle lore names or custom game terminology.
        """
        if not text:
            return text, {}

        active = self.get_active_packs()
        if not active:
            return text, {}

        # Longest terms first to avoid partial shadowing (e.g. "Night City" before "Night")
        mapping_pairs: List[Tuple[str, str]] = []
        seen_lower = set()
        for pack in active:
            for src_term, dst_term in pack.term_replacements.items():
                if src_term.lower() not in seen_lower:
                    seen_lower.add(src_term.lower())
                    mapping_pairs.append((src_term, dst_term))
            for term in pack.do_not_translate:
                if term.lower() not in seen_lower:
                    seen_lower.add(term.lower())
                    mapping_pairs.append((term, term))

        mapping_pairs.sort(key=lambda pair: len(pair[0]), reverse=True)

        protected = text
        placeholders: Dict[str, str] = {}
        idx = 0
        for src_term, replacement in mapping_pairs:
            pattern = re.compile(rf"(?<!\w){re.escape(src_term)}(?!\w)", re.IGNORECASE)
            if pattern.search(protected):
                token = f"SVTERM{idx}X"
                idx += 1
                protected = pattern.sub(token, protected)
                placeholders[token] = replacement

        return protected, placeholders

    @staticmethod
    def restore_terms(translated_text: str, placeholders: Dict[str, str]) -> str:
        if not translated_text or not placeholders:
            return translated_text
        restored = translated_text
        for token, replacement in placeholders.items():
            restored = re.sub(re.escape(token), replacement, restored, flags=re.IGNORECASE)
        return restored
