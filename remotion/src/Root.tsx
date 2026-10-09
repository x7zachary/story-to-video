import "./index.css";
import { Composition } from "remotion";
import { StoryVideo } from "./StoryVideo";
import { AmbientDemo } from "./AmbientDemo";
import timeline from "./timeline.json";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="StoryVideo"
        component={StoryVideo}
        durationInFrames={Math.round(timeline.total * 30)}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ useClips: false }}
      />
      <Composition id="AmbientDemo" component={AmbientDemo} durationInFrames={8 * 90} fps={30} width={1920} height={1080} />
    </>
  );
};
