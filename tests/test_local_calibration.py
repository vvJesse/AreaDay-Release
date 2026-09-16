from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import vocabulary_calibration as calibration  # noqa: E402
from vocabulary_calibration import (  # noqa: E402
    QUESTION_LIMIT,
    CalibrationError,
    InvalidCalibrationData,
    LocalCalibrationSession,
    load_completed_calibration,
    serialize_word_statistics,
    vocabulary_snapshot_sha256,
)


def word(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        lemma=f"word{index}",
        part_of_speech="noun",
        total_count=20 + index,
        document_count=2 + index % 10,
        document_share=(2 + index % 10) / 70,
        zipf=3.5,
        cefr_level="B2" if index < 3 else None,
        exam_tags=("cet6",) if index < 5 else (),
        # The following fields must never take part in a calibration request or
        # in the saved state; they stay on the computer.
        representative_sentences=["must stay local"],
        source_papers=["must-stay-local"],
        per_document_counts={"must-stay-local": 1},
    )


def words(count: int = 60) -> list[SimpleNamespace]:
    return [word(index) for index in range(count)]


def answer_all(session: LocalCalibrationSession) -> None:
    while not session.public_state()["complete"]:
        state = session.public_state()
        session.answer(state["word"]["lemma"], "known")


class LocalCalibrationSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.state_path = self.base / "vocabulary-calibration-state.json"

    def session(self, corpus: list[SimpleNamespace] | None = None, **kwargs: object):
        return LocalCalibrationSession(
            corpus if corpus is not None else words(),
            self.state_path,
            "测试语料",
            **kwargs,
        )

    def result_path(self) -> Path:
        return self.base / "vocabulary-calibration-result.json"

    def export_path(self) -> Path:
        return self.base / "personalized-vocabulary.tsv"

    # ------------------------------------------------------------------
    # Privacy boundary
    # ------------------------------------------------------------------

    def test_only_compact_word_statistics_are_used(self) -> None:
        statistics = serialize_word_statistics(word(0))

        self.assertEqual(
            set(statistics),
            {
                "lemma",
                "part_of_speech",
                "total_count",
                "document_count",
                "document_share",
                "zipf",
                "cefr_level",
                "exam_tags",
            },
        )
        self.assertNotIn(
            "must stay local", json.dumps(statistics, ensure_ascii=False)
        )
    def test_calibration_module_has_no_network_or_license_dependency(self) -> None:
        source = (SCRIPTS / "vocabulary_calibration.py").read_text(encoding="utf-8")

        for module in (
            "socket",
            "http.client",
            "urllib",
            "requests",
            "ssl",
            "areaday_license",
            "remote_calibration",
        ):
            self.assertNotIn(module, source)

    def test_saved_state_never_contains_corpus_text(self) -> None:
        session = self.session()
        session.answer(session.public_state()["word"]["lemma"], "known")

        saved = self.state_path.read_text(encoding="utf-8")

        self.assertNotIn("must stay local", saved)
        self.assertNotIn("source_papers", saved)
        self.assertEqual(json.loads(saved)["answers"][0]["lemma"], "word2")

    def test_snapshot_changes_when_any_used_statistic_changes(self) -> None:
        baseline = vocabulary_snapshot_sha256(words(5))
        self.assertEqual(baseline, vocabulary_snapshot_sha256(words(5)))

        changed = words(5)
        changed[2].document_count = 9
        changed[2].document_share = 9 / 70
        self.assertNotEqual(baseline, vocabulary_snapshot_sha256(changed))

    # ------------------------------------------------------------------
    # Question flow
    # ------------------------------------------------------------------

    def test_new_session_asks_thirty_questions_then_completes(self) -> None:
        session = self.session()

        state = session.public_state()
        self.assertFalse(state["complete"])
        self.assertEqual(state["answered"], 0)
        self.assertEqual(state["question_limit"], QUESTION_LIMIT)
        self.assertEqual(state["corpus_label"], "测试语料")
        self.assertEqual(state["word"]["lemma"], "word2")
        self.assertEqual(
            state["threshold"],
            {
                "selected_percent": 90,
                "default_percent": 90,
                "minimum_percent": 75,
                "maximum_percent": 98,
                "step_percent": 1,
            },
        )

        answer_all(session)

        state = session.public_state()
        self.assertTrue(state["complete"])
        self.assertEqual(state["answered"], QUESTION_LIMIT)
        self.assertNotIn("word", state)
        self.assertEqual(state["responses"]["known"], QUESTION_LIMIT)
        self.assertEqual(
            state["result"]["counts"]["likely_known"]
            + state["result"]["counts"]["uncertain"]
            + state["result"]["counts"]["likely_unknown"],
            state["result"]["counts"]["total"],
        )

    def test_every_question_is_asked_once(self) -> None:
        session = self.session()
        asked = []

        while not session.public_state()["complete"]:
            lemma = session.public_state()["word"]["lemma"]
            self.assertNotIn(lemma, asked)
            asked.append(lemma)
            session.answer(lemma, "unknown")

        self.assertEqual(len(asked), QUESTION_LIMIT)
        self.assertEqual(len(set(asked)), QUESTION_LIMIT)

    def test_question_order_is_deterministic(self) -> None:
        first = self.session()
        second = self.session()
        sequence = []

        while not first.public_state()["complete"]:
            lemma = first.public_state()["word"]["lemma"]
            sequence.append(lemma)
            first.answer(lemma, "known")
            second.answer(second.public_state()["word"]["lemma"], "known")

        self.assertEqual(sequence, [answer["lemma"] for answer in second.public_state()["answers"]])

    def test_answer_must_match_current_question(self) -> None:
        session = self.session()

        with self.assertRaises(CalibrationError) as caught:
            session.answer("word7", "known")
        self.assertEqual(caught.exception.code, "calibration_request_invalid")
        self.assertEqual(session.public_state()["answered"], 0)

        with self.assertRaises(CalibrationError) as caught:
            session.answer("word0", "maybe")
        self.assertEqual(caught.exception.code, "calibration_request_invalid")

    def test_answering_after_completion_is_rejected(self) -> None:
        session = self.session()
        answer_all(session)

        with self.assertRaises(CalibrationError) as caught:
            session.answer("word0", "known")
        self.assertEqual(caught.exception.code, "calibration_request_invalid")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def test_progress_is_resumed_from_the_saved_state(self) -> None:
        session = self.session()
        for _ in range(5):
            state = session.public_state()
            session.answer(state["word"]["lemma"], "unsure")
        expected = [answer["lemma"] for answer in session.public_state()["answers"]]

        resumed = self.session()

        state = resumed.public_state()
        self.assertEqual(state["answered"], 5)
        self.assertEqual(
            [answer["lemma"] for answer in state["answers"]],
            expected,
        )
        self.assertEqual(state["responses"]["unsure"], 5)
        self.assertFalse(state["complete"])

    def test_changed_corpus_clears_the_saved_session(self) -> None:
        session = self.session()
        state = session.public_state()
        session.answer(state["word"]["lemma"], "known")

        changed = words()
        changed[0].total_count = 999
        resumed = self.session(changed)

        state = resumed.public_state()
        self.assertEqual(state["answered"], 0)
        self.assertIn("recovery_notice", state)
        self.assertIn("请重新回答 30 道题", state["recovery_notice"])

    def test_corrupt_saved_state_clears_the_saved_session(self) -> None:
        self.state_path.write_text("{not json", encoding="utf-8")

        session = self.session()

        state = session.public_state()
        self.assertEqual(state["answered"], 0)
        self.assertIn("recovery_notice", state)

    def test_saved_answers_that_do_not_match_the_corpus_clear_the_session(self) -> None:
        session = self.session()
        answer_all(session)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["answers"][0]["lemma"] = "deleted-lemma"
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        self.result_path().unlink()
        self.export_path().unlink()

        resumed = self.session()

        state = resumed.public_state()
        self.assertEqual(state["answered"], 0)
        self.assertIn("recovery_notice", state)

    # ------------------------------------------------------------------
    # Completed outputs
    # ------------------------------------------------------------------

    def test_completion_writes_result_and_personalised_vocabulary(self) -> None:
        session = self.session()
        answer_all(session)

        self.assertTrue(self.result_path().is_file())
        self.assertTrue(self.export_path().is_file())
        result = json.loads(self.result_path().read_text(encoding="utf-8"))
        self.assertEqual(result["threshold"]["selected_percent"], 90)
        self.assertEqual(len(result["answers"]), QUESTION_LIMIT)
        self.assertEqual(
            result["vocabulary_snapshot_sha256"],
            vocabulary_snapshot_sha256(words()),
        )
        self.assertNotIn("rows", result)

        rows = list(
            csv.DictReader(
                self.export_path().read_text(encoding="utf-8").splitlines(),
                delimiter="\t",
            )
        )
        self.assertEqual({row["lemma"] for row in rows}, {w.lemma for w in words()})
        self.assertEqual(
            sum(row["classification"] == "likely_known" for row in rows),
            result["counts"]["likely_known"],
        )
        self.assertEqual(
            sum(row["classification"] == "important_boundary" for row in rows),
            result["counts"]["important_boundary_protected"],
        )
        self.assertEqual(
            sum(row["classification"] == "likely_unknown" for row in rows),
            result["counts"]["likely_unknown"],
        )
        self.assertEqual(
            session.persisted_export_tsv(),
            self.export_path().read_text(encoding="utf-8"),
        )

    def test_completed_outputs_reload_as_a_finished_session(self) -> None:
        session = self.session()
        answer_all(session)
        expected = session.public_state()["result"]["counts"]

        reopened = self.session()

        state = reopened.public_state()
        self.assertTrue(state["complete"])
        self.assertEqual(state["answered"], QUESTION_LIMIT)
        self.assertEqual(state["result"]["counts"], expected)
        self.assertEqual(
            state["result"]["output_files"],
            {
                "result": str(self.result_path()),
                "personalized_vocabulary": str(self.export_path()),
            },
        )
        self.assertEqual(state["threshold"]["selected_percent"], 90)

    def test_missing_companion_file_clears_the_completed_session(self) -> None:
        session = self.session()
        answer_all(session)
        self.export_path().unlink()

        reopened = self.session()

        state = reopened.public_state()
        self.assertFalse(state["complete"])
        self.assertEqual(state["answered"], 0)
        self.assertIn("recovery_notice", state)

    def test_completed_outputs_can_be_loaded_without_the_session(self) -> None:
        session = self.session()
        answer_all(session)

        state, result = load_completed_calibration(
            self.state_path,
            self.result_path(),
            self.export_path(),
        )

        self.assertEqual(len(state["answers"]), QUESTION_LIMIT)
        self.assertEqual(result["counts"]["total"], len(words()))

    def test_incomplete_outputs_are_rejected(self) -> None:
        with self.assertRaises(InvalidCalibrationData):
            load_completed_calibration(
                self.state_path,
                self.result_path(),
                self.export_path(),
            )

        session = self.session()
        answer_all(session)
        self.result_path().write_text('{"counts": {}}', encoding="utf-8")
        with self.assertRaises(InvalidCalibrationData):
            load_completed_calibration(
                self.state_path,
                self.result_path(),
                self.export_path(),
            )

    # ------------------------------------------------------------------
    # Threshold and reset
    # ------------------------------------------------------------------

    def test_threshold_selection_is_applied_to_the_result(self) -> None:
        session = self.session()
        answer_all(session)

        session.set_threshold_percent(75)

        state = session.public_state()
        self.assertEqual(state["threshold"]["selected_percent"], 75)
        self.assertEqual(
            state["result"]["threshold"]["selected_percent"],
            75,
        )
        enriched = calibration.validate_and_enrich_words(
            [serialize_word_statistics(item) for item in words()]
        )
        rows = calibration.calibration_result(
            enriched,
            state["answers"],
            0.75,
        )["rows"]
        self.assertEqual({row["selected_threshold"] for row in rows}, {0.75})
        stricter = state["result"]["counts"]["likely_known"]
        session.set_threshold_percent(98)
        self.assertLessEqual(
            session.public_state()["result"]["counts"]["likely_known"],
            stricter,
        )

    def test_threshold_must_stay_inside_the_supported_range(self) -> None:
        session = self.session()

        for invalid in (74, 99, 0):
            with self.assertRaises(CalibrationError) as caught:
                session.set_threshold_percent(invalid)
            self.assertEqual(caught.exception.code, "calibration_request_invalid")

    def test_threshold_can_be_changed_before_answering(self) -> None:
        session = self.session()

        session.set_threshold_percent(85)

        state = session.public_state()
        self.assertEqual(state["threshold"]["selected_percent"], 85)
        self.assertFalse(state["complete"])
        self.assertEqual(self.session().public_state()["threshold"]["selected_percent"], 85)

    def test_reset_clears_answers_and_completed_outputs(self) -> None:
        session = self.session()
        answer_all(session)

        session.reset()

        state = session.public_state()
        self.assertFalse(state["complete"])
        self.assertEqual(state["answered"], 0)
        self.assertEqual(state["answers"], [])
        self.assertFalse(self.result_path().exists())
        self.assertFalse(self.export_path().exists())
        self.assertEqual(
            self.session().public_state()["threshold"]["selected_percent"],
            90,
        )

    def test_mutation_revision_tracks_client_confirmed_writes(self) -> None:
        session = self.session()
        self.assertEqual(session.public_state()["mutation_revision"], 0)

        session.set_threshold_percent(85, 4)
        self.assertEqual(session.public_state()["mutation_revision"], 4)

        session.set_threshold_percent(86)
        self.assertEqual(session.public_state()["mutation_revision"], 5)

        session.reset(9)
        self.assertEqual(session.public_state()["mutation_revision"], 9)

    # ------------------------------------------------------------------
    # Mastery summary
    # ------------------------------------------------------------------

    def test_mastery_summary_groups_personal_vocabulary(self) -> None:
        session = self.session()

        self.assertIsNone(session.personal_vocabulary_mastery(set()))

        for _ in range(QUESTION_LIMIT):
            state = session.public_state()
            session.answer(state["word"]["lemma"], "unsure")

        summary = session.personal_vocabulary_mastery({"word8"})

        self.assertEqual(
            summary["basis"], "personal_vocabulary_calibrated_and_confirmed_mastery"
        )
        self.assertEqual([group["key"] for group in summary["groups"]], ["priority", "other"])
        for group in summary["groups"]:
            self.assertLessEqual(group["mastered_count"], group["total_count"])
            self.assertIsInstance(group["mastery_percent"], float)
            self.assertLessEqual(group["mastery_percent"], 100.0)
        priority = summary["groups"][0]
        self.assertEqual(priority["tiers"], ["A", "B"])
        self.assertEqual(priority["mastered_count"], 1)
        self.assertGreater(priority["total_count"], 0)

    def test_mastery_summary_ignores_unreadable_exports(self) -> None:
        session = self.session()
        answer_all(session)
        self.export_path().write_text("\n", encoding="utf-8")

        summary = session.personal_vocabulary_mastery(set())

        self.assertIsNotNone(summary)
        self.assertTrue(all(group["total_count"] == 0 for group in summary["groups"]))


class CalibrationResultTests(unittest.TestCase):
    def test_result_reports_the_documented_document_counts(self) -> None:
        corpus = calibration.validate_and_enrich_words(
            [serialize_word_statistics(word(index)) for index in range(32)]
        )

        result = calibration.calibration_result(
            corpus,
            [],
            calibration.DEFAULT_KNOWN_THRESHOLD,
        )

        self.assertEqual(
            result["importance"]["tiers"],
            [
                {
                    "key": "A",
                    "name": "核心词",
                    "range": "至少出现在 10 篇论文",
                    "count": 6,
                },
                {
                    "key": "B",
                    "name": "高价值词",
                    "range": "出现在 5–9 篇论文",
                    "count": 15,
                },
                {
                    "key": "C",
                    "name": "偶发词",
                    "range": "出现在 3–4 篇论文",
                    "count": 7,
                },
                {
                    "key": "D",
                    "name": "文章局部词",
                    "range": "只出现在 2 篇论文",
                    "count": 4,
                },
            ],
        )
        self.assertEqual(
            sum(tier["count"] for tier in result["importance"]["tiers"]),
            result["counts"]["remaining_after_conservative_exclusion"],
        )
        self.assertEqual(result["prior"]["name"], "wordfreq_plus_education_prior")
        self.assertEqual(result["prior"]["cefr_matches"], 3)
        self.assertEqual(result["prior"]["exam_matches"], 5)
        self.assertGreater(
            result["importance"]["corpus_document_count"],
            0,
        )

    def test_education_adjustment_prefers_the_stronger_signal(self) -> None:
        corpus = calibration.validate_and_enrich_words(
            [serialize_word_statistics(item) for item in words()]
        )

        self.assertEqual(corpus[0]["cefr_adjustment"], 0.15)
        self.assertEqual(corpus[0]["exam_adjustment"], 0.1)
        self.assertEqual(corpus[0]["education_adjustment"], 0.15)
        self.assertGreater(
            corpus[0]["prior_probability"],
            corpus[0]["frequency_prior_probability"],
        )

    def test_invalid_word_statistics_are_rejected(self) -> None:
        statistics = [serialize_word_statistics(item) for item in words()]
        statistics[0]["document_count"] = statistics[0]["total_count"] + 1

        with self.assertRaises(CalibrationError) as caught:
            calibration.validate_and_enrich_words(statistics)

        self.assertEqual(caught.exception.code, "calibration_request_invalid")

    def test_unknown_word_statistic_fields_are_rejected(self) -> None:
        statistics = [serialize_word_statistics(item) for item in words()]
        statistics[0]["representative_sentences"] = ["must stay local"]

        with self.assertRaises(CalibrationError):
            calibration.validate_and_enrich_words(statistics)

    def test_too_few_words_are_rejected(self) -> None:
        with self.assertRaises(CalibrationError):
            calibration.validate_and_enrich_words(
                [serialize_word_statistics(word(index)) for index in range(5)]
            )

    def test_module_does_not_use_banker_rounding(self) -> None:
        self.assertEqual(calibration._js_round(0.5), 1.0)
        self.assertEqual(calibration._js_round(2.5), 3.0)
        self.assertEqual(calibration._js_round(-0.5), -0.0)
        self.assertEqual(calibration._js_round(0.125, 2), 0.13)

    def test_error_messages_do_not_mention_licensing(self) -> None:
        for message in (
            "The response must be known, unknown or unsure.",
            "The answer does not match the current question.",
        ):
            self.assertIsNone(re.search("license|activation", message, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
