#!/usr/bin/env python3
"""Bounded corpus stages; TASK-02 currently provides PDF extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from academic_text import clean_academic_text, extract_pdf_text
from process_metrics import append_sample


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _safe(value: str, used: set[str]) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not safe:
        safe = "paper-" + hashlib.sha256(value.encode()).hexdigest()[:16]
    candidate = safe
    if candidate in used:
        suffix = hashlib.sha256(value.encode()).hexdigest()[:12]
        candidate = f"{safe}-{suffix}"
        counter = 2
        while candidate in used:
            candidate = f"{safe}-{suffix}-{counter}"
            counter += 1
    used.add(candidate)
    return candidate


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def extract(workspace: Path) -> int:
    analysis = workspace / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    candidates = {
        str(row.get("candidate_id") or row.get("openalex_id") or ""): row
        for row in _rows(workspace / "candidates.jsonl")
    }
    records: list[dict[str, Any]] = []
    used_text_names: set[str] = set()
    for result in _rows(workspace / "download-results.jsonl"):
        if result.get("status") not in {"downloaded", "existing"}:
            continue
        work_id = str(result.get("candidate_id") or result.get("openalex_id") or "")
        raw_pdf_value = result.get("path") or result.get("local_pdf")
        if not work_id or not raw_pdf_value:
            continue
        pdf = Path(raw_pdf_value)
        candidate = candidates.get(work_id, {})
        record: dict[str, Any] = {
            "openalex_id": work_id,
            "discovery_order": candidate.get("discovery_order"),
            "title": candidate.get("title") or pdf.stem or "Local paper",
            "abstract": candidate.get("abstract"),
            "doi": candidate.get("doi"),
            "arxiv_id": candidate.get("arxiv_id") or result.get("arxiv_id"),
            "source_url": candidate.get("source_url") or "",
            "authors": candidate.get("authors") or [],
            "publication_year": candidate.get("publication_year") or candidate.get("year"),
            "pdf": str(pdf),
            "status": "pending",
        }
        try:
            raw_text, page_count = extract_pdf_text(pdf)
            text, cleaning = clean_academic_text(raw_text)
            target = analysis / "text" / f"{_safe(work_id, used_text_names)}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_text(target, text)
            record.update(
                status="extracted",
                text=str(target),
                page_count=page_count,
                body_word_count=cleaning["body_word_count"],
                extraction_low_confidence=int(cleaning["body_word_count"]) < 100,
                cleaning=cleaning,
            )
        except Exception as error:
            record.update(status="failed", error=f"{type(error).__name__}: {error}")
        append_sample(workspace, "extract")
        records.append(record)
    _atomic_jsonl(analysis / "paper-work-records.jsonl", records)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        return extract(args.workspace.expanduser().resolve())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
