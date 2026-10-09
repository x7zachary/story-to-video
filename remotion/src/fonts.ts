import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Fonts are NOT shipped (licensing). Put two font files you are allowed to use into public/fonts/:
//   kai.ttf    subtitles / poem lines   e.g. LXGW WenKai 霞鹜文楷 (SIL OFL 1.1)
//   title.ttf  title card              e.g. Ma Shan Zheng 马善政毛笔楷书 (SIL OFL 1.1)
// `python setup/stv_setup.py check` reports missing fonts.
export const KAI = "StvKai";
export const XINGKAI = "StvTitle";

loadFont({ family: KAI, url: staticFile("fonts/kai.ttf"), format: "truetype", display: "block" });
loadFont({ family: XINGKAI, url: staticFile("fonts/title.ttf"), format: "truetype", display: "block" });
