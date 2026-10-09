import { Audio, Video } from "@remotion/media";
import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Ambient, AmbientSpec, toSpecs } from "./Ambient";
import { KAI, XINGKAI } from "./fonts";
import timeline from "./timeline.json";

type Shot = {
  shot: number;
  name: string;
  start: number;
  end: number;
  image: string;
  clip?: string;
  zoom?: number; // reuse of a keyframe as a punch-in crop
  focus?: [number, number]; // zoom anchor, 0..1
  overlay?: AmbientSpec | AmbientSpec[]; // code-drawn ambient motion (dust, flies, steam...), see Ambient.tsx
  move?: string; // Ken Burns move: in | out | left | right | up | still (manifest `move`)
  flashback?: boolean; // warm sepia wash (manifest `flashback`)
};
type Line = { text: string; start: number; end: number; speaker?: string };

export type StoryProps = { readonly useClips: boolean };

const FPS = 30;
const XFADE = 18; // crossfade length between shots, frames
const f = (sec: number) => Math.round(sec * FPS);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = Easing.bezier(0.33, 0, 0.2, 1);

// Ken Burns moves: [scaleFrom, scaleTo, xFrom%, xTo%, yFrom%, yTo%]
const MOVES: Record<string, [number, number, number, number, number, number]> = {
  in: [1.03, 1.13, 0, 0, 0, 0],
  out: [1.14, 1.03, 0, 0, 0, 0],
  left: [1.12, 1.12, 2.5, -2.5, 0, 0],
  right: [1.12, 1.12, -2.5, 2.5, 0, 0],
  up: [1.1, 1.14, 0, 0, 1.5, -1.5],
  still: [1.0, 1.04, 0, 0, 0, 0],
};

const KenBurns: React.FC<{ shot: Shot; len: number }> = ({ shot, len }) => {
  const frame = useCurrentFrame();
  const [s0, s1, x0, x1, y0, y1] = MOVES[shot.move ?? "in"] ?? MOVES.in;
  const zoom = shot.zoom ?? 1;
  const [fx, fy] = shot.focus ?? [0.5, 0.5];
  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "black" }}>
      <Img
        src={staticFile(shot.image)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transformOrigin: `${fx * 100}% ${fy * 100}%`,
          scale: zoom * interpolate(frame, [0, len], [s0, s1], { ...clamp, easing: ease }),
          translate: interpolate(frame, [0, len], [`${x0}% ${y0}%`, `${x1}% ${y1}%`], { ...clamp, easing: ease }),
        }}
      />
    </AbsoluteFill>
  );
};

// AI-animated shot; a gentle push-in keeps it alive if the clip holds its last frame
const ClipLayer: React.FC<{ shot: Shot; len: number }> = ({ shot, len }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: "black", overflow: "hidden" }}>
      <Video
        src={staticFile(shot.clip as string)}
        muted
        objectFit="cover"
        style={{
          width: "100%",
          height: "100%",
          scale: interpolate(frame, [0, len], [1.0, 1.05], { ...clamp, easing: ease }),
        }}
      />
    </AbsoluteFill>
  );
};

const ShotLayer: React.FC<{ shot: Shot; len: number; first: boolean; useClip: boolean }> = ({
  shot, len, first, useClip,
}) => {
  const frame = useCurrentFrame();
  const opacity = first ? 1 : interpolate(frame, [0, XFADE], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ opacity }}>
      {useClip ? <ClipLayer shot={shot} len={len} /> : <KenBurns shot={shot} len={len} />}
      {toSpecs(shot.overlay).map((o, i) => (
        <Ambient key={i} spec={o} />
      ))}
      {shot.flashback ? (
        // flashback: warm sepia wash and soft edge
        <AbsoluteFill style={{ backgroundColor: "rgba(120, 80, 30, 0.18)", mixBlendMode: "multiply" }} />
      ) : null}
    </AbsoluteFill>
  );
};

const Subtitle: React.FC<{ line: Line; len: number }> = ({ line, len }) => {
  const frame = useCurrentFrame();
  const dialogue = line.speaker && line.speaker !== "narrator";
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 92 }}>
      <div
        style={{
          fontFamily: KAI,
          fontSize: 58,
          lineHeight: 1.25,
          letterSpacing: "0.06em",
          color: dialogue ? "#f7e6b5" : "#f5f2ea",
          textShadow:
            "0 0 3px rgba(0,0,0,0.95), 0 0 8px rgba(0,0,0,0.8), 2px 2px 2px rgba(0,0,0,0.9), -2px -2px 2px rgba(0,0,0,0.9)",
          opacity: interpolate(frame, [0, 4, len - 4, len], [0, 1, 1, 0], clamp),
          maxWidth: 1600,
          textAlign: "center",
        }}
      >
        {dialogue ? `「${line.text}」` : line.text}
      </div>
    </AbsoluteFill>
  );
};

const TitleCard: React.FC<{ title: string; subtitle: string; len: number }> = ({ title, subtitle, len }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background: "radial-gradient(ellipse at center, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0) 70%)",
        opacity: interpolate(frame, [len - 24, len], [1, 0], clamp),
      }}
    >
      <div
        style={{
          fontFamily: XINGKAI,
          fontSize: 190,
          color: "#f4ecd8",
          letterSpacing: "0.18em",
          textShadow: "0 0 30px rgba(0,0,0,0.6), 0 4px 12px rgba(0,0,0,0.7)",
          opacity: interpolate(frame, [12, 60], [0, 1], { ...clamp, easing: ease }),
          filter: `blur(${interpolate(frame, [12, 66], [10, 0], clamp)}px)`,
          scale: interpolate(frame, [0, len], [1.06, 1.0], clamp),
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontFamily: KAI,
          fontSize: 50,
          color: "#e9dfc6",
          letterSpacing: "0.5em",
          marginTop: 24,
          textShadow: "0 2px 8px rgba(0,0,0,0.8)",
          opacity: interpolate(frame, [54, 84], [0, 1], clamp),
        }}
      >
        {subtitle}
      </div>
    </AbsoluteFill>
  );
};

// The 偈语 written into the old book: vertical columns, right to left, each character inked in as it is spoken.
const PoemOverlay: React.FC<{ lines: Line[]; start: number; len: number }> = ({ lines, start, len }) => {
  const frame = useCurrentFrame();
  const t = start + frame / FPS;
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        opacity: interpolate(frame, [0, 12, len - 18, len], [0, 1, 1, 0], clamp),
      }}
    >
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(250,240,215,0.28) 0%, rgba(0,0,0,0.35) 80%)" }} />
      <div style={{ display: "flex", flexDirection: "row-reverse", gap: 70 }}>
        {lines.map((line, li) => {
          const chars = Array.from(line.text);
          return (
            <div key={li} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              {chars.map((ch, ci) => {
                const at = line.start + ((line.end - line.start) * ci) / Math.max(1, chars.length);
                const p = interpolate(t, [at - 0.05, at + 0.35], [0, 1], clamp);
                const punct = "，。？！".includes(ch);
                if (punct) {
                  return <span key={ci} style={{ height: 44 }} />;
                }
                return (
                  <span
                    key={ci}
                    style={{
                      fontFamily: XINGKAI,
                      fontSize: 92,
                      lineHeight: "108px",
                      color: "#1f140b",
                      opacity: p,
                      filter: `blur(${(1 - p) * 6}px)`,
                      textShadow: "0 0 1px rgba(31,20,11,0.6), 0 0 18px rgba(255,248,230,0.55)",
                    }}
                  >
                    {ch}
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const EndCard: React.FC<{ lines: string[]; len: number }> = ({ lines, len }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <AbsoluteFill style={{ backgroundColor: "black", opacity: interpolate(frame, [0, 40], [0, 0.35], clamp) }} />
      <div
        style={{
          fontFamily: XINGKAI,
          fontSize: 130,
          color: "#f6eed9",
          letterSpacing: "0.2em",
          textShadow: "0 0 30px rgba(0,0,0,0.7)",
          opacity: interpolate(frame, [6, 50], [0, 1], { ...clamp, easing: ease }),
          filter: `blur(${interpolate(frame, [6, 56], [8, 0], clamp)}px)`,
        }}
      >
        {lines[0]}
        <span style={{ display: "inline-block", width: 90 }} />
        {lines[1]}
      </div>
      <div
        style={{
          fontFamily: KAI,
          fontSize: 48,
          color: "#e6dcc4",
          letterSpacing: "0.12em",
          marginTop: 40,
          textShadow: "0 2px 8px rgba(0,0,0,0.8)",
          opacity: interpolate(frame, [60, 90], [0, 1], clamp),
        }}
      >
        {lines[2]}
      </div>
      <AbsoluteFill style={{ backgroundColor: "black", opacity: interpolate(frame, [len - 45, len], [0, 1], clamp) }} />
    </AbsoluteFill>
  );
};

const FilmLook: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      <AbsoluteFill
        style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)" }}
      />
      {/* bottom shade keeps subtitles legible over bright frames */}
      <AbsoluteFill style={{ background: "linear-gradient(to top, rgba(0,0,0,0.45) 0%, rgba(0,0,0,0) 26%)" }} />
      <AbsoluteFill style={{ opacity: 0.07, mixBlendMode: "overlay" }}>
        <Img src={staticFile(`grain/grain_${Math.floor(frame / 2) % 6}.png`)} style={{ width: "100%", height: "100%" }} />
      </AbsoluteFill>
    </>
  );
};

export const StoryVideo: React.FC<StoryProps> = ({ useClips }) => {
  const { durationInFrames } = useVideoConfig();
  const shots = timeline.shots as Shot[];
  const half = XFADE / 2;
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {shots.map((shot, i) => {
        const from = i === 0 ? 0 : f(shot.start) - half;
        const to = i === shots.length - 1 ? durationInFrames : f(shot.end) + half;
        return (
          <Sequence key={`shot-${i}`} name={`Shot ${shot.shot} ${shot.name}`} from={from} durationInFrames={to - from}>
            <ShotLayer shot={shot} len={to - from} first={i === 0} useClip={useClips && Boolean(shot.clip)} />
          </Sequence>
        );
      })}
      <FilmLook />
      {timeline.title ? (
        <Sequence name="Title" durationInFrames={f(timeline.title.end)}>
          <TitleCard title={timeline.title.title} subtitle={timeline.title.subtitle} len={f(timeline.title.end)} />
        </Sequence>
      ) : null}
      {timeline.poem ? (
        <Sequence name="Poem" from={f(timeline.poem.start)} durationInFrames={f(timeline.poem.end) - f(timeline.poem.start)}>
          <PoemOverlay
            lines={timeline.poem.lines as Line[]}
            start={f(timeline.poem.start) / FPS}
            len={f(timeline.poem.end) - f(timeline.poem.start)}
          />
        </Sequence>
      ) : null}
      {(timeline.subtitles as Line[]).map((line, i) => (
        <Sequence key={`sub-${i}`} name={`Sub ${line.text}`} from={f(line.start)} durationInFrames={Math.max(1, f(line.end) - f(line.start))}>
          <Subtitle line={line} len={Math.max(1, f(line.end) - f(line.start))} />
        </Sequence>
      ))}
      {timeline.endcard ? (
        <Sequence name="End card" from={f(timeline.endcard.start)} durationInFrames={durationInFrames - f(timeline.endcard.start)}>
          <EndCard lines={timeline.endcard.lines} len={durationInFrames - f(timeline.endcard.start)} />
        </Sequence>
      ) : null}
      <Audio src={staticFile((timeline as { audio?: string }).audio ?? "audio/mix.wav")} />
    </AbsoluteFill>
  );
};
