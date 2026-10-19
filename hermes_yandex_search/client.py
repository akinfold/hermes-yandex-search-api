"""Yandex Search API v2 client.

A small HTTP client for the Yandex Search API that needs nothing beyond
``httpx`` and the standard library. It knows nothing about Hermes and can be
unit-tested in isolation.

Two search modes are implemented:

* :meth:`YandexSearchClient.web_search` -> classic web results (a list of
  links with titles and snippets), parsed from the Base64/XML ``rawData``
  payload the ``/v2/web/search`` endpoint returns.
* :meth:`YandexSearchClient.generative_search` -> a grounded, LLM-synthesised
  answer with cited sources from the ``/v2/gen/search`` endpoint.

Every request is authenticated with an ``Authorization: Api-Key <key>`` header
and carries the mandatory ``folderId`` in the JSON body (the API rejects
requests without it).

Docs: https://aistudio.yandex.ru/docs/ru/search-api/concepts/
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any

# ElementTree only holds the parsed tree: _parse_xml drives Expat itself, checks
# the document and the Expat version first, and refuses any DTD.
from xml.etree import ElementTree as ET  # nosec B405
from xml.parsers import expat

import httpx

#: The largest XML document _parse_xml accepts, in bytes: about 4.7 times the
#: largest live 100-result report measured (about 445 KB). pyexpat feeds Expat
#: chunks of 1 MiB, so a document this size takes at most two XML_Parse calls,
#: and on Expat before 2.6.0 a token spanning them is re-scanned at most once:
#: CVE-2023-52425 is bounded, not unreachable. The cap also bounds the time and
#: memory of any cost in Expat not known yet. pyexpat holds the GIL while it
#: parses, so a slow parse blocks the whole Hermes process; the cap keeps that
#: short.
MAX_XML_BYTES = 2 * 1024 * 1024

#: The longest Base64 ``rawData`` that can decode to MAX_XML_BYTES or fewer:
#: Base64 turns every 3 bytes into 4 characters and pads the last group. It is
#: decoded with ``validate=True``, which refuses whitespace and anything else
#: outside the alphabet, so nothing longer can decode to a document under the cap.
MAX_RAW_DATA_CHARS = 4 * -(-MAX_XML_BYTES // 3)

#: The oldest Expat this plugin parses with: a safety margin on top of the
#: guards in _parse_xml, not a promise that Expat has no bugs. The guards work
#: on any Expat: refusing the DTD rules out every entity and every external
#: fetch, reading only UTF-8 keeps Expat's UTF-16 decoder out of reach (it let
#: malformed surrogates through before 2.8.5, CVE-2026-93990), and
#: MAX_XML_BYTES bounds time and memory. They already neutralise what 2.4.5
#: fixed, Expat passing malformed UTF-8 and namespace separators on to the
#: application (CVE-2022-25235, CVE-2022-25236): malformed UTF-8 never reaches
#: Expat, and a separator in a namespace URI only bends a name, which this
#: module handles as plain Python text. Python can use the system libexpat
#: instead of its own copy, so the version is checked at run time.
#: Distributions backport fixes without raising the version, so the floor stays
#: below what current ones ship (2.5.0 on Debian 12 and RHEL 9, 2.4.7 on
#: Ubuntu 22.04).
MIN_EXPAT_VERSION = (2, 4, 5)

#: Where the README explains which Expat the plugin needs.
REQUIREMENTS_URL = "https://github.com/akinfold/hermes-yandex-search-api#requirements"

DEFAULT_BASE_URL = "https://searchapi.api.cloud.yandex.net"
DEFAULT_SEARCH_TYPE = "SEARCH_TYPE_RU"
DEFAULT_TIMEOUT = 30.0

WEB_SEARCH_PATH = "/v2/web/search"
GEN_SEARCH_PATH = "/v2/gen/search"

# Market/domain the query is run against. See
# https://aistudio.yandex.ru/docs/ru/search-api/concepts/web-search
VALID_SEARCH_TYPES = frozenset(
    {
        "SEARCH_TYPE_RU",
        "SEARCH_TYPE_TR",
        "SEARCH_TYPE_COM",
        "SEARCH_TYPE_KK",
        "SEARCH_TYPE_BE",
        "SEARCH_TYPE_UZ",
    }
)


class YandexSearchError(Exception):
    """Raised when the Yandex Search API returns an error or an unusable body."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


@dataclass(frozen=True)
class WebResult:
    """A single web search result."""

    title: str
    url: str
    description: str
    domain: str = ""
    position: int = 0


@dataclass(frozen=True)
class GenerativeSource:
    """A source cited by the generative answer."""

    url: str
    title: str = ""
    used_text: str = ""


@dataclass(frozen=True)
class GenerativeAnswer:
    """The result of a generative (grounded) search."""

    text: str
    sources: list[GenerativeSource] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    fixed_query: str = ""
    is_answer_rejected: bool = False
    is_bullet_answer: bool = False


class YandexSearchClient:
    """Client for the Yandex Search API v2.

    Args:
        api_key: Yandex Cloud API key (``Authorization: Api-Key`` value).
        folder_id: Yandex Cloud folder ("catalog") id; sent as ``folderId``.
        search_type: Default market/domain enum used for both search modes.
        base_url: API host; override for testing or a private gateway.
        timeout: Per-request timeout in seconds.
        client: Optional pre-built ``httpx.Client`` (useful for tests). When
            provided, the caller owns its lifecycle and :meth:`close` is a
            no-op for it.
    """

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        *,
        search_type: str = DEFAULT_SEARCH_TYPE,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not folder_id or not folder_id.strip():
            raise ValueError("folder_id must be a non-empty string")
        if search_type not in VALID_SEARCH_TYPES:
            raise ValueError(
                f"search_type must be one of {sorted(VALID_SEARCH_TYPES)}, got {search_type!r}"
            )

        self._api_key = api_key.strip()
        self._folder_id = folder_id.strip()
        self._search_type = search_type
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client if this instance created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> YandexSearchClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- transport ----------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        body = dict(payload)
        body["folderId"] = self._folder_id
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Api-Key {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._client.post(url, json=body, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise YandexSearchError(f"HTTP request to {path} failed: {exc}") from exc

        if response.status_code >= 400:
            raise self._error_from_response(response)
        return response

    @staticmethod
    def _error_from_response(response: httpx.Response) -> YandexSearchError:
        message = f"HTTP {response.status_code}"
        request_id: str | None = None
        try:
            data = response.json()
        except ValueError:
            text = response.text.strip()
            if text:
                message = f"{message}: {text[:500]}"
            return YandexSearchError(message, status_code=response.status_code)

        if isinstance(data, dict):
            api_message = data.get("message") or data.get("error")
            if api_message:
                message = f"{message}: {api_message}"
            for detail in data.get("details", []) or []:
                if isinstance(detail, dict) and detail.get("requestId"):
                    request_id = detail["requestId"]
                    break
        return YandexSearchError(message, status_code=response.status_code, request_id=request_id)

    # -- web search ---------------------------------------------------------

    def web_search(
        self,
        query: str,
        *,
        n_results: int = 5,
        page: int = 0,
        region: str | None = None,
        localization: str | None = None,
        fix_typo: bool = True,
        family_mode: str = "FAMILY_MODE_MODERATE",
    ) -> list[WebResult]:
        """Run a classic web search and return a list of :class:`WebResult`.

        Args:
            query: Free-text search query.
            n_results: Maximum number of results to return (1..100).
            page: Zero-based result page index.
            region: Optional Yandex region id (e.g. ``"213"`` for Moscow).
            localization: Optional ``LOCALIZATION_*`` enum for snippet language.
            fix_typo: Whether Yandex should auto-correct typos in the query.
            family_mode: Adult-content filter (``FAMILY_MODE_*``).
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        n_results = max(1, min(int(n_results), 100))

        payload: dict[str, Any] = {
            "query": {
                "searchType": self._search_type,
                "queryText": query.strip(),
                "page": max(0, int(page)),
                "familyMode": family_mode,
                "fixTypoMode": "FIX_TYPO_MODE_ON" if fix_typo else "FIX_TYPO_MODE_OFF",
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_DEEP",
                "groupsOnPage": n_results,
                "docsInGroup": 1,
            },
            "responseFormat": "FORMAT_XML",
        }
        if region:
            payload["region"] = str(region)
        if localization:
            payload["l10N"] = localization

        response = self._post(WEB_SEARCH_PATH, payload)
        raw = self._extract_raw_data(response)
        results = _parse_web_xml(raw)
        return results[:n_results]

    @staticmethod
    def _extract_raw_data(response: httpx.Response) -> bytes:
        try:
            data = response.json()
        except ValueError as exc:
            raise YandexSearchError("Yandex response was not valid JSON") from exc
        raw_data = data.get("rawData") if isinstance(data, dict) else None
        if not raw_data:
            raise YandexSearchError("Yandex response did not contain 'rawData'")
        # Refuse a payload that cannot decode to a document under the cap before
        # paying to decode it; _check_document still checks the decoded size.
        if len(raw_data) > MAX_RAW_DATA_CHARS:
            raise YandexSearchError(
                f"Refusing to parse the Yandex XML response: its Base64 is {len(raw_data)} "
                f"characters, more than the limit of {MAX_RAW_DATA_CHARS}"
            )
        try:
            return base64.b64decode(raw_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise YandexSearchError("Yandex 'rawData' was not valid Base64") from exc

    # -- generative search --------------------------------------------------

    def generative_search(
        self,
        query: str | None = None,
        *,
        messages: list[dict[str, str]] | None = None,
        sites: list[str] | None = None,
        hosts: list[str] | None = None,
        urls: list[str] | None = None,
        fix_misspell: bool = True,
    ) -> GenerativeAnswer:
        """Run a generative (grounded) search and return a :class:`GenerativeAnswer`.

        Provide either ``query`` (a single user turn) or a full ``messages``
        list. ``sites``/``hosts``/``urls`` optionally restrict the sources the
        answer is grounded on (mutually exclusive; the first non-empty one is
        used).
        """
        if messages is None:
            if not query or not query.strip():
                raise ValueError("either query or messages must be provided")
            messages = [{"role": "ROLE_USER", "content": query.strip()}]
        if not messages:
            raise ValueError("messages must not be empty")

        payload: dict[str, Any] = {
            "messages": messages,
            "searchType": self._search_type,
            "fixMisspell": bool(fix_misspell),
        }
        if sites:
            payload["site"] = {"site": list(sites)}
        elif hosts:
            payload["host"] = {"host": list(hosts)}
        elif urls:
            payload["url"] = {"url": list(urls)}

        response = self._post(GEN_SEARCH_PATH, payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise YandexSearchError("Yandex generative response was not valid JSON") from exc
        return _parse_generative(data)


# ---------------------------------------------------------------------------
# Parsing helpers (module-level so they are trivially unit-testable)
# ---------------------------------------------------------------------------


def _element_text(element: ET.Element | None) -> str:
    """Return the full inline text of an element, dropping highlight tags.

    Yandex wraps matched terms in ``<hlword>`` inside ``<title>`` and
    ``<passage>``; ``itertext`` flattens those away while preserving order.
    """
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _strip_namespaces(root: ET.Element) -> None:
    """Drop XML namespaces in place so plain tag paths match.

    The Yandex report is currently namespace-free, but stripping any namespace
    (``{ns}tag`` -> ``tag``) keeps parsing working should Yandex ever add one,
    rather than silently returning zero results.
    """
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.rsplit("}", 1)[1]


def _raise_for_xml_error(root: ET.Element) -> None:
    """Yandex sometimes reports failures inside the XML envelope rather than by status."""
    error = root.find("./response/error")
    if error is not None and (error.text or "").strip():
        raise YandexSearchError(f"Yandex search error: {error.text.strip()}")


def _version_text(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def _check_expat_version() -> None:
    """Refuse to parse anything with an Expat older than :data:`MIN_EXPAT_VERSION`."""
    found = tuple(expat.version_info)
    if found < MIN_EXPAT_VERSION:
        raise YandexSearchError(
            "Refusing to parse the Yandex XML response: this Python uses Expat "
            f"{_version_text(found)}, older than {_version_text(MIN_EXPAT_VERSION)}, the "
            f"oldest this plugin parses with. See {REQUIREMENTS_URL}"
        )


def _is_utf8(raw: bytes) -> bool:
    """Whether *raw* is UTF-8 without a NUL byte, the only form Expat gets to read.

    Even when told the encoding, Expat switches to UTF-16 at a UTF-16 byte order
    mark, which is never UTF-8, or when either of the first two bytes is NUL; NUL
    is refused anywhere.
    """
    if b"\x00" in raw:
        return False
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _check_document(raw: bytes) -> None:
    """Refuse a document larger than :data:`MAX_XML_BYTES` or not in UTF-8."""
    if len(raw) > MAX_XML_BYTES:
        raise YandexSearchError(
            f"Refusing to parse the Yandex XML response: it is {len(raw)} bytes, "
            f"more than the limit of {MAX_XML_BYTES}"
        )
    if not _is_utf8(raw):
        raise YandexSearchError("Rejected Yandex XML response: it is not UTF-8")


def _clark(name: str) -> str:
    """Spell a name as ElementTree does: Expat's ``uri}local`` becomes ``{uri}local``."""
    return "{" + name if "}" in name else name


def _refuse_dtd(*_args: object) -> None:
    """Expat calls this at ``<!DOCTYPE``, before it reads any of the DTD."""
    raise YandexSearchError("Rejected unsafe Yandex XML response: it declares a DTD")


def _parse_xml(raw: bytes) -> ET.Element:
    """Parse an untrusted XML document into the tree ``ElementTree.fromstring`` would build.

    Yandex sends UTF-8, so the document must be UTF-8, whatever encoding it
    declares, and at most :data:`MAX_XML_BYTES` long. Entities can only be
    declared in a DTD, so refusing the DTD at ``<!DOCTYPE`` leaves no entity to
    expand (billion laughs, quadratic blowup) and no external entity or DTD to
    resolve; Expat itself never opens files or connections. ElementTree's own
    parser keeps parsing after a handler raises, so Expat is driven here
    directly: a handler that raises stops it on the spot.
    """
    _check_expat_version()
    _check_document(raw)
    builder = ET.TreeBuilder()
    # The encoding given here overrides the one the document declares, so Expat
    # never calls back into Python's codecs for an encoding it lacks.
    parser = expat.ParserCreate(encoding="utf-8", namespace_separator="}")
    parser.StartDoctypeDeclHandler = _refuse_dtd
    parser.StartElementHandler = lambda tag, attrib: builder.start(
        _clark(tag), {_clark(name): value for name, value in attrib.items()}
    )
    parser.EndElementHandler = lambda tag: builder.end(_clark(tag))
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise YandexSearchError(f"Could not parse Yandex XML response: {exc}") from exc
    return builder.close()


def _parse_web_xml(raw: bytes) -> list[WebResult]:
    """Parse the ``<yandexsearch>`` XML document into :class:`WebResult` items.

    The document is untrusted: :func:`_parse_xml` refuses any DTD, so a malicious
    response cannot mount an entity-expansion (billion laughs) or external-entity
    (XXE) attack. It also refuses a document that is too large or not UTF-8, and
    refuses to parse at all on an Expat older than :data:`MIN_EXPAT_VERSION`.
    """
    root = _parse_xml(raw)
    _strip_namespaces(root)
    _raise_for_xml_error(root)

    results: list[WebResult] = []
    for doc in root.findall("./response/results/grouping/group/doc"):
        url = _element_text(doc.find("url")) or (doc.get("url") or "")
        if not url:
            continue
        results.append(
            WebResult(
                title=_element_text(doc.find("title")) or url,
                url=url,
                description=_extract_description(doc),
                domain=_element_text(doc.find("domain")),
                position=len(results) + 1,
            )
        )
    return results


def _extract_description(doc: ET.Element) -> str:
    """Build a snippet from the document's passages, falling back to headline."""
    passages = [_element_text(passage) for passage in doc.findall("./passages/passage")]
    passages = [p for p in passages if p]
    if passages:
        return " ".join(passages)
    return _element_text(doc.find("headline"))


def _generative_sources(raw: Any) -> list[GenerativeSource]:
    """The cited sources, skipping anything that is not an object."""
    return [
        GenerativeSource(
            url=src.get("url", ""),
            title=src.get("title", ""),
            used_text=src.get("usedText", ""),
        )
        for src in (raw or [])
        if isinstance(src, dict)
    ]


def _generative_queries(raw: Any) -> list[str]:
    """The queries Yandex actually ran; entries arrive as objects or bare strings."""
    queries: list[str] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("text"):
            queries.append(item["text"])
        elif isinstance(item, str):
            queries.append(item)
    return queries


def _parse_generative(data: Any) -> GenerativeAnswer:
    """Parse a ``GenSearchResponse`` (or a 1-element array wrapping one)."""
    if isinstance(data, list):
        # Streaming-off responses are sometimes wrapped in a 1-element array;
        # take the last (most complete) element.
        data = data[-1] if data else {}
    if not isinstance(data, dict):
        raise YandexSearchError("Unexpected generative response shape")

    message = data.get("message") or {}
    text = message.get("content", "") if isinstance(message, dict) else ""

    return GenerativeAnswer(
        text=text,
        sources=_generative_sources(data.get("sources")),
        search_queries=_generative_queries(data.get("searchQueries")),
        fixed_query=data.get("fixedMisspellQuery", "") or "",
        is_answer_rejected=bool(data.get("isAnswerRejected", False)),
        is_bullet_answer=bool(data.get("isBulletAnswer", False)),
    )
