"""
SubVision AI — Language Learning Vocabulary Notebook & Rich Anki Deck Module.

Allows learners watching games, movies, or shows to save vocabulary words along
with their bilingual subtitle context, search/manage their personal notebook,
and export rich HTML-formatted Anki TSV decks.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import os
import re
from typing import Dict, List, Optional

from subvision.hardware import get_writable_data_dir

try:
    from subvision.glossary import extract_speaker_and_body as _extract_speaker_and_body
except Exception:
    _extract_speaker_and_body = None


_RE_SPEAKER_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9 .'-]{0,24}:\s*")
_RE_ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_RE_TAG_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")

# Common high-frequency English stopwords & contractions excluded from study extraction
STOPWORDS = frozenset(
    {
        "about", "after", "again", "all", "also", "and", "any", "are", "aren't",
        "back", "because", "been", "before", "being", "but", "can", "can't",
        "cannot", "come", "could", "couldn't", "did", "didn't", "does",
        "doesn't", "doing", "don't", "done", "down", "even", "every", "for",
        "from", "get", "gets", "getting", "going", "gonna", "got", "gotta",
        "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he'd",
        "he'll", "he's", "her", "here", "here's", "hers", "herself", "him",
        "himself", "his", "how", "how's", "i'd", "i'll", "i'm", "i've", "into",
        "isn't", "it's", "its", "itself", "just", "know", "let", "let's", "like",
        "look", "made", "make", "many", "may", "maybe", "more", "most", "much",
        "must", "myself", "need", "never", "not", "now", "off", "okay", "one",
        "only", "other", "our", "ours", "out", "over", "own", "really", "right",
        "said", "same", "say", "see", "she", "she'd", "she'll", "she's",
        "should", "shouldn't", "some", "something", "still", "such", "sure",
        "take", "tell", "than", "that", "that's", "the", "their", "theirs",
        "them", "themselves", "then", "there", "there's", "these", "they",
        "they'd", "they'll", "they're", "they've", "thing", "things", "think",
        "this", "those", "through", "time", "too", "two", "under", "until",
        "very", "wanna", "want", "was", "wasn't", "way", "we'd", "we'll",
        "we're", "we've", "well", "were", "weren't", "what", "what's", "when",
        "where", "where's", "which", "while", "who", "who's", "whom", "why",
        "will", "with", "without", "won't", "would", "wouldn't", "yeah", "yes",
        "yet", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
        "yourself",
    }
)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sanitize_tsv_field(text: str) -> str:
    return (text or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _sanitize_anki_tag(tag: str) -> str:
    cleaned = _RE_TAG_UNSAFE.sub("_", (tag or "").strip()).strip("_")
    return cleaned


@dataclass
class VocabCard:
    word: str
    translation: str
    context_en: str
    context_tr: str
    source: str = ""
    added_at: str = ""
    seen_count: int = 1

    def __post_init__(self) -> None:
        self.word = (self.word or "").strip()
        self.translation = (self.translation or "").strip()
        self.context_en = (self.context_en or "").strip()
        self.context_tr = (self.context_tr or "").strip()
        self.source = (self.source or "").strip()
        if not self.added_at:
            self.added_at = _utc_now_iso()
        try:
            self.seen_count = max(1, int(self.seen_count))
        except (TypeError, ValueError):
            self.seen_count = 1

    def to_dict(self) -> Dict[str, object]:
        return {
            "word": self.word,
            "translation": self.translation,
            "context_en": self.context_en,
            "context_tr": self.context_tr,
            "source": self.source,
            "added_at": self.added_at,
            "seen_count": self.seen_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "VocabCard":
        return cls(
            word=str(data.get("word") or ""),
            translation=str(data.get("translation") or ""),
            context_en=str(data.get("context_en") or ""),
            context_tr=str(data.get("context_tr") or ""),
            source=str(data.get("source") or ""),
            added_at=str(data.get("added_at") or ""),
            seen_count=int(data.get("seen_count") or 1),
        )


def extract_study_words(en_line: str, min_length: int = 3) -> List[str]:
    """
    Extracts candidate vocabulary words from an English subtitle line.

    Strips speaker prefixes (e.g. "Arthur: ..." or "[Narrator] ..."), tokenizes
    English words including contractions, filters out high-frequency stopwords
    and words shorter than `min_length`, and returns deduplicated lowercase
    words in order of appearance.
    """
    if not en_line or not isinstance(en_line, str):
        return []

    cleaned = en_line.replace("’", "'").replace("‘", "'").strip()
    if not cleaned:
        return []

    body = cleaned
    if _extract_speaker_and_body is not None:
        speaker, extracted_body = _extract_speaker_and_body(cleaned)
        body = extracted_body
        if speaker is None:
            body = _RE_SPEAKER_PREFIX.sub("", body)
    else:
        body = _RE_SPEAKER_PREFIX.sub("", body)

    min_len = max(1, int(min_length))
    results: List[str] = []
    seen = set()

    for token in _RE_ENGLISH_WORD.findall(body):
        lower = token.lower()
        if len(lower) < min_len:
            continue
        if lower in STOPWORDS:
            continue
        if lower not in seen:
            seen.add(lower)
            results.append(lower)

    return results


def highlight_word_html(sentence: str, word: str) -> str:
    """
    HTML-escapes `sentence` safely and wraps case-insensitive whole-word
    occurrences of `word` in `<b>...</b>` tags for Anki readability.
    """
    if not sentence:
        return ""

    target = (word or "").strip()
    if not target:
        return html.escape(sentence, quote=True)

    pattern = re.compile(rf"(?<!\w){re.escape(target)}(?!\w)", re.IGNORECASE)
    parts: List[str] = []
    last_end = 0
    for match in pattern.finditer(sentence):
        parts.append(html.escape(sentence[last_end : match.start()], quote=True))
        parts.append(f"<b>{html.escape(match.group(0), quote=True)}</b>")
        last_end = match.end()
    parts.append(html.escape(sentence[last_end:], quote=True))
    return "".join(parts)


class VocabNotebook:
    """
    Persistent vocabulary notebook backed by an atomically-written JSON file,
    with case-insensitive deduplication, search, and rich Anki TSV export.
    """

    def __init__(self, storage_path: Optional[str] = None) -> None:
        if storage_path:
            self.storage_path = storage_path
        else:
            self.storage_path = os.path.join(
                get_writable_data_dir(), "vocab_notebook.json"
            )
        self._cards: Dict[str, VocabCard] = {}
        self.load()

    def load(self) -> None:
        self._cards.clear()
        if not os.path.isfile(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return

        items = raw.get("cards", []) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return

        for entry in items:
            if not isinstance(entry, dict):
                continue
            card = VocabCard.from_dict(entry)
            if card.word:
                self._cards[card.word.lower()] = card

    def save(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.storage_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        payload = {
            "version": 1,
            "cards": [card.to_dict() for card in self._cards.values()],
        }
        tmp_path = f"{self.storage_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
        os.replace(tmp_path, self.storage_path)

    def add_card(
        self,
        word: str,
        translation: str,
        context_en: str,
        context_tr: str,
        source: str = "",
    ) -> VocabCard:
        clean_word = (word or "").strip()
        if not clean_word:
            raise ValueError("word must be a non-empty string")

        key = clean_word.lower()
        clean_translation = (translation or "").strip()
        clean_context_en = (context_en or "").strip()
        clean_context_tr = (context_tr or "").strip()
        clean_source = (source or "").strip()

        existing = self._cards.get(key)
        if existing is not None:
            existing.seen_count += 1
            if clean_translation:
                existing.translation = clean_translation
            if clean_context_en:
                existing.context_en = clean_context_en
            if clean_context_tr:
                existing.context_tr = clean_context_tr
            if clean_source:
                existing.source = clean_source
            self.save()
            return existing

        card = VocabCard(
            word=clean_word,
            translation=clean_translation,
            context_en=clean_context_en,
            context_tr=clean_context_tr,
            source=clean_source,
        )
        self._cards[key] = card
        self.save()
        return card

    def remove_card(self, word: str) -> bool:
        key = (word or "").strip().lower()
        if not key or key not in self._cards:
            return False
        del self._cards[key]
        self.save()
        return True

    def search(self, query: str) -> List[VocabCard]:
        needle = (query or "").strip().lower()
        if not needle:
            return self.list_cards()

        matches: List[VocabCard] = []
        for card in self._cards.values():
            if (
                needle in card.word.lower()
                or needle in card.translation.lower()
                or needle in card.context_en.lower()
                or needle in card.source.lower()
            ):
                matches.append(card)
        return matches

    def list_cards(self) -> List[VocabCard]:
        return list(self._cards.values())

    def export_anki_tsv(
        self, output_path: str, deck_tag: str = "SubVisionAI"
    ) -> int:
        """
        Exports all notebook cards to a UTF-8-BOM Anki-ready tab-separated file
        with HTML formatting and tag metadata. Returns the number of exported cards.
        """
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        base_tag = _sanitize_anki_tag(deck_tag) or "SubVisionAI"
        cards = self.list_cards()

        lines = [
            "#separator:tab",
            "#html:true",
            "#tags column:4",
        ]

        for card in cards:
            escaped_word = html.escape(card.word, quote=True)
            highlighted_en = highlight_word_html(card.context_en, card.word)
            front = _sanitize_tsv_field(
                f"<b>{escaped_word}</b><br><small>{highlighted_en}</small>"
            )

            escaped_tr_meaning = html.escape(card.translation, quote=True)
            escaped_ctx_tr = html.escape(card.context_tr, quote=True)
            back = _sanitize_tsv_field(
                f"{escaped_tr_meaning}<br><small>{escaped_ctx_tr}</small>"
            )

            source_col = _sanitize_tsv_field(html.escape(card.source, quote=True))

            tags = [base_tag]
            source_tag = _sanitize_anki_tag(card.source)
            if source_tag and source_tag.lower() != base_tag.lower():
                tags.append(source_tag)
            tags_col = " ".join(tags)

            lines.append(f"{front}\t{back}\t{source_col}\t{tags_col}")

        with open(output_path, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

        return len(cards)
