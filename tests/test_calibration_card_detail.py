from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


SPEC = importlib.util.spec_from_file_location(
    "researchramp_calibration_card_detail_tests",
    ROOT / "app" / "server.py",
)
APP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = APP
SPEC.loader.exec_module(APP)


CARD = {
    "lemma": "model",
    "part_of_speech": "noun",
    "display_form": "model",
    "meaning_en": "n. a hypothetical description of a complex entity or process",
    "meaning_zh": "n. 模型, 模范, 模特儿",
    "context": (
        "Index Terms—Large language model, retrieval-augmented generation. "
        "We train a large model on domain text. The survey lists several models."
    ),
}


class FakeLearningStore:
    def mastered_word_forms(self) -> list[str]:
        return []


class FakeContinuousStore:
    def __init__(self, cards: dict[tuple[str, str], dict[str, object]]) -> None:
        self.cards = cards
        self.learning_store = FakeLearningStore()

    def _catalog_card(self, lemma: str, part_of_speech: str = "") -> dict[str, object]:
        card = self.cards.get((lemma.casefold(), part_of_speech.casefold()))
        if card is None:
            raise ValueError(f"简报词汇不在已完成的领域词卡目录中：{lemma}")
        return copy.deepcopy(card)


class FakeSession:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    def public_state(self) -> dict[str, object]:
        return copy.deepcopy(self.state)

    def personal_vocabulary_mastery(self, forms: list[str]) -> dict[str, object]:
        return {"mastered": len(forms)}


def context(store: object, state: dict[str, object]) -> object:
    return APP.DomainContext(
        domain_id="demo",
        display_name="Demo",
        workspace=None,
        session=FakeSession(state),
        continuous_store=store,
    )


def question_state() -> dict[str, object]:
    return {
        "mutation_revision": 4,
        "corpus_label": "demo",
        "recovery_notice": "",
        "answered": 3,
        "question_limit": 30,
        "complete": False,
        "word": {"lemma": "model", "part_of_speech": "noun"},
    }


def result_state() -> dict[str, object]:
    return {
        "mutation_revision": 4,
        "corpus_label": "demo",
        "recovery_notice": "",
        "answered": 30,
        "question_limit": 30,
        "complete": True,
        "word": None,
        "result": {
            "counts": {"total": 2, "likely_known": 1, "uncertain": 0, "likely_unknown": 1},
            "known_boundary": [{"lemma": "model", "part_of_speech": "noun"}],
            "remaining_boundary": [{"lemma": "unknownword", "part_of_speech": "noun"}],
        },
    }


class CardTextTests(unittest.TestCase):
    def test_a_short_gloss_is_only_normalized(self) -> None:
        self.assertEqual(
            APP.compact_card_text("  n. 模型,\n  模范  ", limit=140),
            "n. 模型, 模范",
        )

    def test_a_long_gloss_is_cut_with_an_ellipsis(self) -> None:
        compacted = APP.compact_card_text("a" * 400, limit=40)
        self.assertEqual(len(compacted), 40)
        self.assertTrue(compacted.endswith("…"))

    def test_the_example_is_the_sentence_that_uses_the_word(self) -> None:
        self.assertEqual(
            APP.example_sentence(CARD["context"], ("model",)),
            "We train a large model on domain text.",
        )

    def test_a_keyword_line_is_skipped_for_a_full_sentence(self) -> None:
        self.assertEqual(
            APP.example_sentence(CARD["context"], ("model",)),
            "We train a large model on domain text.",
        )

    def test_a_mid_sentence_fragment_is_skipped_for_a_full_sentence(self) -> None:
        context = (
            "Retrievers are usually built from published papers. "
            "2021) as default retrievers R to recall the top-k relevant documents. "
            "The default setting of the retriever follows the published configuration."
        )
        self.assertEqual(
            APP.example_sentence(context, ("default",)),
            "The default setting of the retriever follows the published configuration.",
        )

    def test_a_keyword_line_is_still_used_when_nothing_else_matches(self) -> None:
        self.assertEqual(
            APP.example_sentence(
                "Index Terms—Large language model, retrieval-augmented generation.",
                ("model",),
            ),
            "Index Terms—Large language model, retrieval-augmented generation.",
        )

    def test_an_inflected_surface_form_still_matches(self) -> None:
        self.assertEqual(
            APP.example_sentence("Tail. The report mentions models briefly.", ("model",)),
            "The report mentions models briefly.",
        )

    def test_a_word_is_not_matched_inside_a_longer_word(self) -> None:
        self.assertEqual(
            APP.example_sentence("The start is near. The art of science.", ("art",)),
            "The art of science.",
        )

    def test_an_empty_context_has_no_example(self) -> None:
        self.assertEqual(APP.example_sentence("   ", ("model",)), "")

    def test_a_context_without_the_word_still_supplies_a_bounded_example(self) -> None:
        example = APP.example_sentence("z" * 400, ("model",), limit=60)
        self.assertEqual(len(example), 60)
        self.assertTrue(example.endswith("…"))


class CalibrationCardDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APP.AppRuntime(
            [context(None, question_state())],
            initial_domain_id="demo",
            initial_view="vocabulary",
        )

    def test_the_question_carries_the_reviewed_gloss_and_example(self) -> None:
        store = FakeContinuousStore({("model", "noun"): CARD})
        calibration = self.runtime.calibration_state(
            context(store, question_state())
        )

        word = calibration["word"]
        self.assertEqual(word["display_form"], "model")
        self.assertEqual(word["meaning_zh"], "n. 模型, 模范, 模特儿")
        self.assertEqual(
            word["meaning_en"], "n. a hypothetical description of a complex entity or process"
        )
        self.assertEqual(word["example"], "We train a large model on domain text.")

    def test_the_boundary_lists_carry_the_same_detail(self) -> None:
        store = FakeContinuousStore(
            {
                ("model", "noun"): CARD,
                ("unknownword", "noun"): {
                    "lemma": "unknownword",
                    "part_of_speech": "noun",
                    "display_form": "unknownword",
                    "meaning_en": "n. absent from the reviewed catalog",
                    "meaning_zh": "n. 目录中缺词",
                    "context": "An unknownword appears in this sentence.",
                },
            }
        )
        calibration = self.runtime.calibration_state(context(store, result_state()))

        known = calibration["result"]["known_boundary"][0]
        remaining = calibration["result"]["remaining_boundary"][0]
        self.assertEqual(known["meaning_zh"], "n. 模型, 模范, 模特儿")
        self.assertEqual(known["example"], "We train a large model on domain text.")
        self.assertEqual(remaining["meaning_zh"], "n. 目录中缺词")
        self.assertEqual(
            remaining["example"], "An unknownword appears in this sentence."
        )

    def test_a_word_missing_from_the_catalog_is_left_untouched(self) -> None:
        store = FakeContinuousStore({})
        calibration = self.runtime.calibration_state(context(store, question_state()))

        self.assertEqual(calibration["word"], {"lemma": "model", "part_of_speech": "noun"})

    def test_a_corpus_without_continuous_state_is_left_untouched(self) -> None:
        calibration = self.runtime.calibration_state(context(None, question_state()))

        self.assertEqual(calibration["word"], {"lemma": "model", "part_of_speech": "noun"})


class CardDetailUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.script = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    def test_the_question_front_stays_a_recall_prompt(self) -> None:
        self.assertIn('setText("word", calibration.word.display_form || calibration.word.lemma);', self.script)
        self.assertNotIn('setText("word", calibration.word.meaning_zh', self.script)

    def test_the_current_word_gets_its_gloss_and_example_behind_a_toggle(self) -> None:
        self.assertIn('id="answerDetail"', self.page)
        self.assertIn('id="answerDetailMeaningZh"', self.page)
        self.assertIn('id="answerDetailExample"', self.page)
        self.assertIn("显示答案", self.page)
        self.assertIn("function renderAnswerDetail(", self.script)
        self.assertIn("renderAnswerDetail(calibration.word);", self.script)
        self.assertIn(".answer-detail {", self.styles)
        self.assertIn(".answer-detail-toggle {", self.styles)

    def test_the_answer_never_belongs_to_the_word_before_it(self) -> None:
        self.assertNotIn("上一个词", self.page)
        self.assertNotIn("上一个词", self.script)
        self.assertNotIn("answerDetailWord", self.page)
        self.assertNotIn("answeredCard", self.script)
        self.assertNotIn("answerLabels", self.script)

    def test_every_question_starts_with_its_answer_collapsed(self) -> None:
        self.assertIn('class="answer-detail" hidden', self.page)
        self.assertIn("<summary id=\"answerDetailToggle\"", self.page)
        self.assertIn("block.open = false;", self.script)
        self.assertIn("block.hidden = !hasDetail;", self.script)

    def test_the_boundary_lists_render_the_gloss_and_example(self) -> None:
        self.assertIn('glossLine.className = "word-gloss";', self.script)
        self.assertIn('exampleLine.className = "word-example";', self.script)
        self.assertIn(".word-gloss {", self.styles)
        self.assertIn(".word-example {", self.styles)


if __name__ == "__main__":
    unittest.main()
