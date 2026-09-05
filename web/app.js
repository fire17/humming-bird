import { GardenRenderer } from "./renderer.js";
const $ = (id) => document.getElementById(id),
	storageKey = "hummingbird-garden-v1";
let state,
	worker,
	renderer,
	ready = false,
	lastPaint = 0,
	paints = 0,
	simMs = 0,
	paintMs = 0,
	interval = performance.now(),
	build;
const held = new Set(),
	canvas = $("canvas"),
	host = $("garden");
let settings = {};
try {
	settings = JSON.parse(localStorage.getItem(storageKey) || "{}") || {};
} catch {}
if (
	matchMedia("(prefers-reduced-motion: reduce)").matches &&
	!Object.hasOwn(settings, "paused")
)
	settings = { ...settings, paused: true, calm: true };
const send = (data) => worker?.postMessage(data);
const change = (values) => send({ op: "settings", values });
const sizes = () => {
	const r = host.getBoundingClientRect(),
		cell = Math.max(3, Math.min(6, r.width / 80, r.height / 48));
	return {
		width: Math.max(38, Math.floor(r.width / cell)),
		height: Math.max(16, Math.floor(r.height / ((cell * 8) / 3))),
	};
};
function resize() {
	const r = host.getBoundingClientRect();
	renderer?.resize(r.width, r.height);
	if (ready) send({ op: "resize", ...sizes() });
}
function updateUI() {
	settings = state.settings;
	$("score").textContent = state.score.toLocaleString();
	$("nectar").textContent = `${state.hearts.length}/${state.heart_limit}`;
	$("flock").textContent = settings.flock_count;
	$("birds").value = settings.flock_count;
	$("birds-value").textContent = settings.flock_count;
	$("hearts").value = settings.nectar_limit;
	$("hearts-value").textContent = settings.nectar_limit;
	for (const [id, key] of Object.entries({
		waves: "auto_spawn",
		refill: "nectar_refill",
		gravity: "gravity_assist",
		calm: "calm",
		extended: "extended_board",
	}))
		$(id).checked = settings[key];
	$("pilot").setAttribute("aria-pressed", settings.player_mode);
	$("pilot").innerHTML = settings.player_mode
		? "Autopilot <kbd>P</kbd>"
		: "Pilot a bird <kbd>P</kbd>";
	$("pause").setAttribute("aria-pressed", settings.paused);
	$("pause").innerHTML = settings.paused
		? "Resume <kbd>Space</kbd>"
		: "Pause <kbd>Space</kbd>";
	document.body.classList.toggle("piloting", settings.player_mode);
	const serialized = JSON.stringify(settings);
	if (serialized !== updateUI.saved) {
		try {
			localStorage.setItem(storageKey, serialized);
		} catch {}
		updateUI.saved = serialized;
	}
}
async function boot() {
	for (const button of document.querySelectorAll("header button,footer button"))
		button.disabled = true;
	const [meta, image, version] = await Promise.all([
		fetch("./assets.json").then((r) => r.json()),
		new Promise((resolve, reject) => {
			const i = new Image();
			i.onload = () => resolve(i);
			i.onerror = reject;
			i.src = "./atlas.png";
		}),
		fetch("./version.json").then((r) => r.json()),
	]);
	build = version.build;
	renderer = new GardenRenderer(canvas, image, meta);
	resize();
	$("build").textContent = `Engine ${meta.build} · build ${build}`;
	worker = new Worker(new URL("./worker.js", import.meta.url), {
		type: "module",
	});
	worker.onerror = (event) => fail(event.message);
	worker.onmessage = ({ data }) => {
		if (data.type === "loading")
			$("loading-message").textContent = data.message;
		if (data.type === "error") fail(data.message);
		if (data.type === "ready") {
			ready = true;
			$("loading").hidden = true;
			for (const b of document.querySelectorAll("header button,footer button"))
				b.disabled = false;
			resize();
			send({ op: "visibility", visible: !document.hidden });
		}
		if (data.type === "frame") {
			state = data.state;
			simMs = simMs * 0.9 + data.cost * 0.1;
			updateUI();
		}
	};
	send({ op: "init", options: { ...sizes(), settings } });
	requestAnimationFrame(paint);
}
function fail(message) {
	$("loading").hidden = false;
	$("loading-message").textContent = `The garden couldn't start: ${message}`;
	$("retry").hidden = false;
	console.error(message);
}
$("retry").onclick = () => location.reload();
function paint(now) {
	if (state && now - lastPaint >= 30 && !document.hidden) {
		paintMs = paintMs * 0.9 + renderer.draw(state) * 0.1;
		lastPaint = now;
		paints++;
	}
	if (now - interval >= 1000) {
		const fps = (paints * 1000) / (now - interval);
		$("performance").textContent = `${Math.round(fps)} fps · ${renderer.mode}`;
		$("performance").title =
			`Shared engine: ${simMs.toFixed(2)} ms · render submission: ${paintMs.toFixed(2)} ms (GPU execution excluded)`;
		$("performance").dataset.simMs = simMs.toFixed(3);
		$("performance").dataset.paintMs = paintMs.toFixed(3);
		$("performance").dataset.fps = fps.toFixed(1);
		paints = 0;
		interval = now;
	}
	requestAnimationFrame(paint);
}
const toggle = (key) => change({ [key]: !settings[key] });
$("pilot").onclick = () => toggle("player_mode");
$("pause").onclick = () => toggle("paused");
$("scatter").onclick = () => send({ op: "scatter" });
function panel(open) {
	$("settings").hidden = !open;
	$("settings-button").setAttribute("aria-expanded", open);
	if (open) $("close-settings").focus();
	else $("settings-button").focus();
}
$("settings-button").onclick = () => panel($("settings").hidden);
$("close-settings").onclick = () => panel(false);
$("birds").oninput = (e) => change({ flock_count: Number(e.target.value) });
$("hearts").oninput = (e) => change({ nectar_limit: Number(e.target.value) });
for (const [id, key] of Object.entries({
	waves: "auto_spawn",
	refill: "nectar_refill",
	gravity: "gravity_assist",
	calm: "calm",
	extended: "extended_board",
}))
	$(id).onchange = (e) => change({ [key]: e.target.checked });
function plant(event) {
	if (!state) return;
	const r = canvas.getBoundingClientRect();
	send({
		op: "plant",
		x: Math.floor(((event.clientX - r.left) / r.width) * state.width),
		y: Math.floor(((event.clientY - r.top) / r.height) * state.height),
	});
	canvas.focus();
}
canvas.ondblclick = plant;
canvas.onpointerup = (e) => {
	if (e.pointerType !== "mouse") plant(e);
};
function input() {
	const has = (...keys) => keys.some((k) => held.has(k));
	send({
		op: "input",
		x: Number(has("d", "arrowright")) - Number(has("a", "arrowleft")),
		y: Number(has("s", "arrowdown")) - Number(has("w", "arrowup")),
	});
}
window.addEventListener("keydown", (e) => {
	if (
		!ready ||
		e.ctrlKey ||
		e.metaKey ||
		e.altKey ||
		/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)
	)
		return;
	const key = e.key.toLowerCase();
	if (
		[
			"w",
			"a",
			"s",
			"d",
			"arrowup",
			"arrowdown",
			"arrowleft",
			"arrowright",
		].includes(key)
	) {
		e.preventDefault();
		held.add(key);
		input();
		return;
	}
	if (e.repeat) return;
	const toggles = {
		p: "player_mode",
		o: "auto_spawn",
		f: "gravity_assist",
		c: "calm",
		e: "extended_board",
		" ": "paused",
	};
	if (toggles[key]) {
		e.preventDefault();
		toggle(toggles[key]);
	} else if (key === "n") {
		if (e.shiftKey) toggle("nectar_refill");
		else send({ op: "scatter" });
	} else if (key === "x") send({ op: "clear" });
	else if (key === "+" || key === "=")
		change({ flock_count: settings.flock_count + 1 });
	else if (key === "-") change({ flock_count: settings.flock_count - 1 });
	else if (/^[1-9]$/.test(key)) change({ flock_count: Number(key) });
	else if (key === "[" || key === "]")
		change({ nectar_limit: settings.nectar_limit + (key === "]" ? 1 : -1) });
	else if (key === "enter" && e.target === canvas) {
		e.preventDefault();
		send({
			op: "plant",
			x: Math.floor(state.width / 2),
			y: Math.floor(state.height / 2),
		});
	} else if (key === "escape") panel(false);
});
window.addEventListener("keyup", (e) => {
	held.delete(e.key.toLowerCase());
	input();
});
window.addEventListener("blur", () => {
	held.clear();
	input();
});
document.addEventListener("visibilitychange", () => {
	held.clear();
	input();
	send({ op: "visibility", visible: !document.hidden });
});
const pad = $("joystick");
let pointer;
pad.onpointerdown = (e) => {
	pointer = e.pointerId;
	pad.setPointerCapture(pointer);
	pad.onpointermove(e);
};
pad.onpointermove = (e) => {
	if (e.pointerId !== pointer) return;
	const r = pad.getBoundingClientRect(),
		dx = (e.clientX - r.left - r.width / 2) / 35,
		dy = (e.clientY - r.top - r.height / 2) / 35;
	send({
		op: "input",
		x: Math.abs(dx) > 0.2 ? Math.sign(dx) : 0,
		y: Math.abs(dy) > 0.2 ? Math.sign(dy) : 0,
	});
	pad.firstElementChild.style.transform = `translate(${Math.max(-30, Math.min(30, dx * 30))}px,${Math.max(-30, Math.min(30, dy * 30))}px)`;
};
pad.onpointerup = pad.onpointercancel = () => {
	pointer = undefined;
	send({ op: "input", x: 0, y: 0 });
	pad.firstElementChild.style.transform = "";
};
new ResizeObserver(resize).observe(host);
$("update").onclick = () => location.reload();
setInterval(
	async () => {
		if (document.hidden) return;
		try {
			const version = await fetch("./version.json", { cache: "no-store" }).then(
				(r) => r.json(),
			);
			if (build && version.build !== build) {
				if (location.hostname === "localhost") location.reload();
				else $("update").hidden = false;
			}
		} catch {}
	},
	location.hostname === "localhost" ? 2000 : 60000,
);
boot().catch((error) => fail(String(error)));
