"""Untrusted XML: what the web-search parser refuses, and which Expat it parses with."""

from __future__ import annotations

import codecs
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from hermes_yandex_search import client
from hermes_yandex_search.client import (
    MAX_XML_BYTES,
    MIN_EXPAT_VERSION,
    YandexSearchError,
    _parse_web_xml,
    _parse_xml,
)

from .conftest import SAMPLE_WEB_XML

#: What _parse_xml says when it refuses a DTD. Expat's own limits (on entity
#: amplification, for one) fail with other messages, so matching this proves the
#: refusal happened before Expat expanded anything.
DTD_REFUSED = "Rejected unsafe Yandex XML response: it declares a DTD"

NOT_UTF8 = "Rejected Yandex XML response: it is not UTF-8"

FILE_TEXT = "the contents of a local file"


def report(dtd: str = "", title: str = "Title", url_attr: str = "") -> bytes:
    """A one-result Yandex report: *dtd* before the root, *title* as the result's title."""
    doc_attrs = f" url='{url_attr}'" if url_attr else ""
    url = "" if url_attr else "<url>https://x.example/</url>"
    return (
        f"<?xml version='1.0' encoding='utf-8'?>{dtd}"
        "<yandexsearch><response><results><grouping><group>"
        f"<doc{doc_attrs}>{url}<title>{title}</title></doc>"
        "</group></grouping></results></response></yandexsearch>"
    ).encode()


@pytest.fixture
def local_file(tmp_path: Path) -> Path:
    path = tmp_path / "local.txt"
    path.write_text(FILE_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    """A local port that counts as fetched if anything connects to it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(0.2)
        yield server


def assert_never_connected(server: socket.socket) -> None:
    with pytest.raises(TimeoutError):
        server.accept()


def url_of(server: socket.socket) -> str:
    host, port = server.getsockname()
    return f"http://{host}:{port}/evil"


# -- the DTD is refused, whatever it declares ---------------------------------


def test_refuses_even_a_harmless_entity() -> None:
    # Expat itself would expand this one: only the parser's own refusal stops it.
    payload = report("<!DOCTYPE yandexsearch [<!ENTITY t 'tea'>]>", "&t;")
    with pytest.raises(YandexSearchError, match=DTD_REFUSED):
        _parse_web_xml(payload)


def test_refuses_billion_laughs() -> None:
    entities = "<!ENTITY lol0 'lol'>" + "".join(
        f"<!ENTITY lol{level} '{f'&lol{level - 1};' * 10}'>" for level in range(1, 10)
    )
    payload = report(f"<!DOCTYPE yandexsearch [{entities}]>", "&lol9;")
    with pytest.raises(YandexSearchError, match=DTD_REFUSED):
        _parse_web_xml(payload)


def test_refuses_quadratic_blowup() -> None:
    payload = report(f"<!DOCTYPE yandexsearch [<!ENTITY big '{'B' * 50_000}'>]>", "&big;" * 50_000)
    with pytest.raises(YandexSearchError, match=DTD_REFUSED):
        _parse_web_xml(payload)


def test_refuses_an_external_file_entity(local_file: Path) -> None:
    payload = report(
        f"<!DOCTYPE yandexsearch [<!ENTITY xxe SYSTEM '{local_file.as_uri()}'>]>", "&xxe;"
    )
    with pytest.raises(YandexSearchError, match=DTD_REFUSED) as exc_info:
        _parse_web_xml(payload)
    assert FILE_TEXT not in str(exc_info.value)


def test_refuses_an_external_network_entity(listener: socket.socket) -> None:
    payload = report(
        f"<!DOCTYPE yandexsearch [<!ENTITY xxe SYSTEM '{url_of(listener)}'>]>", "&xxe;"
    )
    with pytest.raises(YandexSearchError, match=DTD_REFUSED):
        _parse_web_xml(payload)
    assert_never_connected(listener)


def test_refuses_an_external_dtd(listener: socket.socket, local_file: Path) -> None:
    payload = report(f"<!DOCTYPE yandexsearch SYSTEM '{url_of(listener)}'>", "&xxe;")
    with pytest.raises(YandexSearchError, match=DTD_REFUSED):
        _parse_web_xml(payload)
    assert_never_connected(listener)

    payload = report(f"<!DOCTYPE yandexsearch SYSTEM '{local_file.as_uri()}'>")
    with pytest.raises(YandexSearchError, match=DTD_REFUSED) as exc_info:
        _parse_web_xml(payload)
    assert FILE_TEXT not in str(exc_info.value)


# -- what is left without a DTD -----------------------------------------------


@pytest.mark.parametrize("where", ["text", "attribute"])
def test_large_tokens_are_harmless(where: str) -> None:
    # One token larger than the 1 MiB chunks CPython feeds Expat: the case of
    # CVE-2023-52425, which Expat before 2.6.0 re-scans once per chunk. Under
    # MAX_XML_BYTES that is at most one re-scan; here it is a long title or URL.
    big = "A" * (MAX_XML_BYTES - 1024)
    assert len(big) > 1024 * 1024
    if where == "text":
        (result,) = _parse_web_xml(report(title=big))
        assert result.title == big
    else:
        (result,) = _parse_web_xml(report(url_attr=f"https://x.example/{big}"))
        assert result.url == f"https://x.example/{big}"


def test_refuses_a_document_over_the_size_limit() -> None:
    title = "A" * (MAX_XML_BYTES - len(report(title="")))
    (result,) = _parse_web_xml(report(title=title))
    assert result.title == title

    # One byte over the limit, with a DTD and a byte that is never UTF-8: only
    # the size is reported, so the size check ran before the UTF-8 check and
    # before Expat saw anything.
    dtd = "<!DOCTYPE yandexsearch [<!ENTITY t 'tea'>]>"
    oversized = report(dtd=dtd, title=title[len(dtd) :]) + b"\xff"
    assert len(oversized) == MAX_XML_BYTES + 1
    with pytest.raises(YandexSearchError) as exc_info:
        _parse_web_xml(oversized)
    assert str(exc_info.value) == (
        f"Refusing to parse the Yandex XML response: it is {MAX_XML_BYTES + 1} bytes, "
        f"more than the limit of {MAX_XML_BYTES}"
    )


#: The largest live 100-result report measured, in October 2026: about 445 KB.
LARGEST_REPORT_MEASURED = 445_000


def test_the_size_limit_leaves_a_margin_over_real_reports() -> None:
    # Much less margin risks refusing a real report; a much higher limit lets a
    # hostile one cost more time and memory.
    assert MAX_XML_BYTES >= 4 * LARGEST_REPORT_MEASURED
    assert MAX_XML_BYTES <= 4 * 1024 * 1024


# -- UTF-8 only ----------------------------------------------------------------

#: A lone UTF-16 high surrogate followed by "A": Expat before 2.8.5 decodes the
#: pair as U+10041, a character the document never contained (CVE-2026-93990).
LONE_SURROGATE = (
    codecs.BOM_UTF16_LE
    + "<?xml version='1.0' encoding='utf-16'?><y>".encode("utf-16-le")
    + b"\x00\xd8"
    + "A</y>".encode("utf-16-le")
)


@pytest.mark.parametrize(
    "raw",
    [
        LONE_SURROGATE,
        codecs.BOM_UTF16_LE + "<r>x</r>".encode("utf-16-le"),
        codecs.BOM_UTF16_BE + "<r>x</r>".encode("utf-16-be"),
        "<r>x</r>".encode("utf-16-le"),
        "<r>x</r>".encode("utf-16-be"),
        b"<?xml version='1.0' encoding='windows-1252'?><r>\x80</r>",
        b"<r>a\x00b</r>",
    ],
    ids=[
        "lone-surrogate",
        "utf-16le-bom",
        "utf-16be-bom",
        "utf-16le",
        "utf-16be",
        "windows-1252",
        "nul",
    ],
)
def test_refuses_a_document_that_is_not_utf8(raw: bytes) -> None:
    with pytest.raises(YandexSearchError, match=NOT_UTF8):
        _parse_xml(raw)


@pytest.mark.parametrize("declared", ["windows-1252", "iso-8859-1", "utf-16", "x-unknown"])
def test_reads_utf8_whatever_encoding_is_declared(declared: str) -> None:
    raw = f"<?xml version='1.0' encoding='{declared}'?><r>\u20ac\u0436</r>".encode()
    assert _parse_xml(raw).text == "\u20ac\u0436"


def test_accepts_a_utf8_byte_order_mark() -> None:
    (result,) = _parse_web_xml(codecs.BOM_UTF8 + report())
    assert result.title == "Title"


def test_an_undeclared_entity_is_a_parse_error() -> None:
    with pytest.raises(YandexSearchError, match="Could not parse Yandex XML response: undefined"):
        _parse_web_xml(report(title="&xxe;"))


def test_builds_the_tree_elementtree_would() -> None:
    root = _parse_xml(
        b"<?xml version='1.0' encoding='utf-8'?>"
        b"<y:a xmlns:y='urn:y' xmlns='urn:d' y:id='1' plain='2'>"
        b"<b>\xe2\x82\xac <!-- dropped --><?dropped too?>&amp;<![CDATA[<x>]]></b>tail</y:a>"
    )
    assert root.tag == "{urn:y}a"
    assert root.attrib == {"{urn:y}id": "1", "plain": "2"}
    (child,) = list(root)
    assert child.tag == "{urn:d}b"
    assert child.text == "\u20ac &<x>"
    assert child.tail == "tail"


def test_parses_a_report_with_prefixed_names() -> None:
    xml = (
        "<y:yandexsearch xmlns:y='urn:yandex'><y:response><y:results><y:grouping>"
        "<y:group><y:doc><y:url>https://ns.example/z</y:url><y:title>Z</y:title></y:doc>"
        "</y:group></y:grouping></y:results></y:response></y:yandexsearch>"
    )
    (result,) = _parse_web_xml(xml.encode("utf-8"))
    assert (result.url, result.title) == ("https://ns.example/z", "Z")


# -- which Expat it parses with -----------------------------------------------


@pytest.mark.parametrize("version", [(2, 4, 4), (2, 3, 99), (1, 95, 8)])
def test_refuses_to_parse_on_an_old_expat(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]
) -> None:
    monkeypatch.setattr(client.expat, "version_info", version)
    found = ".".join(map(str, version))
    with pytest.raises(YandexSearchError) as exc_info:
        _parse_web_xml(SAMPLE_WEB_XML.encode("utf-8"))
    message = str(exc_info.value)
    assert f"this Python uses Expat {found}, older than 2.4.5, the oldest" in message
    assert message.endswith("See https://github.com/akinfold/hermes-yandex-search-api#requirements")


def test_the_requirements_link_names_a_readme_section() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert client.REQUIREMENTS_URL.endswith("#requirements")
    assert "\n## Requirements\n" in readme


# 2.4.7: Ubuntu 22.04's libexpat; 2.5.0: Debian 12's and RHEL 9's. 2.10.0 also
# catches a version compared as text.
@pytest.mark.parametrize(
    "version", [MIN_EXPAT_VERSION, (2, 4, 7), (2, 5, 0), (2, 6, 0), (2, 10, 0), (3, 0, 0)]
)
def test_parses_on_a_supported_expat(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]
) -> None:
    monkeypatch.setattr(client.expat, "version_info", version)
    assert len(_parse_web_xml(SAMPLE_WEB_XML.encode("utf-8"))) == 2


def test_readme_names_the_same_minimum_and_size_limit() -> None:
    minimum = ".".join(map(str, MIN_EXPAT_VERSION))
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    text = " ".join(readme.split())
    assert f"Expat {minimum} or newer" in text
    assert f"an XML document larger than {MAX_XML_BYTES // (1024 * 1024)} MiB" in text


def test_this_python_has_a_supported_expat() -> None:
    # The suite parses for real; on an older Expat every parsing test above
    # would fail for that reason alone, so say it plainly here.
    assert tuple(client.expat.version_info) >= MIN_EXPAT_VERSION, client.expat.EXPAT_VERSION
