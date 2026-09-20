from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from initialize import (  # noqa: E402
    EXIT_MISSING_KEY,
    InitializationController,
    InitializationError,
    openalex_key_gate,
)
from initialize import main as initialize_main  # noqa: E402
from open_workbench import WorkbenchConflict  # noqa: E402
from tests.test_initial_pipeline import valid_test_profile  # noqa: E402


def controller_args(root: Path) -> argparse.Namespace:
    profile = root / "profile.json"
    profile.write_text(json.dumps(valid_test_profile()), encoding="utf-8")
    return argparse.Namespace(
        command="run",
        profile=profile,
        workspace=root / "workspace",
        registry=root / "registry.json",
        target_papers=10,
        download_workers=2,
        download_workers_per_host=1,
        port=43131,
    )


class InitializationControllerTests(unittest.TestCase):
    def test_candidate_shortfall_requests_a_new_agent_strategy_not_user_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            controller.workspace.mkdir(parents=True)
            (controller.workspace / "candidates.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-packet.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-summary.json").write_text(
                json.dumps({"candidate_count": 1}), encoding="utf-8"
            )
            (controller.workspace / "research-profile.json").write_text(
                json.dumps(valid_test_profile()), encoding="utf-8"
            )
            (controller.workspace / "search-attempts.json").write_text(
                "[]\n", encoding="utf-8"
            )

            with self.assertRaises(StopIteration):
                controller._prepare_assets()

            status = json.loads(controller.status_path.read_text(encoding="utf-8"))
            self.assertEqual(
                status["next_action"]["type"], "design_retrieval_strategy"
            )
            self.assertEqual(
                status["next_action"]["actor"], "current_host_agent"
            )
            self.assertTrue(
                status["next_action"]["output"].endswith(
                    "retrieval-strategy-02.json"
                )
            )

    def test_three_failed_strategies_end_only_when_no_usable_pdf_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            controller.workspace.mkdir(parents=True)
            (controller.workspace / "candidates.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-packet.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-summary.json").write_text(
                json.dumps({"candidate_count": 1}), encoding="utf-8"
            )
            (controller.workspace / "retrieval-strategy-state.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "maximum_strategy_count": 3,
                        "attempts": [
                            {"strategy_id": f"attempt-{index}"}
                            for index in range(1, 4)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (controller.workspace / "candidate-review-selection-03.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (controller.workspace / "cold-start-summary.json").write_text(
                json.dumps({"has_usable_pdfs": False, "successful_pdfs": 0}),
                encoding="utf-8",
            )

            with (
                patch.object(controller, "_run_helper"),
                self.assertRaises(StopIteration),
            ):
                controller._prepare_assets()

            status = json.loads(controller.status_path.read_text(encoding="utf-8"))
            self.assertTrue(status["terminal"])
            self.assertEqual(status["status"], "corpus_unavailable")
            self.assertEqual(
                status["next_action"]["type"], "provide_local_pdfs_later"
            )
            self.assertEqual(status["next_action"]["successful_pdfs"], 0)

    def test_twenty_usable_pdfs_continue_after_search_strategies_are_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = controller_args(root)
            args.target_papers = 70
            controller = InitializationController(args)
            analysis = controller.workspace / "analysis"
            analysis.mkdir(parents=True)
            (controller.workspace / "candidates.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-packet.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-selection-03.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (controller.workspace / "retrieval-strategy-state.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "maximum_strategy_count": 3,
                        "attempts": [
                            {"strategy_id": f"attempt-{index}"}
                            for index in range(1, 4)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (controller.workspace / "cold-start-summary.json").write_text(
                json.dumps({"has_usable_pdfs": True, "successful_pdfs": 20}),
                encoding="utf-8",
            )
            (analysis / "orthography-review-input.json").write_text(
                '{"candidates":[]}\n', encoding="utf-8"
            )
            (analysis / "terminology-review-input.json").write_text(
                '{"candidates":[]}\n', encoding="utf-8"
            )

            with self.assertRaises(StopIteration):
                controller._prepare_assets()

            status = json.loads(controller.status_path.read_text(encoding="utf-8"))
            self.assertFalse(status["terminal"])
            self.assertEqual(status["checkpoint"], "orthography_review_needed")

    def test_workbench_conflict_is_a_clean_error_instead_of_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            registry = SimpleNamespace(
                register=lambda *_args, **_kwargs: SimpleNamespace(
                    domain_id="test-domain"
                )
            )
            denial = WorkbenchConflict(
                "AreaDay cannot bind a loopback port anywhere in the candidate "
                "range 43131-43140. Every attempt was refused by the operating "
                "system or by the sandbox rather than by another service."
            )
            with (
                patch("initialize.DomainRegistry", return_value=registry),
                patch(
                    "initialize.launchable_registry_domain_ids",
                    return_value=("test-domain",),
                ),
                patch("initialize.ensure_workbench", side_effect=denial),
            ):
                with self.assertRaises(InitializationError) as raised:
                    controller._launch_and_verify({"profile_id": "test-domain"})

            self.assertIn(
                "refused by the operating system or by the sandbox",
                str(raised.exception),
            )

    def test_launch_verification_uses_the_selected_fallback_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            analysis = controller.workspace / "analysis"
            analysis.mkdir(parents=True)
            (analysis / "vocabulary-map.tsv").write_text(
                "lemma\tpart_of_speech\ttotal_count\tdocument_count\tdocument_share\n"
                + "".join(
                    f"word{index}\tnoun\t1\t1\t1.0\n" for index in range(30)
                ),
                encoding="utf-8",
            )
            selected_port = controller.args.port + 1
            launch = {
                "status": "started",
                "instance_id": "fallback-instance",
                "domain_id": "test-domain",
                "port": selected_port,
                "url": (
                    f"http://127.0.0.1:{selected_port}/"
                    "?domain=test-domain#vocabulary"
                ),
            }
            app_state = {
                "domain_id": "test-domain",
                "calibration": {
                    "question_limit": 30,
                    "complete": False,
                    "word": {},
                    "answered": 0,
                },
                "terminology": {"count": 0, "terms": []},
            }
            terms_api = {"count": 0, "terms": []}
            registry = SimpleNamespace(
                register=lambda *_args, **_kwargs: SimpleNamespace(
                    domain_id="test-domain"
                )
            )
            identity_probe = SimpleNamespace(
                kind=SimpleNamespace(value="match"),
                identity={"instance_id": "fallback-instance"},
            )

            with (
                patch("initialize.DomainRegistry", return_value=registry),
                patch(
                    "initialize.launchable_registry_domain_ids",
                    return_value=("test-domain",),
                ),
                patch("initialize.ensure_workbench", return_value=launch),
                patch(
                    "initialize.probe_workbench",
                    return_value=identity_probe,
                ) as probe,
                patch(
                    "initialize._json_get",
                    side_effect=[app_state, terms_api],
                ) as json_get,
                patch(
                    "initialize.load_finalized_terminology",
                    return_value=(
                        [],
                        {},
                        {"selected_terminology_count": 0},
                    ),
                ),
            ):
                result = controller._launch_and_verify(
                    {"profile_id": "test-domain"}
                )

            self.assertEqual(result["port"], selected_port)
            self.assertEqual(probe.call_args.args[0], selected_port)
            self.assertEqual(
                [call.args[0] for call in json_get.call_args_list],
                [selected_port, selected_port],
            )

    def test_host_review_is_nonterminal_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            controller.workspace.mkdir(parents=True)
            packet = controller.workspace / "candidate-review-packet.jsonl"
            packet.write_text('{"candidate_id":"W1"}\n', encoding="utf-8")
            selection = controller.workspace / "candidate-review-selection.json"

            payload = controller._host_action(
                "review_candidates",
                input_path=packet,
                output_path=selection,
                checkpoint="candidate_review_needed",
                instructions="Review and resume.",
            )

            self.assertFalse(payload["terminal"])
            self.assertEqual(payload["status"], "host_action_required")
            self.assertEqual(payload["next_action"]["actor"], "current_host_agent")
            self.assertEqual(payload["next_action"]["input"], str(packet))
            self.assertNotIn("input_sha256", payload["next_action"])

    def test_learning_asset_review_has_both_inputs_and_one_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            controller.workspace.mkdir(parents=True)
            terminology = controller.workspace / "terminology-review-input.json"
            vocabulary_batch = controller.workspace / "vocabulary-card-review-batch.json"
            terminology.write_text("{}\n", encoding="utf-8")
            vocabulary_batch.write_text("{}\n", encoding="utf-8")
            selection = controller.workspace / "selection.json"

            payload = controller._host_action(
                "review_vocabulary_cards_and_terminology",
                input_paths={
                    "terminology": terminology,
                    "vocabulary_card_review_batch": vocabulary_batch,
                },
                output_path=selection,
                checkpoint="learning_asset_review_needed",
                instructions="Review both and resume.",
            )

            self.assertEqual(
                payload["next_action"]["inputs"],
                {
                    "terminology": str(terminology),
                    "vocabulary_card_review_batch": str(vocabulary_batch),
                },
            )
            self.assertEqual(payload["next_action"]["output"], str(selection))

    def test_orthography_review_is_requested_before_card_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            analysis = controller.workspace / "analysis"
            analysis.mkdir(parents=True)
            (controller.workspace / "candidates.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-packet.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-selection.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (controller.workspace / "cold-start-summary.json").write_text(
                '{"has_usable_pdfs":true,"successful_pdfs":1}\n', encoding="utf-8"
            )
            (analysis / "orthography-review-input.json").write_text(
                '{"candidates":[{"observed_lemma":"whic"}]}\n',
                encoding="utf-8",
            )
            (analysis / "orthography-review-summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "reviewer": "current-host-agent",
                        "reviewed_candidate_count": 1,
                        "replacement_count": 0,
                        "drop_count": 0,
                        "unchanged_candidate_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            (analysis / "terminology-review-input.json").write_text(
                '{"candidates":[]}\n', encoding="utf-8"
            )

            with patch("initialize.prepare_review_input") as prepare_cards:
                with self.assertRaises(StopIteration):
                    controller._prepare_assets()

            prepare_cards.assert_not_called()
            status = json.loads(controller.status_path.read_text(encoding="utf-8"))
            self.assertEqual(
                status["next_action"]["type"], "review_vocabulary_orthography"
            )
            self.assertEqual(
                status["next_action"]["input"],
                str(analysis / "orthography-review-input.json"),
            )

    def test_completed_batch_with_a_drop_advances_to_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = InitializationController(controller_args(root))
            analysis = controller.workspace / "analysis"
            analysis.mkdir(parents=True)
            (controller.workspace / "candidates.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-packet.jsonl").write_text(
                '{"candidate_id":"W1"}\n', encoding="utf-8"
            )
            (controller.workspace / "candidate-review-selection.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (controller.workspace / "cold-start-summary.json").write_text(
                '{"has_usable_pdfs":true,"successful_pdfs":1}\n', encoding="utf-8"
            )
            (analysis / "orthography-review-input.json").write_text(
                '{"candidates":[]}\n', encoding="utf-8"
            )
            (analysis / "orthography-review-summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "reviewer": "current-host-agent",
                        "reviewed_candidate_count": 0,
                        "replacement_count": 0,
                        "drop_count": 0,
                        "explicit_keep_count": 0,
                        "unchanged_candidate_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            (analysis / "terminology-review-input.json").write_text(
                '{"candidates":[]}\n', encoding="utf-8"
            )
            candidates = [
                {
                    "observed_lemma": f"word{index}" if index < 6 else "geotagging",
                    "representative_sentences": [],
                    "dictionary_candidates": [],
                    "acronym_expansions": [],
                }
                for index in range(1, 7)
            ]
            batches = []
            for index, candidate in enumerate(candidates, start=1):
                path = analysis / f"batch-{index:03d}.json"
                output = analysis / f"batch-{index:03d}-output.json"
                path.write_text(
                    json.dumps({"candidate_count": 1, "candidates": [candidate]}),
                    encoding="utf-8",
                )
                result = {
                    "schema_version": 1,
                    "reviewer": "current-host-agent",
                    "vocabulary_card_review_schema_version": 3,
                    "vocabulary_card_glosses": (
                        {}
                        if candidate["observed_lemma"] == "geotagging"
                        else {
                            candidate["observed_lemma"]: {
                                "meaning_zh": f"词{index}",
                                "sense_key": f"word-{index}",
                                "context_rationale": "Meaning is clear in context.",
                            }
                        }
                    ),
                    "vocabulary_card_drops": (
                        ["geotagging"]
                        if candidate["observed_lemma"] == "geotagging"
                        else []
                    ),
                }
                if index == 1:
                    result["terminology"] = {}
                    result["terminology_explanations"] = {}
                output.write_text(json.dumps(result), encoding="utf-8")
                batches.append(
                    {
                        "batch_index": index,
                        "candidate_count": 1,
                        "path": str(path),
                        "output": str(output),
                        "lemmas": [candidate["observed_lemma"]],
                    }
                )
            (analysis / "vocabulary-card-review-input.json").write_text(
                json.dumps(
                    {
                        "candidate_count": 6,
                        "batch_count": 6,
                        "batches": batches,
                    }
                ),
                encoding="utf-8",
            )

            def complete_finalization(*_args, **_kwargs):
                (analysis / "domain-assets-summary.json").write_text(
                    json.dumps(
                        {
                            "ready_for_calibration": True,
                            "vocabulary_cards": {
                                "semantic_review_contract_version": 3
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            with (
                patch("initialize.prepare_review_input"),
                patch.object(
                    controller, "_run_helper", side_effect=complete_finalization
                ) as run_helper,
            ):
                controller._prepare_assets()

            run_helper.assert_called_once()
            self.assertIn(
                "finalize_domain_assets.py",
                " ".join(str(value) for value in run_helper.call_args.args[0]),
            )

    def test_verified_service_is_the_only_successful_terminal_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = controller_args(root)
            controller = InitializationController(args)
            service = {
                "status": "started",
                "instance_id": "verified-instance",
                "domain_id": "test-domain",
                "url": "http://127.0.0.1:43131/?domain=test-domain#vocabulary",
                "vocabulary_ready": True,
                "terminology_ready": True,
            }
            with (
                patch.object(controller, "_prepare_assets"),
                patch("initialize.validate_initialized_workspace"),
                patch.object(controller, "_launch_and_verify", return_value=service),
            ):
                payload = controller.run()

            self.assertTrue(payload["terminal"])
            self.assertEqual(payload["status"], "awaiting_user_calibration")
            self.assertEqual(payload["checkpoint"], "calibration_ready")
            self.assertEqual(payload["next_action"]["actor"], "user")
            self.assertTrue(payload["service"]["vocabulary_ready"])
            self.assertTrue(payload["service"]["terminology_ready"])


class OpenAlexKeyGateTests(unittest.TestCase):
    """A missing key stops the run before it touches the workspace."""

    def test_gate_hands_over_the_file_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            credentials = Path(temporary) / "config" / "credentials.ini"
            printed = io.StringIO()
            with patch("initialize.credentials_path", return_value=credentials), patch(
                "initialize.load_openalex_api_key",
                side_effect=RuntimeError("AreaDay needs a personal OpenAlex API key."),
            ), patch("initialize.open_in_editor", return_value="open") as editor, contextlib.redirect_stdout(
                printed
            ):
                code = openalex_key_gate()

            self.assertEqual(code, EXIT_MISSING_KEY)
            editor.assert_called_once_with(credentials)
            self.assertTrue(credentials.is_file())
            self.assertIn("api_key =", credentials.read_text(encoding="utf-8"))
            message = printed.getvalue()
            self.assertIn("no usable OpenAlex API key", message)
            self.assertIn("Then run this command again. Nothing else runs until then.", message)

    def test_gate_can_skip_the_editor_without_skipping_the_handover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            credentials = Path(temporary) / "config" / "credentials.ini"
            with patch("initialize.credentials_path", return_value=credentials), patch(
                "initialize.load_openalex_api_key",
                side_effect=RuntimeError("AreaDay needs a personal OpenAlex API key."),
            ), patch("initialize.open_in_editor") as editor, contextlib.redirect_stdout(io.StringIO()):
                code = openalex_key_gate(open_editor=False)

            self.assertEqual(code, EXIT_MISSING_KEY)
            editor.assert_not_called()
            self.assertTrue(credentials.is_file())

    def test_gate_accepts_a_configured_key(self) -> None:
        with patch.dict(os.environ, {"OPENALEX_API_KEY": "A" * 22}):
            self.assertIsNone(openalex_key_gate())

    def test_main_stops_before_the_controller_touches_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            credentials = root / "config" / "credentials.ini"
            profile = root / "profile.json"
            profile.write_text(json.dumps(valid_test_profile()), encoding="utf-8")
            workspace = root / "workspace"
            argv = [
                "initialize.py",
                "run",
                "--profile",
                str(profile),
                "--workspace",
                str(workspace),
                "--no-open",
            ]
            with patch.object(sys, "argv", argv), patch(
                "initialize.credentials_path", return_value=credentials
            ), patch(
                "initialize.load_openalex_api_key",
                side_effect=RuntimeError("AreaDay needs a personal OpenAlex API key."),
            ), contextlib.redirect_stdout(io.StringIO()):
                code = initialize_main()

            self.assertEqual(code, EXIT_MISSING_KEY)
            self.assertFalse(workspace.exists())


if __name__ == "__main__":
    unittest.main()
