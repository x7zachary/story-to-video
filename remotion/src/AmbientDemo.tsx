// Preview of every overlay type, 3 s each, over a neutral warm interior gradient (npx remotion studio -> AmbientDemo).
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Ambient, AmbientType } from "./Ambient";

const TYPES: AmbientType[] = ["dust", "flies", "fireflies", "embers", "snow", "rain", "steam", "flicker"];

export const AmbientDemo: React.FC = () => (
  <AbsoluteFill style={{ background: "linear-gradient(160deg, #6b5a46 0%, #2e261f 60%, #15110d 100%)" }}>
    {TYPES.map((type, i) => (
      <Sequence key={type} from={i * 90} durationInFrames={90} name={type}>
        <Ambient spec={type === "steam" ? { type, region: [0.35, 0.4, 0.65, 0.9] } : type === "flies" ? { type, region: [0.3, 0.3, 0.7, 0.7] } : { type }} />
        <AbsoluteFill style={{ color: "white", fontSize: 48, padding: 40, fontFamily: "sans-serif" }}>{type}</AbsoluteFill>
      </Sequence>
    ))}
  </AbsoluteFill>
);
