"""Tests for music.py on synthetic audio (no real song needed):

  python -X utf8 test_music.py

A 120 BPM click track with accents on every bar's first beat; at 12.0 s the arrangement changes (louder, brighter,
extra high-frequency content). music.analyze must recover the tempo, the first beat, and the change point.
"""
import os
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import music  # noqa: E402

SR = 44100


def synth(bpm, seconds, first_beat, change_at):
    n = int(seconds * SR)
    x = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    rng = np.random.default_rng(1)
    k = 0
    while True:
        t = first_beat + k * beat
        if t >= seconds - 0.2:
            break
        i = int(t * SR)
        L = int(0.09 * SR)
        env = np.exp(-np.arange(L) / (0.02 * SR))
        late = t >= change_at
        accent = 1.0 if k % 4 == 0 else 0.6
        f0 = 90.0 if k % 4 == 0 else 180.0
        tt = np.arange(L) / SR
        click = np.sin(2 * np.pi * f0 * tt) * env * accent * (0.5 if not late else 0.8)
        if late:                                                            # brighter, noisier arrangement after the change
            click += rng.normal(0, 0.25, L).astype(np.float32) * env * 0.5
            click += np.sin(2 * np.pi * 2600 * tt) * env * 0.25
        x[i:i + L] += click.astype(np.float32)
        k += 1
    if change_at < seconds:                                                 # sustained pad after the change
        t = np.arange(n) / SR
        pad = (0.12 * (np.sin(2 * np.pi * 330 * t) + np.sin(2 * np.pi * 495 * t) + np.sin(2 * np.pi * 660 * t))).astype(np.float32)
        x += np.where(t >= change_at, pad, 0.0).astype(np.float32)
    return x / (np.abs(x).max() + 1e-9) * 0.8


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def analysed(bpm=120, first=0.37, change=12.0, seconds=30.0):
    path = os.path.join(tempfile.mkdtemp(), "t.wav")
    write_wav(path, synth(bpm, seconds, first, change))
    return music.analyze(path, kernel_s=3.0)


def test_recovers_tempo_and_first_beat():
    m = analysed()
    assert abs(m["tempo"]["bpm"] - 120) < 0.6, m["tempo"]
    assert abs(m["tempo"]["first_beat_s"] - 0.37) < 0.03 or abs(m["tempo"]["first_beat_s"] - 0.87) < 0.03, m["tempo"]


def test_finds_the_arrangement_change():
    m = analysed()
    near = [s for s in m["sections"] if abs(s["time_s"] - 12.0) <= 1.2]
    assert near, m["sections"]
    assert near[0]["mean_db_after"] > near[0]["mean_db_before"], near[0]


def test_other_tempo():
    m = analysed(bpm=92, first=0.5, change=14.0)
    assert abs(m["tempo"]["bpm"] - 92) < 0.6 or abs(m["tempo"]["bpm"] - 184) < 1.2, m["tempo"]


def test_bar_phase_reported_with_confidence():
    m = analysed()
    bp = m["bar_phase"]
    assert 0 <= bp["best"] <= 3 and len(bp["scores"]) == 4 and "ambiguous" in bp, bp


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
