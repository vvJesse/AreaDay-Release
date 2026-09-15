"""Build corpus-derived lemma and terminology records with local spaCy."""

from __future__ import annotations

import math
import re
import sqlite3
import json
from collections import Counter, defaultdict, deque
from typing import Any, Iterable


SHARED_TERMINOLOGY_MIN_DOCUMENT_SHARE = 0.10
# A single document/chunk in flight is intentional: the lexical stage runs in
# a short-lived process with a small memory budget.  Keep this constant public
# because callers and tests use it as part of the stage contract.
SPACY_PIPE_BATCH_SIZE = 1
MAX_CHUNK_CHARACTERS = 50_000
MAX_CHUNK_TOKENS = 10_000


def select_shared_terminology_candidates(
    candidates: list[dict[str, Any]],
    included_document_count: int,
    *,
    minimum_document_share: float = SHARED_TERMINOLOGY_MIN_DOCUMENT_SHARE,
) -> tuple[list[dict[str, Any]], int]:
    """Keep phrases used across enough papers to represent shared field language."""
    if included_document_count < 1:
        return [], 0
    minimum_document_count = max(
        1, math.ceil(included_document_count * minimum_document_share)
    )
    selected = [
        dict(candidate)
        for candidate in candidates
        if int(candidate.get("document_count") or 0) >= minimum_document_count
    ]
    return selected, minimum_document_count


VOCAB_POS = frozenset({"NOUN", "VERB", "ADJ", "ADV"})
TERM_POS = frozenset({"NOUN", "PROPN", "ADJ"})
TERM_CONNECTORS = frozenset({"of", "for", "to", "in", "on", "with", "from", "by"})
LEMMA_RE = re.compile(r"^[a-z][a-z'-]*$")
ACRONYM_RE = re.compile(
    r"\b([A-Za-z][A-Za-z-]*(?:\s+(?:of|for|to|in|on|with|and|[A-Za-z][A-Za-z-]*)){1,8})"
    r"\s*\(([A-Z][A-Z0-9-]{1,12})\)"
)


def load_spacy_pipeline():
    import spacy

    pipeline = spacy.load("en_core_web_sm", disable=["ner"])
    pipeline.max_length = max(pipeline.max_length, 2_000_000)
    return pipeline


def _whitespace_token_count(value: str) -> int:
    return len(value.split())


def _hard_chunks(text: str, maximum_characters: int, maximum_tokens: int) -> Iterable[str]:
    """Split an overlong sentence without dropping or reordering characters."""
    if not text:
        return
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + maximum_characters)
        # A normal character window can still contain too many whitespace
        # tokens.  Move the boundary left to the end of the Nth token.
        while end > start and _whitespace_token_count(text[start:end]) > maximum_tokens:
            matches = list(re.finditer(r"\S+", text[start:end]))
            if not matches or len(matches) <= maximum_tokens:
                break
            end = start + matches[maximum_tokens - 1].end()
        if end <= start:
            end = min(length, start + maximum_characters)
        # A single token may be larger than the character bound; hard cutting
        # it is the only valid fallback, and is explicitly part of TASK-04.
        yield text[start:end]
        start = end


def _sentence_chunks(paragraph: str) -> Iterable[str]:
    """Yield sentence-sized pieces, retaining every non-empty character."""
    # This deliberately remains a light-weight splitter. spaCy is not loaded
    # by the controller/extract/select/serialize processes.
    pattern = re.compile(r".+?(?:[.!?](?:[\"')\]}]*)?(?=\s|$)|$)", re.DOTALL)
    position = 0
    for match in pattern.finditer(paragraph):
        piece = paragraph[position : match.end()]
        if piece.strip():
            yield piece
        position = match.end()
    if position < len(paragraph) and paragraph[position:].strip():
        yield paragraph[position:]


def text_chunks(
    text: str,
    maximum_characters: int = MAX_CHUNK_CHARACTERS,
    maximum_tokens: int = MAX_CHUNK_TOKENS,
) -> Iterable[str]:
    """Yield normalized paragraph chunks under both memory/input limits.

    Paragraph order is preserved.  A paragraph that exceeds either bound is
    split at sentence boundaries first; only a sentence that still exceeds a
    bound is character-split.  Joining the returned chunks with ``\\n\\n``
    reproduces the normalized source (paragraph outer whitespace removed).
    """
    if maximum_characters < 1 or maximum_tokens < 1:
        raise ValueError("chunk limits must be positive")
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_size = 0
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if (
            len(paragraph) > maximum_characters
            or _whitespace_token_count(paragraph) > maximum_tokens
        ):
            if current:
                yield "\n\n".join(current)
                current = []
                current_size = 0
                current_tokens = 0
            sentence_parts: list[str] = []
            sentence_size = 0
            sentence_tokens = 0
            for sentence in _sentence_chunks(paragraph):
                sentence = sentence.strip()
                sentence_len = len(sentence)
                sentence_word_count = _whitespace_token_count(sentence)
                if (
                    sentence_len > maximum_characters
                    or sentence_word_count > maximum_tokens
                ):
                    if sentence_parts:
                        yield " ".join(sentence_parts)
                        sentence_parts = []
                        sentence_size = 0
                        sentence_tokens = 0
                    yield from _hard_chunks(
                        sentence, maximum_characters, maximum_tokens
                    )
                    continue
                addition = sentence_len + (1 if sentence_parts else 0)
                if sentence_parts and (
                    sentence_size + addition > maximum_characters
                    or sentence_tokens + sentence_word_count > maximum_tokens
                ):
                    yield " ".join(sentence_parts)
                    sentence_parts = []
                    sentence_size = 0
                    sentence_tokens = 0
                sentence_parts.append(sentence)
                sentence_size += sentence_len + (1 if sentence_size else 0)
                sentence_tokens += sentence_word_count
            if sentence_parts:
                yield " ".join(sentence_parts)
            continue
        additional = len(paragraph) + (2 if current else 0)
        paragraph_tokens = _whitespace_token_count(paragraph)
        if current and (
            current_size + additional > maximum_characters
            or current_tokens + paragraph_tokens > maximum_tokens
        ):
            yield "\n\n".join(current)
            current = []
            current_size = 0
            current_tokens = 0
        current.append(paragraph)
        current_size += additional
        current_tokens += paragraph_tokens
    if current:
        yield "\n\n".join(current)


def juilland_dispersion(document_counts: list[int]) -> float:
    count = len(document_counts)
    if count <= 1:
        return 1.0 if sum(document_counts) else 0.0
    mean = sum(document_counts) / count
    if mean == 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in document_counts) / count
    coefficient = math.sqrt(variance) / mean
    return max(0.0, min(1.0, 1.0 - coefficient / math.sqrt(count - 1)))


def _sentence_text(sentence: Any) -> str:
    return re.sub(r"\s+", " ", sentence.text).strip()


def _term_from_span(span: Any) -> tuple[str, str] | None:
    tokens = list(span)
    while tokens and (tokens[0].is_stop or tokens[0].is_punct):
        tokens.pop(0)
    while tokens and (tokens[-1].is_stop or tokens[-1].is_punct):
        tokens.pop()
    if not 2 <= len(tokens) <= 6:
        return None

    canonical_tokens: list[str] = []
    content_count = 0
    for token in tokens:
        lower = token.text.casefold()
        if token.pos_ in TERM_POS and token.is_alpha:
            canonical = (
                token.text.casefold()
                if token.pos_ == "PROPN"
                else (token.lemma_ or token.text).casefold()
            )
            canonical_tokens.append(canonical)
            content_count += 1
        elif lower in TERM_CONNECTORS and canonical_tokens:
            canonical_tokens.append(lower)
        elif token.text == "-" and canonical_tokens:
            canonical_tokens.append("-")
        else:
            return None
    if content_count < 2 or canonical_tokens[-1] in TERM_CONNECTORS:
        return None
    canonical = " ".join(canonical_tokens).replace(" - ", "-")
    surface = re.sub(r"\s+", " ", span.text).strip()
    if len(canonical) < 5 or not any(character.isalpha() for character in canonical):
        return None
    return canonical, surface


def _add_example(
    examples: dict[str, list[dict[str, str]]],
    key: str,
    sentence: str,
    work_id: str,
    *,
    limit: int = 3,
) -> None:
    if not 35 <= len(sentence) <= 500:
        return
    records = examples[key]
    if len(records) >= limit:
        return
    if any(record["sentence"] == sentence for record in records):
        return
    records.append({"openalex_id": work_id, "sentence": sentence})


def build_lexical_assets(
    documents: list[dict[str, Any]],
    *,
    nlp: Any | None = None,
    include_raw_document: bool = False,
) -> dict[str, Any]:
    """Create lemma records and unreviewed multiword terminology candidates."""
    if include_raw_document and len(documents) > 1:
        raise ValueError("include_raw_document is only supported for one document")
    nlp = nlp or load_spacy_pipeline()
    lemma_by_document: dict[str, Counter[str]] = {}
    lemma_surfaces: dict[str, Counter[str]] = defaultdict(Counter)
    lemma_pos: dict[str, Counter[str]] = defaultdict(Counter)
    lemma_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    term_by_document: dict[str, Counter[str]] = {}
    term_surfaces: dict[str, Counter[str]] = defaultdict(Counter)
    term_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    acronym_expansions: dict[str, Counter[str]] = defaultdict(Counter)
    total_processed_tokens = 0

    document_work_ids = [str(document["openalex_id"]) for document in documents]
    document_lemma_counts = [Counter() for _ in documents]
    document_term_counts = [Counter() for _ in documents]

    pending_document_indexes: deque[int] = deque()

    def chunk_stream() -> Iterable[str]:
        for document_index, document in enumerate(documents):
            for raw_chunk in text_chunks(str(document.get("clean_text") or "")):
                for expansion, acronym in ACRONYM_RE.findall(raw_chunk):
                    cleaned_expansion = re.sub(r"\s+", " ", expansion).strip().casefold()
                    acronym_expansions[acronym][cleaned_expansion] += 1
                pending_document_indexes.append(document_index)
                yield raw_chunk

    parsed_chunks = nlp.pipe(
        chunk_stream(),
        batch_size=SPACY_PIPE_BATCH_SIZE,
        n_process=1,
    )
    for parsed in parsed_chunks:
        document_index = pending_document_indexes.popleft()
        work_id = document_work_ids[document_index]
        document_lemmas = document_lemma_counts[document_index]
        document_terms = document_term_counts[document_index]
        total_processed_tokens += len(parsed)
        for token in parsed:
            if (
                token.pos_ not in VOCAB_POS
                or token.is_stop
                or not token.is_alpha
                or token.like_num
            ):
                continue
            lemma = (token.lemma_ or token.text).casefold().strip("'-")
            if len(lemma) < 2 or not LEMMA_RE.fullmatch(lemma):
                continue
            document_lemmas[lemma] += 1
            lemma_surfaces[lemma][token.text] += 1
            lemma_pos[lemma][token.pos_] += 1

        sentence_text_cache: dict[tuple[int, int], str] = {}

        def cached_sentence_text(sentence: Any) -> str:
            key = (
                int(getattr(sentence, "start", id(sentence))),
                int(getattr(sentence, "end", id(sentence))),
            )
            if key not in sentence_text_cache:
                sentence_text_cache[key] = _sentence_text(sentence)
            return sentence_text_cache[key]

        for sentence in parsed.sents:
            sentence_text = cached_sentence_text(sentence)
            sentence_lemmas = {
                (token.lemma_ or token.text).casefold().strip("'-")
                for token in sentence
                if token.pos_ in VOCAB_POS
                and not token.is_stop
                and token.is_alpha
                and not token.like_num
            }
            for lemma in sentence_lemmas:
                if LEMMA_RE.fullmatch(lemma):
                    _add_example(lemma_examples, lemma, sentence_text, work_id)

        for chunk in parsed.noun_chunks:
            normalized = _term_from_span(chunk)
            if normalized is None:
                continue
            canonical, surface = normalized
            document_terms[canonical] += 1
            term_surfaces[canonical][surface] += 1
            _add_example(
                term_examples,
                canonical,
                cached_sentence_text(chunk.sent),
                work_id,
            )

    for work_id, document_lemmas, document_terms in zip(
        document_work_ids,
        document_lemma_counts,
        document_term_counts,
    ):
        lemma_by_document[work_id] = document_lemmas
        term_by_document[work_id] = document_terms

    work_ids = list(lemma_by_document)
    total_lemma_tokens = sum(sum(counts.values()) for counts in lemma_by_document.values())
    minimum_documents = 2 if len(work_ids) >= 3 else 1
    minimum_total_count = 3 if len(work_ids) >= 3 else 2
    vocabulary: list[dict[str, Any]] = []
    all_lemmas = set().union(*(counts.keys() for counts in lemma_by_document.values())) if work_ids else set()
    for lemma in all_lemmas:
        per_document = [lemma_by_document[work_id][lemma] for work_id in work_ids]
        total_count = sum(per_document)
        document_count = sum(value > 0 for value in per_document)
        if total_count < minimum_total_count or document_count < minimum_documents:
            continue
        surface_forms = [
            {"form": form, "count": count}
            for form, count in lemma_surfaces[lemma].most_common(8)
        ]
        source_papers = [work_id for work_id in work_ids if lemma_by_document[work_id][lemma]]
        vocabulary.append(
            {
                "lemma": lemma,
                "part_of_speech": lemma_pos[lemma].most_common(1)[0][0],
                "total_count": total_count,
                "frequency_per_million": round(
                    total_count * 1_000_000 / total_lemma_tokens, 3
                )
                if total_lemma_tokens
                else 0.0,
                "document_count": document_count,
                "document_share": round(document_count / len(work_ids), 6),
                "dispersion": round(juilland_dispersion(per_document), 6),
                "per_document_counts": {
                    work_id: lemma_by_document[work_id][lemma]
                    for work_id in work_ids
                    if lemma_by_document[work_id][lemma]
                },
                "surface_forms": surface_forms,
                "representative_sentences": lemma_examples[lemma],
                "source_papers": source_papers,
            }
        )
    vocabulary.sort(
        key=lambda item: (
            -item["document_count"],
            -item["dispersion"],
            -item["total_count"],
            item["lemma"],
        )
    )

    term_document_counts: Counter[str] = Counter()
    term_total_counts: Counter[str] = Counter()
    for counts in term_by_document.values():
        term_total_counts.update(counts)
        term_document_counts.update(counts.keys())

    eligible_terms = {
        term
        for term, count in term_total_counts.items()
        if count >= 2 and term_document_counts[term] >= minimum_documents
    }
    parent_frequencies: dict[str, list[int]] = defaultdict(list)
    for parent in eligible_terms:
        parent_tokens = parent.split()
        if len(parent_tokens) <= 2:
            continue
        for length in range(2, len(parent_tokens)):
            for start in range(0, len(parent_tokens) - length + 1):
                child = " ".join(parent_tokens[start : start + length])
                if child in eligible_terms:
                    parent_frequencies[child].append(term_total_counts[parent])

    terminology: list[dict[str, Any]] = []
    for term in eligible_terms:
        count = term_total_counts[term]
        nested = parent_frequencies.get(term) or []
        adjusted = count - (sum(nested) / len(nested) if nested else 0)
        c_value = max(0.0, math.log2(len(term.split())) * adjusted)
        aliases = [
            acronym
            for acronym, expansions in acronym_expansions.items()
            if term in expansions
        ]
        terminology.append(
            {
                "term": term,
                "total_count": count,
                "document_count": term_document_counts[term],
                "document_share": round(term_document_counts[term] / len(work_ids), 6),
                "c_value": round(c_value, 6),
                "surface_forms": [
                    {"form": form, "count": surface_count}
                    for form, surface_count in term_surfaces[term].most_common(6)
                ],
                "acronyms": sorted(aliases),
                "representative_sentences": term_examples[term],
                "source_papers": [
                    work_id for work_id in work_ids if term_by_document[work_id][term]
                ],
            }
        )
    terminology.sort(
        key=lambda item: (
            -item["document_count"],
            -item["c_value"],
            -item["total_count"],
            item["term"],
        )
    )
    result = {
        "vocabulary": vocabulary,
        "terminology_candidates": terminology,
        "included_document_count": len(work_ids),
        "processed_spacy_token_count": total_processed_tokens,
        "content_lemma_token_count": total_lemma_tokens,
        "minimum_document_count": minimum_documents,
    }
    if include_raw_document:
        work_id = work_ids[0] if work_ids else None
        result["raw_document"] = {
            "openalex_id": work_id,
            "lemma_counts": dict(lemma_by_document[work_id]) if work_id else {},
            "term_counts": dict(term_by_document[work_id]) if work_id else {},
            "lemma_surfaces": {lemma: dict(values) for lemma, values in lemma_surfaces.items()},
            "lemma_pos": {lemma: dict(values) for lemma, values in lemma_pos.items()},
            "lemma_examples": {lemma: list(values) for lemma, values in lemma_examples.items()},
            "term_surfaces": {term: dict(values) for term, values in term_surfaces.items()},
            "term_examples": {term: list(values) for term, values in term_examples.items()},
            "acronyms": {acronym: dict(values) for acronym, values in acronym_expansions.items()},
            "processed_spacy_token_count": total_processed_tokens,
        }
    return result


def assets_from_sqlite(db_path: Any) -> dict[str, Any]:
    """Stream SQLite rows, retaining at most one lemma/term group at once."""
    connection = sqlite3.connect(str(db_path))
    try:
        work_ids: list[str] = []
        cursor = connection.execute("SELECT work_id FROM documents ORDER BY ordinal")
        while batch := cursor.fetchmany(256):
            work_ids.extend(str(row[0]) for row in batch)
        minimum_documents = 2 if len(work_ids) >= 3 else 1
        token_row = connection.execute("SELECT COALESCE(SUM(count),0) FROM lemma").fetchone()
        total_lemma_tokens = int(token_row[0] or 0)
        processed_row = connection.execute(
            "SELECT COALESCE(SUM(CAST(value AS INTEGER)),0) FROM stats "
            "WHERE key='processed_spacy_token_count'"
        ).fetchone()
        total_processed_tokens = int(processed_row[0] or 0)

        vocabulary: list[dict[str, Any]] = []
        cursor = connection.execute(
            "SELECT lemma.work_id, lemma.lemma, lemma.count, lemma.pos_json, "
            "lemma.surface_json, lemma.examples_json FROM lemma "
            "JOIN documents ON documents.work_id=lemma.work_id "
            "ORDER BY lemma.lemma, documents.ordinal"
        )
        current: str | None = None
        counts: dict[str, int] = {}
        positions: Counter[str] = Counter()
        surfaces: Counter[str] = Counter()
        examples: list[dict[str, str]] = []

        def emit_lemma(lemma: str | None) -> None:
            if lemma is None:
                return
            per_document = [counts.get(work_id, 0) for work_id in work_ids]
            total_count = sum(per_document)
            document_count = sum(value > 0 for value in per_document)
            if total_count < (3 if len(work_ids) >= 3 else 2) or document_count < minimum_documents:
                return
            vocabulary.append({
                "lemma": lemma,
                "part_of_speech": positions.most_common(1)[0][0],
                "total_count": total_count,
                "frequency_per_million": round(total_count * 1_000_000 / total_lemma_tokens, 3) if total_lemma_tokens else 0.0,
                "document_count": document_count,
                "document_share": round(document_count / len(work_ids), 6),
                "dispersion": round(juilland_dispersion(per_document), 6),
                "per_document_counts": {work_id: counts[work_id] for work_id in work_ids if counts.get(work_id)},
                "surface_forms": [{"form": form, "count": value} for form, value in surfaces.most_common(8)],
                "representative_sentences": examples,
                "source_papers": [work_id for work_id in work_ids if counts.get(work_id)],
            })

        while batch := cursor.fetchmany(256):
            for work_id, lemma, count, pos_json, surface_json, examples_json in batch:
                lemma = str(lemma)
                if current != lemma:
                    emit_lemma(current)
                    current, counts, positions, surfaces, examples = lemma, {}, Counter(), Counter(), []
                counts[str(work_id)] = int(count)
                for key, value in json.loads(pos_json or "{}").items():
                    positions[key] += int(value)
                for key, value in json.loads(surface_json or "{}").items():
                    surfaces[key] += int(value)
                for value in json.loads(examples_json or "[]"):
                    if len(examples) >= 3:
                        break
                    if 35 <= len(value.get("sentence", "")) <= 500 and not any(item.get("sentence") == value.get("sentence") for item in examples):
                        examples.append(value)
        emit_lemma(current)
        vocabulary.sort(key=lambda item: (-item["document_count"], -item["dispersion"], -item["total_count"], item["lemma"]))

        # A compact summary of term totals is sufficient for C-value nesting;
        # only eligible terms retain their final per-document/source fields.
        term_summaries: dict[str, tuple[int, int, list[str], list[dict[str, Any]], Counter[str]]] = {}
        cursor = connection.execute(
            "SELECT term.work_id, term.term, term.count, term.surface_json, term.examples_json "
            "FROM term JOIN documents ON documents.work_id=term.work_id "
            "ORDER BY term.term, documents.ordinal"
        )
        current = None
        counts = {}
        surfaces = Counter()
        examples = []

        def emit_term(term: str | None) -> None:
            if term is None:
                return
            total = sum(counts.values())
            docs = [work_id for work_id in work_ids if counts.get(work_id)]
            if total >= 2 and len(docs) >= minimum_documents:
                term_summaries[term] = (total, len(docs), docs, list(examples), Counter(surfaces))

        while batch := cursor.fetchmany(256):
            for work_id, term, count, surface_json, examples_json in batch:
                term = str(term)
                if current != term:
                    emit_term(current)
                    current, counts, surfaces, examples = term, {}, Counter(), []
                counts[str(work_id)] = int(count)
                for key, value in json.loads(surface_json or "{}").items():
                    surfaces[key] += int(value)
                for value in json.loads(examples_json or "[]"):
                    if len(examples) >= 3:
                        break
                    if 35 <= len(value.get("sentence", "")) <= 500 and not any(item.get("sentence") == value.get("sentence") for item in examples):
                        examples.append(value)
        emit_term(current)
        term_total_counts = {term: data[0] for term, data in term_summaries.items()}
        parent_frequencies: dict[str, list[int]] = defaultdict(list)
        eligible_terms = set(term_summaries)
        for parent in eligible_terms:
            tokens = parent.split()
            if len(tokens) <= 2:
                continue
            for length in range(2, len(tokens)):
                for start in range(0, len(tokens) - length + 1):
                    child = " ".join(tokens[start:start + length])
                    if child in eligible_terms:
                        parent_frequencies[child].append(term_total_counts[parent])
        acronym_expansions: dict[str, set[str]] = defaultdict(set)
        cursor = connection.execute("SELECT acronym, expansion FROM acronym ORDER BY acronym, expansion")
        while batch := cursor.fetchmany(256):
            for acronym, expansion in batch:
                acronym_expansions[str(acronym)].add(str(expansion))
        terminology: list[dict[str, Any]] = []
        for term, (count, doc_count, docs, term_examples, term_surfaces) in term_summaries.items():
            nested = parent_frequencies.get(term) or []
            adjusted = count - (sum(nested) / len(nested) if nested else 0)
            terminology.append({
                "term": term,
                "total_count": count,
                "document_count": doc_count,
                "document_share": round(doc_count / len(work_ids), 6),
                "c_value": round(max(0.0, math.log2(len(term.split())) * adjusted), 6),
                "surface_forms": [{"form": form, "count": value} for form, value in term_surfaces.most_common(6)],
                "acronyms": sorted(acronym for acronym, expansions in acronym_expansions.items() if term in expansions),
                "representative_sentences": term_examples,
                "source_papers": docs,
            })
        terminology.sort(key=lambda item: (-item["document_count"], -item["c_value"], -item["total_count"], item["term"]))
        return {
            "vocabulary": vocabulary,
            "terminology_candidates": terminology,
            "included_document_count": len(work_ids),
            "processed_spacy_token_count": total_processed_tokens,
            "content_lemma_token_count": total_lemma_tokens,
            "minimum_document_count": minimum_documents,
        }
    finally:
        connection.close()
