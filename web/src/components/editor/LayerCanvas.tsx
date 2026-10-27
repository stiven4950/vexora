import { useEffect, useRef, useState, type RefObject } from "react";

import { centerAt, visibleAt, type LayerLayout, type LiveState } from "../../api/liveLayers";

/** Baldosas que el shader recorre como mucho (MAX_LAYER_TRACKS + "rest" en composite/atlas.py). */
const MAX_TILES = 17;

/**
 * La mezcla de composite/composite.py, al revés: el plano del mosaico en luz lineal y, por cada
 * pista encendida, `acc = acc * (1 - A·g) + C·g`, con C decodificado de `srgb(C / (1 + C))`, el
 * color de engine/tint.py `recolor` y el tamaño alrededor del centro de su energía (`scale_about`).
 */
const FRAGMENT = `#version 300 es
precision highp float;
uniform sampler2D atlas;
uniform vec2 atlasSize;
uniform vec4 plate;
uniform vec2 tileSize;
uniform int count;
uniform vec4 origin[${MAX_TILES}];
uniform vec4 params[${MAX_TILES}];
uniform vec3 tint[${MAX_TILES}];
uniform vec2 center[${MAX_TILES}];
in vec2 uv;
out vec4 color;

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

vec3 toLinear(vec3 c) {
  return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}
vec3 toSrgb(vec3 c) {
  c = max(c, 0.0);
  return clamp(mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)), 0.0, 1.0);
}
vec4 tile(vec2 at, vec2 p) {
  // Medio píxel hacia adentro: el filtro no mezcla con la baldosa de al lado.
  vec2 inside = clamp(p, 0.5 / tileSize, 1.0 - 0.5 / tileSize);
  return texture(atlas, (at + inside * tileSize) / atlasSize);
}
vec3 recolor(vec3 c, vec3 t) {
  float luma = dot(c, LUMA);
  float peak = max(c.r, max(c.g, c.b));
  float white = peak > 1e-6 ? min(c.r, min(c.g, c.b)) / peak : 0.0;
  float lt = max(dot(t, LUMA), 1e-6);
  return luma * (t / lt) * (1.0 - white) + vec3(luma) * white;
}

void main() {
  vec3 acc = toLinear(texture(atlas, (plate.xy + uv * plate.zw) / atlasSize).rgb);
  for (int i = 0; i < ${MAX_TILES}; i++) {
    if (i >= count) break;
    float gain = params[i].x;
    if (gain <= 0.0) continue;
    vec2 p = center[i] + (uv - center[i]) / params[i].y;
    if (any(lessThan(p, vec2(0.0))) || any(greaterThan(p, vec2(1.0)))) continue;
    vec3 x = min(toLinear(tile(origin[i].xy, p).rgb), vec3(0.995));
    vec3 c = x / (1.0 - x);
    if (params[i].z > 0.5) c = recolor(c, tint[i]);
    float a = origin[i].z >= 0.0 ? tile(origin[i].zw, p).r : 0.0;
    acc = acc * (1.0 - min(a * gain, 1.0)) + c * gain;
  }
  color = vec4(toSrgb(acc), 1.0);
}`;

const VERTEX = `#version 300 es
in vec2 corner;
out vec2 uv;
void main() {
  // La fila 0 de la textura es la de arriba del video: y crece hacia abajo, como en el mosaico.
  uv = vec2(corner.x + 1.0, 1.0 - corner.y) * 0.5;
  gl_Position = vec4(corner, 0.0, 1.0);
}`;

interface Props {
  /** El video del mosaico (el reproductor lo controla: reproducir, pausar y buscar). */
  video: RefObject<HTMLVideoElement | null>;
  layout: LayerLayout;
  live: LiveState;
  className?: string;
}

type Gl = {
  gl: WebGL2RenderingContext;
  texture: WebGLTexture;
  uniform: (name: string) => WebGLUniformLocation | null;
};

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("WebGL: no se pudo crear el shader");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) ?? "WebGL: shader no válido");
  return shader;
}

function setup(canvas: HTMLCanvasElement): Gl {
  const gl = canvas.getContext("webgl2", { premultipliedAlpha: false, antialias: false });
  if (!gl) throw new Error("Este navegador no tiene WebGL 2");
  const program = gl.createProgram();
  if (!program) throw new Error("WebGL: no se pudo crear el programa");
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) ?? "WebGL: programa no válido");
  gl.useProgram(program);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const corner = gl.getAttribLocation(program, "corner");
  gl.enableVertexAttribArray(corner);
  gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
  const texture = gl.createTexture();
  if (!texture) throw new Error("WebGL: no se pudo crear la textura");
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const cache = new Map<string, WebGLUniformLocation | null>();
  const uniform = (name: string) => {
    if (!cache.has(name)) cache.set(name, gl.getUniformLocation(program, name));
    return cache.get(name) ?? null;
  };
  return { gl, texture, uniform };
}

/**
 * La vista en vivo: dibuja en un canvas el fotograma actual del mosaico de capas con los cambios
 * pendientes (`live`, de api/liveLayers.ts). Redibuja con cada fotograma nuevo del video y cada vez
 * que cambian los cambios, aunque esté en pausa.
 */
export function LayerCanvas({ video, layout, live, className }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const state = useRef<Gl | null>(null);
  const liveRef = useRef(live);
  const [failure, setFailure] = useState<string | null>(null);
  liveRef.current = live;

  const draw = () => {
    const ctx = state.current;
    const v = video.current;
    if (!ctx || !v || v.readyState < 2) return;
    const { gl, texture, uniform } = ctx;
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, v);
    const t = v.currentTime;
    const frame = Math.min(Math.floor(t * layout.fps + 1e-3), layout.frames - 1);
    const tiles = liveRef.current.tiles.slice(0, MAX_TILES);
    const origin = new Float32Array(MAX_TILES * 4);
    const params = new Float32Array(MAX_TILES * 4);
    const tint = new Float32Array(MAX_TILES * 3);
    const center = new Float32Array(MAX_TILES * 2);
    tiles.forEach((item, i) => {
      origin.set([item.tile.c[0], item.tile.c[1], item.tile.a ? item.tile.a[0] : -1, item.tile.a ? item.tile.a[1] : -1], i * 4);
      params.set([visibleAt(item, t) ? item.gain : 0, item.size, item.tint ? 1 : 0, 0], i * 4);
      if (item.tint) tint.set(item.tint, i * 3);
      center.set(centerAt(item.tile, frame), i * 2);
    });
    gl.uniform1i(uniform("atlas"), 0);
    gl.uniform2f(uniform("atlasSize"), layout.width, layout.height);
    gl.uniform4f(uniform("plate"), ...layout.plate);
    gl.uniform2f(uniform("tileSize"), layout.tile[0], layout.tile[1]);
    gl.uniform1i(uniform("count"), tiles.length);
    gl.uniform4fv(uniform("origin"), origin);
    gl.uniform4fv(uniform("params"), params);
    gl.uniform3fv(uniform("tint"), tint);
    gl.uniform2fv(uniform("center"), center);
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
  const drawRef = useRef(draw);
  drawRef.current = draw;

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    element.width = layout.plate[2];
    element.height = layout.plate[3];
    try {
      state.current = setup(element);
      setFailure(null);
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : String(cause));
      return;
    }
    // Un fotograma nuevo del video (requestVideoFrameCallback donde exista; si no, cada cuadro de pantalla).
    const v = video.current;
    let handle = 0;
    let stopped = false;
    const withFrames = v && "requestVideoFrameCallback" in v;
    const onFrame = () => {
      if (stopped) return;
      drawRef.current();
      if (withFrames && v) handle = v.requestVideoFrameCallback(onFrame);
      else handle = requestAnimationFrame(onFrame);
    };
    onFrame();
    const redraw = () => drawRef.current();
    v?.addEventListener("seeked", redraw);
    v?.addEventListener("loadeddata", redraw);
    return () => {
      stopped = true;
      if (withFrames && v) v.cancelVideoFrameCallback(handle);
      else cancelAnimationFrame(handle);
      v?.removeEventListener("seeked", redraw);
      v?.removeEventListener("loadeddata", redraw);
      state.current = null;
    };
  }, [layout, video]);

  // En pausa no llegan fotogramas: los cambios se dibujan en cuanto ocurren.
  useEffect(() => {
    drawRef.current();
  }, [live]);

  if (failure) return <p role="alert">{failure}</p>;
  return <canvas ref={canvas} className={className} aria-label="Vista en vivo con los cambios" />;
}
