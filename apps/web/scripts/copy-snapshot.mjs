// Copies the published snapshot into public/data so the build ships it. It is the build-time copy of the
// pipeline's `data` branch; the copy is never committed (public/data/ is git-ignored).
//
//   node scripts/copy-snapshot.mjs                          download the `data` branch from GitHub (what the Vercel build does)
//   node scripts/copy-snapshot.mjs --from-git origin/data   read it from a local git ref instead: no download
//   node scripts/copy-snapshot.mjs --from-dir <folder>      copy a local snapshot folder (e.g. the pipeline's out/snapshot)
//
// Download mode reads DATA_REPO (default AhmadAnzar/TimeGlobe) and DATA_REF (default "data").
// A snapshot that cannot be copied, or that has no meta.json afterwards, fails the build: stale or empty data never ships.
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dest = join(webDir, "public", "data");
const fail = (message) => {
  console.error(`copy-snapshot: ${message}`);
  process.exit(1);
};

if (!dest.startsWith(join(webDir, "public") + sep)) fail("refusing to write outside public/");
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });

const arg = (name) => (process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : null);
const fromGit = arg("--from-git");
const fromDir = arg("--from-dir");

if (fromDir) {
  if (!existsSync(resolve(fromDir))) fail(`${fromDir} does not exist`);
  cpSync(resolve(fromDir), dest, { recursive: true });
} else if (fromGit) {
  const top = spawnSync("git", ["rev-parse", "--show-toplevel"], { cwd: webDir, encoding: "utf8" });
  if (top.status !== 0) fail("not inside a git checkout");
  // From the repository root: run in a subdirectory, git archive would only pack that subdirectory.
  const archive = spawnSync("git", ["archive", "--format=tar", fromGit], {
    cwd: top.stdout.trim(),
    maxBuffer: 512 * 1024 * 1024,
  });
  if (archive.status !== 0) fail(`git archive ${fromGit} failed: ${archive.stderr}`);
  // tar runs inside the destination (cwd) instead of taking -C <path>: the GNU tar bundled with Git for
  // Windows misreads a "C:\..." path.
  const untar = spawnSync("tar", ["-x", "-f", "-"], { cwd: dest, input: archive.stdout });
  if (untar.status !== 0) fail(`tar failed: ${untar.stderr}`);
} else {
  const repo = process.env.DATA_REPO ?? "AhmadAnzar/TimeGlobe";
  const ref = process.env.DATA_REF ?? "data";
  const url = `https://codeload.github.com/${repo}/tar.gz/refs/heads/${ref}`;
  const response = await fetch(url, { headers: { "user-agent": "TimeGlobe-build/0.1 (+https://github.com/AhmadAnzar/TimeGlobe)" } });
  if (!response.ok) fail(`${url}: HTTP ${response.status}`);
  const body = Buffer.from(await response.arrayBuffer());
  // The tarball has one top-level folder (repo-ref/); strip it.
  const untar = spawnSync("tar", ["-x", "-z", "--strip-components=1", "-f", "-"], { cwd: dest, input: body });
  if (untar.status !== 0) fail(`tar failed: ${untar.stderr}`);
}

if (!existsSync(join(dest, "meta.json"))) fail("no meta.json after the copy: the snapshot is empty or malformed");
const files = readdirSync(dest, { recursive: true, withFileTypes: true }).filter((entry) => entry.isFile()).length;
console.log(`copy-snapshot: ${files} files from ${fromDir ? `folder ${fromDir}` : fromGit ? `git ref ${fromGit}` : "the data branch download"} into public/data`);
