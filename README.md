# Time Globe

An interactive 3D globe of the UTC timekeeping network: national labs, their clocks, the flow
of data to BIPM near Paris, and 28 years of drift. Live at time.anzarahmad.me (not yet).

Status: phase 1 (data spike). See the scope PDF in this repo for the plan.

## Layout

- `apps/web` - React, Vite, TypeScript, globe.gl, d3 (phase 3)
- `apps/api` - FastAPI (phase 4)
- `pipeline/` - Python ingestion: BIPM API, Circular T, GNSS, labs (spike in phase 1)
- `infra/`, `.github/workflows/` - deployment and the scheduled ingest
- `tests/` - pytest; parsers are tested against real saved files in `tests/fixtures/`
- `docs/` - working notes

## Development

```
cd pipeline
python -m pytest
```

Copy `.env.example` to `.env` and fill it in. Secrets live only in `.env` locally and in GitHub
Actions secrets in CI.

## Contact

timeglobe@anzarahmad.me

## Data rules

- Only BIPM API results and Circular T are used; the raw clock and link folders are never downloaded.
- Scrapers send an honest User-Agent, run at most monthly and back off on errors.
- No BIPM logo and no wording that suggests an official BIPM product.

## Attribution

Time data: © BIPM Time Department (Circular T, API, Time Database), licensed under CC BY 4.0.
Processed and visualized by Panda. Not affiliated with or endorsed by BIPM. NTP server counts:
NTP Pool Project. Basemap: Natural Earth. Imagery: NASA Blue Marble. Geocoding © OpenStreetMap contributors.
