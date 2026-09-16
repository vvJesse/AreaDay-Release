from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from vocabulary_calibration import LocalCalibrationSession  # noqa: E402


def word(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        lemma=f"word{index}",
        part_of_speech="noun",
        total_count=4,
        document_count=2,
        document_share=0.02,
        zipf=3.0,
        cefr_level=None,
        exam_tags=(),
    )


def write_completed_result(root: Path, total: int = 30) -> tuple[Path, bytes, bytes]:
    state_path = root / "vocabulary-calibration-session.json"
    answers = [
        {"lemma": f"word{index}", "response": "known"} for index in range(30)
    ]
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "vocabulary_snapshot_sha256": "fixture-snapshot-from-another-corpus",
                "answers": answers,
            }
        ),
        encoding="utf-8",
    )
    export_path = root / "personalized-vocabulary.tsv"
    export_path.write_text(
        "lemma\tclassification\n"
        + "".join(f"word{index}\tlikely_known\n" for index in range(total)),
        encoding="utf-8",
    )
    result = {
        "counts": {
            "total": total,
            "likely_known": total,
            "uncertain": 0,
            "likely_unknown": 0,
            "remaining_after_conservative_exclusion": 0,
            "important_boundary_protected": 0,
        },
        "threshold": {"selected_percent": 90},
        "importance": {"tiers": []},
        "known_boundary": [],
        "remaining_boundary": [],
        "answers": answers,
        "vocabulary_snapshot_sha256": "original-server-snapshot",
        "personalized_vocabulary_sha256": hashlib.sha256(
            export_path.read_bytes()
        ).hexdigest(),
    }
    result_path = root / "vocabulary-calibration-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return state_path, result_path.read_bytes(), export_path.read_bytes()


class VocabularyResultPersistenceTests(unittest.TestCase):
    def test_completed_result_is_frozen_and_remains_viewable_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path, result_before, export_before = write_completed_result(root)

            session = LocalCalibrationSession(
                [word(index) for index in range(700)],
                state_path,
                "changed local corpus",
            )

            self.assertTrue(session.public_state()["complete"])
            self.assertEqual(session.public_state()["result"]["counts"]["total"], 30)
            self.assertEqual(session.result_path.read_bytes(), result_before)
            self.assertEqual(session.export_path.read_bytes(), export_before)

    def test_parseable_result_ignores_hash_line_endings_and_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path, _, export_before = write_completed_result(root)
            (root / "personalized-vocabulary.tsv").write_bytes(
                export_before.replace(b"\n", b"\r\n")
            )
            result_path = root / "vocabulary-calibration-result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["counts"]["total"] = 29
            result_path.write_text(json.dumps(result), encoding="utf-8")

            session = LocalCalibrationSession(
                [word(index) for index in range(30)],
                state_path,
                "line ending changed",
            )

            self.assertTrue(session.public_state()["complete"])
            self.assertEqual(session.public_state()["result"]["counts"]["total"], 29)

    def test_strict_snapshot_check_restarts_when_the_corpus_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path, _, _ = write_completed_result(root)

            session = LocalCalibrationSession(
                [word(index) for index in range(30)],
                state_path,
                "strict workspace",
                enforce_snapshot_match=True,
            )

            self.assertFalse(session.public_state()["complete"])
            self.assertEqual(session.public_state()["answered"], 0)
            self.assertIn("请重新回答 30 道题", session.public_state()["recovery_notice"])

    def test_unloadable_completed_result_is_cleared_and_restarted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path, _, _ = write_completed_result(root)
            (root / "personalized-vocabulary.tsv").unlink()

            session = LocalCalibrationSession(
                [word(index) for index in range(30)],
                state_path,
                "damaged completed result",
            )

            self.assertFalse((root / "vocabulary-calibration-result.json").exists())
            self.assertFalse((root / "personalized-vocabulary.tsv").exists())
            self.assertEqual(json.loads(state_path.read_text())["answers"], [])
            self.assertIn("请重新回答 30 道题", session.public_state()["recovery_notice"])


if __name__ == "__main__":
    unittest.main()
