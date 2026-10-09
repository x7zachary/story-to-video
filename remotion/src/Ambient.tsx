// Code-drawn ambient motion ("overlay" tier): dust, flies, fireflies, embers, snow, rain, steam, light flicker.
// Deterministic (seeded), costs no GPU and cannot invent people or objects, unlike an AI clip. Self-contained so
// other Remotion projects can copy this one file. Spec comes from the manifest shot's `overlay` field.
import React from "react";
import { AbsoluteFill, random, useCurrentFrame, useVideoConfig } from "remotion";

export type AmbientType = "dust" | "flies" | "fireflies" | "embers" | "snow" | "rain" | "steam" | "flicker";
export type AmbientSpec = {
  type: AmbientType;
  count?: number;
  region?: [number, number, number, number]; // x0, y0, x1, y1 as fractions of the frame
  intensity?: number; // opacity scale, default 1
  seed?: number;
};

const DEFAULT_COUNT: Record<AmbientType, number> = {
  dust: 40, flies: 4, fireflies: 14, embers: 24, snow: 70, rain: 120, steam: 12, flicker: 1,
};

// smooth deterministic wander in -1..1
const wander = (t: number, s: number) =>
  0.6 * Math.sin(t * (0.9 + s * 0.7) + s * 10) + 0.4 * Math.sin(t * (2.3 + s * 1.1) + s * 3);
const loop = (v: number) => v - Math.floor(v);

export const Ambient: React.FC<{ spec: AmbientSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const [x0, y0, x1, y1] = spec.region ?? [0, 0, 1, 1];
  const rw = (x1 - x0) * width;
  const rh = (y1 - y0) * height;
  const k = spec.intensity ?? 1;
  const n = spec.count ?? DEFAULT_COUNT[spec.type];
  const seed = `${spec.type}-${spec.seed ?? 0}`;
  const r = (i: number, j: number) => random(`${seed}-${i}-${j}`);

  if (spec.type === "flicker") {
    const a = 0.08 + 0.05 * wander(t * 6, r(0, 0)) + 0.03 * Math.sin(t * 23);
    return <AbsoluteFill style={{ backgroundColor: "rgb(255, 170, 80)", opacity: Math.max(0, a) * k, mixBlendMode: "soft-light" }} />;
  }

  const parts = Array.from({ length: n }, (_, i) => {
    const s = r(i, 0);
    const bx = x0 * width + r(i, 1) * rw;
    const by = y0 * height + r(i, 2) * rh;
    let x = bx;
    let y = by;
    let size = 3;
    let style: React.CSSProperties = {};
    switch (spec.type) {
      case "dust": {
        x = bx + 30 * wander(t * 0.25, s);
        y = y0 * height + loop(r(i, 2) - t * (0.01 + 0.02 * s)) * rh;
        size = 2 + 3 * r(i, 3);
        style = { background: "rgba(255, 240, 210, 1)", opacity: k * (0.25 + 0.45 * (0.5 + 0.5 * Math.sin(t * (1 + s * 2) + s * 9))),
          filter: "blur(0.6px)" };
        break;
      }
      case "flies": {
        // erratic loops around a home point plus a fast jitter; dark body with a pale wing blur
        x = bx + rw * 0.18 * wander(t * 1.6, s) + 4 * Math.sin(t * 37 + s * 50);
        y = by + rh * 0.14 * wander(t * 2.1, s + 5) + 4 * Math.cos(t * 41 + s * 30);
        size = 7 + 3 * r(i, 3);
        style = { background: "rgba(25, 22, 18, 0.9)", boxShadow: "0 0 3px 2px rgba(210, 210, 200, 0.35)", opacity: k };
        break;
      }
      case "fireflies": {
        x = bx + 60 * wander(t * 0.4, s);
        y = by + 40 * wander(t * 0.35, s + 3);
        size = 4 + 3 * r(i, 3);
        const pulse = Math.max(0, Math.sin(t * (1.2 + s) + s * 20));
        style = { background: "rgba(255, 245, 160, 1)", boxShadow: "0 0 12px 6px rgba(220, 255, 120, 0.6)", opacity: k * pulse };
        break;
      }
      case "embers": {
        const p = loop(r(i, 2) + t * (0.15 + 0.2 * s));
        x = bx + 40 * wander(t * 0.8, s) * p;
        y = y1 * height - p * rh;
        size = 2 + 3 * r(i, 3);
        style = { background: "rgba(255, 150, 60, 1)", boxShadow: "0 0 6px 3px rgba(255, 110, 30, 0.6)", opacity: k * (1 - p) };
        break;
      }
      case "snow": {
        x = bx + 25 * wander(t * 0.5, s);
        y = y0 * height + loop(r(i, 2) + t * (0.05 + 0.07 * s)) * rh;
        size = 2 + 5 * r(i, 3);
        style = { background: "rgba(255, 255, 255, 0.95)", opacity: k * (0.5 + 0.5 * r(i, 4)), filter: "blur(0.8px)" };
        break;
      }
      case "rain": {
        x = bx + 60 * loop(r(i, 2) + t * 1.5);
        y = y0 * height + loop(r(i, 2) + t * (1.4 + 0.6 * s)) * rh;
        return (
          <div key={i} style={{ position: "absolute", left: x, top: y, width: 1.5, height: 40 + 30 * s, borderRadius: 1,
            background: "rgba(220, 230, 240, 1)", opacity: k * 0.25, transform: "rotate(12deg)" }} />
        );
      }
      case "steam": {
        const p = loop(r(i, 2) + t * (0.08 + 0.06 * s));
        x = bx + 50 * wander(t * 0.3, s) * p;
        y = y1 * height - p * rh;
        size = 80 + 180 * p;
        // wide, soft, slowly rising wisps (round blobs read as balls)
        return (
          <div key={i} style={{ position: "absolute", left: x - size / 2, top: y - size * 0.3, width: size, height: size * 0.6,
            borderRadius: "50%", background: "rgba(255, 255, 255, 1)", opacity: k * 0.16 * Math.sin(Math.PI * p),
            filter: "blur(30px)", mixBlendMode: "screen", transform: `rotate(${20 * wander(t * 0.2, s)}deg)` }} />
        );
      }
      default:
        break;
    }
    return (
      <div key={i} style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size,
        borderRadius: "50%", ...style }} />
    );
  });
  return <AbsoluteFill style={{ pointerEvents: "none" }}>{parts}</AbsoluteFill>;
};

export const toSpecs = (o: AmbientSpec | AmbientSpec[] | undefined): AmbientSpec[] => (o ? (Array.isArray(o) ? o : [o]) : []);
