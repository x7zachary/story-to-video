"""Tests for lint.py / stylelock.py. No pytest in the venv, so this runs as a plain script:

  python -X utf8 test_lint.py

Each test seeds ONE mistake into an otherwise clean manifest and asserts lint catches it (and that the clean
manifest has no ERROR). The last test runs lint over the real projects: no ERROR allowed.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import lint  # noqa: E402
import stylelock  # noqa: E402


def clean():
    return {
        "slug": "t", "root": r"D:\nowhere", "title": "t",
        "style": {"image_style": "flat gouache picture-book art", "flashback_style": "faded gouache", "motion_suffix": "slow",
                  "wan_negative": "3d", "palette_en": ["celadon green", "ochre"], "palette_zh": ["青瓷绿", "赭石"],
                  "hard_constraints": "flat color fields, matte even light, generous empty space",
                  "banned_terms": ["soft glow", "bloom", "volumetric"]},
        "characters": {"BOY": {"descriptor": "a small boy in a celadon green jacket", "signature_color": "celadon green"}},
        "segments": [{"id": "s1", "shots": [1, 2]}],
        "shots": [
            {"id": 1, "name": "a", "type": "wide", "motion_class": "atmosphere", "importance": 3,
             "image_prompt": "{BOY} walks along a river bank at dawn", "motion_prompt": "mist drifts",
             "spans": [{"start": 0.0, "end": 5.0}]},
            {"id": 2, "name": "b", "type": "crop", "motion_class": "object", "importance": 2, "reuse_of": 1,
             "spans": [{"start": 5.0, "end": 9.0}]},
        ],
        "timeline": {"total": 9.0, "segments": [], "subtitles": []},
    }


def codes(findings, level):
    return {c for lv, c, _ in findings if lv == level}


def seeded(mutate):
    m = clean()
    mutate(m)
    return lint.lint(m, files=False)


def test_clean_manifest_has_no_errors():
    f = lint.lint(clean(), files=False)
    assert not codes(f, "ERROR"), f


def test_undefined_placeholder():
    f = seeded(lambda m: m["shots"][0].update(image_prompt="{GHOST} walks"))
    assert any(c == "placeholder" and "GHOST" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_banned_term_in_shot_prompt():
    f = seeded(lambda m: m["shots"][0].update(image_prompt="{BOY} stands in soft glow"))
    assert any(c == "style-lock" and "soft glow" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_signature_colour_missing_from_descriptor():
    f = seeded(lambda m: m["characters"]["BOY"].update(descriptor="a small boy in a jacket"))
    assert any(c == "style-lock" and "signature_color" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_negation_is_warned_in_english_and_chinese():
    f = seeded(lambda m: m["shots"][0].update(image_prompt="{BOY} eats lunch, no scallions on the plate"))
    assert any(c == "negation" and "scallions" in msg for lv, c, msg in f if lv == "WARN"), f
    f = seeded(lambda m: m["shots"][0].update(image_prompt="{BOY} 吃午饭，不要葱"))
    assert any(c == "negation" and "不要" in msg for lv, c, msg in f if lv == "WARN"), f


def test_negation_in_character_descriptor_is_attributed_to_the_character():
    f = seeded(lambda m: m["characters"]["BOY"].update(descriptor="a small boy in a celadon green jacket without a hat"))
    assert any(c == "negation" and "character BOY" in msg for lv, c, msg in f if lv == "WARN"), f


def test_reuse_chain_and_self_reuse():
    f = seeded(lambda m: m["shots"][1].update(reuse_of=2))
    assert any(c == "schema" and "itself" in msg for lv, c, msg in f if lv == "ERROR"), f

    def chain(m):
        m["shots"].append({"id": 3, "name": "c", "type": "crop", "motion_class": "object", "importance": 1, "reuse_of": 2,
                           "spans": [{"start": 9.0, "end": 10.0}]})
        m["timeline"]["total"] = 10.0
    f = seeded(chain)
    assert any(c == "schema" and "chain" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_unknown_motion_class_and_missing_tag():
    f = seeded(lambda m: m["shots"][0].update(motion_class="levitating"))
    assert any(c == "schema" and "levitating" in msg for lv, c, msg in f if lv == "ERROR"), f
    f = seeded(lambda m: m["shots"][0].pop("importance"))
    assert any(c == "schema" and "importance" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_segment_lists_missing_shot():
    f = seeded(lambda m: m["segments"][0].update(shots=[1, 99]))
    assert any(c == "schema" and "99" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_overlapping_and_gapped_spans():
    f = seeded(lambda m: m["shots"][1].update(spans=[{"start": 4.0, "end": 9.0}]))
    assert any(c == "timing" and "overlap" in msg for lv, c, msg in f if lv == "ERROR"), f
    f = seeded(lambda m: m["shots"][1].update(spans=[{"start": 6.0, "end": 9.0}]))
    assert any(c == "timing" and "gap" in msg for lv, c, msg in f if lv == "WARN"), f


def test_manifest_without_lock_fields_is_untouched_by_compose():
    m = clean()
    for k in ("palette_en", "palette_zh", "hard_constraints", "banned_terms"):
        m["style"].pop(k)
    assert stylelock.lock_text(m["style"]) == ""
    assert stylelock.style_text(m["style"]) == m["style"]["image_style"]
    assert stylelock.style_text(m["style"], flashback=True) == m["style"]["flashback_style"]


def test_lock_text_is_appended_after_style():
    st = clean()["style"]
    t = stylelock.style_text(st)
    assert t.startswith(st["image_style"]) and "celadon green, ochre" in t and "flat color fields" in t, t


def test_style_text_must_not_contain_its_own_banned_terms():
    f = seeded(lambda m: m["style"].update(image_style="flat gouache with a soft glow"))
    assert any(c == "style-lock" and "image_style" in msg for lv, c, msg in f if lv == "ERROR"), f


def test_shipped_presets_obey_their_own_ban_lists():
    import brief
    for pid in ("cinematic_realistic", "ink_wash", "storybook", "flat_gouache"):
        p = brief.load_preset(pid)
        f = lint.lint({"style": p, "shots": [], "characters": {}}, files=False)
        assert not [x for x in f if x[0] == "ERROR"], (pid, f)


def test_brief_lock_carries_lock_fields_into_manifest_and_prompts():
    import shutil
    import tempfile
    import brief
    import stills
    tmp = tempfile.mkdtemp()
    old_projects = config.PROJECTS
    config.PROJECTS = tmp
    try:
        story = os.path.join(tmp, "story.txt")
        open(story, "w", encoding="utf-8").write("x")
        brief.init("lockdemo", story, "demo")
        brief.lock("lockdemo", "flat_gouache", "16:9", "auto", palette_en="vermilion, jade, ink black")
        m = config.load_manifest("lockdemo")
        assert m["style"]["palette_en"] == ["vermilion", "jade", "ink black"], m["style"]      # film palette overrides preset
        assert m["style"]["hard_constraints"].startswith("Everything is drawn flat") or "flat 2D" in m["style"]["hard_constraints"]
        shot = {"id": 1, "image_prompt": "a fisherman at the shore"}
        prompt = stills.compose(m, shot)
        assert prompt.startswith("a fisherman at the shore. hand-painted 2D animation art"), prompt[:80]
        assert "vermilion, jade, ink black" in prompt and "flat 2D color fields" in prompt, prompt
        # an older preset locks exactly as before: no lock fields leak into the manifest
        brief.lock("lockdemo", "storybook", "16:9", "auto")
        m = config.load_manifest("lockdemo")
        assert set(m["style"]) == {"image_style", "flashback_style", "motion_suffix", "wan_negative"}, set(m["style"])
        assert stills.compose(m, shot) == "a fisherman at the shore. " + m["style"]["image_style"]
    finally:
        config.PROJECTS = old_projects
        shutil.rmtree(tmp, ignore_errors=True)


def test_partial_coverage_skips_gap_and_edge_warnings_but_not_overlaps():
    def partial(m):
        m["timeline"]["coverage"] = "partial"
        m["shots"][1].update(spans=[{"start": 20.0, "end": 24.0}])             # big gap before it, and the film ends at 30 s
        m["timeline"]["total"] = 30.0
    f = seeded(partial)
    assert not [x for x in f if x[1] == "timing" and ("gap" in x[2] or "first shot" in x[2] or "before the end" in x[2])], f
    f = seeded(lambda m: (m["timeline"].update(coverage="partial"), m["shots"][1].update(spans=[{"start": 4.0, "end": 9.0}])))
    assert any(c == "timing" and "overlap" in msg for lv, c, msg in f if lv == "ERROR"), f
    f = seeded(lambda m: m["shots"][1].update(spans=[{"start": 20.0, "end": 24.0}]))                 # same data, full coverage expected
    assert any(c == "timing" and "gap" in msg for lv, c, msg in f if lv == "WARN"), f


def motion_msgs(mp, **shot):
    def mut(m):
        m["shots"][0].update(motion_prompt=mp, **shot)
    return [msg for lv, c, msg in seeded(mut) if c == "motion"]


def test_clean_motion_prompt_has_no_motion_warning():
    assert not motion_msgs("mist drifts over the river, the camera slowly pushes in"), motion_msgs("mist drifts")


def test_motion_overload_sequence_and_acting_beats():
    msgs = motion_msgs("the boy laughs, rubs his neck, looks down, then looks up with a smile, the camera pushes in",
                       motion_class="human_static")
    assert any("acting beats" in x for x in msgs), msgs
    assert any("multi-step" in x for x in msgs), msgs
    assert any("motion_class is human_static" in x for x in msgs), msgs
    assert any("simultaneous events" in x for x in motion_msgs("mist drifts, leaves fall, water ripples, birds circle, smoke rises")), "events"


def test_motion_entry_and_unseen_object():
    assert any("enters / appears" in x for x in motion_msgs("a stranger walks into the frame")), "entry"
    msgs = motion_msgs("the cat walks along the bank, the camera pans")
    assert any("'cat" in x for x in msgs), msgs
    assert not [x for x in motion_msgs("the boy's sleeves flutter, the river glitters") if "names" in x]   # body parts / things in the keyframe


def test_hold_still_character_and_slow_motion():
    def mut(m):
        m["characters"]["BOY"]["hold_still"] = True
        m["shots"][0].update(motion_prompt="the boy waves his hand", spans=[{"start": 0.0, "end": 5.0}])
    assert any("must hold still" in msg for lv, c, msg in seeded(mut) if c == "motion")
    msgs = motion_msgs("mist drifts", motion_class="human_static", spans=[{"start": 0.0, "end": 7.0}])
    assert any("slow" in x and "motion" in x for x in msgs), msgs


def test_camera_and_overlay_tiers_are_not_motion_checked():
    assert not motion_msgs("a stranger walks into the frame", motion_tier="overlay")


def test_motion_tier_and_overlay_schema():
    f = seeded(lambda m: m["shots"][0].update(motion_tier="wiggle"))
    assert any(c == "schema" and "motion_tier" in msg for lv, c, msg in f if lv == "ERROR"), f
    f = seeded(lambda m: m["shots"][0].update(motion_tier="overlay"))
    assert any(c == "schema" and "no overlay spec" in msg for lv, c, msg in f if lv == "ERROR"), f
    f = seeded(lambda m: m["shots"][0].update(motion_tier="overlay", overlay={"type": "fog"}))
    assert any(c == "schema" and "overlay" in msg for lv, c, msg in f if lv == "ERROR"), f
    f = seeded(lambda m: m["shots"][0].update(motion_tier="overlay", overlay=[{"type": "flies", "region": [0.3, 0.3, 0.7, 0.7]}]))
    assert not codes(f, "ERROR"), f
    assert any("ai_env" in x for x in motion_msgs("the boy waves his hand", motion_tier="ai_env"))


def test_shipped_examples_are_clean():
    import glob
    paths = glob.glob(os.path.join(config.PLUGIN_ROOT, "examples", "*", "manifest.example.json"))
    assert paths, "no example manifests found"
    for p in paths:
        f = lint.lint(json.load(open(p, encoding="utf-8")), files=False)
        assert not f, (p, f)                                   # the examples must not even warn
    print(f"  (examples checked: {len(paths)})")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as e:
            failed += 1
            print("FAIL", name, "->", str(e)[:300])
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
