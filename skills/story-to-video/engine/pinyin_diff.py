"""Pinyin-level comparison of ASR output vs the script (homophone-tolerant pronunciation QA).

Usage: python pinyin_diff.py <asr_report.json> [<manifest tts_replace applied: --slug SLUG>]
Why pinyin: ASR of classical Chinese confuses homophones (福斯/佛寺); those must not count as TTS mistakes.
What it can and cannot show: it catches dropped/wrong syllables and wrong tone-less readings; it cannot certify
tones or polyphone choices when the ASR itself hears a homophone. Treat 'suspect' lines as things to listen to.
"""
import difflib
import json
import os
import re
import sys

from opencc import OpenCC
from pypinyin import Style, lazy_pinyin

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

t2s = OpenCC("t2s")
DIGITS = "零一二三四五六七八九"


def num_to_cn(m):
    n = int(m.group())
    if n < 10:
        return DIGITS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return ("" if tens == 1 else DIGITS[tens]) + "十" + (DIGITS[ones] if ones else "")
    return "".join(DIGITS[int(c)] for c in m.group())


def normalize(s):
    s = re.sub(r"\d+", num_to_cn, s)
    return t2s.convert(s)


def syl(s):
    return [p for p in lazy_pinyin(s, style=Style.NORMAL) if p.strip()]


if __name__ == "__main__":
    report = json.load(open(sys.argv[1], encoding="utf-8"))
    replace = {}
    if "--slug" in sys.argv:
        replace = config.load_manifest(sys.argv[sys.argv.index("--slug") + 1]).get("tts_replace", {})
    out, total, bad = [], 0, 0
    for r in report:
        ref = r["ref"]
        for k, v in replace.items():        # what the TTS was actually asked to say
            ref = ref.replace(k, v)
        a, b = syl(ref), syl(normalize(r["hyp"]))
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        diffs = [(" ".join(a[i1:i2]), " ".join(b[j1:j2])) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
        rate = 1 - sm.ratio()
        total += len(a)
        bad += sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
        out.append({"id": r["id"], "syllable_diff_rate": round(rate, 3), "diffs": diffs, "ref": ref, "hyp": normalize(r["hyp"])})
    path = os.path.join(os.path.dirname(sys.argv[1]), "pinyin_report.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = [f"overall syllable mismatch: {bad}/{total} = {bad/total:.1%}"]
    for o in sorted(out, key=lambda x: -x["syllable_diff_rate"]):
        lines.append(f"{o['id']} {o['syllable_diff_rate']:.2f}  ref={o['ref']}\n      hyp={o['hyp']}\n      diffs={o['diffs']}")
    open(os.path.join(os.path.dirname(sys.argv[1]), "pinyin_summary.txt"), "w", encoding="utf-8").write("\n".join(lines))
    print("written pinyin_summary.txt")
