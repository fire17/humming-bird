import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
const python =
	process.env.PYTHON ||
	(existsSync(".venv/bin/python") ? ".venv/bin/python" : "python3");
const result = spawnSync(python, ["scripts/export_web.py"], {
	stdio: "inherit",
});
if (result.status !== 0) process.exit(result.status || 1);
await mkdir("web-dist/runtime", { recursive: true });
for (const name of [
	"pyodide.mjs",
	"pyodide.asm.mjs",
	"pyodide.asm.wasm",
	"python_stdlib.zip",
	"pyodide-lock.json",
]) {
	await cp(`node_modules/pyodide/${name}`, `web-dist/runtime/${name}`);
}
const files = ["index.html", "style.css", "app.js", "renderer.js", "worker.js"];
const hash = createHash("sha256");
hash.update(await readFile("web-dist/assets.json"));
for (const name of files) {
	const data = await readFile(`web/${name}`);
	hash.update(data);
	await cp(`web/${name}`, `web-dist/${name}`);
}
await cp("index.html", "web-dist/about.html");
await cp("assets", "web-dist/assets", { recursive: true });
await cp("THIRD_PARTY.md", "web-dist/THIRD_PARTY.md");
await cp("licenses", "web-dist/licenses", { recursive: true });
await writeFile("web-dist/CNAME", "hummingbird.akeyo.io\n");
await writeFile("web-dist/.nojekyll", "");
await writeFile(
	"web-dist/version.json",
	JSON.stringify({ build: hash.digest("hex").slice(0, 12) }),
);
console.log("Built web-dist — runtime, art and Python engine are self-hosted.");
