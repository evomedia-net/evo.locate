# Evomedia.net evo.locate — https://github.com/evomedia-net/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

"""evo.locate - self-hosted IP geolocation API.

A drop-in replacement for ip2location.io's free tier, backed by DB-IP Lite
databases held locally. No account, no API key, no per-query cost, and no
visitor IP ever leaves the host it runs on.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import DatabaseUnavailable, GeoDatabases

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("evo.locate")

def _read_version() -> str:
    """The build stamp, read from build-version.json - the one source of truth.

    This used to be a hardcoded literal, which meant the fleet stamp and the
    version the API reports were two independent facts. On 2026-08-31 they
    drifted: zbump moved build-version.json to v0.0.0.1.4, but /health kept
    answering 0.0.0.1.3, and because the stamp was not in the image the rebuild
    produced a byte-identical layer set - so compose correctly saw no change and
    never restarted the container. A deploy that changes nothing looks exactly
    like a deploy that worked.

    An unreadable stamp returns "unknown" rather than a plausible-looking
    number. Inventing a version is how the drift stayed invisible; a health
    endpoint saying "unknown" is a question, and a wrong number is not.
    """
    try:
        raw = json.loads((Path(__file__).resolve().parent.parent / "build-version.json").read_text(encoding="utf-8"))
        stamp = str(raw["version"]).strip().lstrip("v")
        parts = stamp.split(".")
        if len(parts) != 5 or not all(p.isdigit() for p in parts):
            return "unknown"
        return stamp
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


VERSION = _read_version()

# DB-IP Lite is CC BY 4.0. Anything displaying these results owes DB-IP a
# visible credit with a link, so it travels on every response as a header
# rather than living only in documentation nobody reads.
ATTRIBUTION = "IP Geolocation by DB-IP (https://db-ip.com)"

DATA_DIR = Path(os.environ.get("EVO_LOCATE_DATA_DIR", "/data"))
REFRESH_INTERVAL_HOURS = int(os.environ.get("EVO_LOCATE_REFRESH_HOURS", "24"))
SKIP_BOOT_DOWNLOAD = os.environ.get("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", "").lower() in {"1", "true", "yes"}

databases = GeoDatabases(DATA_DIR)
_stop = threading.Event()


def _refresh_loop() -> None:
    """Check for a newer monthly release periodically.

    DB-IP publishes monthly, so a daily check is generous. The download is a
    no-op when the local copy already matches the newest published month.
    """
    while not _stop.wait(REFRESH_INTERVAL_HOURS * 3600):
        try:
            if databases.refresh_all():
                logger.info("Databases refreshed")
        except Exception:
            logger.exception("Scheduled refresh failed; keeping existing databases")


@asynccontextmanager
async def lifespan(app: FastAPI):
    databases.open_all()
    if not databases.ready and not SKIP_BOOT_DOWNLOAD:
        logger.info("No local database found, fetching on first boot")
        try:
            databases.refresh_all()
        except Exception:
            logger.exception("First-boot download failed; /v1/lookup will 503 until it succeeds")
    worker = threading.Thread(target=_refresh_loop, name="refresh", daemon=True)
    worker.start()
    try:
        yield
    finally:
        _stop.set()
        databases.close()


class PrettyJSONResponse(JSONResponse):
    """Indented JSON on every response, success and error alike.

    The responses are a few hundred bytes at most, so readability in a
    browser, curl or a log costs nothing measurable on the wire.
    """

    def render(self, content) -> bytes:
        return (json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# Markdown, rendered at the top of /docs. The code samples live here rather
# than only in the README so the interactive docs are self-sufficient.
DESCRIPTION = """\
Look up an IP address **or hostname**. Plain HTTP, no client library needed.

Results shown on a web page owe DB-IP a credit — see `GET /v1/attribution`.

#### Client examples

**Python** (standard library only):

```python
import json
from urllib.request import urlopen

with urlopen("http://localhost:9100/v1/lookup/8.8.8.8") as resp:
    geo = json.load(resp)

print(f"{geo['ip']}: {geo['city_name']}, {geo['country_name']} ({geo['as']})")
```

**Node.js** (18+, built-in `fetch`):

```js
const resp = await fetch("http://localhost:9100/v1/lookup/8.8.8.8");
if (!resp.ok) {
  const { detail } = await resp.json();
  throw new Error(`lookup failed (${resp.status}): ${detail}`);
}
const geo = await resp.json();

console.log(`${geo.ip}: ${geo.city_name}, ${geo.country_name} (${geo.as})`);
```
"""

# docs_url=None because /docs is served by our own route below: FastAPI's
# stock page offers no way to style the description, and the client examples
# should sit in a collapsible card like the endpoint sections do.
app = FastAPI(
    title="evo.locate",
    version=VERSION,
    summary="Self-hosted IP geolocation. No key, no signup, no per-query cost.",
    description=DESCRIPTION,
    lifespan=lifespan,
    default_response_class=PrettyJSONResponse,
    docs_url=None,
)

# Same Swagger UI setup FastAPI generates, with two additions: a plain
# "evo.locate" tab title, and an onComplete hook that folds everything under
# the description's "Client examples" heading into a <details> card styled
# like the endpoint sections. If the heading ever disappears the hook is a
# no-op and the description renders flat - nothing breaks.
DOCS_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>evo.locate</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>
.info details.client-samples {
  margin: 20px 0;
  background: #fff;
  border: 1px solid rgba(59, 65, 81, .3);
  border-radius: 4px;
  box-shadow: 0 0 3px rgba(0, 0, 0, .19);
}
.info details.client-samples > summary {
  cursor: pointer;
  padding: 10px 20px;
  font-size: 16px;
  font-weight: 700;
  color: #3b4151;
  user-select: none;
}
.info details.client-samples[open] > summary {
  border-bottom: 1px solid rgba(59, 65, 81, .3);
}
.info details.client-samples > .samples-body {
  padding: 5px 20px 15px;
}
</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle({
  url: "/openapi.json",
  dom_id: "#swagger-ui",
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePlugin],
  layout: "BaseLayout",
  deepLinking: true,
  showExtensions: true,
  showCommonExtensions: true,
  onComplete: () => {
    const heading = document.querySelector(".info .description h4");
    if (!heading) return;
    const details = document.createElement("details");
    details.className = "client-samples";
    const summary = document.createElement("summary");
    summary.textContent = heading.textContent;
    const body = document.createElement("div");
    body.className = "samples-body";
    let node = heading.nextSibling;
    while (node) {
      const next = node.nextSibling;
      body.appendChild(node);
      node = next;
    }
    details.append(summary, body);
    heading.replaceWith(details);
  },
});
</script>
</body>
</html>
"""


@app.get("/docs", include_in_schema=False)
def docs() -> HTMLResponse:
    return HTMLResponse(DOCS_HTML)


# Registered on the starlette base class so it also catches the router's own
# 404/405 responses, not just HTTPExceptions raised inside route handlers.
@app.exception_handler(StarletteHTTPException)
async def pretty_http_exception(request, exc: StarletteHTTPException) -> PrettyJSONResponse:
    """Errors are what a browser sees first; format them like everything else."""
    return PrettyJSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


@app.middleware("http")
async def add_attribution_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Data-Attribution"] = ATTRIBUTION
    return response


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """The bare URL is only ever a human in a browser; send them to the docs."""
    return RedirectResponse(url="/docs")


@app.get("/health", summary="Liveness and database status")
def health() -> PrettyJSONResponse:
    present = databases.present()
    ready = databases.ready
    return PrettyJSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "loading",
            "version": VERSION,
            "databases": present,
        },
    )


@app.get("/v1/attribution", summary="Attribution required by the data licence")
def attribution() -> dict[str, str]:
    return {
        "text": ATTRIBUTION,
        "url": "https://db-ip.com",
        "licence": "CC BY 4.0",
        "note": (
            "DB-IP Lite is Creative Commons Attribution 4.0. Any page that "
            "displays results from this service must credit DB-IP with a link."
        ),
    }


def _resolve_hostname(name: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Resolve a hostname to one address, or None if it does not resolve.

    IPv4 is preferred when a name has both: the Lite databases' IPv4 coverage
    is denser, and callers get a stable answer instead of one that flips with
    the resolver's record ordering.
    """
    try:
        infos = socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return None
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    for address in addresses:
        if address.version == 4:
            return address
    return addresses[0] if addresses else None


@app.get("/v1/lookup/{ip}", summary="Look up an IP address or hostname")
def lookup(ip: str, response: Response) -> dict:
    """A literal IP is looked up as-is and never touches the network.

    Anything else is treated as a hostname and resolved through the host's
    DNS resolver first — that resolution is the only network traffic, and it
    carries the name, never any visitor address.
    """
    hostname: str | None = None
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        resolved = _resolve_hostname(ip)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"'{ip}' is not a valid IP address or a resolvable hostname",
            )
        hostname, parsed, ip = ip, resolved, str(resolved)

    # Private and loopback space is not in any geolocation database. Answering
    # 200 with empty fields would be indistinguishable from "we looked and
    # found nothing", so say plainly that it is not a routable address.
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
        detail = f"'{hostname}' resolves to '{ip}', which" if hostname else f"'{ip}'"
        raise HTTPException(status_code=422, detail=f"{detail} is not a public address")

    try:
        record = databases.lookup(ip)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # IP results change only when the monthly database does. A name can point
    # somewhere new whenever its DNS does, so those get a DNS-sized lifetime.
    max_age = 300 if hostname else 86400
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return record
