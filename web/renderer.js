// One transparent sprite atlas, one GPU batch. Art comes from native glyph masks.
export class GardenRenderer {
	constructor(canvas, image, meta) {
		this.canvas = canvas;
		this.image = image;
		this.meta = meta;
		this.gl = canvas.getContext("webgl2", {
			alpha: false,
			antialias: false,
			powerPreference: "low-power",
		});
		if (!this.gl) {
			this.ctx = canvas.getContext("2d", { alpha: false });
			this.mode = "Canvas";
			return;
		}
		this.mode = "WebGL";
		const gl = this.gl;
		const shader = (type, source) => {
			const s = gl.createShader(type);
			gl.shaderSource(s, source);
			gl.compileShader(s);
			if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
				throw Error(gl.getShaderInfoLog(s));
			return s;
		};
		const vertex = `#version 300 es
      in vec2 p; in vec2 uv; in float hue; uniform vec2 resolution;
      out vec2 tex; out float shift;
      void main(){gl_Position=vec4(p/resolution*vec2(2.,-2.)+vec2(-1.,1.),0.,1.);tex=uv;shift=hue;}`;
		const fragment = `#version 300 es
      precision highp float; in vec2 tex; in float shift; uniform sampler2D atlas; out vec4 color;
      vec3 rgbToHsl(vec3 c){float hi=max(max(c.r,c.g),c.b),lo=min(min(c.r,c.g),c.b),d=hi-lo,l=(hi+lo)*.5;
      if(d<.00001)return vec3(0.,0.,l);float h=hi==c.r?mod((c.g-c.b)/d,6.):hi==c.g?(c.b-c.r)/d+2.:(c.r-c.g)/d+4.;return vec3(h/6.,d/(1.-abs(2.*l-1.)),l);}
      vec3 hslToRgb(vec3 c){vec3 k=mod(vec3(0.,8.,4.)+c.x*12.,12.);float a=c.y*min(c.z,1.-c.z);return c.z-a*max(vec3(-1.),min(min(k-3.,9.-k),vec3(1.)));}
      void main(){color=texture(atlas,tex);if(shift!=0.){vec3 h=rgbToHsl(color.rgb);h.x=fract(h.x+shift);color.rgb=hslToRgb(h);}}`;
		this.program = gl.createProgram();
		gl.attachShader(this.program, shader(gl.VERTEX_SHADER, vertex));
		gl.attachShader(this.program, shader(gl.FRAGMENT_SHADER, fragment));
		gl.linkProgram(this.program);
		if (!gl.getProgramParameter(this.program, gl.LINK_STATUS))
			throw Error(gl.getProgramInfoLog(this.program));
		gl.useProgram(this.program);
		this.buffer = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
		for (const [name, size, offset] of [
			["p", 2, 0],
			["uv", 2, 8],
			["hue", 1, 16],
		]) {
			const loc = gl.getAttribLocation(this.program, name);
			gl.enableVertexAttribArray(loc);
			gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 20, offset);
		}
		const texture = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, texture);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
		gl.clearColor(0, 0, 0, 1);
		this.resolution = gl.getUniformLocation(this.program, "resolution");
	}
	resize(width, height) {
		this.width = width;
		this.height = height;
		this.dpr = Math.min(devicePixelRatio || 1, 2);
		this.canvas.width = Math.round(width * this.dpr);
		this.canvas.height = Math.round(height * this.dpr);
	}
	draw(state) {
		const started = performance.now(),
			sprites = [],
			[cx, cy] = state.camera;
		const cw = this.width / state.width,
			ch = this.height / state.height;
		const add = (index, x, y, hue = 0, mirror = false) =>
			sprites.push({
				index,
				x: (x - cx) * cw,
				y: (y - cy) * ch,
				w: 32 * cw,
				h: 12 * ch,
				hue,
				mirror,
			});
		state.leaves.forEach((leaf) => add(this.meta.leaf, leaf.x, leaf.y));
		state.hearts.forEach((heart) =>
			add(
				this.meta.frames +
					Math.floor(
						((state.time / 3 + heart.phase_offset) % 1) * this.meta.hearts,
					),
				heart.x,
				heart.y,
			),
		);
		state.birds.forEach((bird) =>
			add(
				Math.floor(bird.wing_position) % this.meta.frames,
				bird.x,
				bird.y,
				bird.hue_shift,
				bird.facing < 0,
			),
		);
		if (this.gl) {
			const gl = this.gl,
				vertices = [];
			for (const s of sprites) {
				const sx = (s.index % 10) * 256,
					sy = Math.floor(s.index / 10) * 96;
				let u0 = sx / this.meta.atlasWidth,
					u1 = (sx + 256) / this.meta.atlasWidth;
				if (s.mirror) [u0, u1] = [u1, u0];
				const v0 = sy / this.meta.atlasHeight,
					v1 = (sy + 96) / this.meta.atlasHeight;
				for (const [x, y, u, v] of [
					[s.x, s.y, u0, v0],
					[s.x + s.w, s.y, u1, v0],
					[s.x, s.y + s.h, u0, v1],
					[s.x, s.y + s.h, u0, v1],
					[s.x + s.w, s.y, u1, v0],
					[s.x + s.w, s.y + s.h, u1, v1],
				])
					vertices.push(x, y, u, v, s.hue);
			}
			gl.viewport(0, 0, this.canvas.width, this.canvas.height);
			gl.clear(gl.COLOR_BUFFER_BIT);
			gl.uniform2f(this.resolution, this.width, this.height);
			gl.bufferData(
				gl.ARRAY_BUFFER,
				new Float32Array(vertices),
				gl.DYNAMIC_DRAW,
			);
			gl.drawArrays(gl.TRIANGLES, 0, vertices.length / 5);
		} else {
			const c = this.ctx;
			c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
			c.fillStyle = "#000";
			c.fillRect(0, 0, this.width, this.height);
			c.imageSmoothingEnabled = false;
			for (const s of sprites) {
				c.save();
				c.translate(s.x + (s.mirror ? s.w : 0), s.y);
				c.scale(s.mirror ? -1 : 1, 1);
				c.filter = s.hue ? `hue-rotate(${s.hue * 360}deg)` : "none";
				c.drawImage(
					this.image,
					(s.index % 10) * 256,
					Math.floor(s.index / 10) * 96,
					256,
					96,
					0,
					0,
					s.w,
					s.h,
				);
				c.restore();
			}
		}
		return performance.now() - started;
	}
}
