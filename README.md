# Time Globe

An interactive 3D globe of the UTC timekeeping network: national labs, their clocks, the flow
of data to BIPM near Paris, and 28 years of drift.

Status: phase 1 (data spike).

## Layout

- `apps/web` - React, Vite, TypeScript, globe.gl, d3 (phase 3)
- `apps/api` - FastAPI (phase 4)
- `pipeline/` - Python ingestion: BIPM API, Circular T, GNSS, labs (spike in phase 1)
- `infra/`, `.github/workflows/` - deployment and the scheduled ingest
- `tests/` - pytest; parsers are tested against real saved files in `tests/fixtures/`
- `docs/` - data findings per phase

## Development

```
cd pipeline
python -m pytest
```

Copy `.env.example` to `.env` and fill it in.

### Web app (`apps/web`)

```
cd apps/web
npm install --ignore-scripts
npm run data:local      # copies the published snapshot from your local origin/data ref (git fetch origin data first)
npm run dev             # http://localhost:5173
```

`npm run data:dir -- <folder>` copies any local snapshot folder instead (for example the pipeline's
`pipeline/out/snapshot`), `npm test` runs the tests, and `npm run build` copies the snapshot from the
`data` branch, checks it against the 300 KB first-load data budget, builds, and checks the JavaScript
budget. The copied snapshot (`public/data/`) is never committed.

## Contact

<a href="https://mail.google.com/mail/?view=cm&to=timeglobe@anzarahmad.me" target="_blank"><img src="https://img.shields.io/badge/Email-D14836?logo=gmail&logoColor=white" alt="Email"></a>

## Data rules

- Only BIPM API results and Circular T are used; the raw clock and link folders are never downloaded.
- Scrapers send an honest User-Agent, run at most monthly and back off on errors.
- No BIPM logo and no wording that suggests an official BIPM product.

## Attribution

Time data: © BIPM Time Department (Circular T, API, Time Database), licensed under CC BY 4.0.
Processed and visualized by Panda. Not affiliated with or endorsed by BIPM. NTP server counts:
NTP Pool Project. Basemap: Natural Earth (public domain). Geocoding © OpenStreetMap contributors.

Land outlines: Natural Earth 110m land (`ne_110m_land.geojson`), release **v5.1.2** from the official GitHub
mirror, https://github.com/nvkelso/natural-earth-vector (public domain; terms at
https://www.naturalearthdata.com/about/terms-of-use/). The coordinates are rounded to 2 decimals and the
properties dropped by `apps/web/scripts/prepare-land.mjs`; the processed file is
`apps/web/public/geo/land-110m.json`, the raw download is not committed.
