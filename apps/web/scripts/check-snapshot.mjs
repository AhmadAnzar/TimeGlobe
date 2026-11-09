// node scripts/check-snapshot.mjs [dir]   (default: public/data). Exits 1 if the snapshot must not ship.
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { checkSnapshot } from "./lib/check-snapshot.mjs";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dir = process.argv[2] ? resolve(process.argv[2]) : join(webDir, "public", "data");
const { ok, lines } = checkSnapshot(dir);
console.log(lines.join("\n"));
process.exit(ok ? 0 : 1);
