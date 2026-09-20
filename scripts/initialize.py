#!/usr/bin/env python3
"""Drive AreaDay from a confirmed profile to a verified local calibration.

This is the sole lifecycle owner for the unattended part of first-time setup.
Discovery, review preparation, download, analysis, and finalization are internal
checkpoints.  None of them is a successful terminal result.  The operation may
hand work back to the host agent for contextual review, but it becomes terminal
after either the live library service proves that both vocabulary and terminology
are available for the selected registered domain or all three bounded retrieval
strategies fail to obtain even one usable PDF.

A run also stops before it does anything else when no usable OpenAlex API key is
configured.  The credentials file is opened for the user, the reason is printed
once, and the process exits with code 4: nothing runs until the key is saved and
the command is started again.
"""

from __future__ import annotations

import argparse
import http.client
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

from acquire_mini_corpus import (
    MAX_RETRIEVAL_STRATEGIES,
    RETRIEVAL_STATE_NAME,
    candidate_sufficiency_count,
    load_retrieval_state,
)
from configure_openalex import (
    SETTINGS_URL as OPENALEX_SETTINGS_URL,
    open_in_editor,
    prepare_for_editing,
)
from domain_registry import (
    DomainRegistry,
    default_registry_path,
    validate_initialized_workspace,
)
from vocabulary_cards import (
    GLOSS_DATA_NAME,
    REVIEW_SCHEMA_VERSION,
    merge_review_batch_outputs,
    prepare_review_input,
    validate_review_batch,
)
from open_workbench import (
    DEFAULT_WORKBENCH_IDLE_TIMEOUT_SECONDS,
    HOST,
    WorkbenchAccessError,
    WorkbenchCleanupError,
    WorkbenchConflict,
    WorkbenchStartupError,
    default_port,
    ensure_workbench,
    launchable_registry_domain_ids,
    probe_workbench,
    start_workbench,
)
from orthography_contract import orthography_summary_is_complete
from research_profile import validate_profile
from areaday_core import credentials_path, load_openalex_api_key, read_json, utc_now, write_json
from terminology_assets import load_finalized_terminology


SCHEMA_VERSION = 1
APP_API_VERSION = 6
STATUS_NAME = "status.json"
LOCK_NAME = ".initialization.lock"
EXIT_MISSING_KEY = 4
WORKBENCH_FAILURES = (
    WorkbenchConflict,
    WorkbenchStartupError,
    WorkbenchAccessError,
    WorkbenchCleanupError,
)


class InitializationError(RuntimeError):
    """A persistent or external condition prevented safe continuation."""


class ResumeScopeError(InitializationError):
    """The invocation does not belong to the persisted operation scope."""


def _read_json_object(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _json_get(port: int, path: str, *, domain_id: str | None = None) -> dict[str, Any]:
    connection = http.client.HTTPConnection(HOST, port, timeout=2.0)
    headers = {"Accept": "application/json", "Connection": "close"}
    if domain_id is not None:
        headers["X-AreaDay-Domain"] = domain_id
        headers["X-AreaDay-API-Version"] = str(APP_API_VERSION)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read(2_000_000)
    finally:
        connection.close()
    if response.status != 200:
        raise InitializationError(
            f"Workbench readiness probe failed: GET {path} returned {response.status}"
        )
    try:
        value = json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise InitializationError(
            f"Workbench readiness probe returned invalid JSON: {path}"
        ) from error
    if not isinstance(value, dict):
        raise InitializationError(
            f"Workbench readiness probe returned a non-object: {path}"
        )
    return value


class InitializationController:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.workspace = args.workspace.expanduser().resolve()
        self.profile_path = args.profile.expanduser().resolve()
        self.registry_path = args.registry.expanduser().resolve()
        self.status_path = self.workspace / STATUS_NAME
        self.operation_id = uuid.uuid4().hex
        self.revision = 0
        self.previous_status: dict[str, Any] | None = None
        self.profile_id = ""
        if self.profile_path.is_file():
            candidate_profile = _read_json_object(self.profile_path)
            self.profile_id = str(candidate_profile.get("profile_id") or "")
        if self.status_path.is_file():
            previous = _read_json_object(self.status_path)
            if (
                previous.get("schema_version") == SCHEMA_VERSION
                and previous.get("operation") == "prepare_calibration"
            ):
                self.previous_status = previous
                self.operation_id = str(previous.get("operation_id") or self.operation_id)
                raw_revision = previous.get("revision", 0)
                if isinstance(raw_revision, int) and not isinstance(raw_revision, bool):
                    self.revision = raw_revision

    def _status(
        self,
        status: str,
        *,
        terminal: bool,
        checkpoint: str,
        next_action: dict[str, Any] | None = None,
        service: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        self.revision += 1
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "operation": "prepare_calibration",
            "operation_id": self.operation_id,
            "revision": self.revision,
            "updated_at": utc_now(),
            "profile": str(self.profile_path),
            "profile_id": self.profile_id,
            "workspace": str(self.workspace),
            "registry": str(self.registry_path),
            "target_papers": self.args.target_papers,
            "target_papers_is_reference": True,
            "status": status,
            "terminal": terminal,
            "checkpoint": checkpoint,
            "next_action": next_action,
        }
        if service is not None:
            payload["service"] = service
        if error is not None:
            payload["error"] = error
        write_json(self.status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return payload

    def _host_action(
        self,
        action_type: str,
        *,
        input_path: Path | None = None,
        input_paths: dict[str, Path] | None = None,
        output_path: Path,
        checkpoint: str,
        instructions: str,
    ) -> dict[str, Any]:
        next_action: dict[str, Any] = {
            "actor": "current_host_agent",
            "type": action_type,
            "output": str(output_path),
            "instructions": instructions,
            "resume": self.resume_command(),
        }
        if input_path is not None:
            next_action["input"] = str(input_path)
        if input_paths is not None:
            next_action["inputs"] = {
                name: str(path) for name, path in input_paths.items()
            }
        return self._status(
            "host_action_required",
            terminal=False,
            checkpoint=checkpoint,
            next_action=next_action,
        )

    def resume_command(self) -> list[str]:
        return [
            str(Path(sys.executable).absolute()),
            str(Path(__file__).resolve()),
            "run",
            "--profile",
            str(self.profile_path),
            "--workspace",
            str(self.workspace),
            "--registry",
            str(self.registry_path),
            "--target-papers",
            str(self.args.target_papers),
            "--download-workers",
            str(self.args.download_workers),
            "--download-workers-per-host",
            str(self.args.download_workers_per_host),
            "--port",
            str(self.args.port),
            "--idle-timeout-seconds",
            str(
                getattr(
                    self.args,
                    "idle_timeout_seconds",
                    DEFAULT_WORKBENCH_IDLE_TIMEOUT_SECONDS,
                )
            ),
        ]

    def _run_helper(
        self,
        command: list[str],
        checkpoint: str,
        *,
        accepted_codes: tuple[int, ...] = (0,),
    ) -> int:
        self._status("running", terminal=False, checkpoint=checkpoint)
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1])
        if result.returncode not in accepted_codes:
            raise InitializationError(
                f"Internal checkpoint {checkpoint} failed with exit code "
                f"{result.returncode}; inspect the preserved workspace and resume."
            )
        return result.returncode

    def _acquire_command(self, *extra: str) -> list[str]:
        return [
            sys.executable,
            str(Path(__file__).with_name("acquire_mini_corpus.py")),
            "--profile",
            str(self.profile_path),
            "--workspace",
            str(self.workspace),
            "--registry",
            str(self.registry_path),
            "--target-papers",
            str(self.args.target_papers),
            "--download-workers",
            str(self.args.download_workers),
            "--download-workers-per-host",
            str(self.args.download_workers_per_host),
            *extra,
        ]

    def _retrieval_attempt_count(self) -> int:
        state_path = self.workspace / RETRIEVAL_STATE_NAME
        if state_path.is_file():
            return len(load_retrieval_state(self.workspace)["attempts"])
        if (self.workspace / "candidates.jsonl").is_file():
            # Workspaces created before bounded strategy tracking represent one
            # completed initial search, not a fresh allowance of three more.
            return 1
        return 0

    def _strategy_path(self, attempt_number: int) -> Path:
        return self.workspace / f"retrieval-strategy-{attempt_number:02d}.json"

    def _candidate_selection_path(self, attempt_count: int) -> Path:
        if attempt_count <= 1:
            return self.workspace / "candidate-review-selection.json"
        return self.workspace / f"candidate-review-selection-{attempt_count:02d}.json"

    def _run_pending_retrieval_strategy(self) -> None:
        attempt_count = self._retrieval_attempt_count()
        if attempt_count >= MAX_RETRIEVAL_STRATEGIES:
            return
        strategy_path = self._strategy_path(attempt_count + 1)
        if strategy_path.is_file():
            self._run_helper(
                self._acquire_command(
                    "--search-only",
                    "--strategy",
                    str(strategy_path),
                ),
                f"retrieval_strategy_{attempt_count + 1}",
            )

    def _request_retrieval_strategy(self, *, reason: str) -> dict[str, Any]:
        attempt_count = self._retrieval_attempt_count()
        if attempt_count >= MAX_RETRIEVAL_STRATEGIES:
            raise InitializationError("No unused retrieval strategy remains")
        inputs = {
            "research_profile": self.workspace / "research-profile.json",
            "search_attempts": self.workspace / "search-attempts.json",
            "candidate_summary": self.workspace / "candidate-review-summary.json",
        }
        acquisition_summary = self.workspace / "cold-start-summary.json"
        if acquisition_summary.is_file():
            inputs["acquisition_summary"] = acquisition_summary
        attempt_number = attempt_count + 1
        return self._host_action(
            "design_retrieval_strategy",
            input_paths=inputs,
            output_path=self._strategy_path(attempt_number),
            checkpoint=f"retrieval_strategy_{attempt_number}_needed",
            instructions=(
                f"The existing corpus is insufficient because {reason}. Create retrieval "
                f"strategy {attempt_number} of {MAX_RETRIEVAL_STRATEGIES} autonomously "
                "(before this unattended phase started, the user was explicitly told "
                "they could leave the task and may not be available to answer another "
                "retrieval-choice question). It must remain within the confirmed research "
                "scope but differ "
                "meaningfully from earlier attempts through provider choice, scholarly "
                "wording, synonyms, or search angle. Write schema_version=1, a unique "
                "strategy_id, providers, and the search_queries and/or "
                "arxiv_search_queries needed by those providers. Include a retrieval_scope "
                "override only when the newly selected provider needs taxonomy or category "
                "information absent from the profile; then immediately resume."
            ),
        )

    def _finish_without_usable_pdfs(self, acquisition: dict[str, Any]) -> dict[str, Any]:
        successful = int(acquisition.get("successful_pdfs") or 0)
        return self._status(
            "corpus_unavailable",
            terminal=True,
            checkpoint="retrieval_strategies_exhausted",
            next_action={
                "actor": "user",
                "type": "provide_local_pdfs_later",
                "successful_pdfs": successful,
                "message": (
                    "The bounded online search is finished without a usable PDF. You may "
                    "later provide a directory of relevant PDFs; they will be combined "
                    "with valid papers already collected."
                ),
            },
        )

    def _prepare_assets(self) -> None:
        candidates = self.workspace / "candidates.jsonl"
        candidate_packet = self.workspace / "candidate-review-packet.jsonl"
        if not candidates.is_file() or not candidate_packet.is_file():
            self._run_helper(
                self._acquire_command("--search-only"),
                "discovering_and_preparing_candidate_review",
            )
        self._run_pending_retrieval_strategy()

        candidate_summary_path = self.workspace / "candidate-review-summary.json"
        if not candidate_summary_path.is_file():
            candidate_count = sum(
                1
                for line in candidates.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            write_json(
                candidate_summary_path,
                {
                    "schema_version": 1,
                    "candidate_count": candidate_count,
                    "review_packet_count": sum(
                        1
                        for line in candidate_packet.read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if line.strip()
                    ),
                    "target_papers": self.args.target_papers,
                },
            )
        candidate_summary = _read_json_object(candidate_summary_path)
        candidate_count = int(candidate_summary.get("candidate_count") or 0)
        attempt_count = self._retrieval_attempt_count()
        candidate_selection = self._candidate_selection_path(attempt_count)
        if (
            candidate_count < candidate_sufficiency_count(self.args.target_papers)
            and attempt_count < MAX_RETRIEVAL_STRATEGIES
            and not candidate_selection.is_file()
        ):
            self._request_retrieval_strategy(
                reason=(
                    f"only {candidate_count} plausible candidates were found, below the "
                    f"{candidate_sufficiency_count(self.args.target_papers)}-candidate "
                    "search-sufficiency point"
                )
            )
            raise StopIteration

        if not any(candidate_packet.read_text(encoding="utf-8").splitlines()):
            acquisition_path = self.workspace / "cold-start-summary.json"
            acquisition = (
                _read_json_object(acquisition_path)
                if acquisition_path.is_file()
                else {"successful_pdfs": 0}
            )
            self._finish_without_usable_pdfs(acquisition)
            raise StopIteration

        if not candidate_selection.is_file():
            self._host_action(
                "review_candidates",
                input_path=candidate_packet,
                output_path=candidate_selection,
                checkpoint="candidate_review_needed",
                instructions=(
                    "Select an ordered, relevant set with enough backups for the target. "
                    "Write schema_version=1, reviewer=current-host-agent, "
                    "selected_candidate_ids, and review_summary; then immediately resume."
                ),
            )
            raise StopIteration

        orthography_input = self.workspace / "analysis" / "orthography-review-input.json"
        if not orthography_input.is_file():
            self._run_helper(
                self._acquire_command(
                    "--selection",
                    str(candidate_selection),
                    "--analyze",
                ),
                "downloading_and_analyzing_corpus",
                accepted_codes=(0, 2),
            )

        summary_path = self.workspace / "cold-start-summary.json"
        if not summary_path.is_file():
            raise InitializationError("Acquisition did not write cold-start-summary.json")
        acquisition = _read_json_object(summary_path)
        successful = int(acquisition.get("successful_pdfs") or 0)
        if successful < 1:
            attempt_count = self._retrieval_attempt_count()
            if attempt_count < MAX_RETRIEVAL_STRATEGIES:
                self._request_retrieval_strategy(
                    reason="no usable PDFs were obtained"
                )
            else:
                self._finish_without_usable_pdfs(acquisition)
            raise StopIteration

        terminology_input = self.workspace / "analysis" / "terminology-review-input.json"
        if not terminology_input.is_file():
            raise InitializationError("Analysis did not write terminology review input")

        orthography_selection = (
            self.workspace / "analysis" / "orthography-review-selection.json"
        )
        orthography_summary = (
            self.workspace / "analysis" / "orthography-review-summary.json"
        )
        orthography_is_complete = (
            orthography_summary.is_file()
            and orthography_summary_is_complete(_read_json_object(orthography_summary))
        )
        if not orthography_is_complete:
            if not orthography_selection.is_file():
                self._host_action(
                    "review_vocabulary_orthography",
                    input_path=orthography_input,
                    output_path=orthography_selection,
                    checkpoint="orthography_review_needed",
                    instructions=(
                        "Review every suspicious vocabulary lemma. Write one "
                        "schema_version=1 review with reviewer=current-host-agent, "
                        "lemma_keeps, lemma_replacements, lemma_drops, and "
                        "review_summary. Every candidate must appear in exactly one "
                        "of lemma_keeps, lemma_replacements, or lemma_drops; then "
                        "immediately resume."
                    ),
                )
                raise StopIteration
            self._run_helper(
                [
                    sys.executable,
                    str(Path(__file__).with_name("apply_orthography_review.py")),
                    "--workspace",
                    str(self.workspace),
                    "--selection",
                    str(orthography_selection),
                ],
                "finalizing_vocabulary_orthography",
            )

        card_review_input = self.workspace / "analysis" / "vocabulary-card-review-input.json"
        combined_selection = self.workspace / "analysis" / "domain-review-selection.json"
        assets_summary = self.workspace / "analysis" / "domain-assets-summary.json"
        assets_are_current = False
        if assets_summary.is_file():
            existing_summary = _read_json_object(assets_summary)
            cards_summary = existing_summary.get("vocabulary_cards")
            assets_are_current = (
                existing_summary.get("ready_for_calibration") is True
                and isinstance(cards_summary, dict)
                and cards_summary.get("semantic_review_contract_version")
                == REVIEW_SCHEMA_VERSION
            )
        if not assets_are_current:
            prepare_review_input(
                self.workspace,
                Path(__file__).resolve().parents[1] / "app" / "data" / GLOSS_DATA_NAME,
            )

        if not assets_are_current:
            card_review = _read_json_object(card_review_input)
            batches = card_review.get("batches")
            if not isinstance(batches, list) or not batches:
                raise InitializationError("Vocabulary-card review batches are missing")
            next_batch = None
            for batch in batches:
                if not isinstance(batch, dict):
                    raise InitializationError(
                        "Vocabulary-card review batch manifest is invalid"
                    )
                result_path = Path(str(batch.get("output") or ""))
                if not result_path.is_file():
                    next_batch = batch
                    break
                batch_payload = _read_json_object(Path(str(batch.get("path") or "")))
                try:
                    batch_result = _read_json_object(result_path)
                    validate_review_batch(
                        batch_result,
                        [
                            candidate
                            for candidate in batch_payload.get("candidates") or []
                            if isinstance(candidate, dict)
                        ],
                    )
                    if int(batch.get("batch_index") or 0) == 1 and (
                        not isinstance(batch_result.get("terminology"), dict)
                        or not isinstance(
                            batch_result.get("terminology_explanations"), dict
                        )
                    ):
                        raise ValueError(
                            "The first review batch must include terminology decisions"
                        )
                except ValueError:
                    next_batch = batch
                    break
            if next_batch is not None:
                batch_path = Path(str(next_batch.get("path") or ""))
                result_path = Path(str(next_batch.get("output") or ""))
                action_inputs = {"vocabulary_card_review_batch": batch_path}
                batch_index = int(next_batch.get("batch_index") or 0)
                batch_count = int(card_review.get("batch_count") or 0)
                if batch_index == 1:
                    action_inputs["terminology"] = terminology_input
                self._host_action(
                    "review_vocabulary_cards_and_terminology",
                    input_paths=action_inputs,
                    output_path=result_path,
                    checkpoint="learning_asset_review_needed",
                    instructions=(
                        f"Review vocabulary-card batch {batch_index} of {batch_count}. "
                        + (
                            "Also review the terminology input and create one schema_version=1 "
                            "selection with reviewer=current-host-agent, terminology, "
                            "terminology_explanations, vocabulary_card_glosses, "
                            "vocabulary_card_drops, "
                            if batch_index == 1
                            else "Create one schema_version=1 selection with "
                            "reviewer=current-host-agent containing only this batch's "
                            "vocabulary_card_glosses and vocabulary_card_drops, "
                        )
                        + f"vocabulary_card_review_schema_version={REVIEW_SCHEMA_VERSION}, "
                        "and review_summary. The batch records are in top-level .candidates; "
                        "verify .candidate_count, and either gloss each item with a sense_key "
                        "and brief context_rationale or put an item that cannot be judged "
                        "confidently in vocabulary_card_drops. Never copy the first dictionary "
                        "entry across the batch. Corpus acronym expansions and representative "
                        "sentences control conflicting senses. Do not read or reproduce earlier "
                        "batch outputs. Write this batch output and immediately resume; "
                        "the controller will supply the next bounded batch until exact "
                        "coverage is complete."
                    ),
                )
                raise StopIteration
            merge_review_batch_outputs(batches, combined_selection)
            self._run_helper(
                [
                    sys.executable,
                    str(Path(__file__).with_name("finalize_domain_assets.py")),
                    "--workspace",
                    str(self.workspace),
                    "--selection",
                    str(combined_selection),
                ],
                "finalizing_vocabulary_and_terminology",
            )
        summary = _read_json_object(assets_summary)
        cards_summary = summary.get("vocabulary_cards")
        if (
            summary.get("ready_for_calibration") is not True
            or not isinstance(cards_summary, dict)
            or cards_summary.get("semantic_review_contract_version")
            != REVIEW_SCHEMA_VERSION
        ):
            raise InitializationError(
                "Vocabulary and terminology finalization did not complete"
            )

    def _launch_and_verify(self, profile: dict[str, Any]) -> dict[str, Any]:
        registration = DomainRegistry(self.registry_path).register(self.workspace)
        domain_id = registration.domain_id
        registry = DomainRegistry(self.registry_path)
        domain_ids = launchable_registry_domain_ids(registry, domain_id)
        starter = lambda path, selected, view, port: start_workbench(
            path,
            selected,
            view,
            port,
            ready_calibration_domain=domain_id,
            idle_timeout_seconds=getattr(
                self.args,
                "idle_timeout_seconds",
                DEFAULT_WORKBENCH_IDLE_TIMEOUT_SECONDS,
            ),
        )
        try:
            launch = ensure_workbench(
                self.registry_path,
                domain_id,
                "vocabulary",
                self.args.port,
                expected_domain_ids=domain_ids,
                starter=starter,
            )
            selected_port = int(launch["port"])
            identity_probe = probe_workbench(
                selected_port,
                self.registry_path,
                expected_domain_ids=domain_ids,
                timeout=2.0,
            )
        except WORKBENCH_FAILURES as error:
            raise InitializationError(str(error)) from error
        if identity_probe.kind.value != "match" or identity_probe.identity is None:
            raise InitializationError("The launched workbench failed its identity probe")

        query = urlencode({"domain_id": domain_id})
        app_state = _json_get(
            selected_port,
            f"/api/app-state?{query}",
            domain_id=domain_id,
        )
        terms_api = _json_get(
            selected_port,
            f"/api/terms?{query}",
            domain_id=domain_id,
        )
        terms, _explanations, summary = load_finalized_terminology(
            self.workspace,
            require_review_summary=True,
        )
        calibration = app_state.get("calibration")
        embedded_terms = app_state.get("terminology")
        expected_term_names = {
            str(item.get("term") or "").strip().casefold() for item in terms
        }
        embedded_term_names = {
            str(item.get("term") or "").strip().casefold()
            for item in (embedded_terms or {}).get("terms", [])
            if isinstance(item, dict)
        }
        api_term_names = {
            str(item.get("term") or "").strip().casefold()
            for item in terms_api.get("terms", [])
            if isinstance(item, dict)
        }
        if (
            app_state.get("domain_id") != domain_id
            or not isinstance(calibration, dict)
            or calibration.get("question_limit") != 30
            or (
                calibration.get("complete") is not True
                and not isinstance(calibration.get("word"), dict)
            )
            or not isinstance(embedded_terms, dict)
            or embedded_terms.get("count") != len(terms)
            or terms_api.get("count") != len(terms)
            or embedded_term_names != expected_term_names
            or api_term_names != expected_term_names
            or summary is None
            or summary.get("selected_terminology_count") != len(terms)
        ):
            raise InitializationError(
                "The live workbench did not expose the finalized vocabulary and "
                "terminology snapshot for the selected domain"
            )
        vocabulary_path = self.workspace / "analysis" / "vocabulary-map.tsv"
        import csv

        with vocabulary_path.open(encoding="utf-8", newline="") as handle:
            vocabulary_rows = list(csv.DictReader(handle, delimiter="\t"))
        vocabulary_lemmas = [
            str(item.get("lemma") or "").strip().casefold()
            for item in vocabulary_rows
        ]
        vocabulary_entry_count = len(vocabulary_lemmas)
        if (
            vocabulary_entry_count < 30
            or len(set(vocabulary_lemmas)) != vocabulary_entry_count
            or not all(vocabulary_lemmas)
        ):
            raise InitializationError(
                "The finalized vocabulary map must contain at least 30 unique lemmas"
            )
        return {
            **launch,
            "registry": str(self.registry_path),
            "profile_id": profile["profile_id"],
            "domain_ids": list(domain_ids),
            "vocabulary_ready": True,
            "vocabulary_entry_count": vocabulary_entry_count,
            "terminology_ready": True,
            "terminology_count": len(terms),
            "calibration_answered": calibration.get("answered"),
            "verified_at": utc_now(),
        }

    def run(self) -> dict[str, Any]:
        self.workspace.mkdir(parents=True, exist_ok=True)
        lock_path = self.workspace / LOCK_NAME
        with lock_path.open("a+") as lock:
            try:
                if fcntl is not None:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:  # pragma: no cover - exercised on Windows
                    import msvcrt

                    lock.seek(0)
                    if not lock.read(1):
                        lock.write("0")
                        lock.flush()
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except (BlockingIOError, OSError) as error:
                raise InitializationError(
                    f"Another initialization controller is active for {self.workspace}"
                ) from error
            profile = _read_json_object(self.profile_path)
            validate_profile(profile)
            self.profile_id = str(profile["profile_id"])
            if self.previous_status is not None:
                expected_scope = {
                    "profile": str(self.profile_path),
                    "workspace": str(self.workspace),
                    "registry": str(self.registry_path),
                    "target_papers": self.args.target_papers,
                }
                mismatched = [
                    key
                    for key, expected in expected_scope.items()
                    if self.previous_status.get(key) != expected
                ]
                if mismatched:
                    raise ResumeScopeError(
                        "Existing initialization status belongs to a different "
                        f"operation scope: {', '.join(mismatched)}"
                    )
            existing_profile = self.workspace / "research-profile.json"
            if existing_profile.is_file() and _read_json_object(
                existing_profile
            ) != profile:
                raise ResumeScopeError(
                    "Workspace is already bound to a different confirmed profile"
                )
            self._status("running", terminal=False, checkpoint="preparing_calibration")
            try:
                self._prepare_assets()
            except StopIteration:
                return _read_json_object(self.status_path)
            validate_initialized_workspace(self.workspace)
            service = self._launch_and_verify(profile)
            return self._status(
                "awaiting_user_calibration",
                terminal=True,
                checkpoint="calibration_ready",
                next_action={
                    "actor": "user",
                    "type": "answer_vocabulary_calibration",
                    "url": service["url"],
                    "question_count": 30,
                },
                service=service,
            )

    def inspect(self) -> dict[str, Any]:
        if not self.status_path.is_file():
            raise InitializationError(
                f"No initialization status exists in {self.workspace}"
            )
        payload = _read_json_object(self.status_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload


def openalex_key_gate(*, open_editor: bool = True) -> int | None:
    """Stop before any work when no usable OpenAlex key is configured.

    AreaDay cannot search papers anonymously and the key cannot be invented, so a
    missing or unusable key ends this invocation: the credentials file is opened
    for the user to fill in, the reason is printed once, and no checkpoint, lock
    or status file is touched.  Returns an exit code when the run must stop, or
    ``None`` when a usable key is configured.
    """
    try:
        load_openalex_api_key()
    except (RuntimeError, ValueError) as error:
        credentials = credentials_path()
        opened = ""
        try:
            prepare_for_editing(credentials)
            if open_editor:
                opened = open_in_editor(credentials)
        except OSError as problem:
            print(f"Could not prepare {credentials}: {problem}")

        lines = [
            "AreaDay is not starting: no usable OpenAlex API key is configured.",
            str(error),
            f"Credentials file: {credentials}",
            f"Get the key from {OPENALEX_SETTINGS_URL} (free; about 22 characters).",
            (
                f"It was opened with {opened}; paste the key after 'api_key =' and save it."
                if opened
                else "Open that file in a text editor and paste the key after 'api_key ='."
            ),
            "Then run this command again. Nothing else runs until then.",
        ]
        guide = Path(__file__).resolve().parent.parent / "assets" / "openalex-help.html"
        if guide.is_file():
            lines.append(f"Illustrated steps: {guide}")
        print("\n".join(lines))
        return EXIT_MISSING_KEY
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"), nargs="?", default="run")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("--target-papers", type=int, default=70)
    parser.add_argument("--download-workers", type=int, default=4)
    parser.add_argument("--download-workers-per-host", type=int, default=2)
    parser.add_argument(
        "--port",
        type=int,
        help="Preferred workbench port; defaults to 8765.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not launch a text editor when the OpenAlex key is missing",
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=int,
        default=DEFAULT_WORKBENCH_IDLE_TIMEOUT_SECONDS,
        help="Stop the calibration workbench after this many idle seconds.",
    )
    args = parser.parse_args()
    if not 1 <= args.target_papers <= 100:
        parser.error("--target-papers must be between 1 and 100")
    if args.download_workers < 1:
        parser.error("--download-workers must be positive")
    if not 1 <= args.download_workers_per_host <= args.download_workers:
        parser.error("--download-workers-per-host must be between 1 and --download-workers")
    if args.port is None:
        args.port = default_port()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.idle_timeout_seconds < 0:
        parser.error("--idle-timeout-seconds must be zero or positive")
    return args


def main() -> int:
    args = parse_args()
    if args.command == "run":
        stopped = openalex_key_gate(open_editor=not args.no_open)
        if stopped is not None:
            return stopped
    controller = InitializationController(args)
    try:
        if args.command == "status":
            controller.inspect()
        else:
            controller.run()
        return 0
    except ResumeScopeError as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "terminal": False,
                    "error": str(error),
                    "authoritative_status": str(controller.status_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    except (InitializationError, FileNotFoundError, ValueError) as error:
        controller._status(
            "failed",
            terminal=False,
            checkpoint="blocked",
            error=str(error),
            next_action={
                "actor": "current_host_agent",
                "type": "diagnose_and_resume",
                "resume": controller.resume_command(),
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
