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
curl localhost:8080/v1/lookup/8.8.8.8
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

## API

| Endpoint | Purpose |
|---|---|
| `GET /v1/lookup/{ip}` | Look up one address. IPv4 and IPv6. |
| `GET /health` | `200` when ready, `503` while databases are still loading. |
| `GET /v1/attribution` | The credit the data licence requires. |
| `GET /docs` | Interactive OpenAPI documentation. |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | Found. Fields may be empty strings if the address is not in the database. |
| `400` | Not a valid IP address. |
| `422` | Valid, but private/loopback/link-local — not something any geolocation database can answer. |
| `503` | Databases not loaded yet. |

Responses carry `Cache-Control: public, max-age=86400`, since results only change when the monthly database does.

## Using it as an ip2location drop-in

Behind nginx:

```nginx
location ~ ^/api/geo/(.+)$ {
    proxy_pass http://evo_locate:8080/v1/lookup/$1;
}
```

The response uses ip2location's field names (`country_code`, `country_name`, `region_name`, `city_name`, `asn`, `as`). Their paid-tier fields — `isp`, `domain`, `usage_type` — are **omitted**, exactly as they are on the free tier, so existing callers that fall back on them keep working unchanged.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EVO_LOCATE_DATA_DIR` | `/data` | Where the `.mmdb` files live. Mount a volume here. |
| `EVO_LOCATE_REFRESH_HOURS` | `24` | How often to check DB-IP for a newer monthly release. |
| `EVO_LOCATE_SKIP_BOOT_DOWNLOAD` | unset | Skip the first-boot download. Useful in tests and air-gapped setups. |
| `LOG_LEVEL` | `INFO` | Standard Python log levels. |

The databases are **never committed to this repository** and are not baked into the image — they are large, republished monthly, and carry their own licence. The service fetches them.

Downloads are written to a temporary file and only moved into place after they have been fully written and successfully parsed, so a truncated or corrupt download never replaces a working database.

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

To check the real download path and real data end to end:

```bash
python scripts/smoke_real_db.py
```

That one does hit the network and pulls ~62 MB, which is why it is not part of the suite.

## Licence

Code: [MIT](LICENSE). Data: CC BY 4.0, © DB-IP.
