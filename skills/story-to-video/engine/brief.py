"""Stage 0: director's brief (style + hook decisions) for a new story.

  python brief.py init    <slug> <story.txt> [--title T]   create projects/<slug>, brief.json skeleton, brief.md
  python brief.py samples <slug> [--scene "..."] [--presets a,b,c]
                                                            one quick Z-Image sample per style preset -> style_samples/
  python brief.py hook    <slug> <hooks.json>               score hook candidates, pick the best, record the rationale
  python brief.py lock    <slug> --preset ID [--aspect 16:9] [--hook N] [--mode auto|interactive]
                                [--palette-en "a,b,c"] [--palette-zh "甲,乙,丙"]
                                                            write style.json + manifest skeleton (style, characters);
                                                            presets with a palette / hard_constraints lock them in (stylelock.py)

Two modes (same artifacts): `interactive` = the agent asks the user (AskUserQuestion) and shows the sample images;
`auto` = the agent decides by the rules in SKILL.md, writes the reasons into brief.md, keeps the samples so the user
can override in the morning.
"""
import argparse
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import stylelock  # noqa: E402

PRESETS = os.path.join(config.ENGINE, "presets")


def load_preset(pid):
    return json.load(open(os.path.join(PRESETS, pid + ".json"), encoding="utf-8"))


def init(slug, story, title):
    d = config.project_dir(slug)
    os.makedirs(os.path.join(d, "style_samples"), exist_ok=True)
    shutil.copy(story, os.path.join(d, "story.txt"))
    brief = {"slug": slug, "title": title or slug, "platform": None, "aspect": "16:9", "target_seconds": None,
             "narration_tone": None, "preset": None, "mode": None, "hook": None, "decisions": []}
    json.dump(brief, open(os.path.join(d, "brief.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(d, "brief.md"), "w", encoding="utf-8").write(
        f"# 导演简报：{title or slug}\n\n"
        "## 待决策（交互模式逐条问用户；自动模式由 Claude 按 SKILL.md 规则决定并写明理由）\n"
        "1. 平台/画幅：16:9 横屏（B站/YouTube）或 9:16 竖屏（抖音/视频号）\n"
        "2. 目标时长：\n3. 画风预设（见 style_samples/）：cinematic_realistic / ink_wash / storybook\n"
        "4. 旁白语气：沉稳叙事 / 悬疑 / 温情\n5. 钩子（前 3–6 秒）：见 hook 评分\n")
    print("initialized", d)


def samples(slug, scene, preset_ids):
    import comfy
    import graphs
    d = config.project_dir(slug)
    scene = scene or "an old Chinese scholar in a scholar's robe standing before a sealed wooden temple door, winter mist, dusk"
    comfy.start(1.5)
    for pid in preset_ids:
        p = load_preset(pid)
        w, h = p["sample_size"]
        files = comfy.run(graphs.zimage_graph(f"{scene}. {stylelock.style_text(p)}", 42, w, h, f"engine/style_{slug}_{pid}"))
        shutil.copy(files[0], os.path.join(d, "style_samples", pid + ".png"))
        print("sample:", pid)


def score_hook(c):
    """Deterministic rubric over attributes the agent fills in (0/1 unless noted). Max 10."""
    s = 0.0
    s += 3 * c.get("conflict_or_mystery", 0)                 # does it open a question the viewer wants answered?
    s += 2 * c.get("has_ready_visual", 0)                    # a shot already exists / is cheap to generate
    s += 2 * (1 if c.get("seconds", 99) <= 6 else 0)          # lands inside 6 s
    s += 2 * (1 - c.get("spoils_ending", 0))                  # does not give away the ending
    s += 1 * c.get("callback_payoff", 0)                      # pays off again later in the story
    return s


def hook(slug, path):
    cands = json.load(open(path, encoding="utf-8"))
    for c in cands:
        c["score"] = score_hook(c)
    top = max(c["score"] for c in cands)
    tied = sorted((c for c in cands if c["score"] == top), key=lambda c: (c.get("seconds", 99), c["id"]))
    best = tied[0]                       # tie-break: shorter hook, then id; the tie is recorded so a human can overrule
    d = config.project_dir(slug)
    b = json.load(open(os.path.join(d, "brief.json"), encoding="utf-8"))
    b["hook"] = best
    b["decisions"].append({"topic": "hook", "options": [(c["id"], c["score"]) for c in cands], "chosen": best["id"], "tied": [c["id"] for c in tied]})
    json.dump(b, open(os.path.join(d, "brief.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(d, "brief.md"), "a", encoding="utf-8") as f:
        f.write("\n## 钩子评分\n" + "\n".join(f"- [{c['id']}] {c['score']:.0f}/10 {c['type']}：{c['text']}" for c in sorted(cands, key=lambda c: -c["score"])) + f"\n\n**选定：{best['id']}**"
                + (f"（与 {', '.join(c['id'] for c in tied[1:])} 同分，按更短者优先；建议交互模式人工三选一）" if len(tied) > 1 else "") + "\n")
    print("chosen hook:", best["id"], best["score"])


def lock(slug, preset, aspect, mode, palette_en=None, palette_zh=None):
    d = config.project_dir(slug)
    p = load_preset(preset)
    b = json.load(open(os.path.join(d, "brief.json"), encoding="utf-8"))
    b.update(preset=preset, aspect=aspect, mode=mode)
    w, h = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    json.dump(b, open(os.path.join(d, "brief.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(p, open(os.path.join(d, "style.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chars = json.load(open(os.path.join(d, "characters.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "characters.json")) else {}
    style = {"image_style": p["image_style"], "flashback_style": p["flashback_style"], "motion_suffix": p["motion_suffix"],
             "wan_negative": p["wan_negative"]}
    for k in ("palette_en", "palette_zh", "hard_constraints", "banned_terms"):      # style-lock fields (optional, see stylelock.py)
        if p.get(k):
            style[k] = p[k]
    if palette_en:                                      # this film's own palette overrides the preset default
        style["palette_en"] = [x.strip() for x in palette_en.split(",") if x.strip()]
        style["palette_source"] = "project"             # lint: a project palette is not 'drift' from the preset
    if palette_zh:
        style["palette_zh"] = [x.strip() for x in palette_zh.replace("，", ",").split(",") if x.strip()]
        style["palette_source"] = "project"
    m = {"slug": slug, "title": b["title"], "root": d, "fps": 30, "width": w, "height": h, "brief": b,
         "style": style,
         "hook": b.get("hook"), "characters": chars, "voices": {}, "tts_replace": {}, "segments": [], "shots": [], "timeline": {}}
    config.save_manifest(slug, m)
    print("locked style + wrote manifest skeleton:", config.manifest_path(slug))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("slug")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--title", default="")
    ap.add_argument("--scene", default="")
    ap.add_argument("--presets", default="cinematic_realistic,ink_wash,storybook")
    ap.add_argument("--preset", default="cinematic_realistic")
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--mode", default="auto")
    ap.add_argument("--palette-en", default="", help="comma-separated colour names for this film (overrides the preset's)")
    ap.add_argument("--palette-zh", default="", help="same, in Chinese (documentation only)")
    a = ap.parse_args()
    if a.cmd == "init":
        init(a.slug, a.arg, a.title)
    elif a.cmd == "samples":
        samples(a.slug, a.scene, a.presets.split(","))
    elif a.cmd == "hook":
        hook(a.slug, a.arg)
    elif a.cmd == "lock":
        lock(a.slug, a.preset, a.aspect, a.mode, a.palette_en, a.palette_zh)
