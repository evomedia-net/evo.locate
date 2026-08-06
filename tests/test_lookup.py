# Evomedia.net evo.locate — https://github.com/kellymichels/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

"""Tests for evo.locate.

These never download a real database. A tiny mmdb is built in-process with
`mmdbencoder` so the tests are fast, offline and deterministic; the DB-IP
files are 124 MB and change monthly, which makes them useless as fixtures.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", "1")


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """A data directory holding hand-built city and asn databases."""
    mmdb_writer = pytest.importorskip(
        "mmdb_writer", reason="mmdb_writer is needed to build fixture databases"
    )
    from netaddr import IPSet  # bundled with mmdb_writer

    tmp = Path(tempfile.mkdtemp(prefix="evolocate-test-"))

    # ip_version=6 gives a dual-stack database, matching what DB-IP publishes.
    # An IPv4-only fixture would make the IPv6 test assert the wrong thing.
    # Each family goes in its own call: mmdb_writer rejects a mixed IPSet.
    city_record = {
        "country": {"iso_code": "US", "names": {"en": "United States"}},
        "subdivisions": [{"names": {"en": "California"}}],
        "city": {"names": {"en": "Mountain View"}},
        "location": {"latitude": 37.386, "longitude": -122.0838},
    }
    city = mmdb_writer.MMDBWriter(6, "test-city", languages=["en"], ipv4_compatible=True)
    city.insert_network(IPSet(["8.8.8.0/24"]), city_record)
    city.insert_network(IPSet(["2001:4860:4860::/48"]), city_record)
    city.to_db_file(str(tmp / "dbip-city-lite.mmdb"))

    asn_record = {
        "autonomous_system_number": 15169,
        "autonomous_system_organization": "Google LLC",
    }
    asn = mmdb_writer.MMDBWriter(6, "test-asn", languages=["en"], ipv4_compatible=True)
    asn.insert_network(IPSet(["8.8.8.0/24"]), asn_record)
    asn.insert_network(IPSet(["2001:4860:4860::/48"]), asn_record)
    asn.to_db_file(str(tmp / "dbip-asn-lite.mmdb"))

    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Stub the resolver so no test ever touches real DNS.

    Unparseable input now falls through to hostname resolution, so without
    this the malformed-address tests would each fire a real (slow, networked,
    nondeterministic) DNS query.
    """
    import socket

    table = {
        # v6 listed first so the v4-preference behavior is what the test proves
        "dns.google": ["2001:4860:4860::8888", "8.8.8.8"],
        "v6only.example": ["2001:4860:4860::8888"],
        "internal.example": ["10.0.0.1"],
    }

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(socket.EAI_NONAME, f"{host} does not resolve")
        return [
            (
                socket.AF_INET6 if ":" in addr else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (addr, 0),
            )
            for addr in table[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture()
def client(data_dir, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EVO_LOCATE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", "1")

    import importlib

    from app import database as database_module
    from app import main as main_module

    importlib.reload(database_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as c:
        yield c


# --- the drop-in contract -------------------------------------------------
#
# admin-logs.html gates on `country_code` being truthy and then reads
# city_name, country_name and `as`. If any of these names drift, the dashboard
# silently degrades to "Unknown" rather than erroring, so they are asserted
# explicitly rather than through a schema.


def test_lookup_returns_ip2location_field_names(client):
    body = client.get("/v1/lookup/8.8.8.8").json()
    assert body["country_code"] == "US"
    assert body["country_name"] == "United States"
    assert body["city_name"] == "Mountain View"
    assert body["region_name"] == "California"
    assert body["as"] == "Google LLC"
    assert body["asn"] == "15169"
    assert body["ip"] == "8.8.8.8"


def test_paid_tier_fields_are_absent_exactly_as_upstream(client):
    """ip2location's free tier omits these; callers already handle that."""
    body = client.get("/v1/lookup/8.8.8.8").json()
    for field in ("isp", "domain", "usage_type"):
        assert field not in body


def test_unknown_address_still_answers_with_country_code_key(client):
    """A public address outside the database must answer, not 500.

    Note 198.51.100.0/24 (TEST-NET-2) is NOT usable here: Python's ipaddress
    module reports it as private, so it would take the 422 path instead.
    """
    resp = client.get("/v1/lookup/9.9.9.9")
    assert resp.status_code == 200
    assert resp.json()["country_code"] == ""


@pytest.mark.parametrize("bad", ["not-an-ip", "999.1.1.1", "8.8.8.8.8", ""])
def test_malformed_addresses_are_rejected(client, bad):
    assert client.get(f"/v1/lookup/{bad}").status_code in (400, 404)


@pytest.mark.parametrize("private", ["10.0.0.1", "192.168.1.1", "127.0.0.1", "169.254.1.1"])
def test_private_addresses_are_reported_not_guessed(client, private):
    assert client.get(f"/v1/lookup/{private}").status_code == 422


def test_ipv6_is_accepted(client):
    assert client.get("/v1/lookup/2001:4860:4860::8888").status_code == 200


# --- hostname convenience -------------------------------------------------


def test_hostname_is_resolved_preferring_ipv4(client):
    resp = client.get("/v1/lookup/dns.google")
    assert resp.status_code == 200
    body = resp.json()
    # the stub lists the AAAA record first; the A record must still win
    assert body["ip"] == "8.8.8.8"
    assert body["country_code"] == "US"


def test_hostname_gets_dns_sized_cache_not_database_sized(client):
    resp = client.get("/v1/lookup/dns.google")
    assert "max-age=300" in resp.headers["Cache-Control"]


def test_ipv6_only_hostname_is_looked_up(client):
    body = client.get("/v1/lookup/v6only.example").json()
    assert body["ip"] == "2001:4860:4860::8888"
    assert body["country_code"] == "US"


def test_unresolvable_hostname_is_rejected(client):
    resp = client.get("/v1/lookup/does-not-exist.example")
    assert resp.status_code == 400


def test_hostname_resolving_to_private_space_answers_422(client):
    resp = client.get("/v1/lookup/internal.example")
    assert resp.status_code == 422
    assert "10.0.0.1" in resp.json()["detail"]


# --- operational surface --------------------------------------------------


def test_root_redirects_to_docs(client):
    """The bare URL should land a browser on the API docs, not a 404."""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/docs"


def test_health_reports_ready_when_databases_present(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["databases"] == {"city": True, "asn": True}


def test_attribution_travels_on_every_response(client):
    """CC BY compliance must not depend on anyone reading the README."""
    for path in ("/health", "/v1/lookup/8.8.8.8", "/v1/attribution"):
        assert "db-ip.com" in client.get(path).headers["X-Data-Attribution"]


def test_docs_page_is_served_by_the_custom_route(client):
    """docs_url=None hands /docs to our route; it must still actually serve."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "SwaggerUIBundle" in resp.text
    assert "<title>evo.locate</title>" in resp.text


def test_json_is_pretty_printed_everywhere(client):
    """Success, handler errors, and the router's own 404 all render indented."""
    for path in ("/v1/lookup/8.8.8.8", "/health", "/v1/lookup/not-an-ip", "/no-such-path"):
        assert client.get(path).text.startswith('{\n  "'), path


def test_lookup_is_cacheable(client):
    resp = client.get("/v1/lookup/8.8.8.8")
    assert "max-age" in resp.headers.get("Cache-Control", "")
