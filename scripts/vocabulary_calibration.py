#!/usr/bin/env python3
"""Local 30-question vocabulary calibration.

The Bayesian word-knowledge model, the question selection and the result
classification all run in this process.  No corpus text, no word statistics and
no license leave the machine.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any


QUESTION_LIMIT = 30
DEFAULT_KNOWN_THRESHOLD = 0.9
MIN_KNOWN_THRESHOLD = 0.75
MAX_KNOWN_THRESHOLD = 0.98
IMPORTANT_BOUNDARY_MARGIN = 0.05
UNKNOWN_THRESHOLD = 0.3
THETA_GRID = tuple(-5 + index / 80 for index in range(801))
WORD_STATISTIC_FIELDS = (
    "lemma",
    "part_of_speech",
    "total_count",
    "document_count",
    "document_share",
    "zipf",
    "cefr_level",
    "exam_tags",
)
CEFR_ADJUSTMENTS = {"A1": 0.8, "A2": 0.6, "B1": 0.35, "B2": 0.15}
EXAM_ADJUSTMENTS = {"gk": 0.3, "cet4": 0.2, "cet6": 0.1}
CALIBRATION_RESPONSES = ("known", "unknown", "unsure")

SESSION_SCHEMA_VERSION = 1

RECOVERY_NOTICE = "本地校准数据无法读取，已清除。请重新回答 30 道题。"


class CalibrationError(RuntimeError):
    """A local calibration request could not be applied."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidCalibrationData(ValueError):
    """The local calibration files cannot be loaded as one completed result."""


def load_completed_calibration(
    state_path: Path,
    result_path: Path,
    export_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the fields used by the app, without byte-level consistency checks."""

    if not all(path.is_file() for path in (state_path, result_path, export_path)):
        raise InvalidCalibrationData("calibration output files are incomplete")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        with export_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not {"lemma", "classification"}.issubset(reader.fieldnames or []):
                raise InvalidCalibrationData(
                    "personalized vocabulary columns are invalid"
                )
            list(reader)
    except InvalidCalibrationData:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        csv.Error,
    ) as error:
        raise InvalidCalibrationData(
            "calibration output files cannot be loaded"
        ) from error

    answers = state.get("answers") if isinstance(state, dict) else None
    if (
        not isinstance(state, dict)
        or not isinstance(result, dict)
        or not isinstance(answers, list)
        or len(answers) != QUESTION_LIMIT
        or not isinstance(result.get("counts"), dict)
        or not isinstance(result.get("threshold"), dict)
        or not isinstance(result.get("importance"), dict)
    ):
        raise InvalidCalibrationData("completed calibration data has an invalid format")
    return state, result


def clear_calibration_outputs(
    state_path: Path,
    result_path: Path,
    export_path: Path,
) -> None:
    """Remove only product-generated calibration outputs."""

    for path in (state_path, result_path, export_path):
        path.unlink(missing_ok=True)


def serialize_word_statistics(word: Any) -> dict[str, Any]:
    return {
        "lemma": str(word.lemma),
        "part_of_speech": str(word.part_of_speech),
        "total_count": int(word.total_count),
        "document_count": int(word.document_count),
        "document_share": float(word.document_share),
        "zipf": float(word.zipf),
        "cefr_level": word.cefr_level,
        "exam_tags": list(word.exam_tags),
    }


def vocabulary_snapshot_sha256(words: list[Any]) -> str:
    snapshot = json.dumps(
        [
            serialize_word_statistics(word)
            for word in sorted(words, key=lambda item: item.lemma)
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


def _js_round(value: float, digits: int = 0) -> float:
    """Round like JavaScript's Math.round (half away from zero, not banker's)."""

    factor = 10**digits
    return math.floor(value * factor + 0.5) / factor


def sigmoid(value: float) -> float:
    bounded = max(-30.0, min(30.0, value))
    return 1 / (1 + math.exp(-bounded))


def logit(probability: float) -> float:
    bounded = max(1e-6, min(1 - 1e-6, probability))
    return math.log(bounded / (1 - bounded))


def frequency_prior(lemma: str, zipf: float) -> float:
    length_penalty = 0.075 * max(len(lemma) - 7, 0)
    return sigmoid(1.55 * (zipf - 3.65) - length_penalty)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _finite_number(value: Any, name: str) -> float:
    if not _is_finite_number(value):
        raise CalibrationError(
            "calibration_request_invalid", f"The {name} field is invalid."
        )
    return float(value)


def _is_integer_number(value: Any) -> bool:
    return _is_finite_number(value) and float(value).is_integer()


def validate_and_enrich_words(
    word_statistics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate word statistics and attach the frequency and education priors."""

    if not isinstance(word_statistics, list):
        raise CalibrationError(
            "calibration_request_invalid",
            "The words field is not a valid word-statistics list.",
        )
    if len(word_statistics) < QUESTION_LIMIT or len(word_statistics) > 10_000:
        raise CalibrationError(
            "calibration_request_invalid",
            "The words field must contain between 30 and 10000 word statistics.",
        )
    seen: set[str] = set()
    enriched: list[dict[str, Any]] = []
    for raw_word in word_statistics:
        if not isinstance(raw_word, dict) or set(raw_word) != set(WORD_STATISTIC_FIELDS):
            raise CalibrationError(
                "calibration_request_invalid",
                "A word statistic contains unexpected or missing fields.",
            )
        raw_lemma = raw_word["lemma"]
        lemma = raw_lemma.strip().lower() if isinstance(raw_lemma, str) else ""
        raw_part_of_speech = raw_word["part_of_speech"]
        part_of_speech = (
            raw_part_of_speech.strip()
            if isinstance(raw_part_of_speech, str)
            else ""
        )
        if not lemma or len(lemma) > 128 or lemma in seen:
            raise CalibrationError(
                "calibration_request_invalid",
                "Every word must have one unique valid lemma.",
            )
        if not part_of_speech or len(part_of_speech) > 32:
            raise CalibrationError(
                "calibration_request_invalid",
                "Every word must have a valid part_of_speech.",
            )
        seen.add(lemma)
        total_count = _finite_number(raw_word["total_count"], "total_count")
        document_count = _finite_number(raw_word["document_count"], "document_count")
        document_share = _finite_number(raw_word["document_share"], "document_share")
        zipf = _finite_number(raw_word["zipf"], "zipf")
        if (
            not _is_integer_number(total_count)
            or total_count < 1
            or not _is_integer_number(document_count)
            or document_count < 1
            or document_count > total_count
            or document_share <= 0
            or document_share > 1
            or zipf < 0
            or zipf > 8
        ):
            raise CalibrationError(
                "calibration_request_invalid",
                "A word statistic contains an out-of-range value.",
            )
        cefr_level = raw_word["cefr_level"]
        if cefr_level is not None and cefr_level not in CEFR_ADJUSTMENTS:
            raise CalibrationError(
                "calibration_request_invalid",
                "A word statistic contains an invalid cefr_level.",
            )
        raw_exam_tags = raw_word["exam_tags"]
        if not isinstance(raw_exam_tags, list) or any(
            tag not in EXAM_ADJUSTMENTS for tag in raw_exam_tags
        ):
            raise CalibrationError(
                "calibration_request_invalid",
                "A word statistic contains invalid exam_tags.",
            )
        exam_tags = sorted(set(raw_exam_tags))
        cefr_adjustment = 0.0 if cefr_level is None else CEFR_ADJUSTMENTS[cefr_level]
        exam_adjustment = max(
            [0.0] + [EXAM_ADJUSTMENTS[tag] for tag in exam_tags],
        )
        education_adjustment = max(cefr_adjustment, exam_adjustment)
        frequency_prior_probability = frequency_prior(lemma, zipf)
        prior_probability = sigmoid(
            logit(frequency_prior_probability) + education_adjustment,
        )
        enriched.append(
            {
                "lemma": lemma,
                "part_of_speech": part_of_speech,
                "total_count": total_count,
                "document_count": document_count,
                "document_share": document_share,
                "zipf": zipf,
                "frequency_prior_probability": frequency_prior_probability,
                "cefr_level": cefr_level,
                "cefr_adjustment": cefr_adjustment,
                "exam_tags": exam_tags,
                "exam_adjustment": exam_adjustment,
                "education_adjustment": education_adjustment,
                "prior_probability": prior_probability,
            }
        )
    return enriched


def _posterior(
    words_by_lemma: dict[str, dict[str, Any]],
    answers: list[dict[str, str]],
) -> list[float]:
    log_weights = [-0.5 * (theta / 1.5) ** 2 for theta in THETA_GRID]
    for answer in answers:
        if answer.get("response") == "unsure":
            continue
        word = words_by_lemma[answer["lemma"]]
        for index, theta in enumerate(THETA_GRID):
            probability = sigmoid(logit(word["prior_probability"]) + theta)
            log_weights[index] += math.log(
                max(
                    1e-12,
                    probability
                    if answer["response"] == "known"
                    else 1 - probability,
                )
            )
    maximum = max(log_weights)
    weights = [math.exp(value - maximum) for value in log_weights]
    total = sum(weights)
    return [value / total for value in weights]


def _probabilities(
    words: list[dict[str, Any]],
    answers: list[dict[str, str]],
) -> tuple[dict[str, float], list[float]]:
    words_by_lemma = {word["lemma"]: word for word in words}
    weights = _posterior(words_by_lemma, answers)
    theta_mean = sum(
        theta * weights[index] for index, theta in enumerate(THETA_GRID)
    )
    theta_variance = sum(
        ((theta - theta_mean) ** 2) * weights[index]
        for index, theta in enumerate(THETA_GRID)
    )
    # Logistic-normal moment approximation. This preserves the Bayesian ability
    # posterior while avoiding an 801-point integration for every corpus word.
    uncertainty_scale = math.sqrt(1 + math.pi * theta_variance / 8)
    predicted = {
        word["lemma"]: sigmoid(
            (logit(word["prior_probability"]) + theta_mean) / uncertainty_scale
        )
        for word in words
    }
    for answer in answers:
        if answer["response"] == "known":
            predicted[answer["lemma"]] = 1.0
        if answer["response"] == "unknown":
            predicted[answer["lemma"]] = 0.0
    return predicted, weights


def importance_tier(word: dict[str, Any]) -> str:
    if word["document_count"] >= 10:
        return "A"
    if word["document_count"] >= 5:
        return "B"
    if word["document_count"] >= 3:
        return "C"
    return "D"


def next_question(
    words: list[dict[str, Any]],
    answers: list[dict[str, str]],
) -> dict[str, Any] | None:
    if len(answers) >= QUESTION_LIMIT:
        return None
    asked = {answer["lemma"] for answer in answers}
    remaining = [word for word in words if word["lemma"] not in asked]
    if not remaining:
        return None
    targets = (0.93, 0.78, 0.63, 0.48, 0.33, 0.18)
    if len(answers) < len(targets):
        target = targets[len(answers)]
        remaining.sort(
            key=lambda word: (
                abs(word["prior_probability"] - target),
                -word["document_count"],
                -word["total_count"],
            )
        )
        return remaining[0]
    predicted, _weights = _probabilities(words, answers)
    maximum_documents = max(word["document_count"] for word in words)
    position_counts: dict[str, int] = {}
    by_lemma = {word["lemma"]: word for word in words}
    for answer in answers:
        position = by_lemma[answer["lemma"]]["part_of_speech"]
        position_counts[position] = position_counts.get(position, 0) + 1
    scored = [
        (
            predicted[word["lemma"]]
            * (1 - predicted[word["lemma"]])
            * (0.8 + 0.2 * (word["document_count"] / maximum_documents))
            / (1 + 0.08 * position_counts.get(word["part_of_speech"], 0)),
            word,
        )
        for word in remaining
    ]
    scored.sort(key=lambda item: -item[0])
    return scored[0][1]


def calibration_result(
    words: list[dict[str, Any]],
    answers: list[dict[str, str]],
    known_threshold: float,
) -> dict[str, Any]:
    predicted, weights = _probabilities(words, answers)
    protected_lemmas = {
        word["lemma"]
        for word in words
        if importance_tier(word) in {"A", "B"}
        and predicted[word["lemma"]] >= known_threshold
        and predicted[word["lemma"]]
        < min(1.0, known_threshold + IMPORTANT_BOUNDARY_MARGIN)
    }
    direct_responses = {answer["lemma"]: answer["response"] for answer in answers}
    rows = [
        {
            **word,
            "probability_known": _js_round(predicted[word["lemma"]], 6),
            "classification": (
                "important_boundary"
                if word["lemma"] in protected_lemmas
                else "likely_known"
                if predicted[word["lemma"]] >= known_threshold
                else "likely_unknown"
                if predicted[word["lemma"]] <= UNKNOWN_THRESHOLD
                else "uncertain"
            ),
            "direct_response": direct_responses.get(word["lemma"]),
            "importance_tier": importance_tier(word),
            "important_boundary_protected": word["lemma"] in protected_lemmas,
            "selected_threshold": known_threshold,
        }
        for word in words
    ]
    rows.sort(key=lambda row: -row["probability_known"])
    likely_known = [row for row in rows if row["classification"] == "likely_known"]
    retained = [row for row in rows if row["classification"] != "likely_known"]
    likely_unknown = [
        row for row in retained if row["classification"] == "likely_unknown"
    ]
    uncertain = [
        row for row in retained if row["classification"] != "likely_unknown"
    ]
    cumulative: list[float] = []
    running = 0.0
    for value in weights:
        running += value
        cumulative.append(running)

    def percentile(target: float) -> float:
        for index, value in enumerate(cumulative):
            if value >= target:
                return THETA_GRID[index]
        return THETA_GRID[-1]

    theta_mean = sum(theta * weights[index] for index, theta in enumerate(THETA_GRID))

    def tier_count(tier: str) -> int:
        return sum(row["importance_tier"] == tier for row in retained)

    corpus_document_count = max(
        [0]
        + [
            _js_round(word["document_count"] / word["document_share"])
            for word in words
            if word["document_share"] > 0
        ]
    )
    return {
        "counts": {
            "total": len(rows),
            "likely_known": len(likely_known),
            "uncertain": len(uncertain),
            "likely_unknown": len(likely_unknown),
            "important_boundary_protected": len(protected_lemmas),
            "remaining_after_conservative_exclusion": len(retained),
        },
        "threshold": {
            "selected_percent": _js_round(known_threshold * 100),
            "default_percent": _js_round(DEFAULT_KNOWN_THRESHOLD * 100),
            "minimum_percent": _js_round(MIN_KNOWN_THRESHOLD * 100),
            "maximum_percent": _js_round(MAX_KNOWN_THRESHOLD * 100),
            "step_percent": 1,
            "important_boundary_margin_percent": _js_round(
                IMPORTANT_BOUNDARY_MARGIN * 100
            ),
        },
        "importance": {
            "corpus_document_count": corpus_document_count,
            "priority_word_count": tier_count("A") + tier_count("B"),
            "occasional_word_count": tier_count("C") + tier_count("D"),
            "tiers": [
                {"key": "A", "name": "核心词", "range": "至少出现在 10 篇论文", "count": tier_count("A")},
                {"key": "B", "name": "高价值词", "range": "出现在 5–9 篇论文", "count": tier_count("B")},
                {"key": "C", "name": "偶发词", "range": "出现在 3–4 篇论文", "count": tier_count("C")},
                {"key": "D", "name": "文章局部词", "range": "只出现在 2 篇论文", "count": tier_count("D")},
            ],
        },
        "theta": {
            "mean": _js_round(theta_mean, 3),
            "p05": _js_round(percentile(0.05), 3),
            "p95": _js_round(percentile(0.95), 3),
        },
        "prior": {
            "name": (
                "wordfreq_plus_education_prior"
                if any(row["education_adjustment"] > 0 for row in rows)
                else "wordfreq_only"
            ),
            "cefr_matches": sum(row["cefr_level"] is not None for row in rows),
            "exam_matches": sum(bool(row["exam_tags"]) for row in rows),
        },
        "known_boundary": sorted(
            likely_known, key=lambda row: row["probability_known"]
        )[:30],
        "remaining_boundary": sorted(
            retained,
            key=lambda row: abs(row["probability_known"] - known_threshold),
        )[:30],
        "rows": rows,
    }


def calibration_public_state(
    words: list[dict[str, Any]],
    answers: list[dict[str, str]],
    known_threshold: float,
    mutation_revision: int,
) -> dict[str, Any]:
    current = next_question(words, answers)
    complete = current is None
    state: dict[str, Any] = {
        "threshold": {
            "selected_percent": _js_round(known_threshold * 100),
            "default_percent": _js_round(DEFAULT_KNOWN_THRESHOLD * 100),
            "minimum_percent": _js_round(MIN_KNOWN_THRESHOLD * 100),
            "maximum_percent": _js_round(MAX_KNOWN_THRESHOLD * 100),
            "step_percent": 1,
        },
        "answered": len(answers),
        "mutation_revision": mutation_revision,
        "question_limit": QUESTION_LIMIT,
        "complete": complete,
        "responses": {
            label: sum(answer["response"] == label for answer in answers)
            for label in CALIBRATION_RESPONSES
        },
        # The answer history contains only lemmas and response labels, so the
        # workbench can recover from an interrupted batch submission.
        "answers": [dict(answer) for answer in answers],
    }
    if current is not None:
        state["word"] = {
            "lemma": current["lemma"],
            "part_of_speech": current["part_of_speech"],
        }
    else:
        result = calibration_result(words, answers, known_threshold)
        result["answers"] = answers
        state["result"] = result
    return state


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


def _selected_revision(mutation_revision: Any, current: int) -> int:
    if isinstance(mutation_revision, int) and not isinstance(mutation_revision, bool):
        return mutation_revision
    return current + 1


def _normalized_answers(answers: Any, words: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(answers, list) or len(answers) > QUESTION_LIMIT:
        raise InvalidCalibrationData("saved calibration answers are invalid")
    lemmas = {word["lemma"] for word in words}
    normalized: list[dict[str, str]] = []
    for answer in answers:
        if (
            not isinstance(answer, dict)
            or not isinstance(answer.get("lemma"), str)
            or answer.get("response") not in CALIBRATION_RESPONSES
            or answer["lemma"] not in lemmas
        ):
            raise InvalidCalibrationData("saved calibration answers are invalid")
        normalized.append(
            {"lemma": answer["lemma"], "response": str(answer["response"])}
        )
    if len({answer["lemma"] for answer in normalized}) != len(normalized):
        raise InvalidCalibrationData("saved calibration answers are invalid")
    return normalized


class LocalCalibrationSession:
    """Answer the 30 calibration questions in process, without a server."""

    def __init__(
        self,
        words: list[Any],
        state_path: Path,
        corpus_label: str,
        *,
        result_path: Path | None = None,
        export_path: Path | None = None,
        enforce_snapshot_match: bool = False,
    ) -> None:
        self.state_path = Path(state_path)
        self.result_path = (
            Path(result_path)
            if result_path is not None
            else self.state_path.with_name("vocabulary-calibration-result.json")
        )
        self.export_path = (
            Path(export_path)
            if export_path is not None
            else self.state_path.with_name("personalized-vocabulary.tsv")
        )
        self.corpus_label = corpus_label
        self.enforce_snapshot_match = enforce_snapshot_match
        self.words = validate_and_enrich_words(
            [serialize_word_statistics(word) for word in words]
        )
        self.snapshot = vocabulary_snapshot_sha256(words)
        self.answers: list[dict[str, str]] = []
        self.known_threshold = DEFAULT_KNOWN_THRESHOLD
        self.mutation_revision = 0
        self.recovery_notice: str | None = None
        self._public_state: dict[str, Any] | None = None
        if self._load_completed_result():
            return
        saved = self._read_saved_state()
        if len(saved.get("answers") or []) >= QUESTION_LIMIT:
            # A full answer set that cannot be loaded as a completed result is
            # unrecoverable; start over instead of showing a broken session.
            self._recover_local_calibration()
            saved = {}
        if saved:
            self.answers = _normalized_answers(saved.get("answers") or [], self.words)
            threshold = saved.get("known_threshold")
            if _is_finite_number(threshold):
                self.known_threshold = max(
                    MIN_KNOWN_THRESHOLD,
                    min(MAX_KNOWN_THRESHOLD, float(threshold)),
                )
            self.mutation_revision = (
                int(saved["mutation_revision"])
                if _is_integer_number(saved.get("mutation_revision"))
                else 0
            )
        self._accept_state()

    def _recover_local_calibration(self) -> None:
        clear_calibration_outputs(self.state_path, self.result_path, self.export_path)
        self.recovery_notice = RECOVERY_NOTICE

    def _read_saved_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._recover_local_calibration()
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("vocabulary_snapshot_sha256") != self.snapshot
            or not isinstance(payload.get("answers"), list)
        ):
            # The corpus behind this session changed or the file is damaged.
            self._recover_local_calibration()
            return {}
        return payload

    def _load_completed_result(self) -> bool:
        if not (self.result_path.is_file() or self.export_path.is_file()):
            return False
        try:
            state, result = load_completed_calibration(
                self.state_path,
                self.result_path,
                self.export_path,
            )
            if (
                self.enforce_snapshot_match
                and result.get("vocabulary_snapshot_sha256") != self.snapshot
            ):
                raise InvalidCalibrationData("vocabulary snapshot does not match")
            self.answers = _normalized_answers(state["answers"], self.words)
            if len(self.answers) != QUESTION_LIMIT:
                raise InvalidCalibrationData("completed calibration is incomplete")
            selected = result.get("threshold", {}).get("selected_percent")
            if _is_integer_number(selected):
                self.known_threshold = max(
                    MIN_KNOWN_THRESHOLD,
                    min(MAX_KNOWN_THRESHOLD, float(selected) / 100),
                )
            revision = result.get("mutation_revision")
            self.mutation_revision = (
                int(revision) if _is_integer_number(revision) else 0
            )
            self._public_state = self._completed_public_state(result)
            return True
        except InvalidCalibrationData:
            self._recover_local_calibration()
            return False

    def _completed_public_state(self, result: dict[str, Any]) -> dict[str, Any]:
        state = {
            "corpus_label": self.corpus_label,
            "answered": QUESTION_LIMIT,
            "question_limit": QUESTION_LIMIT,
            "complete": True,
            "mutation_revision": self.mutation_revision,
            "threshold": result.get("threshold") or {},
            "responses": {
                label: sum(
                    answer.get("response") == label for answer in self.answers
                )
                for label in CALIBRATION_RESPONSES
            },
            "answers": [dict(answer) for answer in self.answers],
            "result": {
                **result,
                "output_files": {
                    "result": str(self.result_path),
                    "personalized_vocabulary": str(self.export_path),
                },
            },
        }
        if self.recovery_notice:
            state["recovery_notice"] = self.recovery_notice
        return state

    def _accept_state(self) -> None:
        calibration = calibration_public_state(
            self.words,
            self.answers,
            self.known_threshold,
            self.mutation_revision,
        )
        if calibration["complete"]:
            self._write_final_outputs(calibration)
            return
        self._save_state()
        state = {"corpus_label": self.corpus_label, **calibration}
        if self.recovery_notice:
            state["recovery_notice"] = self.recovery_notice
        self._public_state = state

    def _save_state(self) -> None:
        payload = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "vocabulary_snapshot_sha256": self.snapshot,
            "known_threshold": self.known_threshold,
            "mutation_revision": self.mutation_revision,
            "answers": self.answers,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    @staticmethod
    def _export_tsv(rows: list[dict[str, Any]]) -> str:
        fields = [
            "lemma",
            "part_of_speech",
            "probability_known",
            "classification",
            "total_count",
            "document_count",
            "zipf",
            "frequency_prior_probability",
            "cefr_level",
            "cefr_adjustment",
            "exam_tags",
            "exam_adjustment",
            "education_adjustment",
            "direct_response",
            "importance_tier",
            "important_boundary_protected",
            "selected_threshold",
        ]
        lines = ["\t".join(fields)]
        for row in rows:
            values = []
            for field in fields:
                value = row.get(field)
                if field == "exam_tags":
                    value = " ".join(value or [])
                elif isinstance(value, bool):
                    value = str(value).lower()
                elif value is None:
                    value = ""
                elif field in {"probability_known", "frequency_prior_probability"}:
                    value = f"{float(value):.6f}"
                elif field in {
                    "cefr_adjustment",
                    "exam_adjustment",
                    "education_adjustment",
                    "selected_threshold",
                }:
                    value = f"{float(value):.2f}"
                elif field == "zipf":
                    value = f"{float(value):.3f}"
                values.append(str(value))
            lines.append("\t".join(values))
        return "\n".join(lines) + "\n"

    def _write_final_outputs(self, calibration: dict[str, Any]) -> None:
        raw_result = calibration.get("result")
        if not isinstance(raw_result, dict) or not isinstance(
            raw_result.get("rows"), list
        ):
            raise CalibrationError(
                "calibration_result_invalid",
                "The calibration result is incomplete.",
            )
        result = dict(raw_result)
        rows = result.pop("rows")
        result.pop("answers", None)
        result["completed_at"] = time.time()
        result["answers"] = [dict(answer) for answer in self.answers]
        result["vocabulary_snapshot_sha256"] = self.snapshot
        result["mutation_revision"] = self.mutation_revision
        export_content = self._export_tsv(rows)
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        result_temporary = self.result_path.with_suffix(self.result_path.suffix + ".tmp")
        export_temporary = self.export_path.with_suffix(self.export_path.suffix + ".tmp")
        result_temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        export_temporary.write_text(export_content, encoding="utf-8")
        os.replace(export_temporary, self.export_path)
        os.replace(result_temporary, self.result_path)
        self._save_state()
        self._public_state = self._completed_public_state(result)

    def public_state(self) -> dict[str, Any]:
        if self._public_state is None:
            raise RuntimeError("Calibration state is unavailable")
        return self._public_state

    def answer(self, lemma: str, response: str) -> None:
        if response not in CALIBRATION_RESPONSES:
            raise CalibrationError(
                "calibration_request_invalid",
                "The response must be known, unknown or unsure.",
            )
        if len(self.answers) >= QUESTION_LIMIT:
            raise CalibrationError(
                "calibration_request_invalid",
                "All calibration questions have been answered.",
            )
        current = next_question(self.words, self.answers)
        if current is None or current["lemma"] != lemma:
            raise CalibrationError(
                "calibration_request_invalid",
                "The answer does not match the current question.",
            )
        self.answers.append({"lemma": lemma, "response": response})
        self.mutation_revision += 1
        self._accept_state()

    def set_threshold_percent(
        self,
        threshold_percent: int,
        mutation_revision: int | None = None,
    ) -> None:
        threshold = int(threshold_percent) / 100
        if not (
            MIN_KNOWN_THRESHOLD - 1e-9 <= threshold <= MAX_KNOWN_THRESHOLD + 1e-9
        ):
            raise CalibrationError(
                "calibration_request_invalid",
                "The threshold must be between 75 and 98 percent.",
            )
        self.known_threshold = threshold
        self.mutation_revision = _selected_revision(
            mutation_revision, self.mutation_revision
        )
        self._accept_state()

    def reset(self, mutation_revision: int | None = None) -> None:
        self.mutation_revision = _selected_revision(
            mutation_revision, self.mutation_revision
        )
        self.answers = []
        self.result_path.unlink(missing_ok=True)
        self.export_path.unlink(missing_ok=True)
        self._accept_state()

    def persisted_export_tsv(self) -> str:
        if not self.export_path.is_file():
            raise RuntimeError("The personalized vocabulary export is not ready")
        return self.export_path.read_text(encoding="utf-8")

    def personal_vocabulary_mastery(
        self,
        mastered_word_forms: set[str],
    ) -> dict[str, Any] | None:
        if not self.export_path.is_file():
            return None
        try:
            reader = csv.DictReader(
                self.export_path.read_text(encoding="utf-8").splitlines(),
                delimiter="\t",
            )
            rows = list(reader)
        except (OSError, csv.Error):
            return None
        groups = []
        for key, label, tiers in (
            ("priority", "重要与核心词", {"A", "B"}),
            ("other", "其他词", {"C", "D"}),
        ):
            selected = [
                row
                for row in rows
                if row.get("importance_tier") in tiers
                and row.get("classification") != "likely_known"
            ]
            mastered = sum(
                row.get("classification") == "important_boundary"
                or str(row.get("lemma") or "").casefold() in mastered_word_forms
                for row in selected
            )
            total = len(selected)
            groups.append(
                {
                    "key": key,
                    "label": label,
                    "tiers": sorted(tiers),
                    "mastered_count": mastered,
                    "total_count": total,
                    "mastery_percent": round(mastered / total * 100, 1)
                    if total
                    else 0.0,
                }
            )
        return {
            "basis": "personal_vocabulary_calibrated_and_confirmed_mastery",
            "groups": groups,
        }
