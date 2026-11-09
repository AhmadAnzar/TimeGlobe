// node scripts/check-bundle.mjs [dist]   Exits 1 when the build's JavaScript is over budget (see lib/check-bundle.mjs).
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { checkBundle } from "./lib/check-bundle.mjs";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = process.argv[2] ? resolve(process.argv[2]) : join(webDir, "dist");
const { ok, lines } = checkBundle(dist);
console.log(lines.join("\n"));
process.exit(ok ? 0 : 1);
