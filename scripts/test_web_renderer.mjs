import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { GardenRenderer } from "../web/renderer.js";
const meta = JSON.parse(await readFile("web-dist/assets.json", "utf8"));
const draws = [];
let position;
const context = {
	setTransform() {},
	fillRect() {},
	save() {},
	restore() {},
	scale() {},
	translate(x, y) {
		position = [x, y];
	},
	drawImage(_image, sx, sy, sw, sh) {
		draws.push({ tile: (sy / 96) * 10 + sx / 256, position, crop: [sw, sh] });
	},
};
globalThis.devicePixelRatio = 1;
const renderer = new GardenRenderer(
	{ getContext: (type) => (type === "2d" ? context : null) },
	{},
	meta,
);
renderer.resize(720, 640);
renderer.draw({
	width: 120,
	height: 40,
	camera: [10, 5],
	time: 0,
	target_leaf: 0,
	effects: { back: [[20, 10, "·:00b9d7"]], front: [[25, 12, "+:7befff"]] },
	leaves: [
		{ x: 10, y: 25 },
		{ x: 50, y: 25 },
	],
	hearts: [{ x: 30, y: 10, phase_offset: 0 }],
	birds: [
		{ ident: 1, x: 10, y: 5, wing_position: 0, hue_shift: 0, facing: 1 },
		{ ident: 2, x: 40, y: 10, wing_position: 1, hue_shift: 0.5, facing: -1 },
	],
});
assert.deepEqual(
	draws.map((d) => d.tile),
	[
		meta.effects["·:00b9d7"],
		meta.leaf,
		meta.dimLeaf,
		meta.frames,
		1,
		meta.effects["+:7befff"],
		0,
	],
);
assert.deepEqual(draws[0].position, [120, 160]); // effects already in screen cells
assert.deepEqual(draws[5].position, [150, 192]);
assert.deepEqual(draws[0].crop, [8, 8]); // one cell, not a bird-sized transparent quad
console.log(
	"Browser draw contract: trail → perches → hearts → companions → marker → player; camera applied once.",
);
