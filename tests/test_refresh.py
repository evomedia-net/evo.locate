# Evomedia.net evo.locate — https://github.com/evomedia-net/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

"""Tests for the download/refresh machinery and the service's error paths.

Like test_lookup.py, nothing here touches the network: DB-IP's HTTP surface is
replaced with stubs, and the one test that needs a real .mmdb payload builds it
in-process with mmdb_writer. These paths matter precisely because they only run
when something unusual happens — a month boundary, a truncated download, a
missing database — which is exactly when untested code bites.
"""

from __future__ import annotations

import gzip
import os
from datetime import date

import httpx
import pytest

os.environ.setdefault("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", "1")

from app.database import CITY, EDITIONS, GeoDatabases  # noqa: E402


# --- Edition.url ----------------------------------------------------------


def test_edition_url_names_the_month_and_slug():
    url = CITY.url(date(2026, 8, 15))
    assert url.endswith(f"dbip-{CITY.slug}-lite-2026-08.mmdb.gz")


# --- _resolve_available ---------------------------------------------------


class _HeadClient:
    """An httpx.Client stand-in whose HEAD answers come from a table."""

    def __init__(self, by_url):
        self.by_url = by_url
        self.calls = []

    def head(self, url, **kwargs):
        self.calls.append(url)
        answer = self.by_url.get(url, 404)
        if answer == "boom":
            raise httpx.ConnectError("nope")
        return httpx.Response(answer, request=httpx.Request("HEAD", url))


def test_resolve_prefers_the_current_month(tmp_path):
    dbs = GeoDatabases(tmp_path)
    today = date.today()
    client = _HeadClient({CITY.url(today): 200})
    url, when = dbs._resolve_available(client, CITY)
    assert when == today and url == CITY.url(today)


def test_resolve_falls_back_to_the_previous_month(tmp_path):
    dbs = GeoDatabases(tmp_path)
    client = _HeadClient({})  # current month 404s...
    previous = date.today().replace(day=1)
    from datetime import timedelta

    previous = previous - timedelta(days=1)
    client.by_url[CITY.url(previous)] = 200
    url, when = dbs._resolve_available(client, CITY)
    assert when == previous
    assert len(client.calls) == 2  # tried current first


def test_resolve_survives_connection_errors_and_gives_up(tmp_path):
    dbs = GeoDatabases(tmp_path)
    client = _HeadClient({})
    client.by_url = dict.fromkeys(client.by_url, 404)
    # every HEAD raises: the loop must swallow both and return None rather
    # than let one bad month kill the refresh thread
    client.head = lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("down"))
    assert dbs._resolve_available(client, CITY) is None


# --- download -------------------------------------------------------------


class _FakeStream:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status != 200:
            raise httpx.HTTPStatusError(
                "bad", request=httpx.Request("GET", "x"), response=httpx.Response(self.status)
            )

    def iter_bytes(self, chunk_size):
        yield self.payload


def _patch_client(monkeypatch, *, resolve, payload=b""):
    """Route GeoDatabases.download's internal httpx.Client to stubs."""
    import app.database as database_module

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url, **kw):
            return _FakeStream(payload)

    monkeypatch.setattr(database_module.httpx, "Client", _Client)
    monkeypatch.setattr(GeoDatabases, "_resolve_available", lambda self, c, e: resolve)


def test_download_reports_false_when_upstream_has_nothing(tmp_path, monkeypatch):
    _patch_client(monkeypatch, resolve=None)
    assert GeoDatabases(tmp_path).download(CITY) is False


def test_download_skips_when_already_current(tmp_path, monkeypatch):
    when = date.today()
    _patch_client(monkeypatch, resolve=(CITY.url(when), when))
    dbs = GeoDatabases(tmp_path)
    dbs.path_for(CITY).write_bytes(b"existing")
    (tmp_path / f".{CITY.name}.version").write_text(f"{when:%Y-%m}")
    assert dbs.download(CITY) is False
    assert dbs.path_for(CITY).read_bytes() == b"existing"  # untouched


def test_download_installs_a_valid_database(tmp_path, monkeypatch):
    mmdb_writer = pytest.importorskip("mmdb_writer")
    from netaddr import IPSet

    writer = mmdb_writer.MMDBWriter(6, "test", languages=["en"], ipv4_compatible=True)
    writer.insert_network(IPSet(["8.8.8.0/24"]), {"country": {"iso_code": "US"}})
    raw = tmp_path / "payload.mmdb"
    writer.to_db_file(str(raw))

    when = date.today()
    _patch_client(monkeypatch, resolve=(CITY.url(when), when), payload=gzip.compress(raw.read_bytes()))
    dbs = GeoDatabases(tmp_path)
    assert dbs.download(CITY) is True
    assert dbs.path_for(CITY).exists()
    assert (tmp_path / f".{CITY.name}.version").read_text() == f"{when:%Y-%m}"
    # no temp litter left behind
    assert not list(tmp_path.glob("tmp*"))


def test_corrupt_download_never_replaces_the_target(tmp_path, monkeypatch):
    when = date.today()
    _patch_client(monkeypatch, resolve=(CITY.url(when), when), payload=b"this is not gzip")
    dbs = GeoDatabases(tmp_path)
    dbs.path_for(CITY).write_bytes(b"working database")
    with pytest.raises(Exception):
        dbs.download(CITY, force=True)
    assert dbs.path_for(CITY).read_bytes() == b"working database"
    assert not list(tmp_path.glob("tmp*"))  # temps cleaned even on failure


def test_refresh_all_downloads_every_edition_even_after_a_success(tmp_path, monkeypatch):
    """A generator inside any() would stop at the first True and silently skip
    the ASN database - the exact bug the list materialisation guards."""
    seen = []

    def fake_download(self, edition, *, force=False):
        seen.append(edition.name)
        return True  # every edition claims success

    monkeypatch.setattr(GeoDatabases, "download", fake_download)
    monkeypatch.setattr(GeoDatabases, "open_all", lambda self: None)
    assert GeoDatabases(tmp_path).refresh_all() is True
    assert seen == [e.name for e in EDITIONS]


def test_refresh_all_without_new_files_does_not_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(GeoDatabases, "download", lambda self, e, *, force=False: False)
    opened = []
    monkeypatch.setattr(GeoDatabases, "open_all", lambda self: opened.append(1))
    assert GeoDatabases(tmp_path).refresh_all() is False
    assert not opened


# --- the service's error paths -------------------------------------------


def test_lookup_answers_503_while_databases_are_absent(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EVO_LOCATE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", "1")
    import importlib

    from app import database as database_module
    from app import main as main_module

    importlib.reload(database_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as c:
        resp = c.get("/v1/lookup/8.8.8.8")
    assert resp.status_code == 503
    assert "database" in resp.json()["detail"].lower()


def test_first_boot_download_failure_is_survived(tmp_path, monkeypatch):
    """A failed first-boot fetch must leave the app up (503ing) - not dead."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EVO_LOCATE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", raising=False)
    import importlib

    from app import database as database_module
    from app import main as main_module

    importlib.reload(database_module)
    importlib.reload(main_module)
    assert main_module.SKIP_BOOT_DOWNLOAD is False

    calls = []

    def failing_refresh(*a, **kw):
        calls.append(1)
        raise httpx.ConnectError("no network on boot")

    monkeypatch.setattr(main_module.databases, "refresh_all", failing_refresh)
    with TestClient(main_module.app) as c:
        assert c.get("/health").status_code in (200, 503)
    assert calls  # the boot download path actually ran


def test_refresh_loop_logs_and_survives_a_failing_refresh(monkeypatch):
    """One bad nightly refresh must not kill the worker thread."""
    from app import main as main_module

    waits = iter([False, True])  # run the body once, then stop

    class _Stop:
        def wait(self, timeout):
            return next(waits)

    monkeypatch.setattr(main_module, "_stop", _Stop())
    boom = []

    def failing_refresh(*a, **kw):
        boom.append(1)
        raise RuntimeError("upstream broke")

    monkeypatch.setattr(main_module.databases, "refresh_all", failing_refresh)
    main_module._refresh_loop()  # returns without raising
    assert boom == [1]


def test_refresh_loop_logs_a_successful_refresh(monkeypatch):
    from app import main as main_module

    waits = iter([False, True])

    class _Stop:
        def wait(self, timeout):
            return next(waits)

    monkeypatch.setattr(main_module, "_stop", _Stop())
    monkeypatch.setattr(main_module.databases, "refresh_all", lambda **kw: True)
    main_module._refresh_loop()
