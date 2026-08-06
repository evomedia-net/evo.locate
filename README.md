# evo.locate

Self-hosted IP geolocation API. **No account, no API key, no per-query cost**, and no visitor IP ever leaves the machine it runs on.

It answers with the same JSON field names as [ip2location.io](https://ip2location.io)'s free tier, so it is a drop-in replacement for anything already written against that API — repoint the URL and you are done.

Data comes from [DB-IP](https://db-ip.com)'s free Lite databases, held locally and refreshed monthly by the service itself.

## Why

Commercial IP geolocation is priced per lookup, and the free tiers that aren't priced per lookup want an account, a key that expires, and a verified email. For the common case — *"which country and network is this log line from?"* — you do not need any of that. The data is a 140 MB file you can just hold.

Running it yourself also means visitor IP addresses are never sent to a third party, which is usually the whole reason the question came up.

## Quick start

```bash
docker compose up -d
```

On first boot it downloads the DB-IP Lite databases (~62 MB compressed, ~140 MB on disk) and starts serving. That takes a minute or two; `/health` answers `503` until it is ready.

```bash
curl localhost:9100/v1/lookup/8.8.8.8
```

```json
{
  "ip": "8.8.8.8",
  "country_code": "US",
  "country_name": "United States",
  "region_name": "California",
  "city_name": "Mountain View",
  "latitude": 37.422,
  "longitude": -122.085,
  "asn": "15169",
  "as": "Google LLC"
}
```

## Running without Docker

It is a plain FastAPI app; Docker is packaging, not a requirement.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
EVO_LOCATE_DATA_DIR=./data .venv/bin/uvicorn app.main:app --port 9100
```

On Windows (PowerShell): `$env:EVO_LOCATE_DATA_DIR = ".\data"`, then `.venv\Scripts\uvicorn app.main:app --port 9100`.

The variable matters here: `EVO_LOCATE_DATA_DIR` defaults to `/data`, which exists in the container but rarely on a bare host. Point it at any writable directory — the databases are downloaded into it on first boot and refreshed in place, and everything else behaves exactly as under Docker.

## API

| Endpoint | Purpose |
|---|---|
| `GET /v1/lookup/{ip}` | Look up one address. IPv4, IPv6, or a hostname. |
| `GET /health` | `200` when ready, `503` while databases are still loading. |
| `GET /v1/attribution` | The credit the data licence requires. |
| `GET /docs` | Interactive OpenAPI documentation. |
| `GET /` | Redirects to `/docs`. |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | Found. Fields may be empty strings if the address is not in the database. |
| `400` | Not a valid IP address or a hostname that resolves. |
| `422` | Valid (or resolved), but private/loopback/link-local — not something any geolocation database can answer. |
| `503` | Databases not loaded yet. |

Anything that doesn't parse as an IP is treated as a hostname: it is resolved through the host's own DNS resolver (preferring IPv4 when a name has both) and the resolved address is looked up — the response's `ip` field tells you which address that was. That DNS query is the only network traffic a lookup can cause, it carries only the name, and literal-IP lookups never make it.

IP responses carry `Cache-Control: public, max-age=86400`, since results only change when the monthly database does. Hostname responses get `max-age=300` — a name can point somewhere new whenever its DNS does.

All responses — errors included — are pretty-printed JSON. They are a few hundred bytes at most, so readability in a browser or a terminal costs nothing measurable.

## Using it as an ip2location drop-in

Behind nginx:

```nginx
location ~ ^/api/geo/(.+)$ {
    proxy_pass http://evo_locate:9100/v1/lookup/$1;
}
```

The response uses ip2location's field names (`country_code`, `country_name`, `region_name`, `city_name`, `asn`, `as`). Their paid-tier fields — `isp`, `domain`, `usage_type` — are **omitted**, exactly as they are on the free tier, so existing callers that fall back on them keep working unchanged.

## Client examples

Plain HTTP, so no client library is needed in any language. Python, standard library only:

```python
import json
from urllib.request import urlopen

# also accepts a hostname, e.g. .../v1/lookup/google.com
with urlopen("http://localhost:9100/v1/lookup/8.8.8.8") as resp:
    geo = json.load(resp)

print(f"{geo['ip']}: {geo['city_name']}, {geo['country_name']} ({geo['as']})")
# 8.8.8.8: Mountain View, United States (Google LLC)
```

A `400`/`422`/`503` raises `urllib.error.HTTPError`; the JSON body's `detail` field says why.

Node.js (18+, built-in `fetch`, no dependencies):

```js
const resp = await fetch("http://localhost:9100/v1/lookup/8.8.8.8");
if (!resp.ok) {
  const { detail } = await resp.json();
  throw new Error(`lookup failed (${resp.status}): ${detail}`);
}
const geo = await resp.json();

console.log(`${geo.ip}: ${geo.city_name}, ${geo.country_name} (${geo.as})`);
// 8.8.8.8: Mountain View, United States (Google LLC)
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EVO_LOCATE_DATA_DIR` | `/data` | Where the `.mmdb` files live. Mount a volume here. |
| `EVO_LOCATE_REFRESH_HOURS` | `24` | How often to check DB-IP for a newer monthly release. |
| `EVO_LOCATE_SKIP_BOOT_DOWNLOAD` | unset | Skip the first-boot download. Useful in tests and air-gapped setups. |
| `LOG_LEVEL` | `INFO` | Standard Python log levels. |

The databases are **never committed to this repository** and are not baked into the image — they are large, republished monthly, and carry their own licence. The service fetches them.

Downloads are written to a temporary file and only moved into place after they have been fully written and successfully parsed, so a truncated or corrupt download never replaces a working database.

## Troubleshooting

| Symptom | What it means and what to do |
|---|---|
| `/health` answers `503` right after starting | Databases not loaded yet. Normal on first boot while the ~62 MB download runs — a minute or two. |
| `503` persists | The download failed; the log says why (no network, proxy, full disk). The refresh worker retries every `EVO_LOCATE_REFRESH_HOURS` (default daily), and restarting the service retries immediately. A failed download never corrupts anything — files are swapped in only after a complete download parses successfully. |
| `{"detail": "Not Found"}` | No route at that path. The API surface is the table above; the bare `/` redirects to `/docs`. |
| `400` on a lookup | The input is neither a valid IP address nor a hostname that resolves. |
| `422` on a lookup | The address — or what the hostname resolved to — is private/loopback/link-local. No geolocation database can answer those. |
| Disk planning | ~140 MB for the two databases, plus ~62 MB transient during each monthly refresh download. |

## Attribution — required

The DB-IP Lite databases are licensed **[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)**. If you display results from this service on a web page, you must credit DB-IP with a link:

```html
IP Geolocation by <a href="https://db-ip.com">DB-IP</a>
```

Every response carries an `X-Data-Attribution` header as a reminder, and `GET /v1/attribution` returns the text and URL, so compliance does not depend on anyone reading this file.

This obligation is yours as the operator. The service code itself is MIT licensed; the **data** is CC BY.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

The test suite builds tiny in-memory `.mmdb` fixtures rather than downloading anything, so it is fast, offline and deterministic.

`README.txt` is a plain-text rendering of this file for terminals and anywhere markdown doesn't render. It is generated — never edit it by hand:

```bash
python scripts/readme_txt.py
```

The test suite fails if it drifts out of sync with `README.md`.

To check the real download path and real data end to end:

```bash
python scripts/smoke_real_db.py
```

That one does hit the network and pulls ~62 MB, which is why it is not part of the suite.

## Licence

Code: [MIT](LICENSE). Data: CC BY 4.0, © DB-IP.
