"""Tests for pipeline.py estimate / continue_from chaining and lint's chain checks. No GPU, no ComfyUI:

  python -X utf8 test_chain.py

The upgrade loop is exercised with a fake Wan attempt. record_outcome is stubbed so the real priors.json is never touched.
"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import lint  # noqa: E402
import pipeline  # noqa: E402


def shot(i, cls="object", imp=3, cont=None, start=0.0, clip=None, **kw):
    s = {"id": i, "name": f"s{i}", "type": "still", "motion_class": cls, "importance": imp, "image_prompt": "x",
         "motion_prompt": "m", "keyframe": f"images/shot_{i:02d}.png", "spans": [{"start": start, "end": start + 5.0}]}
    if cont is not None:
        s["continue_from"] = cont
    if clip:
        s["clip"] = clip
    s.update(kw)
    return s


def manifest(shots, root=r"D:\nowhere"):
    return {"slug": "t", "root": root, "title": "t", "style": {"wan_negative": "n", "motion_suffix": "s", "image_style": "i", "flashback_style": "f"},
            "characters": {}, "shots": shots, "timeline": {"total": 30.0}}


# ------------------------------------------------------------------ estimate
def test_expected_minutes_formula():
    assert abs(pipeline.expected_minutes(1.0, 10) - 10.0) < 1e-9                    # certain success: one attempt
    assert abs(pipeline.expected_minutes(0.0, 10) - (10 + 10 + 10 * pipeline.REDUCED_COST)) < 1e-9   # always fails: all 3 attempts
    assert abs(pipeline.expected_minutes(0.5, 10) - (10 * 1.5 + 10 * pipeline.REDUCED_COST * 0.25)) < 1e-9


def test_estimate_sorts_cumulates_and_flags_budget():
    m = manifest([shot(1, "object", 5), shot(2, "human_static", 4), shot(3, "atmosphere", 2)])
    e = pipeline.estimate(m, 0.0, 30.0)
    assert [r["shot"] for r in e["rows"]] == sorted([r["shot"] for r in e["rows"]], key=lambda i: -next(r["score"] for r in e["rows"] if r["shot"] == i))
    cums = [r["cumulative_min"] for r in e["rows"]]
    assert cums == sorted(cums) and abs(e["total_min"] - cums[-1]) < 0.11
    assert e["fit_in_budget"] == sum(c <= 30.0 for c in cums)


def test_estimate_skips_finished_and_reports_blocked():
    m = manifest([shot(1, clip={"status": "needs_review", "attempts": []}), shot(2, cont=1), shot(3)])
    e = pipeline.estimate(m)
    assert [r["shot"] for r in e["rows"]] == [3], e["rows"]            # 1 is waiting for review, 2 waits for 1
    assert e["blocked"] == [2], e["blocked"]


# ------------------------------------------------------------------ chain_source / rank
def test_chain_modes():
    ok = {"status": "ok", "attempts": []}
    cases = [
        (None, "none"), ({"status": "ok_unreviewed"}, "chain"), ({"status": "ok"}, "chain"),
        ({"status": "failed"}, "fallback"), ({"status": "needs_review"}, "blocked"), ({"status": "running"}, "blocked"), ("no-clip", "blocked"),
    ]
    for clip, want in cases:
        src = shot(1) if clip == "no-clip" else shot(1, clip=clip) if clip else shot(1)
        dep = shot(2, cont=1 if clip is not None else None)
        m = manifest([src, dep])
        mode, _ = pipeline.chain_source(m, dep)
        assert mode == want, (clip, mode, want)
    m = manifest([shot(2, cont=99)])
    assert pipeline.chain_source(m, m["shots"][0])[0] == "fallback"            # dangling reference: do not wait forever


def test_rank_hides_blocked_shots_and_shows_them_once_unlocked():
    m = manifest([shot(1, imp=1), shot(2, imp=5, cont=1)])
    assert [r[1] for r in pipeline.rank(m)] == [1]
    m["shots"][0]["clip"] = {"status": "ok_unreviewed", "attempts": []}
    assert [r[1] for r in pipeline.rank(m)] == [2]


# ------------------------------------------------------------------ real frame extraction
def make_clip(path, frames=10):
    # frame N has uniform luma 20*N (geq), 24 fps
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=24:d={frames / 24}",
                           "-vf", "geq=lum='N*20':cb=128:cr=128,format=yuv420p", "-c:v", "libx264", "-crf", "10", path])


def luma(png):
    from PIL import Image
    import numpy as np
    return float(np.asarray(Image.open(png).convert("L"), dtype=np.float32).mean())


def test_last_frame_png_respects_keep_frames():
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "clips", "raw"))
        make_clip(os.path.join(tmp, "clips", "raw", "shot_01.mp4"), 10)
        m = manifest([], root=tmp)
        src = shot(1, clip={"status": "ok", "raw": "clips/raw/shot_01.mp4", "keep_frames": 7, "attempts": []})
        got = luma(pipeline.last_frame_png(m, src, os.path.join(tmp, "f.png")))
        assert abs(got - 20 * 6) < 12, got                                       # keep_frames=7 -> last kept frame is #6 (luma ~120)
        src["clip"]["keep_frames"] = 10
        got = luma(pipeline.last_frame_png(m, src, os.path.join(tmp, "f2.png")))
        assert abs(got - 20 * 9) < 12, got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ upgrade loop with a fake Wan attempt
def run_upgrade(source_result, fast=False, want_flags=False):
    tmp = tempfile.mkdtemp()
    old_projects, old_run, old_rec, old_start, old_tile = config.PROJECTS, pipeline.run_attempt, pipeline.record_outcome, pipeline.comfy.start, pipeline.qc.tile
    try:
        config.PROJECTS = tmp
        root = os.path.join(tmp, "t")
        os.makedirs(os.path.join(root, "clips", "raw"))
        fake = os.path.join(root, "fake.mp4")
        open(fake, "wb").write(b"x")
        m = manifest([shot(1, imp=1, start=0.0), shot(2, imp=5, cont=1, start=6.0), shot(3, imp=3, start=12.0)], root=root)
        m["slug"] = "t"
        config.save_manifest("t", m)
        calls = []
        fast_flags = []

        def fake_attempt(mm, sh, n, reserve, fast=False, model=None):
            mode, _ = pipeline.chain_source(mm, sh)
            calls.append((sh["id"], n, mode))
            fast_flags.append(fast)
            res = source_result if sh["id"] == 1 else "needs_review"
            rec = {"n": n, "result": res, "frames": 121, "minutes": 0.1}
            return rec, fake

        pipeline.run_attempt = fake_attempt
        pipeline.record_outcome = lambda *a, **k: None                           # never write the real priors.json
        pipeline.comfy.start = lambda *a, **k: None
        pipeline.qc.tile = lambda *a, **k: "tile.jpg"
        pipeline.upgrade("t", 600, 0, [], True, fast)
        return (calls, fast_flags) if want_flags else calls
    finally:
        config.PROJECTS, pipeline.run_attempt, pipeline.record_outcome = old_projects, old_run, old_rec
        pipeline.comfy.start, pipeline.qc.tile = old_start, old_tile
        shutil.rmtree(tmp, ignore_errors=True)


def test_upgrade_runs_chained_shot_after_its_source_and_starts_from_the_chain():
    calls = run_upgrade("needs_review")
    ids = [c[0] for c in calls]
    assert ids.index(1) < ids.index(2), calls                                     # the high-importance chained shot waited for shot 1
    assert (2, 1, "chain") in calls, calls
    assert (3, 1, "none") in calls, calls


def test_upgrade_falls_back_to_own_keyframe_when_source_fails():
    calls = run_upgrade("fail_static")
    assert [c for c in calls if c[0] == 1] == [(1, 1, "none"), (1, 2, "none"), (1, 3, "none")], calls
    assert (2, 1, "fallback") in calls, calls


# ------------------------------------------------------------------ lint chain checks
def chain_findings(mutate):
    m = manifest([shot(1, start=0.0), shot(2, start=6.0, cont=1), shot(3, start=12.0)])
    mutate(m)
    return lint.lint(m, files=False)


def has(f, level, text):
    return any(lv == level and text in msg for lv, c, msg in f)


def test_lint_accepts_a_valid_chain():
    f = chain_findings(lambda m: None)
    assert not [x for x in f if x[0] == "ERROR"], f


def test_lint_rejects_bad_chains():
    assert has(chain_findings(lambda m: m["shots"][1].update(continue_from=99)), "ERROR", "is not a shot")
    assert has(chain_findings(lambda m: m["shots"][1].update(continue_from=2)), "ERROR", "itself")
    assert has(chain_findings(lambda m: m["shots"][2].update(reuse_of=1, continue_from=1)), "ERROR", "crop")

    def loop(m):
        m["shots"][0].update(continue_from=2)
    assert has(chain_findings(loop), "ERROR", "loops"), chain_findings(loop)

    def onto_crop(m):
        m["shots"][0].update(reuse_of=3, image_prompt=None)
        m["shots"][2].pop("reuse_of", None)
    assert has(chain_findings(onto_crop), "ERROR", "crop"), chain_findings(onto_crop)


def test_lint_warns_on_long_chain_and_wrong_time_order():
    def long(m):
        m["shots"].append(shot(4, start=18.0, cont=2))
        m["shots"].append(shot(5, start=24.0, cont=4))
        m["timeline"]["total"] = 30.0
    assert has(chain_findings(long), "WARN", "chain of 3 links"), chain_findings(long)
    assert has(chain_findings(lambda m: m["shots"][1].update(spans=[{"start": 0.0, "end": 5.0}])), "WARN", "appears before"), "order"


# ------------------------------------------------------------------ --fast profile
def test_fast_profile_params_and_costs():
    m = manifest([shot(1, "atmosphere")])                                # environment -> 5B (see choose_model)
    s = m["shots"][0]
    q1 = pipeline.attempt_params(s, m, 1, 0, True)
    assert (q1["w"], q1["h"], q1["frames"], q1["steps"]) == pipeline.FAST_PROFILE == (960, 544, 81, 16), q1
    d1 = pipeline.attempt_params(s, m, 1, 0, False)
    assert (d1["w"], d1["h"], d1["frames"], d1["steps"]) == (1280, 704, 121, 20), d1                  # default unchanged
    d3 = pipeline.attempt_params(s, m, 3, 0, False)
    assert (d3["w"], d3["frames"]) == (960, 81), d3                                                  # retry chain still drops to it
    assert abs(pipeline.expected_minutes(0.5, 3.4, True) - 3.4 * 1.75) < 1e-9                         # every attempt costs the same
    assert pipeline.est_minutes(m, True) == pipeline.FAST_DEFAULT_MIN
    m["shots"][0]["clip"] = {"status": "failed", "attempts": [{"dtype": "fp8", "res": "960x544", "minutes": 3.3},
                                                               {"dtype": "fp8", "res": "1280x704", "minutes": 13.5}]}
    assert pipeline.est_minutes(m, True) == 3.3                      # only the 960x544 attempt counts for the fast estimate
    assert pipeline.est_minutes(m) == 13.5                           # the default estimate is the unchanged median of all attempts


def test_frames_follow_the_shot_length():
    m = manifest([shot(1, "atmosphere"), shot(2, start=6.0, reuse_of=1)])
    s = m["shots"][0]
    s["spans"] = [{"start": 0.0, "end": 2.0}]
    m["shots"][1]["spans"] = [{"start": 6.0, "end": 8.0}]
    f = pipeline.attempt_params(s, m, 1, 0, False)["frames"]
    assert f == 69 and (f - 1) % 4 == 0, f                         # (2.0 + 0.8 margin) s * 24 = 67.2 -> 4n+1 grid -> 69
    m["shots"][1]["spans"] = [{"start": 6.0, "end": 9.5}]              # a crop reusing the clip needs it longer
    assert pipeline.attempt_params(s, m, 1, 0, False)["frames"] == 105
    assert pipeline.attempt_params(s, m, 1, 0, True)["frames"] == 81    # capped by the fast profile
    assert [r[1] for r in pipeline.rank(m)] == [1]                      # the crop itself is never queued


def test_model_is_chosen_per_shot():
    env, obj, ppl = shot(1, "atmosphere"), shot(2, "object"), shot(3, "human_static")
    m = manifest([env, obj, ppl])
    pick = lambda s, **k: pipeline.choose_model(m, s, **k)[0]                # noqa: E731
    assert (pick(env), pick(obj), pick(ppl)) == ("5b", "a14b", "a14b")
    assert pick(shot(4, "atmosphere", motion_prompt="a woman walks along the shore")) == "a14b"   # acting in the prompt
    assert pick(shot(5, "human_motion", wan_model="5b")) == "5b"                                  # the shot says so
    assert pick(ppl, model="5b") == "5b" and pick(env, model="a14b") == "a14b"                    # --model forces
    assert pick(ppl, fast=True) == "5b"                                                           # --fast = 5B fast profile
    failed = shot(6, "atmosphere", clip={"status": "failed", "attempts": [{"model": "5b", "result": "fail_numeric"}]})
    rejected = shot(7, "atmosphere", clip={"status": "failed", "attempts": [{"result": "needs_review", "review": {"verdict": "reject"}}]})
    timeout = shot(8, "atmosphere", clip={"status": "failed", "attempts": [{"model": "5b", "result": "fail_timeout"}]})
    assert (pick(failed), pick(rejected), pick(timeout)) == ("a14b", "a14b", "5b")                # escalate, but not on a stall
    m["wan_model"] = "5b"
    assert pick(ppl) == "5b"                                                                      # a project can pin it
    p = pipeline.attempt_params(ppl, manifest([ppl]), 1)
    assert (p["model"], p["fps"], p["w"], p["h"]) == ("a14b", 16, 848, 480), p


def test_upgrade_passes_fast_to_every_attempt():
    calls, flags = run_upgrade("needs_review", fast=True, want_flags=True)
    assert flags and all(flags), flags
    calls, flags = run_upgrade("needs_review", fast=False, want_flags=True)
    assert flags and not any(flags), flags


def test_estimate_fast_is_cheaper():
    m = manifest([shot(1, "object", 5), shot(2, "human_static", 4)])
    slow, fast = pipeline.estimate(m, 0.0, 600.0, model="5b"), pipeline.estimate(m, 0.0, 600.0, True)
    assert fast["total_min"] < slow["total_min"] / 2, (fast["total_min"], slow["total_min"])


def test_project_palette_is_not_reported_as_drift():
    import tempfile
    import brief
    tmp = tempfile.mkdtemp()
    old = config.PROJECTS
    config.PROJECTS = tmp
    try:
        story = os.path.join(tmp, "s.txt")
        open(story, "w", encoding="utf-8").write("x")
        brief.init("pal", story, "pal")
        brief.lock("pal", "flat_gouache", "16:9", "auto", palette_en="red, jade")
        f = lint.lint(config.load_manifest("pal"), files=False)
        assert not [x for x in f if x[1] == "style-lock" and "differs" in x[2]], f
        brief.lock("pal", "flat_gouache", "16:9", "auto")
        m = config.load_manifest("pal")
        m["style"]["palette_en"] = ["something", "else"]                                           # edited by hand, no 'project' mark
        f = lint.lint(m, files=False)
        assert any(x[1] == "style-lock" and "palette_en" in x[2] for x in f), f
    finally:
        config.PROJECTS = old
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as e:
            failed += 1
            print("FAIL", name, "->", str(e)[:400])
        except Exception as e:                                                    # a crash is a failure too
            failed += 1
            print("ERROR", name, "->", type(e).__name__, str(e)[:400])
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
