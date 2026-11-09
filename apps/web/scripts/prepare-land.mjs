// One-time script: turns the raw Natural Earth land file into the small file the globe loads.
//
//   node scripts/prepare-land.mjs .raw/ne_110m_land.geojson public/geo/land-110m.json
//
// Source:   Natural Earth 110m land, ne_110m_land.geojson, from the official GitHub mirror
//           https://github.com/nvkelso/natural-earth-vector at tag v5.1.2
//           https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_land.geojson
// Licence:  public domain (https://www.naturalearthdata.com/about/terms-of-use/)
// Changes:  coordinates rounded to 2 decimals (about 1 km, far below what a globe shows), consecutive
//           duplicate points removed, properties/bbox/crs dropped. The raw file is not committed.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { gzipSync } from "node:zlib";
import { roundGeoJson } from "./lib/round-geojson.mjs";

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: node scripts/prepare-land.mjs <raw geojson> <output json>");
  process.exit(2);
}

const rawText = readFileSync(input, "utf8");
const { geojson, stats } = roundGeoJson(JSON.parse(rawText), 2);
const processed = JSON.stringify(geojson);
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, processed);

const gz = (text) => gzipSync(text, { level: 9 }).length;
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;
const rawBytes = Buffer.byteLength(rawText);
const outBytes = Buffer.byteLength(processed);
console.log(`features: ${stats.featuresIn} in, ${stats.featuresOut} out (${stats.featuresDropped} dropped), holes dropped: ${stats.ringsDropped}`);
console.log(`raw:       ${rawBytes.toLocaleString("en-US")} bytes (${kb(rawBytes)}), gzip ${gz(rawText).toLocaleString("en-US")} bytes (${kb(gz(rawText))})`);
console.log(`processed: ${outBytes.toLocaleString("en-US")} bytes (${kb(outBytes)}), gzip ${gz(processed).toLocaleString("en-US")} bytes (${kb(gz(processed))})`);
console.log(`wrote ${output}`);
