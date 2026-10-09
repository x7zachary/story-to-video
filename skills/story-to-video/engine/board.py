"""Storyboard table for the D2 discussion (before any image is generated) and for later sign-offs.

  python board.py <slug> [--out notes/storyboard.md]

One row per shot: id, time, lyric / narration, picture (desc_zh if the shot has it, else the image prompt), people,
motion tier, the motion beat, and lint's [motion] warnings for that shot. Markdown, so it can be pasted into the chat or
opened in the file pane; the user answers per shot id ("12: 不要动人, 只动镜头").
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import lint  # noqa: E402
import pipeline  # noqa: E402

TIER_ZH = {"camera": "镜头运动", "overlay": "代码叠加", "ai_env": "AI·环境", "ai_action": "AI·人物"}


def narration(m, s):
    if s.get("lyric"):
        return s["lyric"]
    segs = [g for g in (m.get("timeline") or {}).get("subtitles", []) if s.get("spans") and
            g["start"] < s["spans"][0]["end"] and g["end"] > s["spans"][0]["start"]]
    return " / ".join(g["text"] for g in segs)


def cell(text, n=90):
    text = re.sub(r"\s+", " ", str(text or "")).replace("|", "/")
    return text if len(text) <= n else text[:n - 1] + "…"


def board(m):
    warns = {}
    for lv, code, msg in lint.lint(m, files=False):
        mo = re.match(r"shot (\d+): (.*)", msg)
        if code == "motion" and mo:
            warns.setdefault(int(mo.group(1)), []).append(mo.group(2).split(";")[0])
    rows = ["| # | 时间 | 歌词/旁白 | 画面 | 人物 | 动态 | 动作 | 提醒 |", "|---|---|---|---|---|---|---|---|"]
    for s in sorted(m["shots"], key=lambda x: min((sp["start"] for sp in x.get("spans", [])), default=0)):
        sp = s.get("spans") or [{"start": 0, "end": 0}]
        t = f"{sp[0]['start']:.1f}–{sp[0]['end']:.1f}"
        pic = s.get("desc_zh") or (f"（裁切自 #{s['reuse_of']}）" if s.get("reuse_of") is not None else s.get("image_prompt", ""))
        people = ", ".join(sorted(set(lint.PLACEHOLDER.findall(str(s.get("image_prompt", ""))))))
        tier = TIER_ZH.get(s.get("motion_tier"), s.get("motion_tier") or f"({s.get('motion_class', '')})")
        if s.get("overlay"):
            ov = s["overlay"] if isinstance(s["overlay"], list) else [s["overlay"]]
            tier += " +" + "+".join(o.get("type", "?") for o in ov)
        if s.get("reuse_of") is None and s.get("motion_prompt") and s.get("motion_tier") not in ("camera", "overlay"):
            tier += " · " + pipeline.choose_model(m, s)[0].upper()
        motion = s.get("motion_zh") or ("" if s.get("motion_tier") in ("camera", "overlay") else s.get("motion_prompt", ""))
        rows.append(f"| {s['id']} | {t} | {cell(narration(m, s), 30)} | {cell(pic)} | {people} | {tier} | {cell(motion, 70)} | "
                    f"{cell('；'.join(warns.get(s['id'], [])), 80)} |")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--out")
    a = ap.parse_args()
    m = config.load_manifest(a.slug)
    text = f"# {m.get('title', a.slug)} 分镜表\n\n" + board(m)
    if a.out:
        path = a.out if os.path.isabs(a.out) else os.path.join(m["root"], a.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)
        print(f"wrote {path}")
    else:
        print(text)
