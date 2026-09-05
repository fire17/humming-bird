import { loadPyodide } from "./runtime/pyodide.mjs";
let py,
	tick,
	command,
	timer,
	visible = true,
	last = 0;
const send = (text, cost = 0) =>
	postMessage({ type: "frame", state: JSON.parse(text), cost });
async function init(options) {
	postMessage({ type: "loading", message: "Loading the shared game engine…" });
	py = await loadPyodide({
		indexURL: new URL("./runtime/", import.meta.url).href,
	});
	const archive = await fetch("./engine.zip");
	if (!archive.ok) throw new Error("Could not load the game engine");
	py.unpackArchive(new Uint8Array(await archive.arrayBuffer()), "zip", {
		extractDir: "/garden",
	});
	py.runPython("import sys\nsys.path.insert(0, '/garden')\nimport bridge");
	const start = py.runPython("bridge.start");
	tick = py.runPython("bridge.tick");
	command = py.runPython("bridge.command");
	send(start(JSON.stringify(options)));
	start.destroy();
	postMessage({ type: "ready" });
	last = performance.now();
	timer = setInterval(() => {
		if (!visible) {
			last = performance.now();
			return;
		}
		const now = performance.now(),
			dt = Math.min(0.1, (now - last) / 1000);
		last = now;
		const state = tick(dt);
		send(state, performance.now() - now);
	}, 1000 / 30);
}
onmessage = async ({ data }) => {
	try {
		if (data.op === "init") await init(data.options);
		else if (data.op === "visibility") {
			visible = data.visible;
			last = performance.now();
		} else if (command) send(command(JSON.stringify(data)));
	} catch (error) {
		clearInterval(timer);
		postMessage({ type: "error", message: String(error) });
	}
};
