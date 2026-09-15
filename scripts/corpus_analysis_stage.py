#!/usr/bin/env python3
"""Bounded corpus stages; TASK-02 currently provides PDF extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from academic_text import clean_academic_text, extract_pdf_text
from process_metrics import append_sample
from corpus_selection import select_analysis_documents


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


def _write_jsonl_temp(path: Path, rows: list[dict[str, Any]], tag: str) -> Path:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{tag}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


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


def _load_profile(workspace: Path) -> dict[str, Any] | None:
    for name in ("research-profile-input.json", "research-profile.json"):
        path = workspace / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"Research profile must be an object: {path}")
            return payload
    return None


def select(workspace: Path) -> int:
    """Run selection in its own short-lived process and publish its outputs."""

    analysis = workspace / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    records_path = analysis / "paper-work-records.jsonl"
    try:
        # Validate configuration before doing any work so malformed service
        # configuration fails at stage startup, including an empty corpus.
        from onnx_embeddings import configured_batch_size

        configured_batch_size()
        records = _rows(records_path)
        profile = _load_profile(workspace)
        selection = select_analysis_documents(records, profile)
        public_records = [dict(record) for record in records]
        summary = {
            "duplicate_count": selection["duplicate_count"],
            "low_relevance_count": selection["low_relevance_count"],
            "relevance_cutoff": selection["relevance_cutoff"],
            "embedding_anchor_count": selection.get("embedding_anchor_count", 0),
            "included_work_ids": [
                str(document["openalex_id"]) for document in selection["included"]
            ],
        }
        _publish_selection_outputs(records_path, public_records, summary)
        return 0
    finally:
        # Diagnostics must survive both business failures and successful runs.
        append_sample(workspace, "select")


LEXICAL_DB_NAME = ".lexical-work.sqlite3"


def _open_lexical_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-16384")
    connection.execute("PRAGMA mmap_size=0")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            work_id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL, text_path TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lemma (
            work_id TEXT NOT NULL, lemma TEXT NOT NULL, count INTEGER NOT NULL,
            pos_json TEXT NOT NULL, surface_json TEXT NOT NULL, examples_json TEXT NOT NULL,
            PRIMARY KEY (work_id, lemma)
        );
        CREATE TABLE IF NOT EXISTS term (
            work_id TEXT NOT NULL, term TEXT NOT NULL, count INTEGER NOT NULL,
            surface_json TEXT NOT NULL, examples_json TEXT NOT NULL,
            PRIMARY KEY (work_id, term)
        );
        CREATE TABLE IF NOT EXISTS surface (
            kind TEXT NOT NULL, key TEXT NOT NULL, work_id TEXT NOT NULL,
            form TEXT NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY (kind, key, work_id, form)
        );
        CREATE TABLE IF NOT EXISTS example (
            kind TEXT NOT NULL, key TEXT NOT NULL, work_id TEXT NOT NULL,
            sentence TEXT NOT NULL, ordinal INTEGER NOT NULL,
            PRIMARY KEY (kind, key, work_id, sentence)
        );
        CREATE TABLE IF NOT EXISTS acronym (
            acronym TEXT NOT NULL, expansion TEXT NOT NULL, work_id TEXT NOT NULL,
            count INTEGER NOT NULL, PRIMARY KEY (acronym, expansion, work_id)
        );
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT NOT NULL, work_id TEXT NOT NULL DEFAULT '', value TEXT NOT NULL,
            PRIMARY KEY (key, work_id)
        );
        """
    )
    connection.commit()
    return connection


def _upsert_lexical_document(connection: sqlite3.Connection, ordinal: int, document: dict[str, Any], raw: dict[str, Any]) -> None:
    work_id = str(document["openalex_id"])
    connection.execute(
        "INSERT INTO documents(work_id, ordinal, text_path, metadata_json) VALUES(?,?,?,?) "
        "ON CONFLICT(work_id) DO UPDATE SET ordinal=excluded.ordinal, text_path=excluded.text_path, metadata_json=excluded.metadata_json",
        (work_id, ordinal, str(document.get("text") or ""), json.dumps(document, ensure_ascii=False, sort_keys=True)),
    )
    for lemma, count in raw.get("lemma_counts", {}).items():
        pos = raw.get("lemma_pos", {}).get(lemma, {})
        surfaces = raw.get("lemma_surfaces", {}).get(lemma, {})
        examples = raw.get("lemma_examples", {}).get(lemma, [])
        connection.execute(
            "INSERT INTO lemma(work_id, lemma, count, pos_json, surface_json, examples_json) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(work_id, lemma) DO UPDATE SET count=excluded.count, pos_json=excluded.pos_json, surface_json=excluded.surface_json, examples_json=excluded.examples_json",
            (work_id, lemma, int(count), json.dumps(pos), json.dumps(surfaces), json.dumps(examples, ensure_ascii=False)),
        )
        for form, value in surfaces.items():
            connection.execute("INSERT OR REPLACE INTO surface(kind,key,work_id,form,count) VALUES('lemma',?,?,?,?)", (lemma, work_id, form, int(value)))
        for index, example in enumerate(examples):
            connection.execute("INSERT OR REPLACE INTO example(kind,key,work_id,sentence,ordinal) VALUES('lemma',?,?,?,?)", (lemma, work_id, str(example.get("sentence") or ""), index))
    for term, count in raw.get("term_counts", {}).items():
        surfaces = raw.get("term_surfaces", {}).get(term, {})
        examples = raw.get("term_examples", {}).get(term, [])
        connection.execute(
            "INSERT INTO term(work_id, term, count, surface_json, examples_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(work_id, term) DO UPDATE SET count=excluded.count, surface_json=excluded.surface_json, examples_json=excluded.examples_json",
            (work_id, term, int(count), json.dumps(surfaces), json.dumps(examples, ensure_ascii=False)),
        )
        for form, value in surfaces.items():
            connection.execute("INSERT OR REPLACE INTO surface(kind,key,work_id,form,count) VALUES('term',?,?,?,?)", (term, work_id, form, int(value)))
        for index, example in enumerate(examples):
            connection.execute("INSERT OR REPLACE INTO example(kind,key,work_id,sentence,ordinal) VALUES('term',?,?,?,?)", (term, work_id, str(example.get("sentence") or ""), index))
    for acronym, expansions in raw.get("acronyms", {}).items():
        for expansion, count in expansions.items():
            connection.execute("INSERT OR REPLACE INTO acronym(acronym, expansion, work_id, count) VALUES(?,?,?,?)", (acronym, expansion, work_id, int(count)))
    connection.execute("INSERT OR REPLACE INTO stats(key,work_id,value) VALUES('processed_spacy_token_count',?,?)", (work_id, str(int(raw.get("processed_spacy_token_count") or 0))))
    connection.commit()


def lexical(workspace: Path) -> int:
    """Parse included papers one at a time and checkpoint each transaction."""
    from lexical_assets import build_lexical_assets, load_spacy_pipeline

    analysis = workspace / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    records = _rows(analysis / "paper-work-records.jsonl")
    included_ids: set[str] | None = None
    summary_path = analysis / "selection-summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"selection checkpoint missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or not isinstance(summary.get("included_work_ids"), list):
        raise ValueError("selection-summary.json must contain included_work_ids list")
    included_ids = {str(value) for value in summary["included_work_ids"]}
    documents = [record for record in records if record.get("status") == "extracted" and str(record.get("openalex_id")) in included_ids]
    db_path = analysis / LEXICAL_DB_NAME
    connection = _open_lexical_db(db_path)
    try:
        nlp = load_spacy_pipeline() if documents else None
        for ordinal, document in enumerate(documents):
            work_id = str(document["openalex_id"])
            already = connection.execute("SELECT 1 FROM documents WHERE work_id=?", (work_id,)).fetchone()
            if already:
                continue
            text_path = Path(str(document.get("text") or ""))
            # Resolve relative paths against the workspace for hand-authored
            # fixtures while retaining the original public path field.
            if not text_path.is_absolute():
                text_path = workspace / text_path
            text = text_path.read_text(encoding="utf-8")
            assets = build_lexical_assets(
                [{"openalex_id": work_id, "clean_text": text}],
                nlp=nlp,
                include_raw_document=True,
            )
            raw = assets.get("raw_document") or {"openalex_id": work_id}
            _upsert_lexical_document(connection, ordinal, document, raw)
            append_sample(workspace, "lexical")
    except BaseException:
        # The DB is intentionally left in place as a resumable checkpoint.
        raise
    finally:
        connection.close()
        append_sample(workspace, "lexical")
    return 0


def serialize(workspace: Path) -> int:
    """Stream compact lexical rows into the existing formal analysis files."""
    from corpus_analysis import serialize_lexical_stage, validate_serialized_outputs
    from lexical_assets import assets_from_sqlite

    db_path = workspace / "analysis" / LEXICAL_DB_NAME
    if not db_path.is_file():
        raise FileNotFoundError(f"lexical checkpoint missing: {db_path}")
    assets = assets_from_sqlite(db_path)
    records = _rows(workspace / "analysis" / "paper-work-records.jsonl")
    profile = None
    for name in ("research-profile-input.json", "research-profile.json"):
        path = workspace / name
        if path.is_file():
            profile = json.loads(path.read_text(encoding="utf-8"))
            break
    analysis_dir = workspace / "analysis"
    staging_dir = analysis_dir / f".lexical-serialize-staging-{os.getpid()}"
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=False)
    formal_names = (
        "pre-orthography-vocabulary-map.tsv", "vocabulary-map.tsv", "vocabulary.tsv",
        "pre-orthography-vocabulary-map.jsonl", "vocabulary-map.jsonl",
        "raw-terminology-candidates.tsv", "raw-terminology-candidates.jsonl",
        "terminology-candidates.tsv", "terminology-candidates.jsonl",
        "orthography-review-input.json", "terminology-review-input.json",
        "paper-work-records.jsonl", "paper-decisions.jsonl", "papers.jsonl",
        "corpus-stats.json", "summary.md",
    )
    # Invalidate any previous completion marker before doing work so failures
    # cannot be mistaken for a successful resumed serialization.
    (analysis_dir / "corpus-stats.json").unlink(missing_ok=True)
    try:
        serialize_lexical_stage(
            workspace, assets, records=records, profile=profile, staging_dir=staging_dir
        )
        validate_serialized_outputs(staging_dir)
        # The stats file is the sole completion marker. Invalidate any prior
        # marker before publishing the rest, then publish the new marker last.
        for name in formal_names:
            if name == "corpus-stats.json":
                continue
            source = staging_dir / name
            if not source.is_file():
                raise FileNotFoundError(f"serialize staging output missing: {name}")
            os.replace(source, analysis_dir / name)
        os.replace(staging_dir / "corpus-stats.json", analysis_dir / "corpus-stats.json")
        db_path.unlink()
    except BaseException:
        # Never leave a stale or partial completion marker after publication
        # fails. The SQLite checkpoint remains available for recovery.
        (analysis_dir / "corpus-stats.json").unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        append_sample(workspace, "serialize")
    return 0


def _publish_selection_outputs(
    records_path: Path,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    """Publish both selection files with rollback if the second rename fails."""

    summary_path = records_path.with_name("selection-summary.json")
    records_tmp = _write_jsonl_temp(records_path, records, "records")
    summary_tmp = summary_path.with_name(
        f".{summary_path.name}.{os.getpid()}.summary.tmp"
    )
    try:
        with summary_tmp.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        records_backup = records_path.with_name(
            f".{records_path.name}.{os.getpid()}.backup"
        )
        if records_path.exists():
            shutil.copyfile(records_path, records_backup)
        else:
            records_backup = None

        try:
            os.replace(records_tmp, records_path)
            os.replace(summary_tmp, summary_path)
        except BaseException:
            if records_backup is not None and records_backup.exists():
                os.replace(records_backup, records_path)
            elif records_path.exists():
                records_path.unlink()
            raise
        finally:
            if records_backup is not None:
                records_backup.unlink(missing_ok=True)
    finally:
        records_tmp.unlink(missing_ok=True)
        summary_tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--workspace", type=Path, required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--workspace", type=Path, required=True)
    lexical_parser = subparsers.add_parser("lexical")
    lexical_parser.add_argument("--workspace", type=Path, required=True)
    serialize_parser = subparsers.add_parser("serialize")
    serialize_parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        return extract(args.workspace.expanduser().resolve())
    if args.command == "select":
        return select(args.workspace.expanduser().resolve())
    if args.command == "lexical":
        return lexical(args.workspace.expanduser().resolve())
    if args.command == "serialize":
        return serialize(args.workspace.expanduser().resolve())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
