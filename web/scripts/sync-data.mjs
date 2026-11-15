// Copies the pipeline's output (../data) into public/data so Vite serves and bundles it.
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(web, "../data");
const dest = resolve(web, "public/data");

if (!existsSync(resolve(src, "index.json"))) {
  console.error(`No data found at ${src}. Run the pipeline first (see README).`);
  process.exit(1);
}
rmSync(dest, { recursive: true, force: true });
cpSync(src, dest, { recursive: true });
console.log(`Copied ${src} -> ${dest}`);
