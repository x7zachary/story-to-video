"""Pre-flight checklist for a manifest project. Run it before spending GPU time.

  python lint.py <slug> [--no-files]        (or --manifest <path>)

ERROR = the manifest is wrong or contradicts the project's own style lock; fix before generating.  Exit code 1.
WARN  = worth a look (heuristics, planning rules), never blocks.

What it checks
  schema       shot ids unique, required tags present, motion_class known, reuse_of points at a real keyframe shot,
               every character has a descriptor, every segment lists real shots
  placeholders {CHAR} used in a prompt but not defined (the prompt would reach the model with literal braces)
  style lock   signature colour/pattern present in the character descriptor; banned_terms in shot prompts;
               manifest style drifting from its preset
  negation     "no / without / 不要 ..." in prompts: Z-Image-Turbo mostly ignores negatives (A/B test 2026-10-02: no measurable
               effect) and naming a thing can make it appear (a song-MV project: "no scallions" drew scallions)
  timing       shot spans cover the timeline without gaps/overlaps (timeline.coverage = "partial" skips the gap / edge checks
               for films where the shots are only inserts; overlaps are still errors); shots too long to animate or to hold as a still;
               subtitle lines too long; segment audio files present
  files        keyframes / approved clips referenced by the manifest exist on disk
  motion       Wan motion prompts that tend to come out illogical (all WARN): too many simultaneous events, multi-step
               sequences, things entering the frame, acting in a shot whose motion_class says nobody acts, a thing the
               keyframe prompt does not show, acting next to a `hold_still` character, a clip that would need slow motion

Idea borrowed (not code) from zenstory-ai/drama-skills' markdown checker: cross-reference integrity and
"why did this fail" messages instead of a bare pass/fail.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import stylelock  # noqa: E402
import timeline  # noqa: E402

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
PRESET_FIELDS = ("image_style", "flashback_style", "motion_suffix", "wan_negative",
                 "palette_en", "palette_zh", "hard_constraints", "banned_terms")
GAP_WARN, OVERLAP_ERR, EDGE_WARN, SUB_LONG = 0.15, 0.05, 0.15, 24
MAX_LIST = 8   # cap on repeated lines per check so a long manifest does not drown the report
# how a shot moves: camera = Ken Burns only; overlay = Ken Burns + code-drawn ambient motion (no AI);
# ai_env = Wan moves environment / objects only; ai_action = Wan moves a person (one beat). Optional; absent = old behaviour.
MOTION_TIERS = ("camera", "overlay", "ai_env", "ai_action")
OVERLAY_TYPES = ("dust", "flies", "fireflies", "embers", "snow", "rain", "steam", "flicker")      # remotion/src/Ambient.tsx


class Findings(list):
    def add(self, level, code, msg):
        self.append((level, code, msg))


def valid_motion_classes():
    pri = config.load_json("priors.json")
    return {k for k in pri if not k.startswith("_")}


def _prompts(s):
    return [(k, s[k]) for k in ("image_prompt", "motion_prompt") if isinstance(s.get(k), str)]


# ------------------------------------------------------------------ checks
MAX_CHAIN = 2     # tail-frame chains accumulate drift; more than two links is a warning


def _check_chain(by_id, idset, s, cf, f):
    sid = s.get("id")
    if s.get("reuse_of") is not None:
        f.add("ERROR", "schema", f"shot {sid}: continue_from on a crop shot (reuse_of); a crop has no clip of its own")
    if cf not in idset:
        f.add("ERROR", "schema", f"shot {sid}: continue_from {cf} is not a shot")
        return
    if cf == sid:
        f.add("ERROR", "schema", f"shot {sid}: continue_from points at itself")
        return
    if by_id[cf].get("reuse_of") is not None:
        f.add("ERROR", "schema", f"shot {sid}: continue_from {cf}, but shot {cf} is a crop and has no clip to continue from")
        return
    seen, cur, depth = {sid}, by_id[cf], 1
    while cur.get("continue_from") is not None:
        nxt = cur["continue_from"]
        if nxt in seen:
            f.add("ERROR", "schema", f"shot {sid}: continue_from chain loops back through shot {nxt}")
            return
        seen.add(cur.get("id"))
        if nxt not in idset:
            return                                          # reported on that shot itself
        cur, depth = by_id[nxt], depth + 1
    if depth > MAX_CHAIN:
        f.add("WARN", "schema", f"shot {sid}: chain of {depth} links (continue_from); drift accumulates, keep chains to {MAX_CHAIN}")
    a, b = by_id[cf].get("spans") or [], s.get("spans") or []
    if a and b and min(x["start"] for x in a) >= min(x["start"] for x in b):
        f.add("WARN", "schema", f"shot {sid} appears before its continue_from source {cf} in the timeline")


def check_schema(m, f):
    shots = m.get("shots", [])
    classes = valid_motion_classes()
    ids = [s.get("id") for s in shots]
    idset = set(ids)
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        f.add("ERROR", "schema", f"shot id {dup} is used more than once")
    by_id = {s.get("id"): s for s in shots}
    for s in shots:
        sid = s.get("id")
        if not isinstance(sid, int):
            f.add("ERROR", "schema", f"shot {s.get('name', '?')} has a non-integer id {sid!r}")
        ro = s.get("reuse_of")
        if ro is None:
            if not s.get("image_prompt"):
                f.add("ERROR", "schema", f"shot {sid}: no image_prompt and no reuse_of")
        elif ro not in idset:
            f.add("ERROR", "schema", f"shot {sid}: reuse_of {ro} is not a shot")
        elif ro == sid:
            f.add("ERROR", "schema", f"shot {sid}: reuse_of points at itself")
        elif by_id[ro].get("reuse_of") is not None:
            f.add("ERROR", "schema", f"shot {sid}: reuse_of {ro}, but shot {ro} is itself a crop (chain); point at the keyframe shot")
        cf = s.get("continue_from")
        if cf is not None:
            _check_chain(by_id, idset, s, cf, f)
        for tag in ("type", "motion_class", "importance"):
            if s.get(tag) in (None, ""):
                f.add("ERROR", "schema", f"shot {sid}: missing required tag '{tag}'")
        mc = s.get("motion_class")
        if mc and mc not in classes:
            f.add("ERROR", "schema", f"shot {sid}: motion_class '{mc}' unknown (priors.json has {sorted(classes)})")
        tier = s.get("motion_tier")
        if tier is not None and tier not in MOTION_TIERS:
            f.add("ERROR", "schema", f"shot {sid}: motion_tier '{tier}' unknown (use {list(MOTION_TIERS)})")
        ov = s.get("overlay")
        for o in (ov if isinstance(ov, list) else [ov] if ov else []):
            if not isinstance(o, dict) or o.get("type") not in OVERLAY_TYPES:
                f.add("ERROR", "schema", f"shot {sid}: overlay {o!r} needs a type from {list(OVERLAY_TYPES)}")
        if tier == "overlay" and not ov:
            f.add("ERROR", "schema", f"shot {sid}: motion_tier 'overlay' but no overlay spec")
        imp = s.get("importance")
        if imp is not None and not (isinstance(imp, int) and 1 <= imp <= 5):
            f.add("ERROR", "schema", f"shot {sid}: importance {imp!r} should be an integer 1-5")
    for cid, c in (m.get("characters") or {}).items():
        if not str(c.get("descriptor", "")).strip():
            f.add("ERROR", "schema", f"character {cid}: empty descriptor")
    for seg in m.get("segments", []):
        for sid in seg.get("shots", []):
            if sid not in idset:
                f.add("ERROR", "schema", f"segment {seg.get('id')}: lists shot {sid}, which does not exist")


def check_placeholders(m, f):
    chars = set((m.get("characters") or {}).keys())
    used = set()
    n = 0
    for s in m.get("shots", []):
        for key, text in _prompts(s):
            for ph in PLACEHOLDER.findall(text):
                used.add(ph)
                if ph not in chars:
                    n += 1
                    if n <= MAX_LIST:
                        f.add("ERROR", "placeholder", f"shot {s.get('id')} {key}: {{{ph}}} is not defined in characters")
    if n > MAX_LIST:
        f.add("ERROR", "placeholder", f"... and {n - MAX_LIST} more undefined placeholders")
    for c in (m.get("characters") or {}).values():          # characters may embed each other
        used.update(PLACEHOLDER.findall(str(c.get("descriptor", ""))))
    for cid in sorted(chars - used):
        f.add("WARN", "placeholder", f"character {cid} is defined but never used")


def check_negation(m, f):
    for cid, c in (m.get("characters") or {}).items():
        hits = stylelock.negations(str(c.get("descriptor", "")))
        if hits:
            f.add("WARN", "negation", f"character {cid} descriptor names something to avoid ({'; '.join(sorted(set(hits))[:3])}); "
                                      "every shot using it inherits this")
    by_phrase = {}
    for s in m.get("shots", []):
        for h in stylelock.negations(str(s.get("image_prompt", ""))):
            by_phrase.setdefault(h, []).append(s.get("id"))
    for i, (h, ids) in enumerate(sorted(by_phrase.items(), key=lambda kv: -len(kv[1]))):
        if i >= MAX_LIST:
            f.add("WARN", "negation", f"... and {len(by_phrase) - MAX_LIST} more negation phrases in image prompts")
            break
        f.add("WARN", "negation", f"image_prompt '{h}' (shots {ids[:6]}{'...' if len(ids) > 6 else ''}): "
                                  "Z-Image-Turbo mostly ignores negatives and naming a thing can make it appear; say what you want instead")


def check_style_lock(m, f):
    st = m.get("style") or {}
    banned = st.get("banned_terms") or []
    for key in ("image_style", "flashback_style", "hard_constraints"):                 # the style must obey its own ban list
        hit = stylelock.banned_hits(str(st.get(key, "")), banned)
        if hit:
            f.add("ERROR", "style-lock", f"style field '{key}' contains its own banned term(s) {hit}")
    # characters' signature colour / pattern must be in the descriptor, or the lock is decorative
    for cid, c in (m.get("characters") or {}).items():
        for key in ("signature_color", "signature_pattern"):
            if c.get(key) and str(c[key]).lower() not in str(c.get("descriptor", "")).lower():
                f.add("ERROR", "style-lock", f"character {cid}: {key} '{c[key]}' does not appear in its descriptor")
    n = 0
    for s in m.get("shots", []):
        for key, text in _prompts(s):
            hit = stylelock.banned_hits(text, banned)
            if hit:
                n += 1
                if n <= MAX_LIST:
                    f.add("ERROR", "style-lock", f"shot {s.get('id')} {key} uses banned term(s) {hit}")
    if n > MAX_LIST:
        f.add("ERROR", "style-lock", f"... and {n - MAX_LIST} more banned-term hits")
    for cid, c in (m.get("characters") or {}).items():
        hit = stylelock.banned_hits(str(c.get("descriptor", "")), banned)
        if hit:
            f.add("ERROR", "style-lock", f"character {cid} descriptor uses banned term(s) {hit}")
    # snapshot drift: manifest style vs the preset it was locked from
    pid = (m.get("brief") or {}).get("preset")
    path = os.path.join(config.ENGINE, "presets", f"{pid}.json") if pid else None
    if path and os.path.exists(path):
        p = json.load(open(path, encoding="utf-8"))
        own = ("palette_en", "palette_zh") if st.get("palette_source") == "project" else ()     # chosen on purpose at lock time
        diff = [k for k in PRESET_FIELDS if k in p and k not in own and p[k] != st.get(k)]
        if diff:
            f.add("WARN", "style-lock", f"manifest style differs from preset '{pid}' in {diff}: "
                                        "re-run brief.py lock, or confirm the change was intentional")


def check_timing(m, f):
    tl = m.get("timeline") or {}
    total = tl.get("total")
    shots = m.get("shots", [])
    if total:
        spans = sorted((sp["start"], sp["end"], s["id"]) for s in shots for sp in s.get("spans", []))
        if not spans:
            f.add("WARN", "timing", "timeline has a length but no shot has spans")
        else:
            partial = tl.get("coverage") == "partial"       # hybrid film: these shots are inserts in a film made mostly elsewhere
            if spans[0][0] > EDGE_WARN and not partial:
                f.add("WARN", "timing", f"first shot starts at {spans[0][0]:.2f}s, not 0")
            if spans[-1][1] < total - EDGE_WARN and not partial:
                f.add("WARN", "timing", f"last shot ends at {spans[-1][1]:.2f}s, {total - spans[-1][1]:.2f}s before the end ({total}s)")
            if spans[-1][1] > total + EDGE_WARN:
                f.add("ERROR", "timing", f"last shot ends at {spans[-1][1]:.2f}s, after the timeline end ({total}s)")
            for a, b in zip(spans, spans[1:]):
                gap = b[0] - a[1]
                if gap < -OVERLAP_ERR:
                    f.add("ERROR", "timing", f"shots {a[2]} and {b[2]} overlap by {-gap:.2f}s (at {b[0]:.2f}s)")
                elif gap > GAP_WARN and not partial:
                    f.add("WARN", "timing", f"gap of {gap:.2f}s between shots {a[2]} and {b[2]} (at {a[1]:.2f}s)")
        try:
            for sid, d, msg in timeline.validate(m):
                f.add("WARN", "timing", f"shot {sid} ({d}s): {msg}")
        except (KeyError, TypeError):
            pass
    for sub in tl.get("subtitles", []):
        if len(sub.get("text", "")) > SUB_LONG:
            f.add("WARN", "timing", f"subtitle at {sub.get('start')}s is {len(sub['text'])} chars (> {SUB_LONG}): '{sub['text'][:20]}...'")
    root = m.get("root")
    for seg in tl.get("segments", []):
        if root and seg.get("file") and not os.path.exists(os.path.join(root, "audio", seg["file"])):
            f.add("WARN", "timing", f"segment {seg.get('id')}: audio/{seg['file']} is missing")


# ------------------------------------------------------------------ motion plan
# Wan does ONE thing well in ~5 s. A song-MV project (2026-10) used a median of 4.5 simultaneous events per motion prompt and
# multi-step acting ("laughs shyly, rubs the back of his neck, looks down, then looks up"); many of those clips came out
# illogical (objects appearing / vanishing / morphing, actions nobody asked for). These heuristics flag that before GPU time.
MAX_EVENTS = 3                     # ambient events (mist, flicker, ripples) coexist fine; acting beats are counted separately
MAX_ACTING = 1
WAN_CLIP_SECONDS = 121 / 24        # longest clip the 5B profile makes
MIN_SPEED = 0.8                    # keep in step with render.MIN_SPEED (slower reads as dream-like slow motion)
XFADE_MARGIN = 0.8                 # render.XFADE_MARGIN
NO_ACTING = ("atmosphere", "object", "human_static")
CAMERA = re.compile(r"\b(camera|dolly|dollies|pans?|tilts?|zooms?|push(es)? in|pulls? back|orbits?|arcs?|aerial|drone|tracking)\b")
HOLD = re.compile(r"\b(keeps?|stays?|remains?)\b[^,.;]*\b(still|motionless|unmoving)\b")
SPLIT = re.compile(r",|;|\.|\band then\b|\bthen\b|\band\b|\bwhile\b")
SEQUENCE = re.compile(r"\b(then|afterwards?|until|finally|one after another)\b")
ENTRY = re.compile(r"\b(appears?|appearing|enters?|entering|emerges?|arrives?|comes? (in|into|out)|walks? (in|into|up|toward|towards|through)|"
                   r"steps? (in|into|through)|pops? up|someone|another (person|man|woman|figure))\b")
# heavy acting only: a smile, a nod, a sip or breathing came out fine (a hybrid promo film, a song MV)
ACTING = re.compile(r"\b(laugh(s|ing)?|talk(s|ing)?|speaks?|gestur(es?|ing)|waves? (his|her|their)|frowns?|"
                    r"turns? (around|away|his|her)|looks? (up|down|around|at|back|away)|walk(s|ing)?|"
                    r"steps? (forward|back|out|in|into|through|onto)|hugs?|rubs?|scratch(es)?|pours?|picks? up|pats?|toss(es)?|"
                    r"writes|knocks?|claps?|bows?|stands? up|sits? down|shrugs?|rolls? (his|her) eyes)\b")
DET = re.compile(r"\b(?:the|a|an|his|her|their|its|another)\s+([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,2})")
AMBIENT = set("""camera lens frame scene shot view background foreground light lights lighting sunlight moonlight lamplight glow
shadow shadows reflection reflections highlight highlights surface steam mist fog haze smoke dust motes breeze wind air rain snow
sky clouds cloud water ripple ripples flame flames flicker sparkle sparkles leaves leaf petals warm soft slow slowly gentle gently
little slight slightly small subtle few whole same edge corner top side middle center centre left right front back distance end
moment while time way room floor wall walls ground ceiling smile laugh grin sigh nod expression gaze glance weight wake rhythm sound silence warmth
motion movement""".split())
ADJ = set("""strong cold cool warm evening morning night faint thin thick golden pale dim bright old young low high long short tiny
big large other first last next distant nearby two three four several many""".split())
# body parts and breath belong to whoever is in frame
BODY = set("""head hair face cheek cheeks lips lip mouth eyes eye eyelids brow shoulder shoulders chest breath breathing arm arms
hand hands finger fingers wrist wrists sleeve sleeves hem collar back""".split())


def _words(text):
    ws = set(re.findall(r"[a-z]+", text.lower()))                     # "lamp-lit" counts as "lamp" and "lit"
    return ws | {w[:-1] for w in ws if w.endswith("s")} | {w[:-2] for w in ws if w.endswith("es")}


def _expand(text, chars):
    return PLACEHOLDER.sub(lambda mo: str((chars.get(mo.group(1)) or {}).get("descriptor", mo.group(0))), text)


def motion_events(mp):
    """Independent things that move, camera moves and 'X keeps still' constraints not counted."""
    parts = [p.strip() for p in SPLIT.split(mp.lower()) if p and p.strip()]
    return [p for p in parts if not CAMERA.search(p) and not HOLD.search(p)]


def unseen_things(mp, image_text):
    """Noun phrases in the motion prompt none of whose words occur in the keyframe prompt (heuristic: a phrase that starts
    with an ambient word (camera, light, mist) or a body part is skipped)."""
    seen = _words(image_text)
    out = []
    for phrase in DET.findall(mp.lower()):
        ws = phrase.split()
        mods = [w in ADJ or "-" in w or w.endswith(("ed", "ing", "less", "ful", "ous", "y")) for w in ws]
        head = next((w for w, mod in zip(ws, mods) if not mod), ws[-1])
        if ws[0] in ("from", "of", "to") or head in AMBIENT or head.rstrip("s") in AMBIENT or head in BODY or head.rstrip("s") in BODY:
            continue
        if head not in seen and head.rstrip("s") not in seen and head not in out:
            out.append(head)
    return out


def check_motion(m, f):
    chars = m.get("characters") or {}
    hold = {cid for cid, c in chars.items() if c.get("hold_still")}
    by_id = {s.get("id"): s for s in m.get("shots", [])}
    for s in m.get("shots", []):
        mp = s.get("motion_prompt")
        if not isinstance(mp, str) or not mp.strip() or s.get("reuse_of") is not None or s.get("motion_tier") in ("camera", "overlay"):
            continue
        sid, low, cls = s.get("id"), mp.lower(), s.get("motion_class")
        ev = motion_events(mp)
        if len(ev) > MAX_EVENTS:
            f.add("WARN", "motion", f"shot {sid}: {len(ev)} simultaneous events in the motion prompt (> {MAX_EVENTS}); "
                                    "keep one main action plus the camera move")
        seq = sorted(set(x if isinstance(x, str) else x[0] for x in SEQUENCE.findall(low)))
        if seq:
            f.add("WARN", "motion", f"shot {sid}: multi-step sequence ({', '.join(seq)}); a ~5 s clip does one beat, split it across shots")
        entry = sorted({mo.group(0) for mo in ENTRY.finditer(low)})
        if entry:
            f.add("WARN", "motion", f"shot {sid}: something enters / appears ({', '.join(entry)}); Wan invents what is not in the "
                                    "keyframe: put it in the keyframe or cut to it")
        acting = sorted({mo.group(0) for mo in ACTING.finditer(low)})
        beats = [e for e in ev if ACTING.search(e)]
        if len(beats) > MAX_ACTING:
            f.add("WARN", "motion", f"shot {sid}: {len(beats)} acting beats ({'; '.join(b[:30] for b in beats[:3])}); "
                                    "Wan manages one per clip, more come out as nonsense")
        if acting and s.get("motion_tier") == "ai_env":
            f.add("WARN", "motion", f"shot {sid}: motion_tier ai_env (environment only) but the prompt has acting ({', '.join(acting[:3])})")
        elif acting and cls in NO_ACTING:
            f.add("WARN", "motion", f"shot {sid}: acting ({', '.join(acting[:4])}) but motion_class is {cls}; "
                                    "keep it to breathing / light / camera, or reclass it human_motion (lower success prior)")
        img = _expand(str(s.get("image_prompt", "")), chars)
        cf = s.get("continue_from")
        if cf in by_id:
            img += " " + _expand(str(by_id[cf].get("image_prompt", "")), chars)
        unseen = unseen_things(mp, img)
        if unseen:
            f.add("WARN", "motion", f"shot {sid}: the motion prompt names {unseen[:3]}, which the keyframe prompt does not show; "
                                    "Wan will have to invent it")
        used_hold = sorted(h for h in hold if "{" + h + "}" in str(s.get("image_prompt", "")))
        if used_hold and acting:
            f.add("WARN", "motion", f"shot {sid}: {used_hold} must hold still, and the motion prompt has acting "
                                    f"({', '.join(acting[:3])}); make sure it belongs to someone else, or move only camera and environment")
        spans = s.get("spans") or []
        if spans:
            need = max(sp["end"] - sp["start"] for sp in spans) + XFADE_MARGIN
            speed = WAN_CLIP_SECONDS / need
            animatable = cls in ("atmosphere", "object", "hands")
            already = animatable and need - XFADE_MARGIN > config.WAN_MAX_SECONDS + 1.0       # timeline.validate reports it
            if speed < MIN_SPEED and not already:
                f.add("WARN", "motion", f"shot {sid}: needs {need:.1f}s of clip, Wan makes {WAN_CLIP_SECONDS:.1f}s -> {speed:.2f}x slow "
                                        f"motion (min {MIN_SPEED}); split it, chain it (continue_from) or plan it as camera/overlay")


def check_files(m, f):
    root = m.get("root")
    if not root:
        return
    for s in m.get("shots", []):
        kf = s.get("keyframe")
        if kf and not os.path.exists(os.path.join(root, kf)):
            f.add("WARN", "files", f"shot {s.get('id')}: keyframe {kf} is missing on disk")
        c = s.get("clip") or {}
        if c.get("status") == "ok" and c.get("raw") and not os.path.exists(os.path.join(root, c["raw"])):
            f.add("WARN", "files", f"shot {s.get('id')}: approved clip {c['raw']} is missing on disk")


# ------------------------------------------------------------------ driver
def lint(m, files=True):
    f = Findings()
    check_schema(m, f)
    check_placeholders(m, f)
    check_negation(m, f)
    check_style_lock(m, f)
    check_timing(m, f)
    check_motion(m, f)
    if files:
        check_files(m, f)
    return f


def report(name, f):
    errs = [x for x in f if x[0] == "ERROR"]
    print(f"lint {name}: {len(errs)} ERROR, {len(f) - len(errs)} WARN")
    for level in ("ERROR", "WARN"):
        for lv, code, msg in f:
            if lv == level:
                print(f"  {lv:5s} [{code}] {msg}")
    return 1 if errs else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--manifest")
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    path = a.manifest or (config.manifest_path(a.slug) if a.slug else None)
    if not path or not os.path.exists(path):
        print(f"lint: no manifest at {path}")
        sys.exit(2)
    man = json.load(open(path, encoding="utf-8"))
    label = a.manifest or a.slug
    sys.exit(report(label, lint(man, files=not a.no_files)))
