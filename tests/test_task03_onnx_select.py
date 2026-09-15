import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


class BatchConfigurationTests(unittest.TestCase):
    def test_environment_batch_values(self):
        module = importlib.import_module("onnx_embeddings")
        cases = [(None, 32), ("1", 1), ("32", 32)]
        for value, expected in cases:
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ["AREADAY_ONNX_BATCH_SIZE"] = value
                self.assertEqual(module.configured_batch_size(), expected)
        for value in ("", "0", "33", "1.5", "abc", " 1", "1 ", "+1", "１"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"AREADAY_ONNX_BATCH_SIZE": value}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "AREADAY_ONNX_BATCH_SIZE"):
                    module.configured_batch_size()

    def test_explicit_encode_batch_is_strict(self):
        module = importlib.import_module("onnx_embeddings")
        encoder = object.__new__(module.OnnxSentenceEncoder)
        encoder.dimension = 2
        for value in (1, 32):
            with self.subTest(value=value), patch.dict(
                os.environ, {}, clear=True
            ):
                result = encoder.encode([], batch_size=value)
                self.assertEqual(result.shape, (0, 2))
        with patch.dict(os.environ, {"AREADAY_ONNX_BATCH_SIZE": "1"}, clear=True):
            self.assertEqual(encoder.encode([]).shape, (0, 2))
        for value in (True, False, 1.0, "1", 0, -1, 33):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    encoder.encode([], batch_size=value)


class OnnxRuntimeOptionsTests(unittest.TestCase):
    def test_session_options_are_bounded(self):
        module = importlib.import_module("onnx_embeddings")
        class Input:
            def __init__(self, name): self.name = name
        class Options:
            instances = []
            def __init__(self): self.__class__.instances.append(self)
        class Runtime:
            ExecutionMode = type("ExecutionMode", (), {"ORT_SEQUENTIAL": "sequential"})
            SessionOptions = Options
            def disable_telemetry_events(self): pass
            def InferenceSession(self, path, **kwargs):
                self.kwargs = kwargs
                return type("Session", (), {"get_inputs": lambda _: [Input("input_ids"), Input("attention_mask"), Input("token_type_ids")]})()
        class Tokenizer:
            @classmethod
            def from_file(cls, path): return cls()
            def enable_truncation(self, **kwargs): pass
            def token_to_id(self, value): return 0
            def enable_padding(self, **kwargs): pass
        runtime = Runtime()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model"
            model.mkdir()
            (model / "model.onnx").write_bytes(b"model")
            (model / "tokenizer.json").write_text("{}")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"backend": "onnxruntime", "embedding_dimension": 2, "max_sequence_length": 8, "model_file": "model.onnx", "tokenizer_file": "tokenizer.json"}))
            with patch.dict(sys.modules, {"onnxruntime": runtime, "tokenizers": type("T", (), {"Tokenizer": Tokenizer})}):
                module.OnnxSentenceEncoder(model, manifest_path=manifest)
        options = Options.instances[-1]
        self.assertEqual(options.intra_op_num_threads, 1)
        self.assertEqual(options.inter_op_num_threads, 1)
        self.assertEqual(options.execution_mode, "sequential")
        self.assertEqual(runtime.kwargs["sess_options"], options)


class SelectionStageTests(unittest.TestCase):
    def _workspace(self, records, profile=None):
        directory = tempfile.TemporaryDirectory()
        workspace = Path(directory.name)
        analysis = workspace / "analysis"
        analysis.mkdir()
        (analysis / "paper-work-records.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in records)
        )
        if profile is not None:
            (workspace / "research-profile.json").write_text(json.dumps(profile))
        return directory, workspace

    def test_select_matches_legacy_with_real_selection(self):
        stage = importlib.import_module("corpus_analysis_stage")
        selection = importlib.import_module("corpus_selection")
        profile = {"title": "Target domain", "search_queries": [{"query": "target research"}]}
        records = [{"openalex_id": "W1", "title": "Same Study", "abstract": " ".join(["target"] * 25), "status": "extracted", "body_word_count": 100, "discovery_order": 1}, {"openalex_id": "W1D", "title": "Same Study", "doi": "10/same", "abstract": " ".join(["target"] * 25), "status": "extracted", "body_word_count": 90, "discovery_order": 2}]
        records += [{"openalex_id": f"W{i}", "title": f"Target Study {i}", "abstract": " ".join(["target"] * 25), "status": "extracted", "body_word_count": 100, "discovery_order": i} for i in range(2, 8)]
        records.append({"openalex_id": "LOW", "title": "Unrelated", "abstract": " ".join(["crystal"] * 25), "status": "extracted", "body_word_count": 100, "discovery_order": 8})
        def fake_embed(texts):
            import numpy as np
            return np.asarray([[0.0, 1.0] if "crystal" in text else [1.0, 0.0] for text in texts], dtype=np.float32)
        expected_docs = json.loads(json.dumps(records))
        expected = selection.select_analysis_documents(expected_docs, profile, embedding_fn=fake_embed)
        directory, workspace = self._workspace(records, profile)
        try:
            with patch.object(stage, "select_analysis_documents", side_effect=lambda docs, p: selection.select_analysis_documents(docs, p, embedding_fn=fake_embed)):
                self.assertEqual(stage.select(workspace), 0)
            actual = [json.loads(line) for line in (workspace / "analysis/paper-work-records.jsonl").read_text().splitlines()]
            for got, want in zip(actual, expected_docs):
                self.assertEqual(got.get("analysis_decision"), want.get("analysis_decision"))
                self.assertEqual(got.get("duplicate_of"), want.get("duplicate_of"))
                self.assertEqual(got.get("relevance_score"), want.get("relevance_score"))
            summary = json.loads((workspace / "analysis/selection-summary.json").read_text())
            self.assertEqual(summary["duplicate_count"], expected["duplicate_count"])
            self.assertEqual(summary["low_relevance_count"], expected["low_relevance_count"])
            self.assertEqual(summary["relevance_cutoff"], expected["relevance_cutoff"])
            self.assertEqual(summary["embedding_anchor_count"], expected["embedding_anchor_count"])
            self.assertEqual(summary["included_work_ids"], [d["openalex_id"] for d in expected["included"]])
        finally:
            directory.cleanup()

    def test_subprocess_records_select_pid(self):
        records = [{"openalex_id": "W1", "title": "A", "status": "extracted", "body_word_count": 2}]
        directory, workspace = self._workspace(records)
        try:
            result = subprocess.run([sys.executable, str(SCRIPTS / "corpus_analysis_stage.py"), "select", "--workspace", str(workspace)], env=dict(os.environ, PYTHONPATH=str(SCRIPTS)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in (workspace / "analysis/process-memory.jsonl").read_text().splitlines()]
            self.assertTrue(any(row["phase"] == "select" and row["pid"] != os.getpid() for row in rows))
        finally:
            directory.cleanup()

    def test_selection_failure_preserves_both_files(self):
        stage = importlib.import_module("corpus_analysis_stage")
        directory, workspace = self._workspace([{"openalex_id": "W1", "status": "extracted"}])
        records_path = workspace / "analysis/paper-work-records.jsonl"
        summary_path = workspace / "analysis/selection-summary.json"
        summary_path.write_text('{"old":true}\n')
        old_records, old_summary = records_path.read_bytes(), summary_path.read_bytes()
        try:
            with patch.object(stage, "select_analysis_documents", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError): stage.select(workspace)
            self.assertEqual(records_path.read_bytes(), old_records)
            self.assertEqual(summary_path.read_bytes(), old_summary)
            self.assertFalse(list((workspace / "analysis").glob(".*.tmp")))
        finally: directory.cleanup()

    def test_second_publish_failure_rolls_back_records(self):
        stage = importlib.import_module("corpus_analysis_stage")
        directory, workspace = self._workspace([{"openalex_id": "W1", "status": "extracted"}])
        records_path = workspace / "analysis/paper-work-records.jsonl"
        summary_path = workspace / "analysis/selection-summary.json"
        summary_path.write_text('{"old":true}\n')
        old_records, old_summary = records_path.read_bytes(), summary_path.read_bytes()
        original_replace = stage.os.replace
        calls = {"count": 0}
        def fail_second(src, dst):
            calls["count"] += 1
            if calls["count"] == 2: raise OSError("publish failure")
            return original_replace(src, dst)
        try:
            with patch.object(stage, "select_analysis_documents", return_value={"included": [], "duplicate_count": 0, "low_relevance_count": 0, "relevance_cutoff": None, "embedding_anchor_count": 0}), patch.object(stage.os, "replace", side_effect=fail_second):
                with self.assertRaises(OSError): stage.select(workspace)
            self.assertEqual(records_path.read_bytes(), old_records)
            self.assertEqual(summary_path.read_bytes(), old_summary)
            self.assertFalse(list((workspace / "analysis").glob(".*.tmp")))
            self.assertFalse(list((workspace / "analysis").glob(".*.backup")))
        finally: directory.cleanup()

    def test_success_has_consistent_outputs_and_no_temps(self):
        stage = importlib.import_module("corpus_analysis_stage")
        directory, workspace = self._workspace([{"openalex_id": "W1", "status": "extracted"}])
        try:
            with patch.object(stage, "select_analysis_documents", return_value={"included": [{"openalex_id": "W1", "status": "extracted", "analysis_decision": "include"}], "duplicate_count": 0, "low_relevance_count": 0, "relevance_cutoff": None, "embedding_anchor_count": 0}): stage.select(workspace)
            record = json.loads((workspace / "analysis/paper-work-records.jsonl").read_text())
            summary = json.loads((workspace / "analysis/selection-summary.json").read_text())
            self.assertEqual(summary["included_work_ids"], [record["openalex_id"]])
            self.assertFalse(list((workspace / "analysis").glob(".*.tmp")))
            self.assertFalse(list((workspace / "analysis").glob(".*.backup")))
        finally: directory.cleanup()

    def test_imports_do_not_load_onnx(self):
        code = "import sys; import acquire_mini_corpus, corpus_analysis, corpus_analysis_stage; assert 'onnxruntime' not in sys.modules; assert 'onnx_embeddings' not in sys.modules"
        env = dict(os.environ, PYTHONPATH=str(SCRIPTS))
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_embedding_wrapper_lazily_imports_backend(self):
        selection = importlib.import_module("corpus_selection")
        marker = object()
        fake = type("Backend", (), {"embed_texts": staticmethod(lambda texts: marker)})
        with patch.dict(sys.modules, {"onnx_embeddings": fake}):
            self.assertIs(selection.embed_texts(["x"]), marker)


if __name__ == "__main__":
    unittest.main()
