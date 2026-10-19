"""Untrusted XML: what the web-search parser refuses, and which Expat it parses with."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from hermes_yandex_search import client
from hermes_yandex_search.client import (
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
    # CVE-2023-52425, quadratic before Expat 2.6.0. On a supported Expat it is
    # just a long title or URL.
    big = "A" * (5 * 1024 * 1024)
    if where == "text":
        (result,) = _parse_web_xml(report(title=big))
        assert result.title == big
    else:
        (result,) = _parse_web_xml(report(url_attr=f"https://x.example/{big}"))
        assert result.url == f"https://x.example/{big}"


def test_an_undeclared_entity_is_a_parse_error() -> None:
    with pytest.raises(YandexSearchError, match="Could not parse Yandex XML response: undefined"):
        _parse_web_xml(report(title="&xxe;"))


def test_builds_the_tree_elementtree_would() -> None:
    root = _parse_xml(
        # windows-1252 is not built into Expat: Python's codec decodes it.
        b"<?xml version='1.0' encoding='windows-1252'?>"
        b"<y:a xmlns:y='urn:y' xmlns='urn:d' y:id='1' plain='2'>"
        b"<b>\x80 <!-- dropped --><?dropped too?>&amp;<![CDATA[<x>]]></b>tail</y:a>"
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


@pytest.mark.parametrize("version", [(2, 5, 0), (2, 5, 99), (1, 95, 8)])
def test_refuses_to_parse_on_an_old_expat(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]
) -> None:
    monkeypatch.setattr(client.expat, "version_info", version)
    found = ".".join(map(str, version))
    with pytest.raises(YandexSearchError) as exc_info:
        _parse_web_xml(SAMPLE_WEB_XML.encode("utf-8"))
    message = str(exc_info.value)
    assert f"this Python uses Expat {found}, older than 2.6.0" in message


@pytest.mark.parametrize("version", [MIN_EXPAT_VERSION, (2, 6, 1), (2, 10, 0), (3, 0, 0)])
def test_parses_on_a_supported_expat(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]
) -> None:
    monkeypatch.setattr(client.expat, "version_info", version)
    assert len(_parse_web_xml(SAMPLE_WEB_XML.encode("utf-8"))) == 2


def test_readme_names_the_same_minimum() -> None:
    minimum = ".".join(map(str, MIN_EXPAT_VERSION))
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert f"Expat {minimum} or newer" in readme


def test_this_python_has_a_supported_expat() -> None:
    # The suite parses for real; on an older Expat every parsing test above
    # would fail for that reason alone, so say it plainly here.
    assert tuple(client.expat.version_info) >= MIN_EXPAT_VERSION, client.expat.EXPAT_VERSION
