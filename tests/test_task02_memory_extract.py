import json
import importlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from unittest.mock import patch
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from process_metrics import (  # noqa: E402
    FIELDS,
    SystemMemoryMonitor,
    parse_cgroup_events,
    parse_meminfo,
    parse_smaps_rollup,
    parse_status,
    unified_cgroup_path,
)
from concurrent_downloads import (  # noqa: E402
    DEFAULT_MAX_DOWNLOADS,
    DEFAULT_MAX_DOWNLOADS_PER_HOST,
)
from fulltext import (  # noqa: E402
    MAX_DOWNLOAD_CHUNK_BYTES,
    download_licensed_open_access_pdf,
    download_openalex_content_pdf,
)


class Task02MetricsTests(unittest.TestCase):
    def test_linux_fixture_parsers_and_fixed_fields(self):
        self.assertEqual(parse_status("VmRSS: 12 kB\nVmHWM: 30 kB"), {"VmRSS": 12288, "VmHWM": 30720})
        self.assertEqual(parse_smaps_rollup("Rss: 20 kB\nPss: 10 kB"), {"Rss": 20480, "Pss": 10240})
        self.assertEqual(parse_meminfo("MemTotal: 100 kB\nMemAvailable: 50 kB"), {"MemTotal": 102400, "MemAvailable": 51200})
        self.assertEqual(unified_cgroup_path("0::/slice/job", Path("/cgroup")), Path("/cgroup/slice/job"))
        self.assertEqual(parse_cgroup_events("oom 2\noom_kill 1"), {"oom": 2, "oom_kill": 1})

    def test_monitor_is_independent_and_leaves_samples_after_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            monitor = SystemMemoryMonitor(workspace, interval=0.1).start()
            monitor_pid = monitor.pid
            time.sleep(0.25)
            path = workspace / "analysis" / "system-memory.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            monitor.stop()
            monitor.stop()
            self.assertIsNotNone(monitor_pid)
            self.assertGreaterEqual(len(rows), 2)
            self.assertTrue(all(set(row) == set(FIELDS) for row in rows))
            self.assertTrue(all(row["pid"] == monitor_pid for row in rows))
            intervals = [b["timestamp"] - a["timestamp"] for a, b in zip(rows, rows[1:])]
            self.assertTrue(all(interval <= 5.0 for interval in intervals))

    def test_darwin_unsupported_fields_are_null(self):
        with patch("process_metrics.platform.system", return_value="Darwin"), patch(
            "process_metrics.resource.getrusage"
        ) as getrusage:
            getrusage.return_value.ru_maxrss = 1234
            from process_metrics import sample

            row = sample("darwin")
        self.assertEqual(row["rss_bytes"], 1234)
        self.assertEqual(row["peak_rss_bytes"], 1234)
        for field in FIELDS[5:12]:
            self.assertIsNone(row[field])

    def test_read_cgroup_events_uses_real_file(self):
        from process_metrics import read_cgroup_events

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.events").write_text("oom 3\noom_kill 1\n")
            self.assertEqual(read_cgroup_events(root), {"oom": 3, "oom_kill": 1})

    def test_monitor_records_after_failed_child(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            monitor = SystemMemoryMonitor(workspace, interval=0.1).start()
            monitor_pid = monitor.pid
            path = workspace / "analysis/system-memory.jsonl"
            initial_count = len(path.read_text().splitlines())
            child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
            child_pid = child.pid
            child.wait(timeout=5)
            child_end = time.time()
            self.assertEqual(child.returncode, 7)
            for _ in range(20):
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                if len(rows) > initial_count and rows[-1]["timestamp"] >= child_end:
                    break
                time.sleep(0.05)
            self.assertGreater(len(rows), initial_count)
            self.assertTrue(monitor._process is not None and monitor._process.is_alive())
            self.assertNotEqual(monitor_pid, os.getpid())
            self.assertNotEqual(monitor_pid, child_pid)
            monitor.stop()
            self.assertIsNone(monitor._process)
            self.assertTrue(path.is_file())

    def test_real_pdf_extract_matches_legacy_cleaning(self):
        try:
            stage = importlib.import_module("corpus_analysis_stage")
            from academic_text import clean_academic_text, extract_pdf_text
        except ImportError as error:
            self.skipTest(f"real PDF dependency unavailable: {error}")
        source = Path(__file__).resolve().parents[1] / "docs/customer-guide/AreaDay-安装和使用指南-v1.1.0.pdf"
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            pdf = workspace / "source.pdf"
            pdf.write_bytes(source.read_bytes())
            (workspace / "candidates.jsonl").write_text(json.dumps({"candidate_id": "WREAL", "title": "real"}) + "\n")
            (workspace / "download-results.jsonl").write_text(json.dumps({"candidate_id": "WREAL", "status": "downloaded", "path": str(pdf)}) + "\n")
            try:
                expected_raw, expected_pages = extract_pdf_text(pdf)
            except ModuleNotFoundError as error:
                self.skipTest(f"real PDF dependency unavailable: {error}")
            expected_text, _ = clean_academic_text(expected_raw)
            self.assertEqual(stage.extract(workspace), 0)
            rows = [json.loads(line) for line in (workspace / "analysis/paper-work-records.jsonl").read_text().splitlines()]
            row = rows[0]
            self.assertEqual(Path(row["text"]).read_text(), expected_text)
            self.assertEqual(len(Path(row["text"]).read_text()), len(expected_text))
            self.assertEqual(row["page_count"], expected_pages)
            self.assertNotIn("clean_text", row)

    def test_extract_bad_pdf_continues_after_good_result(self):
        try:
            stage = importlib.import_module("corpus_analysis_stage")
            importlib.import_module("pymupdf")
        except ImportError as error:
            self.skipTest(f"real PDF dependency unavailable: {error}")
        source = Path(__file__).resolve().parents[1] / "docs/customer-guide/AreaDay-安装和使用指南-v1.1.0.pdf"
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            pdf = workspace / "real.pdf"
            pdf.write_bytes(source.read_bytes())
            rows = [{"candidate_id": "GOOD"}, {"candidate_id": "BAD"}]
            (workspace / "candidates.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            (workspace / "download-results.jsonl").write_text("\n".join(json.dumps(row) for row in [{"candidate_id": "GOOD", "status": "downloaded", "path": str(pdf)}, {"candidate_id": "BAD", "status": "downloaded", "path": str(workspace / "missing.pdf")}]) + "\n")
            stage.extract(workspace)
            records = [json.loads(line) for line in (workspace / "analysis/paper-work-records.jsonl").read_text().splitlines()]
            self.assertEqual(
                [row["status"] for row in records], ["extracted", "failed"]
            )

    def test_atomic_helpers_clean_temp_on_interrupt(self):
        stage = importlib.import_module("corpus_analysis_stage")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "text.txt"
            with patch.object(stage.os, "replace", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    stage._atomic_text(path, "x")
            self.assertFalse(path.exists())
            self.assertFalse(list(path.parent.glob(".*.tmp")))
            records = Path(directory) / "paper-work-records.jsonl"
            with patch.object(stage.os, "replace", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    stage._atomic_jsonl(records, [{"status": "extracted"}])
            self.assertFalse(records.exists())
            self.assertFalse(list(records.parent.glob(".*.tmp")))

    def test_download_defaults_and_chunk_bound_for_both_downloaders(self):
        self.assertEqual(DEFAULT_MAX_DOWNLOADS, 4)
        self.assertEqual(DEFAULT_MAX_DOWNLOADS_PER_HOST, 2)
        self.assertLessEqual(MAX_DOWNLOAD_CHUNK_BYTES, 256 * 1024)

        class Response:
            url = "https://papers.example/p.pdf"
            headers = {"Content-Length": "10"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
            def raise_for_status(self):
                return None
            @property
            def content(self): raise AssertionError("content must not be accessed")
            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                yield b"%PDF-1.4\n"
        class Session:
            def __init__(self): self.response = Response()
            def get(self, *args, **kwargs):
                self.kwargs = kwargs
                return self.response
        with tempfile.TemporaryDirectory() as directory:
            calls = (
                lambda s, p: download_licensed_open_access_pdf(
                    "https://papers.example/p.pdf", p, session=s
                ),
                lambda s, p: download_openalex_content_pdf(
                    "W1", "key", p, session=s
                ),
            )
            for index, call in enumerate(calls):
                session = Session()
                destination = Path(directory) / f"{index}.pdf"
                call(session, destination)
                self.assertEqual(session.kwargs["stream"], True)
                self.assertEqual(session.response.chunk_size, MAX_DOWNLOAD_CHUNK_BYTES)
                self.assertTrue(destination.exists())

    def test_initialize_commands_forward_download_limits(self):
        try:
            initialize = importlib.import_module("initialize")
        except ImportError as error:
            self.skipTest(f"initialize dependencies unavailable: {error}")
        controller = initialize.InitializationController.__new__(initialize.InitializationController)
        controller.args = Namespace(
            target_papers=1,
            download_workers=2,
            download_workers_per_host=1,
            port=8765,
            idle_timeout_seconds=3600,
        )
        controller.profile_path = Path("profile.json")
        controller.workspace = Path("workspace")
        controller.registry_path = Path("registry.json")
        acquire = controller._acquire_command("--analyze")
        resume = controller.resume_command()
        for command in (acquire, resume):
            self.assertEqual(command[command.index("--download-workers") + 1], "2")
            self.assertEqual(command[command.index("--download-workers-per-host") + 1], "1")


if __name__ == "__main__":
    unittest.main()
