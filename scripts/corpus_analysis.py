"""Build first-pass local vocabulary and terminology assets from corpus PDFs."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import time
from pathlib import Path
from statistics import median
from typing import Any, Callable

from academic_text import clean_academic_text, extract_pdf_text
from corpus_selection import embed_texts, select_analysis_documents
from lexical_assets import build_lexical_assets, select_shared_terminology_candidates
from orthography_review import build_orthography_review_candidates
from areaday_core import utc_now, write_json, write_jsonl
from process_metrics import append_sample


def serialize_lexical_stage(
    workspace: Path,
    assets: dict[str, Any],
    *,
    records: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    staging_dir: Path | None = None,
) -> dict[str, Any]:
    """Publish the formal analysis artifacts from already-serialized assets.

    This is deliberately separate from :func:`analyze_corpus`: the bounded
    pipeline's serialize process receives only compact SQLite-derived assets,
    never the PDF/text corpus or spaCy objects.
    """
    source_analysis_dir = workspace / "analysis"
    output_dir = staging_dir or source_analysis_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if records is None:
        records_path = source_analysis_dir / "paper-work-records.jsonl"
        records = _rows_for_serialization(records_path)
    selection_summary_path = source_analysis_dir / "selection-summary.json"
    if not selection_summary_path.is_file():
        raise FileNotFoundError(f"selection summary missing: {selection_summary_path}")
    selection_summary = json.loads(selection_summary_path.read_text(encoding="utf-8"))
    if not isinstance(selection_summary, dict):
        raise ValueError("selection-summary.json must be an object")
    analysis_dir = output_dir
    vocabulary = assets["vocabulary"]
    raw_terminology = assets["terminology_candidates"]
    terminology, terminology_minimum_documents = select_shared_terminology_candidates(
        raw_terminology, assets["included_document_count"]
    )
    orthography_candidates = build_orthography_review_candidates(vocabulary)
    pre_tsv = analysis_dir / "pre-orthography-vocabulary-map.tsv"
    _write_vocabulary_tsv(pre_tsv, vocabulary)
    _copy_output(pre_tsv, analysis_dir / "vocabulary-map.tsv")
    _copy_output(pre_tsv, analysis_dir / "vocabulary.tsv")
    pre_jsonl = analysis_dir / "pre-orthography-vocabulary-map.jsonl"
    write_jsonl(pre_jsonl, vocabulary)
    _copy_output(pre_jsonl, analysis_dir / "vocabulary-map.jsonl")
    _write_terminology_tsv(analysis_dir / "raw-terminology-candidates.tsv", raw_terminology)
    write_jsonl(analysis_dir / "raw-terminology-candidates.jsonl", raw_terminology)
    _write_terminology_tsv(analysis_dir / "terminology-candidates.tsv", terminology)
    write_jsonl(analysis_dir / "terminology-candidates.jsonl", terminology)
    orthography_review_input = {
        "schema_version": 1,
        "instruction": (
            "These are high-recall suspicious spaCy lemmas, not confirmed errors. "
            "Review every candidate using its surface forms and representative "
            "sentences. Put valid technical terms, names, abbreviations, and legitimate "
            "variants in lemma_keeps. Map a malformed lemma to its correct canonical "
            "lemma. Drop only extraction noise that should not be a vocabulary entry. "
            "Every candidate must appear in exactly one of lemma_keeps, "
            "lemma_replacements, or lemma_drops."
        ),
        "selection_schema": {
            "schema_version": 1,
            "reviewer": "current-host-agent",
            "lemma_keeps": ["observed lemma confirmed as valid"],
            "lemma_replacements": {"observed lemma": "canonical lemma"},
            "lemma_drops": ["observed lemma that is extraction noise"],
            "review_summary": "short factual string",
        },
        "candidates": orthography_candidates,
    }
    write_json(analysis_dir / "orthography-review-input.json", orthography_review_input)
    write_json(
        analysis_dir / "terminology-review-input.json",
        build_terminology_review_input(profile, terminology, terminology_minimum_documents),
    )
    public_records = [{key: value for key, value in record.items() if key != "clean_text"} for record in records]
    records_tmp = analysis_dir / f"paper-work-records.jsonl.{os.getpid()}.tmp"
    write_jsonl(records_tmp, public_records)
    os.replace(records_tmp, analysis_dir / "paper-work-records.jsonl")
    paper_decisions = analysis_dir / "paper-decisions.jsonl"
    write_jsonl(paper_decisions, public_records)
    _copy_output(paper_decisions, analysis_dir / "papers.jsonl")
    body_counts = [int(record.get("body_word_count") or 0) for record in records if record.get("status") == "extracted"]
    stats = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "downloaded_pdf_count": _downloaded_count(workspace, records),
        "analyzed_pdf_count": sum(record.get("status") == "extracted" for record in records),
        "included_paper_count": assets["included_document_count"],
        "duplicate_paper_count": int(selection_summary.get("duplicate_count") or 0),
        "low_relevance_paper_count": int(selection_summary.get("low_relevance_count") or 0),
        "failed_pdf_count": sum(record.get("status") == "failed" for record in records),
        "low_extraction_confidence_count": sum(bool(record.get("extraction_low_confidence")) for record in records),
        "relevance_cutoff": selection_summary.get("relevance_cutoff"),
        "median_body_words_per_extracted_pdf": median(body_counts) if body_counts else 0,
        "processed_spacy_token_count": assets["processed_spacy_token_count"],
        "lemmatizer": "spacy-en-core-web-sm",
        "content_lemma_token_count": assets["content_lemma_token_count"],
        "vocabulary_entry_count": len(vocabulary),
        "raw_terminology_candidate_count": len(raw_terminology),
        "terminology_candidate_count": len(terminology),
        "terminology_minimum_document_share": 0.10,
        "terminology_minimum_document_count": terminology_minimum_documents,
        "orthography_review_candidate_count": len(orthography_candidates),
        "orthography_review_applied": False,
        "minimum_document_count": assets["minimum_document_count"],
        "phase_elapsed_seconds": {
            "pdf_extraction_and_cleaning": 0.0,
            "paper_selection": 0.0,
            "lexical_assets": 0.0,
            "candidate_preparation": 0.0,
            "asset_serialization": 0.0,
        },
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
    write_json(analysis_dir / "corpus-stats.json", stats)
    label = str((profile or {}).get("title") or (profile or {}).get("profile_id") or "Research mini-corpus")
    _atomic_text(analysis_dir / "summary.md", "\n".join([
            f"# {label}: first lexical assets", "",
            "This is the first corpus-derived Vocabulary Map and unreviewed terminology candidate set. It does not estimate the user's mastery.", "",
            f"- PDFs downloaded: {stats['downloaded_pdf_count']}",
            f"- PDFs text-extracted: {stats['analyzed_pdf_count']}",
            f"- Papers included in lexical statistics: {stats['included_paper_count']}",
            f"- Duplicate versions excluded from statistics: {stats['duplicate_paper_count']}",
            f"- Extreme low-relevance papers excluded from statistics: {stats['low_relevance_paper_count']}",
            f"- PDF extraction failures: {stats['failed_pdf_count']}",
            f"- Vocabulary Map entries: {stats['vocabulary_entry_count']}",
            f"- Terminology candidates awaiting host-agent review: {stats['terminology_candidate_count']}",
            f"- Orthography candidates awaiting contextual host-agent review: {stats['orthography_review_candidate_count']}", "",
            "No general-English baseline, topic clustering, topic reweighting, or user-mastery inference was applied.", "",
        ]))
    # Re-parse every formal artifact before the caller removes the checkpoint.
    json_paths = (
        "corpus-stats.json", "terminology-review-input.json",
        "orthography-review-input.json",
    )
    for name in json_paths:
        json.loads((analysis_dir / name).read_text(encoding="utf-8"))
    for name in (
        "vocabulary-map.jsonl", "raw-terminology-candidates.jsonl",
        "terminology-candidates.jsonl", "paper-decisions.jsonl", "papers.jsonl",
    ):
        with (analysis_dir / name).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line)
    for name in (
        "vocabulary-map.tsv", "raw-terminology-candidates.tsv",
        "terminology-candidates.tsv",
    ):
        with (analysis_dir / name).open(encoding="utf-8", newline="") as handle:
            for _ in csv.DictReader(handle, delimiter="\t"):
                pass
    return stats


def _rows_for_serialization(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _downloaded_count(workspace: Path, records: list[dict[str, Any]]) -> int:
    path = workspace / "download-results.jsonl"
    if path.is_file():
        with path.open(encoding="utf-8") as handle:
            return sum(json.loads(line).get("status") in {"downloaded", "existing"} for line in handle if line.strip())
    return sum(record.get("status") in {"downloaded", "existing"} for record in records)


def validate_serialized_outputs(analysis_dir: Path) -> None:
    """Raise if any staged formal JSON/JSONL/TSV artifact is malformed."""
    for name in ("corpus-stats.json", "terminology-review-input.json", "orthography-review-input.json"):
        json.loads((analysis_dir / name).read_text(encoding="utf-8"))
    for name in (
        "pre-orthography-vocabulary-map.jsonl", "vocabulary-map.jsonl",
        "raw-terminology-candidates.jsonl", "terminology-candidates.jsonl",
        "paper-decisions.jsonl", "papers.jsonl",
    ):
        with (analysis_dir / name).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line)
    for name in (
        "pre-orthography-vocabulary-map.tsv", "vocabulary-map.tsv", "vocabulary.tsv",
        "raw-terminology-candidates.tsv", "terminology-candidates.tsv",
    ):
        with (analysis_dir / name).open(encoding="utf-8", newline="") as handle:
            for _ in csv.DictReader(handle, delimiter="\t"):
                pass


def _copy_output(source: Path, destination: Path) -> None:
    """Atomically copy an already-serialized artifact to a compatibility alias."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def _atomic_text(path: Path, text: str) -> None:
    """Publish extracted text only after the complete file is durable."""
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


def _write_vocabulary_tsv(path: Path, vocabulary: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fields = [
        "token",
        "lemma",
        "part_of_speech",
        "total_count",
        "frequency_per_million",
        "document_count",
        "document_share",
        "dispersion",
        "per_document_counts",
        "surface_forms",
        "representative_sentences",
        "source_papers",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for record in vocabulary:
            row = dict(record)
            row["token"] = record["lemma"]
            for key in (
                "per_document_counts",
                "surface_forms",
                "representative_sentences",
                "source_papers",
            ):
                row[key] = json.dumps(row[key], ensure_ascii=False, separators=(",", ":"))
            writer.writerow(row)
    temporary.replace(path)


def _write_terminology_tsv(path: Path, terminology: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fields = [
        "term",
        "total_count",
        "document_count",
        "document_share",
        "c_value",
        "surface_forms",
        "acronyms",
        "representative_sentences",
        "source_papers",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for record in terminology:
            row = dict(record)
            for key in (
                "surface_forms",
                "acronyms",
                "representative_sentences",
                "source_papers",
            ):
                row[key] = json.dumps(row.get(key) or [], ensure_ascii=False, separators=(",", ":"))
            writer.writerow(row)
    temporary.replace(path)


def build_terminology_review_input(
    profile: dict[str, Any] | None,
    terminology: list[dict[str, Any]],
    minimum_document_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": (profile or {}).get("profile_id"),
        "research_title": (profile or {}).get("title"),
        "research_summary": (profile or {}).get("research_summary"),
        "minimum_document_count": minimum_document_count,
        "instruction": (
            "Review this document-coverage-filtered candidate set once. Keep only stable, "
            "shared terminology of this specific research direction that is worth learning "
            "before reading its papers. Reject general academic phrases, named entities, "
            "paper-local coinages, author-specific labels, and redundant variants. A phrase "
            "passing the document threshold is only eligible for review; it is not proof that "
            "the phrase is a term. Do not rescue low-coverage article-local concepts through "
            "exceptions. For every kept term, write a concise contextual English explanation, "
            "Chinese explanation, concept role, and stable sense key. Do not write a separate "
            "selection reason."
        ),
        "output_schema": {
            "schema_version": 1,
            "reviewer": "current-host-agent",
            "terminology": {"exact selected candidate term": 1.0},
            "terminology_explanations": {
                "exact selected candidate term": {
                    "meaning_en": "concise contextual English explanation",
                    "meaning_zh": "concise contextual Chinese explanation",
                    "concept_role": "role in this research direction",
                    "sense_key": "stable sense identifier",
                }
            },
        },
        "candidates": terminology,
    }


def analyze_corpus(
    candidates: list[dict[str, Any]],
    download_results: list[dict[str, Any]],
    workspace: Path,
    *,
    profile: dict[str, Any] | None = None,
    text_extractor: Callable[[Path], tuple[str, int]] = extract_pdf_text,
    embedding_fn=embed_texts,
    nlp: Any | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Extract, clean, deduplicate, conservatively filter, and profile a corpus."""
    def candidate_id(item: dict[str, Any]) -> str:
        return str(item.get("candidate_id") or item.get("openalex_id") or "")

    candidate_by_id = {candidate_id(item): item for item in candidates}
    text_dir = workspace / "analysis" / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    paper_records: list[dict[str, Any]] = []
    phase_elapsed_seconds: dict[str, float] = {}

    phase_started = monotonic()
    for result in download_results:
        if result.get("status") not in {"downloaded", "existing"}:
            continue
        local_pdf = result.get("path") or result.get("local_pdf")
        if not local_pdf:
            continue
        work_id = str(result.get("candidate_id") or result.get("openalex_id") or "")
        if not work_id:
            continue
        candidate = candidate_by_id.get(work_id) or {}
        pdf_path = Path(local_pdf)
        record: dict[str, Any] = {
            "openalex_id": work_id,
            "discovery_order": candidate.get("discovery_order"),
            "title": candidate.get("title") or pdf_path.stem or "Local paper",
            "abstract": candidate.get("abstract"),
            "doi": candidate.get("doi"),
            "arxiv_id": candidate.get("arxiv_id") or result.get("arxiv_id"),
            "source_url": candidate.get("source_url") or "",
            "authors": candidate.get("authors") or [],
            "publication_year": candidate.get("publication_year") or candidate.get("year"),
            "pdf": str(pdf_path),
            "status": "pending",
        }
        try:
            raw_text, page_count = text_extractor(pdf_path)
            clean_text, cleaning = clean_academic_text(raw_text)
            safe_work_id = re.sub(r"[^A-Za-z0-9._-]+", "_", work_id)
            text_path = text_dir / f"{safe_work_id}.txt"
            _atomic_text(text_path, clean_text)
            record.update(
                status="extracted",
                text=str(text_path),
                page_count=page_count,
                body_word_count=cleaning["body_word_count"],
                extraction_low_confidence=int(cleaning["body_word_count"]) < 100,
                cleaning=cleaning,
                clean_text=clean_text,
            )
        except Exception as error:
            record.update(status="failed", error=f"{type(error).__name__}: {error}")
        append_sample(workspace, "extract")
        paper_records.append(record)
    phase_elapsed_seconds["pdf_extraction_and_cleaning"] = round(
        monotonic() - phase_started,
        6,
    )

    phase_started = monotonic()
    selection = select_analysis_documents(
        paper_records,
        profile,
        embedding_fn=embedding_fn,
    )
    phase_elapsed_seconds["paper_selection"] = round(
        monotonic() - phase_started,
        6,
    )
    included_documents = selection["included"]
    phase_started = monotonic()
    assets = build_lexical_assets(included_documents, nlp=nlp)
    phase_elapsed_seconds["lexical_assets"] = round(
        monotonic() - phase_started,
        6,
    )
    phase_started = monotonic()
    vocabulary = assets["vocabulary"]
    raw_terminology = assets["terminology_candidates"]
    terminology, terminology_minimum_documents = select_shared_terminology_candidates(
        raw_terminology,
        assets["included_document_count"],
    )
    orthography_candidates = build_orthography_review_candidates(vocabulary)
    phase_elapsed_seconds["candidate_preparation"] = round(
        monotonic() - phase_started,
        6,
    )

    analysis_dir = workspace / "analysis"
    phase_started = monotonic()
    pre_orthography_vocabulary_tsv = (
        analysis_dir / "pre-orthography-vocabulary-map.tsv"
    )
    _write_vocabulary_tsv(pre_orthography_vocabulary_tsv, vocabulary)
    _copy_output(
        pre_orthography_vocabulary_tsv,
        analysis_dir / "vocabulary-map.tsv",
    )
    _copy_output(pre_orthography_vocabulary_tsv, analysis_dir / "vocabulary.tsv")

    pre_orthography_vocabulary_jsonl = (
        analysis_dir / "pre-orthography-vocabulary-map.jsonl"
    )
    write_jsonl(pre_orthography_vocabulary_jsonl, vocabulary)
    _copy_output(
        pre_orthography_vocabulary_jsonl,
        analysis_dir / "vocabulary-map.jsonl",
    )
    _write_terminology_tsv(
        analysis_dir / "raw-terminology-candidates.tsv",
        raw_terminology,
    )
    write_jsonl(
        analysis_dir / "raw-terminology-candidates.jsonl",
        raw_terminology,
    )
    _write_terminology_tsv(analysis_dir / "terminology-candidates.tsv", terminology)
    write_jsonl(analysis_dir / "terminology-candidates.jsonl", terminology)

    orthography_review_input = {
        "schema_version": 1,
        "instruction": (
            "These are high-recall suspicious spaCy lemmas, not confirmed errors. "
            "Review every candidate using its surface forms and representative "
            "sentences. Put valid technical terms, names, abbreviations, and legitimate "
            "variants in lemma_keeps. Map a malformed lemma to its correct canonical "
            "lemma. Drop only extraction noise that should not be a vocabulary entry. "
            "Every candidate must appear in exactly one of lemma_keeps, "
            "lemma_replacements, or lemma_drops."
        ),
        "selection_schema": {
            "schema_version": 1,
            "reviewer": "current-host-agent",
            "lemma_keeps": ["observed lemma confirmed as valid"],
            "lemma_replacements": {"observed lemma": "canonical lemma"},
            "lemma_drops": ["observed lemma that is extraction noise"],
            "review_summary": "short factual string",
        },
        "candidates": orthography_candidates,
    }
    write_json(
        analysis_dir / "orthography-review-input.json", orthography_review_input
    )

    review_input = build_terminology_review_input(
        profile,
        terminology,
        terminology_minimum_documents,
    )
    write_json(analysis_dir / "terminology-review-input.json", review_input)

    public_paper_records = [
        {key: value for key, value in record.items() if key != "clean_text"}
        for record in paper_records
    ]
    records_tmp = analysis_dir / f"paper-work-records.jsonl.{os.getpid()}.tmp"
    write_jsonl(records_tmp, public_paper_records)
    os.replace(records_tmp, analysis_dir / "paper-work-records.jsonl")
    paper_decisions_path = analysis_dir / "paper-decisions.jsonl"
    write_jsonl(paper_decisions_path, public_paper_records)
    _copy_output(paper_decisions_path, analysis_dir / "papers.jsonl")
    phase_elapsed_seconds["asset_serialization"] = round(
        monotonic() - phase_started,
        6,
    )

    extracted_count = sum(record["status"] == "extracted" for record in paper_records)
    body_counts = [
        int(record["body_word_count"])
        for record in paper_records
        if record["status"] == "extracted"
    ]
    stats = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "downloaded_pdf_count": sum(
            item.get("status") in {"downloaded", "existing"} for item in download_results
        ),
        "analyzed_pdf_count": extracted_count,
        "included_paper_count": len(included_documents),
        "duplicate_paper_count": selection["duplicate_count"],
        "low_relevance_paper_count": selection["low_relevance_count"],
        "failed_pdf_count": sum(record["status"] == "failed" for record in paper_records),
        "low_extraction_confidence_count": sum(
            bool(record.get("extraction_low_confidence")) for record in paper_records
        ),
        "relevance_cutoff": selection["relevance_cutoff"],
        "median_body_words_per_extracted_pdf": median(body_counts) if body_counts else 0,
        "processed_spacy_token_count": assets["processed_spacy_token_count"],
        "lemmatizer": "spacy-en-core-web-sm",
        "content_lemma_token_count": assets["content_lemma_token_count"],
        "vocabulary_entry_count": len(vocabulary),
        "raw_terminology_candidate_count": len(raw_terminology),
        "terminology_candidate_count": len(terminology),
        "terminology_minimum_document_share": 0.10,
        "terminology_minimum_document_count": terminology_minimum_documents,
        "orthography_review_candidate_count": len(orthography_candidates),
        "orthography_review_applied": False,
        "minimum_document_count": assets["minimum_document_count"],
        "phase_elapsed_seconds": phase_elapsed_seconds,
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
    write_json(analysis_dir / "corpus-stats.json", stats)

    research_label = str(
        (profile or {}).get("title")
        or (profile or {}).get("profile_id")
        or "Research mini-corpus"
    )
    lines = [
        f"# {research_label}: first lexical assets",
        "",
        "This is the first corpus-derived Vocabulary Map and unreviewed terminology candidate set. It does not estimate the user's mastery.",
        "",
        f"- PDFs downloaded: {stats['downloaded_pdf_count']}",
        f"- PDFs text-extracted: {stats['analyzed_pdf_count']}",
        f"- Papers included in lexical statistics: {stats['included_paper_count']}",
        f"- Duplicate versions excluded from statistics: {stats['duplicate_paper_count']}",
        f"- Extreme low-relevance papers excluded from statistics: {stats['low_relevance_paper_count']}",
        f"- PDF extraction failures: {stats['failed_pdf_count']}",
        f"- Vocabulary Map entries: {stats['vocabulary_entry_count']}",
        f"- Terminology candidates awaiting host-agent review: {stats['terminology_candidate_count']}",
        f"- Orthography candidates awaiting contextual host-agent review: {stats['orthography_review_candidate_count']}",
        "",
        "No general-English baseline, topic clustering, topic reweighting, or user-mastery inference was applied.",
        "",
    ]
    (analysis_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return stats
