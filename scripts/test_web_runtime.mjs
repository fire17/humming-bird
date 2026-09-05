// Exercise the shipped WASM interpreter and exact bundle, not a JS game mock.
import { loadPyodide } from "pyodide";
import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
const started = performance.now();
const py = await loadPyodide({ indexURL: "node_modules/pyodide/" });
py.unpackArchive(new Uint8Array(await readFile("web-dist/engine.zip")), "zip", {
	extractDir: "/garden",
});
py.runPython(
	"import sys\nsys.path.insert(0,'/garden')\nfrom bridge import BrowserGame",
);
const source = `import json\ng=BrowserGame(160,48,dict(flock_count=24,nectar_refill=True,nectar_limit=60),seed=42)\nfor i in range(120): g.tick()\nprint(json.dumps(g.snapshot(),sort_keys=True))`;
let output = "";
py.setStdout({
	batched: (text) => {
		output += text;
	},
});
py.runPython(source);
const python =
	process.env.PYTHON ||
	(existsSync(".venv/bin/python") ? ".venv/bin/python" : "python3");
const native = spawnSync(
	python,
	["-c", "from web.bridge import BrowserGame\n" + source],
	{ encoding: "utf8" },
);
assert.equal(native.status, 0, native.stderr);
const actual = JSON.parse(output),
	expected = JSON.parse(native.stdout);
assert.equal(actual.score, expected.score);
assert.equal(actual.hearts.length, expected.hearts.length);
assert.equal(actual.birds.length, 24);
actual.birds.forEach((bird, i) => {
	for (const key of ["x", "y", "wing_position"])
		assert.ok(
			Math.abs(bird[key] - expected.birds[i][key]) < 1e-9,
			`${i} ${key}: WASM/native drift`,
		);
});
console.log(
	`WASM/native parity: 24 birds, 60 nectar, 120 ticks; ${actual.collected} collected. ${(performance.now() - started).toFixed(0)} ms including cold WASM startup.`,
);
