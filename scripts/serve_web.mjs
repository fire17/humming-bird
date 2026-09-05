import { watch } from "node:fs";
import { spawnSync } from "node:child_process";
const build = () =>
	spawnSync("bun", ["scripts/build_web.mjs"], { stdio: "inherit" });
build();
let timer;
for (const path of [
	"web",
	"hummingbird_game.py",
	"hummingbird_brain.py",
	"hummingbird_flock.py",
	"humming_bird_assets",
]) {
	watch(path, { recursive: true }, () => {
		clearTimeout(timer);
		timer = setTimeout(build, 200);
	});
}
const port = Number(process.env.PORT || 4173);
Bun.serve({
	port,
	async fetch(request) {
		const path = decodeURIComponent(new URL(request.url).pathname);
		if (path.includes("..")) return new Response("Forbidden", { status: 403 });
		const file = Bun.file(`web-dist${path === "/" ? "/index.html" : path}`);
		return (await file.exists())
			? new Response(file, { headers: { "Cache-Control": "no-cache" } })
			: new Response("Not found", { status: 404 });
	},
});
console.log(`Live development garden: http://localhost:${port}`);
