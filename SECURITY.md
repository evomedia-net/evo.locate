# Security

How to report a vulnerability, what to expect, and what is in scope:
**[the evomedia-net security policy](https://github.com/evomedia-net/.github/blob/main/SECURITY.md)**.
Short version — email [dev@evomedia.net](mailto:dev@evomedia.net), not a public
issue.

What follows is particular to this project. It is a network service whose whole
job is turning IP addresses into places, so the two things worth being explicit
about are what it listens on and what it remembers.

## It is not meant to face the internet

The container **binds `127.0.0.1`**. That is the default on purpose: there is
no account, no API key and no per-query cost, which is the point of the thing
and also means anything that can reach it can query it without limit.

If you put it behind a reverse proxy, that proxy is the security boundary:

- **Rate-limit it.** The deployment here allows 20 requests a minute keyed on
  the real viewer address.
- **Do not pass the caller's address through.** The edge here blanks
  `X-Real-IP` and `X-Forwarded-*` before the request arrives, so a visitor's
  own address never reaches the service just because they loaded a page.
- Exposing it directly, unlimited, is a resource-exhaustion problem rather
  than a data-disclosure one — the database is public data — but it is still
  your bandwidth.

## What it remembers

**Nothing, by design.** A lookup is answered from a local database file and is
not written down: no query log of addresses, no per-caller history, no
analytics. An IP address is personal data in most of the places this might run,
and the cheapest way to keep it safe is not to keep it.

Ordinary access logging is whatever your proxy does, and is yours to configure.

## The database

Geolocation data comes from a third party and is refreshed on a schedule.
`EVO_LOCATE_REFRESH_HOURS` controls how often a newer monthly release is
checked for. Nothing about a refresh executes downloaded content — the file is
a database, read by the reader library, never evaluated.

An answer being **wrong** is not a vulnerability. Geolocation is an estimate,
it is routinely wrong at the city level, and it should not be the only thing
standing between a user and anything that matters.

## Release integrity

Every release carries a `.sha256` beside the zip, and archives built by
`scripts/release.py` carry a `CHECKSUMS.txt` inside as well. Both are
**integrity checks, not signatures** — the manifest travels in the same archive
as the files, so whoever can change one can change the other. They catch a
truncated download, a corrupted mirror and an accidental edit; they do not
catch a forger.

The zips for `v0.0.0.1.1` through `v0.0.0.1.3` predate that script and carry
the outer digest only. `python scripts/release.py --verify` says which is
which rather than implying they are all the same.
