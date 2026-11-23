"""
Unit tests for SubVision AI's Language Learning Vocabulary Notebook & Rich Anki Deck module.
"""

import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from subvision.vocab_learner import (
    VocabCard,
    VocabNotebook,
    extract_study_words,
    highlight_word_html,
)


class TestExtractStudyWords(unittest.TestCase):
    def test_strips_colon_and_bracket_speaker_prefixes(self) -> None:
        words1 = extract_study_words("Arthur: Watch out for the ambush near the canyon!")
        self.assertNotIn("arthur", words1)
        self.assertEqual(words1, ["watch", "ambush", "near", "canyon"])

        words2 = extract_study_words("[Narrator] Vengeance echoed across the valley.")
        self.assertNotIn("narrator", words2)
        self.assertEqual(words2, ["vengeance", "echoed", "across", "valley"])

        words3 = extract_study_words("Dr. Octavius: Calibration completed successfully.")
        self.assertNotIn("octavius", words3)
        self.assertEqual(words3, ["calibration", "completed", "successfully"])

    def test_filters_stopwords_and_short_words(self) -> None:
        line = "I'm sure you can't stop the ambush, and they don't have a clue!"
        words = extract_study_words(line, min_length=3)
        self.assertEqual(words, ["stop", "ambush", "clue"])

        words_min5 = extract_study_words(line, min_length=5)
        self.assertEqual(words_min5, ["ambush"])

    def test_deduplicates_preserving_order(self) -> None:
        line = "Ambush! Prepare for an ambush, retreat and counter the AMBUSH!"
        words = extract_study_words(line)
        self.assertEqual(words, ["ambush", "prepare", "retreat", "counter"])

    def test_handles_contractions_and_empty_input(self) -> None:
        line = "I'm arriving at nine o'clock, don't forget the merchant's ledger."
        words = extract_study_words(line)
        self.assertNotIn("i'm", words)
        self.assertNotIn("don't", words)
        self.assertIn("arriving", words)
        self.assertIn("o'clock", words)
        self.assertIn("merchant's", words)
        self.assertIn("ledger", words)

        self.assertEqual(extract_study_words(""), [])
        self.assertEqual(extract_study_words("   "), [])


class TestHighlightWordHtml(unittest.TestCase):
    def test_case_insensitive_whole_word_bolding(self) -> None:
        sentence = "Ambush ahead! Avoid the ambush, they ambushed our scouts."
        highlighted = highlight_word_html(sentence, "ambush")
        self.assertEqual(
            highlighted,
            "<b>Ambush</b> ahead! Avoid the <b>ambush</b>, they ambushed our scouts.",
        )

    def test_html_escaping_prevents_xss(self) -> None:
        malicious = '<script>alert("ambush")</script> & <img src=x onerror=1> ambush!'
        highlighted = highlight_word_html(malicious, "ambush")
        self.assertNotIn("<script>", highlighted)
        self.assertNotIn("<img", highlighted)
        self.assertIn("&lt;script&gt;", highlighted)
        self.assertIn("&amp;", highlighted)
        self.assertIn("<b>ambush</b>", highlighted)

    def test_empty_sentence_or_word(self) -> None:
        self.assertEqual(highlight_word_html("", "ambush"), "")
        self.assertEqual(
            highlight_word_html("<b>raw</b>", ""),
            "&lt;b&gt;raw&lt;/b&gt;",
        )


class TestVocabNotebook(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.storage_path = os.path.join(self._tmpdir.name, "vocab_notebook.json")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_add_deduplicate_and_increment_seen_count(self) -> None:
        nb = VocabNotebook(storage_path=self.storage_path)
        card1 = nb.add_card(
            word="ambush",
            translation="pusu",
            context_en="Watch out for the ambush!",
            context_tr="Pusuya dikkat et!",
            source="Spider-Man 2",
        )
        self.assertEqual(card1.seen_count, 1)
        self.assertTrue(card1.added_at.endswith("Z"))
        self.assertEqual(len(nb.list_cards()), 1)

        # Re-add with different casing: increments seen_count and updates non-empty fields
        card2 = nb.add_card(
            word="AMBUSH",
            translation="pusu, baskın",
            context_en="",
            context_tr="",
            source="",
        )
        self.assertEqual(card2.seen_count, 2)
        self.assertEqual(card2.translation, "pusu, baskın")
        # Empty fields should preserve previous non-empty context/source
        self.assertEqual(card2.context_en, "Watch out for the ambush!")
        self.assertEqual(card2.context_tr, "Pusuya dikkat et!")
        self.assertEqual(card2.source, "Spider-Man 2")
        self.assertEqual(len(nb.list_cards()), 1)

        with self.assertRaises(ValueError):
            nb.add_card("   ", "boş", "ctx", "bağlam")

    def test_persistence_across_reload(self) -> None:
        nb1 = VocabNotebook(storage_path=self.storage_path)
        nb1.add_card(
            word="reckoning",
            translation="hesaplaşma",
            context_en="A day of reckoning is coming.",
            context_tr="Bir hesaplaşma günü geliyor.",
            source="Red Dead Redemption 2",
        )
        self.assertFalse(os.path.exists(f"{self.storage_path}.tmp"))
        self.assertTrue(os.path.isfile(self.storage_path))

        nb2 = VocabNotebook(storage_path=self.storage_path)
        cards = nb2.list_cards()
        self.assertEqual(len(cards), 1)
        self.assertIsInstance(cards[0], VocabCard)
        self.assertEqual(cards[0].word, "reckoning")
        self.assertEqual(cards[0].translation, "hesaplaşma")
        self.assertEqual(cards[0].source, "Red Dead Redemption 2")
        self.assertEqual(cards[0].seen_count, 1)

    def test_search_and_remove(self) -> None:
        nb = VocabNotebook(storage_path=self.storage_path)
        nb.add_card(
            word="ambush",
            translation="pusu",
            context_en="Watch out for the ambush!",
            context_tr="Pusuya dikkat et!",
            source="Spider-Man 2",
        )
        nb.add_card(
            word="relic",
            translation="yadigar",
            context_en="We recovered the ancient relic.",
            context_tr="Kadim yadigarı kurtardık.",
            source="God of War",
        )

        self.assertEqual(len(nb.search("AMBUSH")), 1)
        self.assertEqual(nb.search("yadigar")[0].word, "relic")
        self.assertEqual(nb.search("ancient")[0].word, "relic")
        self.assertEqual(nb.search("spider-man")[0].word, "ambush")
        self.assertEqual(len(nb.search("")), 2)

        self.assertTrue(nb.remove_card("AMBUSH"))
        self.assertFalse(nb.remove_card("nonexistent"))
        self.assertEqual([c.word for c in nb.list_cards()], ["relic"])

        # Removal persists to disk
        nb_reloaded = VocabNotebook(storage_path=self.storage_path)
        self.assertEqual([c.word for c in nb_reloaded.list_cards()], ["relic"])

    def test_export_anki_tsv_format(self) -> None:
        nb = VocabNotebook(storage_path=self.storage_path)
        nb.add_card(
            word="ambush",
            translation="pusu",
            context_en='They set an Ambush <near> the bridge!\tNow!',
            context_tr="Köprü <yakınında> pusu kurdular!",
            source="Spider-Man 2",
        )
        nb.add_card(
            word="covenant",
            translation="antlaşma",
            context_en="The covenant must never be broken.",
            context_tr="Antlaşma asla bozulmamalı.",
            source="",
        )

        out_path = os.path.join(self._tmpdir.name, "anki_deck.tsv")
        count = nb.export_anki_tsv(out_path, deck_tag="SubVisionAI")
        self.assertEqual(count, 2)

        # Verify UTF-8 BOM
        with open(out_path, "rb") as fb:
            raw_bytes = fb.read()
        self.assertTrue(raw_bytes.startswith(b"\xef\xbb\xbf"))

        text = raw_bytes.decode("utf-8-sig")
        lines = text.splitlines()
        self.assertEqual(lines[0], "#separator:tab")
        self.assertEqual(lines[1], "#html:true")
        self.assertEqual(lines[2], "#tags column:4")
        self.assertEqual(len(lines), 5)

        row1 = lines[3].split("\t")
        self.assertEqual(len(row1), 4)
        self.assertEqual(
            row1[0],
            "<b>ambush</b><br><small>They set an <b>Ambush</b> &lt;near&gt; the bridge! Now!</small>",
        )
        self.assertEqual(
            row1[1],
            "pusu<br><small>Köprü &lt;yakınında&gt; pusu kurdular!</small>",
        )
        self.assertEqual(row1[2], "Spider-Man 2")
        self.assertEqual(row1[3], "SubVisionAI Spider-Man_2")

        row2 = lines[4].split("\t")
        self.assertEqual(len(row2), 4)
        self.assertEqual(row2[2], "")
        self.assertEqual(row2[3], "SubVisionAI")


if __name__ == "__main__":
    unittest.main()
