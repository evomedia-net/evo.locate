"""DB-IP Lite database management: download, refresh, and lookup.

Two databases are used, both from DB-IP's free Lite editions:

  * city  - country/region/city/lat/lon
  * asn   - autonomous system number and the AS organisation name

Both ship in MaxMind DB (.mmdb) format, so the standard `maxminddb` reader
handles them. They are NEVER committed to the repository: the city database
alone is ~124 MB, and redistributing it carries attribution obligations that
are cleaner to leave with DB-IP. The service downloads them on first boot and
refreshes monthly.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import maxminddb

logger = logging.getLogger(__name__)

BASE_URL = "https://download.db-ip.com/free"


@dataclass(frozen=True)
class Edition:
    """One DB-IP Lite edition."""

    name: str          # "city" / "asn" - also the local filename stem
    slug: str          # the slug DB-IP uses in its download URLs

    def url(self, when: date) -> str:
        return f"{BASE_URL}/dbip-{self.slug}-lite-{when:%Y-%m}.mmdb.gz"


CITY = Edition(name="city", slug="city")
ASN = Edition(name="asn", slug="asn")
EDITIONS = (CITY, ASN)


class DatabaseUnavailable(RuntimeError):
    """Raised when a lookup is attempted before any database is present."""


class GeoDatabases:
    """Holds the open readers and swaps them atomically on refresh.

    Readers are replaced by rebinding a single attribute rather than mutating
    a shared object, so an in-flight lookup keeps using the reader it started
    with and never observes a half-open database.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._readers: dict[str, maxminddb.Reader] = {}
        self._lock = threading.Lock()

    # ---- paths ---------------------------------------------------------

    def path_for(self, edition: Edition) -> Path:
        return self.data_dir / f"dbip-{edition.name}-lite.mmdb"

    def present(self) -> dict[str, bool]:
        return {e.name: self.path_for(e).exists() for e in EDITIONS}

    # ---- download ------------------------------------------------------

    def _resolve_available(self, client: httpx.Client, edition: Edition) -> tuple[str, date] | None:
        """Find the newest published file for an edition.

        DB-IP publishes monthly and the current month's file appears partway
        through the month, so the current month is tried first and then the
        previous one. Anything older means something is wrong upstream and we
        would rather keep serving the database already on disk.
        """
        today = date.today()
        previous = (today.replace(day=1) - timedelta(days=1))
        for when in (today, previous):
            url = edition.url(when)
            try:
                resp = client.head(url, follow_redirects=True, timeout=30.0)
            except httpx.HTTPError as exc:
                logger.warning("HEAD failed for %s: %s", url, exc)
                continue
            if resp.status_code == 200:
                return url, when
        return None

    def download(self, edition: Edition, *, force: bool = False) -> bool:
        """Fetch and install one edition. Returns True if a new file landed.

        The download goes to a temporary file and is only moved into place
        once it has been fully written and successfully opened. A truncated
        or corrupt download therefore never replaces a working database.
        """
        target = self.path_for(edition)
        with httpx.Client() as client:
            found = self._resolve_available(client, edition)
            if found is None:
                logger.error("No published %s database found upstream", edition.name)
                return False
            url, when = found

            stamp = self.data_dir / f".{edition.name}.version"
            current = stamp.read_text().strip() if stamp.exists() else ""
            wanted = f"{when:%Y-%m}"
            if current == wanted and target.exists() and not force:
                logger.info("%s database already at %s", edition.name, wanted)
                return False

            logger.info("Downloading %s database (%s)", edition.name, wanted)
            # mkstemp hands back an OPEN descriptor. Closing it matters: on
            # Windows an open handle blocks the unlink in the finally block,
            # and everywhere else it simply leaks.
            tmp_gz = Path(_mkstemp_closed(".mmdb.gz", self.data_dir))
            tmp_out = Path(_mkstemp_closed(".mmdb", self.data_dir))
            try:
                with client.stream("GET", url, follow_redirects=True, timeout=300.0) as resp:
                    resp.raise_for_status()
                    with tmp_gz.open("wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)

                with gzip.open(tmp_gz, "rb") as src, tmp_out.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)

                # Prove it parses before trusting it.
                with maxminddb.open_database(str(tmp_out)):
                    pass

                tmp_out.replace(target)
                stamp.write_text(wanted)
                logger.info("Installed %s database %s (%.1f MB)",
                            edition.name, wanted, target.stat().st_size / 1e6)
                return True
            finally:
                tmp_gz.unlink(missing_ok=True)
                tmp_out.unlink(missing_ok=True)

    def refresh_all(self, *, force: bool = False) -> bool:
        # Materialise the list before calling any(): a generator would
        # short-circuit on the first success and silently skip every
        # remaining edition, leaving the ASN database permanently absent.
        results = [self.download(e, force=force) for e in EDITIONS]
        if any(results):
            self.open_all()
        return any(results)

    # ---- readers -------------------------------------------------------

    def open_all(self) -> None:
        opened: dict[str, maxminddb.Reader] = {}
        for edition in EDITIONS:
            path = self.path_for(edition)
            if path.exists():
                opened[edition.name] = maxminddb.open_database(str(path))
        with self._lock:
            old, self._readers = self._readers, opened
        for reader in old.values():
            try:
                reader.close()
            except Exception:  # pragma: no cover - closing is best effort
                logger.debug("Failed closing a stale reader", exc_info=True)

    def close(self) -> None:
        with self._lock:
            readers, self._readers = self._readers, {}
        for reader in readers.values():
            reader.close()

    @property
    def ready(self) -> bool:
        return CITY.name in self._readers

    # ---- lookup --------------------------------------------------------

    def lookup(self, ip: str) -> dict[str, Any]:
        """Return an ip2location-shaped record for `ip`.

        Field names deliberately mirror ip2location.io's free tier so this is
        a drop-in replacement for callers already written against it. Fields
        that only exist on their paid tiers (isp, domain, usage_type) are
        omitted here exactly as they are omitted there.
        """
        readers = self._readers
        city_reader = readers.get(CITY.name)
        if city_reader is None:
            raise DatabaseUnavailable("city database is not loaded yet")

        city_row = _get(city_reader, ip)
        asn_row = _get(readers[ASN.name], ip) if ASN.name in readers else {}

        country = city_row.get("country", {})
        subdivisions = city_row.get("subdivisions") or []
        location = city_row.get("location", {})

        record: dict[str, Any] = {
            "ip": ip,
            "country_code": country.get("iso_code", ""),
            "country_name": _name_of(country),
            "region_name": _name_of(subdivisions[-1]) if subdivisions else "",
            "city_name": _name_of(city_row.get("city", {})),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "asn": str(asn_row["autonomous_system_number"]) if "autonomous_system_number" in asn_row else "",
            "as": asn_row.get("autonomous_system_organization", ""),
        }
        return record


def _mkstemp_closed(suffix: str, directory: Path) -> str:
    """mkstemp, but with the descriptor closed and only the path returned."""
    fd, name = tempfile.mkstemp(suffix=suffix, dir=directory)
    os.close(fd)
    return name


def _get(reader: maxminddb.Reader, ip: str) -> dict[str, Any]:
    """Look `ip` up, treating "this database cannot answer" as "no data".

    maxminddb raises ValueError when the address family does not match the
    database - looking an IPv6 address up in an IPv4-only file, for instance.
    DB-IP's published Lite databases are dual-stack so this should not happen
    in production, but a lookup miss is not worth a 500: callers already cope
    with an empty record, and a database that is narrower than expected should
    degrade rather than take the endpoint down.
    """
    try:
        return reader.get(ip) or {}
    except ValueError as exc:
        logger.warning("Lookup of %s not answerable by this database: %s", ip, exc)
        return {}


def _name_of(node: dict[str, Any]) -> str:
    """Pull the English name out of an mmdb node, tolerating missing keys."""
    names = (node or {}).get("names") or {}
    return names.get("en", "")
