"""Deterministic metadata discovery helpers for AreaDay."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


OPENALEX_API = "https://api.openalex.org/works"
AREADAY_CREDENTIALS = Path.home() / ".areaday" / "credentials.ini"
LEGACY_CREDENTIALS = Path.home() / ".researchramp" / "credentials.ini"
CONFIG_DIR_VARIABLE = "AREADAY_CONFIG_DIR"
OPENALEX_API_KEY_VARIABLE = "OPENALEX_API_KEY"
ARXIV_ID_RE = re.compile(
    r"(?:arxiv(?:\.org/(?:abs|pdf)/|:)|10\.48550/arxiv\.)("
    r"(?:[a-z][a-z.\-]+/\d{7})|(?:\d{4}\.\d{4,5})"
    r")(?:v\d+)?",
    re.IGNORECASE,
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    temporary.replace(path)


def credentials_path() -> Path:
    """Return the AreaDay-owned OpenAlex configuration file."""
    override = os.environ.get(CONFIG_DIR_VARIABLE, "").strip()
    if override:
        return Path(override).expanduser() / "credentials.ini"
    return AREADAY_CREDENTIALS


def load_openalex_api_key() -> str:
    """Read the one AreaDay-owned OpenAlex configuration."""
    environment_key = os.environ.get(OPENALEX_API_KEY_VARIABLE, "").strip()
    if environment_key:
        return accepted_api_key(environment_key, f"${OPENALEX_API_KEY_VARIABLE}")
    credentials = credentials_path()
    if not credentials.is_file() and LEGACY_CREDENTIALS.is_file():
        credentials.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_CREDENTIALS, credentials)
        credentials.chmod(0o600)
    if not credentials.is_file():
        raise RuntimeError(
            "AreaDay needs a personal OpenAlex API key before it can search. "
            "Run the one-time OpenAlex configuration and paste the key into: "
            f"{credentials}"
        )
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with credentials.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except configparser.Error as exc:
        raise ValueError("AreaDay OpenAlex configuration is malformed") from exc
    if not parser.has_section("openalex"):
        raise ValueError("AreaDay credentials do not contain [openalex]")
    api_key = parser.get("openalex", "api_key", fallback="").strip()
    return accepted_api_key(api_key, str(credentials))


def accepted_api_key(api_key: str, source: str) -> str:
    """Reject the values AreaDay cannot search with, with advice that works."""
    if not api_key:
        raise RuntimeError(
            "AreaDay needs a personal OpenAlex API key before it can search. "
            f"Add the key after 'api_key =' in: {source}"
        )
    if api_key.lower() == "anonymous":
        raise RuntimeError(
            "AreaDay no longer supports anonymous OpenAlex access, because the "
            "shared anonymous budget cannot finish a corpus. Replace "
            f"'anonymous' with a personal API key in: {source}"
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,200}", api_key):
        raise ValueError("AreaDay contains an invalid OpenAlex API key")
    return api_key


def stable_hash(value: Any, length: int = 16) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for token, indexes in inverted_index.items():
        positions.extend((index, token) for index in indexes)
    positions.sort()
    return " ".join(token for _, token in positions)


def openalex_work_id(value: str) -> str:
    return value.rstrip("/").split("/")[-1]


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized or None


def extract_arxiv_id(work: dict[str, Any]) -> str | None:
    """Extract a canonical arXiv identifier only from explicit metadata URLs/IDs."""
    values: list[str] = []
    explicit = work.get("arxiv_id")
    if explicit:
        values.append(str(explicit))
    for value in (work.get("ids") or {}).values():
        if value:
            values.append(str(value))
    values.extend(str(value) for value in (work.get("doi"),) if value)
    for key in ("best_oa_location", "primary_location"):
        location = work.get(key) or {}
        for url_key in ("landing_page_url", "pdf_url"):
            if location.get(url_key):
                values.append(str(location[url_key]))
    for location in work.get("locations") or []:
        for url_key in ("landing_page_url", "pdf_url"):
            if location.get(url_key):
                values.append(str(location[url_key]))

    for value in values:
        raw = value.strip()
        if re.fullmatch(
            r"(?:[a-z][a-z.\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
            raw,
            re.IGNORECASE,
        ):
            return re.sub(r"v\d+$", "", raw, flags=re.IGNORECASE)
        match = ARXIV_ID_RE.search(raw)
        if match:
            return match.group(1)
    return None


def _nested(mapping: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _has_openalex_pdf(work: dict[str, Any]) -> bool:
    has_content = work.get("has_content")
    if isinstance(has_content, dict) and has_content.get("pdf"):
        return True
    content_urls = work.get("content_urls")
    return isinstance(content_urls, dict) and bool(content_urls.get("pdf"))


def _license(work: dict[str, Any]) -> str | None:
    return (
        _nested(work.get("best_oa_location"), "license")
        or _nested(work.get("primary_location"), "license")
        or None
    )


def _open_access_locations(work: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep every explicit OA PDF location so acquisition can change mirrors."""
    ordered_locations: list[dict[str, Any]] = []
    for location in [
        work.get("best_oa_location") or {},
        work.get("primary_location") or {},
        *(work.get("locations") or []),
    ]:
        pdf_url = location.get("pdf_url")
        if not pdf_url or location.get("is_oa") is not True:
            continue
        source = location.get("source") or {}
        ordered_locations.append(
            {
                "pdf_url": str(pdf_url),
                "landing_page_url": location.get("landing_page_url"),
                "license": location.get("license"),
                "version": location.get("version"),
                "source": source.get("display_name"),
                "source_type": source.get("type"),
                "is_open_access": True,
            }
        )

    unique: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for location in ordered_locations:
        url = location["pdf_url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(location)
    return unique


def _authors(work: dict[str, Any], limit: int = 12) -> list[str]:
    names: list[str] = []
    for authorship in work.get("authorships") or []:
        name = _nested(authorship, "author", "display_name")
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _topics(work: dict[str, Any], limit: int = 8) -> list[str]:
    return [
        topic["display_name"]
        for topic in (work.get("topics") or [])[:limit]
        if topic.get("display_name")
    ]


def _openalex_topic_metadata(topic: Any) -> dict[str, Any] | None:
    if not isinstance(topic, dict) or not topic.get("id"):
        return None

    def taxonomy_node(value: Any) -> dict[str, str] | None:
        if not isinstance(value, dict) or not value.get("id"):
            return None
        return {
            "id": str(value["id"]).rsplit("/", 1)[-1],
            "display_name": str(value.get("display_name") or ""),
        }

    return {
        "id": str(topic["id"]).rsplit("/", 1)[-1],
        "display_name": str(topic.get("display_name") or ""),
        "subfield": taxonomy_node(topic.get("subfield")),
        "field": taxonomy_node(topic.get("field")),
        "domain": taxonomy_node(topic.get("domain")),
    }


class OpenAlexClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        api_key: str | None = None,
        refresh: bool = False,
    ) -> None:
        self.cache_dir = cache_dir
        self.api_key = api_key
        self.refresh = refresh

    def search(
        self,
        query: str,
        *,
        per_page: int,
        filters: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "search": query,
            "per_page": str(per_page),
            "page": "1",
        }
        if filters:
            params["filter"] = filters
        cache_identity = dict(params)
        cache_path = self.cache_dir / f"{stable_hash(cache_identity, 24)}.json"
        if cache_path.exists() and not self.refresh:
            return read_json(cache_path)

        url = OPENALEX_API + "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": "AreaDay/1.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, headers=headers)

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                write_json(cache_path, payload)
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"OpenAlex search failed for {query!r}: {last_error}")


def candidate_from_openalex_work(work: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one OpenAlex Work for the shared multi-provider pipeline."""
    raw_id = work.get("id")
    if not raw_id:
        return None
    work_id = openalex_work_id(str(raw_id))
    primary_topic = _openalex_topic_metadata(work.get("primary_topic"))
    topic_metadata = [
        normalized
        for topic in (work.get("topics") or [])
        if (normalized := _openalex_topic_metadata(topic)) is not None
    ]
    return {
        "openalex_id": work_id,
        "openalex_url": raw_id,
        "doi": normalize_doi(work.get("doi")),
        "arxiv_id": extract_arxiv_id(work),
        "ids": work.get("ids") or {},
        "title": work.get("title") or work.get("display_name") or "Untitled",
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "type": work.get("type"),
        "language": work.get("language"),
        "cited_by_count": work.get("cited_by_count") or 0,
        "authors": _authors(work),
        "source": _nested(work.get("primary_location"), "source", "display_name"),
        "topics": _topics(work),
        "primary_topic": primary_topic,
        "topic_metadata": topic_metadata,
        "is_open_access": bool(_nested(work.get("open_access"), "is_oa")),
        "open_access_status": _nested(work.get("open_access"), "oa_status"),
        "license": _license(work),
        "oa_locations": _open_access_locations(work),
        "has_openalex_pdf": _has_openalex_pdf(work),
        "landing_page_url": (
            _nested(work.get("best_oa_location"), "landing_page_url")
            or _nested(work.get("primary_location"), "landing_page_url")
        ),
        "pdf_url": (
            _nested(work.get("best_oa_location"), "pdf_url")
            or _nested(work.get("primary_location"), "pdf_url")
        ),
    }
