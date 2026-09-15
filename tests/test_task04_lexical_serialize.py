from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import acquire_mini_corpus  # noqa: E402
import corpus_analysis_stage  # noqa: E402
import lexical_assets  # noqa: E402


class _Token:
    def __init__(self, text: str, lemma: str, pos: str) -> None:
        self.text, self.lemma_, self.pos_ = text, lemma, pos
        self.is_alpha, self.is_stop, self.like_num, self.is_punct = text.isalpha(), False, False, False


class _Sentence:
    start, end = 0, 5

    def __init__(self, tokens: list[_Token]) -> None:
        self.text = "Model supports robust analysis with contextual evidence."
        self.tokens = tokens

    def __iter__(self):
        return iter(self.tokens)


class _Chunk:
    def __init__(self, sentence: _Sentence, tokens: list[_Token]) -> None:
        self.text, self.sent, self.tokens = "robust analysis", sentence, tokens

    def __iter__(self):
        return iter(self.tokens)


class _Doc:
    def __init__(self, variant: str = "") -> None:
        model_surface = "MODEL" if variant == "2" else ("model" if variant == "3" else "Model")
        model_pos = "VERB" if variant == "2" else "NOUN"
        tokens = [_Token(model_surface, "model", model_pos), _Token("supports", "support", "VERB"), _Token("robust", "robust", "ADJ"), _Token("analysis", "analysis", "NOUN"), _Token("evidence", "evidence", "NOUN")]
        sentence = _Sentence(tokens)
        chunk = _Chunk(sentence, tokens[2:4])
        chunk.text = "Robust analysis" if variant != "3" else "robust analysis"
        self.tokens, self.sents, self.noun_chunks = tokens, [sentence], [chunk]

    def __iter__(self):
        return iter(self.tokens)

    def __len__(self):
        return len(self.tokens)


class _NLP:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def pipe(self, texts, *, batch_size: int, n_process: int):
        self.calls.append((batch_size, n_process))
        for text in texts:
            yield _Doc(str(text)[-1:] if str(text)[-1:] in {"1", "2", "3"} else "")


class Task04Tests(unittest.TestCase):
    def _complete_fixture(self, analysis: Path) -> None:
        analysis.mkdir(parents=True, exist_ok=True)
        stats = {
            "schema_version": 2,
            "outputs": {
                "vocabulary_tsv": "analysis/vocabulary-map.tsv",
                "vocabulary_jsonl": "analysis/vocabulary-map.jsonl",
                "terminology_tsv": "analysis/terminology-candidates.tsv",
                "terminology_jsonl": "analysis/terminology-candidates.jsonl",
                "raw_terminology_jsonl": "analysis/raw-terminology-candidates.jsonl",
                "terminology_review_input": "analysis/terminology-review-input.json",
                "orthography_review_input": "analysis/orthography-review-input.json",
                "paper_decisions": "analysis/paper-decisions.jsonl",
                "text": "analysis/text/",
                "report": "analysis/summary.md",
            },
        }
        (analysis / "corpus-stats.json").write_text(json.dumps(stats), encoding="utf-8")
        for name in ("orthography-review-input.json", "terminology-review-input.json"):
            (analysis / name).write_text("{}", encoding="utf-8")
        for name in ("pre-orthography-vocabulary-map.jsonl", "vocabulary-map.jsonl", "raw-terminology-candidates.jsonl", "terminology-candidates.jsonl", "paper-decisions.jsonl", "papers.jsonl"):
            (analysis / name).write_text("{}\n", encoding="utf-8")
        for name in ("pre-orthography-vocabulary-map.tsv", "vocabulary-map.tsv", "vocabulary.tsv", "raw-terminology-candidates.tsv", "terminology-candidates.tsv"):
            (analysis / name).write_text("header\n", encoding="utf-8")
        (analysis / "summary.md").write_text("complete", encoding="utf-8")

    def test_completion_validator_rejects_each_partial_output(self) -> None:
        names = ["corpus-stats.json", "orthography-review-input.json", "pre-orthography-vocabulary-map.jsonl", "vocabulary-map.jsonl", "vocabulary.tsv", "summary.md"]
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                analysis = Path(directory) / "analysis"
                self._complete_fixture(analysis)
                (analysis / name).unlink()
                self.assertFalse(acquire_mini_corpus._analysis_outputs_complete(analysis))

    def test_completion_validator_accepts_complete_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analysis = Path(directory) / "analysis"
            self._complete_fixture(analysis)
            self.assertTrue(acquire_mini_corpus._analysis_outputs_complete(analysis))

    def test_chunker_enforces_character_and_token_bounds(self) -> None:
        for source in ("x" * 100001, "word " * 10001):
            chunks = list(lexical_assets.text_chunks(source))
            self.assertTrue(chunks)
            self.assertTrue(all(len(chunk) <= 50000 for chunk in chunks))
            self.assertTrue(all(len(chunk.split()) <= 10000 for chunk in chunks))

    def test_raw_document_is_explicit_single_document_opt_in(self) -> None:
        documents = [{"openalex_id": "W1", "clean_text": "source"}]
        default = lexical_assets.build_lexical_assets(documents, nlp=_NLP())
        self.assertNotIn("raw_document", default)
        self.assertEqual(set(default), {"vocabulary", "terminology_candidates", "included_document_count", "processed_spacy_token_count", "content_lemma_token_count", "minimum_document_count"})
        opted = lexical_assets.build_lexical_assets(documents, nlp=_NLP(), include_raw_document=True)
        self.assertIn("raw_document", opted)
        with self.assertRaises(ValueError):
            lexical_assets.build_lexical_assets(documents * 3, nlp=_NLP(), include_raw_document=True)

    def test_chunker_preserves_normalized_character_and_word_order(self) -> None:
        source = "First paragraph stays whole.\n\nSecond paragraph also stays whole."
        chunks = list(lexical_assets.text_chunks(source))
        self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(source.split()))
        long_sentence = "Sentence one. " * 5000
        pieces = list(lexical_assets.text_chunks(long_sentence, maximum_characters=1000, maximum_tokens=1000))
        self.assertGreater(len(pieces), 1)
        self.assertEqual(" ".join(" ".join(pieces).split()), " ".join(long_sentence.split()))
        hard = "token " * 100 + "unbroken" * 1000
        hard_pieces = list(lexical_assets.text_chunks(hard, maximum_characters=100, maximum_tokens=1000))
        self.assertGreater(len(hard_pieces), 1)
        self.assertEqual("".join(hard_pieces), hard.strip())

    def test_chunker_tracks_tokens_when_accumulating_paragraphs(self) -> None:
        source = ("word " * 6000).strip() + "\n\n" + ("next " * 6000).strip()
        chunks = list(lexical_assets.text_chunks(source))
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk.split()) <= 10000 for chunk in chunks))
        self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(source.split()))

    def test_controller_order_and_admission_control(self) -> None:
        calls: list[str] = []

        def runner(command, *, check):
            self.assertTrue(check)
            calls.append(command[2])

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = acquire_mini_corpus.run_analysis_stages(
                workspace, python_executable="python", run=runner,
                memory_reader=lambda: 512 * 1024 * 1024,
            )
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["extract", "select", "lexical", "serialize"])
        self.assertEqual(
            acquire_mini_corpus.run_analysis_stages(
                Path(directory), run=runner, memory_reader=lambda: 1
            ),
            acquire_mini_corpus.INSUFFICIENT_MEMORY_CODE,
        )

    def test_invalid_selection_checkpoint_cannot_skip_select(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            (analysis / "paper-work-records.jsonl").write_text("{}\n", encoding="utf-8")
            (analysis / "selection-summary.json").write_text("{}", encoding="utf-8")
            calls: list[str] = []
            acquire_mini_corpus.run_analysis_stages(
                workspace, run=lambda command, **kwargs: calls.append(command[2]),
                memory_reader=lambda: 512 * 1024 * 1024,
            )
            self.assertEqual(calls, ["select", "lexical", "serialize"])

    def test_monitored_analysis_stops_on_success_low_memory_and_child_failure(self) -> None:
        for outcome in (0, acquire_mini_corpus.INSUFFICIENT_MEMORY_CODE, subprocess.CalledProcessError(1, ["stage"])):
            with self.subTest(outcome=type(outcome).__name__):
                monitor = MagicMock()
                monitor.start.return_value = monitor
                run_patch = patch.object(acquire_mini_corpus, "run_analysis_stages", side_effect=outcome) if isinstance(outcome, BaseException) else patch.object(acquire_mini_corpus, "run_analysis_stages", return_value=outcome)
                with patch.object(acquire_mini_corpus, "SystemMemoryMonitor", return_value=monitor), run_patch:
                    if isinstance(outcome, BaseException):
                        with self.assertRaises(subprocess.CalledProcessError):
                            acquire_mini_corpus._run_monitored_analysis(Path("/tmp/task04-monitor-test"))
                    else:
                        self.assertEqual(acquire_mini_corpus._run_monitored_analysis(Path("/tmp/task04-monitor-test")), outcome)
                monitor.start.assert_called_once()
                monitor.stop.assert_called_once()

    def test_real_short_lived_stage_processes_have_distinct_exited_pids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            pids: list[int] = []

            def runner(command, *, check):
                marker = workspace / f"pid-{len(pids)}"
                child = subprocess.Popen([sys.executable, "-c", f"from pathlib import Path; import os; Path({str(marker)!r}).write_text(str(os.getpid()))"])
                pid = child.pid
                child.wait(timeout=5)
                self.assertTrue(check)
                pids.append(pid)

            self.assertEqual(acquire_mini_corpus.run_analysis_stages(workspace, run=runner, memory_reader=lambda: 512 * 1024 * 1024), 0)
            self.assertEqual(len(pids), 4)
            self.assertEqual(len(set(pids)), 4)
            self.assertTrue(all(not Path(f"/proc/{pid}").exists() for pid in pids))

    def test_unsupported_platform_memory_is_ungated(self) -> None:
        with patch.object(acquire_mini_corpus.platform, "system", return_value="Darwin"):
            self.assertIsNone(acquire_mini_corpus.read_mem_available_bytes())
        calls: list[str] = []
        result = acquire_mini_corpus.run_analysis_stages(
            Path(tempfile.mkdtemp()), run=lambda command, **kwargs: calls.append(command[2]),
            memory_reader=lambda: None,
        )
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["extract", "select", "lexical", "serialize"])

    def test_sqlite_checkpoint_and_streamed_serialize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            text_path = analysis / "paper.txt"
            text_path.write_text("model supports robust analysis", encoding="utf-8")
            record = {"openalex_id": "W1", "status": "extracted", "text": str(text_path), "body_word_count": 5}
            (analysis / "paper-work-records.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            (analysis / "selection-summary.json").write_text(json.dumps({"included_work_ids": ["W1"], "duplicate_count": 2, "low_relevance_count": 3, "relevance_cutoff": 0.42}), encoding="utf-8")
            nlp = _NLP()
            with patch.object(lexical_assets, "load_spacy_pipeline", return_value=nlp):
                self.assertEqual(corpus_analysis_stage.lexical(workspace), 0)
            self.assertEqual(nlp.calls, [(1, 1)])
            db_path = analysis / ".lexical-work.sqlite3"
            connection = corpus_analysis_stage._open_lexical_db(db_path)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"documents", "lemma", "term", "surface", "example", "acronym", "stats"} <= tables)
            self.assertEqual(connection.execute("PRAGMA temp_store").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA cache_size").fetchone()[0], -16384)
            self.assertEqual(connection.execute("PRAGMA mmap_size").fetchone()[0], 0)
            connection.close()
            self.assertEqual(corpus_analysis_stage.serialize(workspace), 0)
            self.assertFalse(db_path.exists())
            stats = json.loads((analysis / "corpus-stats.json").read_text(encoding="utf-8"))
            self.assertEqual(stats["duplicate_paper_count"], 2)
            self.assertEqual(stats["low_relevance_paper_count"], 3)
            self.assertEqual(stats["relevance_cutoff"], 0.42)

    def test_empty_included_ids_process_zero_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            text_path = analysis / "excluded.txt"
            text_path.write_text("excluded content", encoding="utf-8")
            (analysis / "paper-work-records.jsonl").write_text(
                json.dumps({"openalex_id": "W1", "status": "extracted", "text": str(text_path)}) + "\n",
                encoding="utf-8",
            )
            (analysis / "selection-summary.json").write_text(
                json.dumps({"included_work_ids": []}), encoding="utf-8"
            )
            nlp = _NLP()
            with patch.object(lexical_assets, "load_spacy_pipeline", return_value=nlp):
                corpus_analysis_stage.lexical(workspace)
            self.assertEqual(nlp.calls, [])
            connection = sqlite3.connect(analysis / ".lexical-work.sqlite3")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
            connection.close()

    def test_serialize_write_failure_keeps_checkpoint_and_invalidates_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            (analysis / "selection-summary.json").write_text(json.dumps({"included_work_ids": []}), encoding="utf-8")
            corpus_analysis_stage._open_lexical_db(analysis / ".lexical-work.sqlite3").close()
            with patch("corpus_analysis.serialize_lexical_stage", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    corpus_analysis_stage.serialize(workspace)
            self.assertTrue((analysis / ".lexical-work.sqlite3").exists())
            self.assertFalse((analysis / "corpus-stats.json").exists())
            self.assertFalse(any(path.name.startswith(".lexical-serialize-staging-") for path in analysis.iterdir()))
            self.assertFalse(acquire_mini_corpus._analysis_outputs_complete(analysis))

    def test_serialize_publication_failure_keeps_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            (analysis / "selection-summary.json").write_text(json.dumps({"included_work_ids": []}), encoding="utf-8")
            corpus_analysis_stage._open_lexical_db(analysis / ".lexical-work.sqlite3").close()
            real_replace = corpus_analysis_stage.os.replace
            raised = False

            def fail_after_staging(source, destination):
                nonlocal raised
                if "lexical-serialize-staging" in str(source) and not raised:
                    raised = True
                    raise OSError("injected publication failure")
                return real_replace(source, destination)

            with patch.object(corpus_analysis_stage.os, "replace", side_effect=fail_after_staging):
                with self.assertRaises(OSError):
                    corpus_analysis_stage.serialize(workspace)
            self.assertTrue((analysis / ".lexical-work.sqlite3").exists())
            self.assertFalse((analysis / "corpus-stats.json").exists())
            self.assertFalse(any(path.name.startswith(".lexical-serialize-staging-") for path in analysis.iterdir()))

    def test_serialize_corrupt_staging_output_keeps_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            (analysis / "selection-summary.json").write_text(json.dumps({"included_work_ids": []}), encoding="utf-8")
            corpus_analysis_stage._open_lexical_db(analysis / ".lexical-work.sqlite3").close()
            import corpus_analysis
            real_stage = corpus_analysis.serialize_lexical_stage

            def corrupt(*args, **kwargs):
                result = real_stage(*args, **kwargs)
                kwargs["staging_dir"].joinpath("vocabulary-map.jsonl").write_text("{broken", encoding="utf-8")
                return result

            with patch.object(corpus_analysis, "serialize_lexical_stage", side_effect=corrupt):
                with self.assertRaises(ValueError):
                    corpus_analysis_stage.serialize(workspace)
            self.assertTrue((analysis / ".lexical-work.sqlite3").exists())
            self.assertFalse((analysis / "corpus-stats.json").exists())
            self.assertFalse(any(path.name.startswith(".lexical-serialize-staging-") for path in analysis.iterdir()))

    def test_three_document_sqlite_assets_match_legacy_and_exclude_fourth(self) -> None:
        documents = [
            {"openalex_id": "W1", "clean_text": "Robust Analysis supports model evidence (RA). 1"},
            {"openalex_id": "W2", "clean_text": "Robust Analysis supports model evidence (RA). 2"},
            {"openalex_id": "W3", "clean_text": "Robust Analysis supports model evidence (RA). 3"},
        ]
        expected = lexical_assets.build_lexical_assets(documents, nlp=_NLP())
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = workspace / "analysis"
            analysis.mkdir()
            records = []
            for document in documents + [{"openalex_id": "W4", "clean_text": "excluded"}]:
                text_path = analysis / f"{document['openalex_id']}.txt"
                text_path.write_text(document["clean_text"], encoding="utf-8")
                records.append({"openalex_id": document["openalex_id"], "status": "extracted", "text": str(text_path), "body_word_count": 10})
            (analysis / "paper-work-records.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            (analysis / "selection-summary.json").write_text(json.dumps({"included_work_ids": ["W1", "W2", "W3"], "duplicate_count": 1, "low_relevance_count": 1, "relevance_cutoff": 0.2}), encoding="utf-8")
            with patch.object(lexical_assets, "load_spacy_pipeline", return_value=_NLP()):
                corpus_analysis_stage.lexical(workspace)
            actual = lexical_assets.assets_from_sqlite(analysis / ".lexical-work.sqlite3")
            for key in ("vocabulary", "terminology_candidates", "included_document_count", "processed_spacy_token_count", "content_lemma_token_count", "minimum_document_count"):
                self.assertEqual(actual[key], expected[key], key)
            selected_expected = lexical_assets.select_shared_terminology_candidates(expected["terminology_candidates"], 3)
            selected_actual = lexical_assets.select_shared_terminology_candidates(actual["terminology_candidates"], 3)
            self.assertEqual(selected_actual, selected_expected)
            self.assertEqual(corpus_analysis_stage.serialize(workspace), 0)
            decisions = [json.loads(line) for line in (analysis / "paper-decisions.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["openalex_id"] for row in decisions], ["W1", "W2", "W3", "W4"])
            stats = json.loads((analysis / "corpus-stats.json").read_text(encoding="utf-8"))
            self.assertEqual((stats["duplicate_paper_count"], stats["low_relevance_paper_count"]), (1, 1))

    def test_import_and_serialize_subprocess_do_not_load_nlp_backends(self) -> None:
        code = "import sys; import acquire_mini_corpus, corpus_analysis_stage; assert 'spacy' not in sys.modules; assert 'onnxruntime' not in sys.modules; assert 'onnx_embeddings' not in sys.modules"
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=dict(os.environ, PYTHONPATH=str(ROOT / "scripts")),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sqlite_reader_contract_is_fetchmany_only(self) -> None:
        source = Path(ROOT / "scripts" / "lexical_assets.py").read_text(encoding="utf-8")
        streamed = source[source.index("def assets_from_sqlite"):]
        self.assertIn("fetchmany", streamed)
        self.assertNotIn("fetchall", streamed)


if __name__ == "__main__":
    unittest.main()
