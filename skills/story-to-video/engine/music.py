"""Music map: tempo, beat grid, loudness curve and section-boundary CANDIDATES for a song.

  python music.py <audio> [--out map.json] [--bpm N] [--kernel-s 4] [--all] [--ts]

Why: films cut to music (a brand promo, a song MV) need a beat grid and a section list. This used to be
re-written ad hoc for every project. The map is a starting point, not a verdict:
  * tempo can come out at half / double speed -> `tempo.alternatives` lists them, the caller picks
  * which beat is the BAR's first beat is a genuinely weak signal -> `bar_phase` reports a confidence;
    when `ambiguous` is true a human (or the lyrics / the arrangement) has to decide
  * `sections` are timbre-change candidates snapped to beats; expect a few misses and a few extras

Output JSON keys: file, duration_s, tempo{bpm, beat_s, first_beat_s, alternatives[]}, bar_phase{best, scores[], confidence, ambiguous},
loudness_db_per_beat[], sections[{beat, time_s, bar, bar_time_s, novelty, strong, mean_db_before, mean_db_after}].
--ts prints `BEAT` and `T0` constants for a Remotion timeline.ts.

numpy only (no librosa), so it runs in the engine's venv without installs.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

SR, WIN, HOP = 22050, 1024, 256
FPS = SR / HOP
BPM_LO, BPM_HI, BPM_PRIOR, PRIOR_SIGMA_OCT = 55.0, 170.0, 100.0, 0.75
N_BANDS = 24
STRONG = 0.4          # novelty at or above this = 'strong' candidate (checked on two real songs, see test notes in the docs)


def decode(path):
    raw = subprocess.check_output([config.FFMPEG, "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"])
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def stft_mag(x):
    n = (len(x) - WIN) // HOP + 1
    win = np.hanning(WIN).astype(np.float32)
    out = np.empty((n, WIN // 2 + 1), np.float32)
    for a in range(0, n, 2048):
        b = min(n, a + 2048)
        idx = np.arange(a, b)[:, None] * HOP + np.arange(WIN)[None, :]
        out[a:b] = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    return out


def onset_flux(S, lo_bin=0, hi_bin=None):
    L = np.log1p(S[:, lo_bin:hi_bin] * 10)
    f = np.maximum(0, np.diff(L, axis=0)).sum(1)
    return np.concatenate([[0.0], f])


def zscore(v):
    return (v - v.mean()) / (v.std() + 1e-9)


def tempo_candidates(flux):
    n = len(flux)
    f = np.fft.rfft(flux, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    ac = ac / (ac[0] + 1e-9)
    lags = np.arange(int(FPS * 60 / BPM_HI), int(FPS * 60 / BPM_LO) + 1)
    bpm = FPS * 60 / lags
    prior = np.exp(-0.5 * (np.log2(bpm / BPM_PRIOR) / PRIOR_SIGMA_OCT) ** 2)
    score = ac[lags] * prior
    order = np.argsort(-score)
    picked = []
    for i in order:
        if all(abs(bpm[i] / b[0] - 1) > 0.04 for b in picked):
            picked.append((float(bpm[i]), float(ac[lags[i]]), float(score[i]), int(lags[i])))
        if len(picked) == 4:
            break
    return picked


def refine_grid(flux, lag):
    """Comb search around the autocorrelation lag: best period (frames/beat) and phase (frames) over the whole track."""
    sm = np.convolve(flux, np.hanning(5) / np.hanning(5).sum(), mode="same")
    x = np.arange(len(sm))
    best = (-1e9, lag, 0.0)
    for per in np.linspace(lag * 0.97, lag * 1.03, 121):
        for ph in np.linspace(0, per, 60, endpoint=False):
            pos = np.arange(ph, len(sm) - 1, per)
            s = np.interp(pos, x, sm).mean()
            if s > best[0]:
                best = (s, per, ph)
    return best[1], best[2]


def analyze(path, kernel_s=4.0, bpm=None):
    x = decode(path)
    S = stft_mag(x)
    flux = zscore(onset_flux(S))
    cands = tempo_candidates(flux)
    bpm0, _, _, lag = cands[0]
    if bpm:                                    # caller knows the tempo (fixes half / double-time picks)
        bpm0, lag = float(bpm), FPS * 60 / float(bpm)
    per, ph = refine_grid(flux, lag)
    beat_s = per / FPS
    dur = len(x) / SR
    first = ph / FPS
    nb = int((dur - first) / beat_s)
    beat_t = first + beat_s * np.arange(nb)

    # loudness per beat
    db = []
    for k in range(nb):
        a, b = int(beat_t[k] * SR), int((beat_t[k] + beat_s) * SR)
        seg = x[a:b]
        db.append(round(float(20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)), 1) if len(seg) else -90.0)
    db = np.array(db)

    # which of the 4 beats starts the bar: low-band (< 150 Hz) onsets
    low = zscore(onset_flux(S, 1, 8))
    lo_at = np.interp(beat_t * FPS, np.arange(len(low)), low)
    sc = np.array([lo_at[p::4].mean() for p in range(4)])
    srt = np.sort(sc)[::-1]
    conf = float((srt[0] - srt[1]) / (abs(srt[0]) + 1e-9))
    bar_best = int(np.argmax(sc))

    # beat-synchronous timbre -> self-similarity -> Foote novelty (same-half similarity minus cross-boundary similarity)
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    edges = np.geomspace(60, 9000, N_BANDS + 1)
    band = [(freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(N_BANDS)]
    F = np.zeros((nb, N_BANDS), np.float32)
    for k in range(nb):
        a, b = int(beat_t[k] * FPS), max(int(beat_t[k] * FPS) + 1, int((beat_t[k] + beat_s) * FPS))
        seg = np.log1p(S[a:b].mean(0) * 50)
        F[k] = [seg[m].mean() for m in band]
    F = (F - F.mean(0)) / (F.std(0) + 1e-6)
    Fn = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    SSM = Fn @ Fn.T
    K = max(2, min(int(round(kernel_s / beat_s)), nb // 4))          # kernel half-width: ~kernel_s seconds whatever the tempo
    sg = np.r_[-np.ones(K), np.ones(K)]
    g = np.outer(sg, sg)
    nov = np.zeros(nb)
    for i in range(K, nb - K):
        nov[i] = (SSM[i - K:i + K, i - K:i + K] * g).sum()
    nov = np.maximum(nov, 0)
    nov = nov / (nov.max() + 1e-9)
    gap = max(2, int(round(0.9 * kernel_s / beat_s)))                 # keep candidates about a kernel apart
    peaks = []
    for i in np.argsort(-nov):
        if nov[i] < 0.25:
            break
        if all(abs(i - j) >= gap for j in peaks):
            peaks.append(int(i))
    peaks.sort()

    sections = []
    for i in peaks:
        bar = int(round((i - bar_best) / 4))
        bar_beat = bar * 4 + bar_best
        sections.append({
            "beat": i, "time_s": round(float(beat_t[i]), 3), "bar": bar,
            "bar_time_s": round(float(first + beat_s * bar_beat), 3), "novelty": round(float(nov[max(0, i - K // 2):i + K // 2 + 1].max()), 2),
            "strong": bool(nov[max(0, i - K // 2):i + K // 2 + 1].max() >= STRONG),
            "mean_db_before": round(float(db[max(0, i - 8):i].mean()), 1), "mean_db_after": round(float(db[i:i + 8].mean()), 1)})
    return {
        "file": os.path.abspath(path), "duration_s": round(dur, 3),
        "tempo": {"bpm": round(60 / beat_s, 2), "beat_s": round(beat_s, 4), "first_beat_s": round(first, 3),
                  "alternatives": [{"bpm": round(c[0], 1), "autocorr": round(c[1], 3)} for c in cands[1:]]},
        "bar_phase": {"best": bar_best, "scores": [round(float(s), 2) for s in sc], "confidence": round(conf, 2), "ambiguous": conf < 0.1},
        "loudness_db_per_beat": db.tolist(), "sections": sections,
    }


def summary(m, show_all=False):
    t = m["tempo"]
    print(f"{os.path.basename(m['file'])}: {m['duration_s']}s")
    print(f"  tempo {t['bpm']} BPM (beat {t['beat_s']}s), first beat {t['first_beat_s']}s; other candidates: "
          + ", ".join(f"{a['bpm']} BPM" for a in t["alternatives"][:3]))
    bp = m["bar_phase"]
    print(f"  first beat of a bar = beat #{bp['best']} of the 4 (scores {bp['scores']}, confidence {bp['confidence']}"
          + (", AMBIGUOUS: confirm by ear / lyrics)" if bp["ambiguous"] else ")"))
    shown = [s for s in m["sections"] if show_all or s["strong"]]
    print(f"  section candidates, {'all' if show_all else 'strong only'} ({len(shown)} of {len(m['sections'])}); time | bar | novelty | dB before -> after:")
    for s in shown:
        print(f"    {s['time_s']:7.2f}s | bar {s['bar']:3d} @ {s['bar_time_s']:7.2f}s | {s['novelty']:.2f} | {s['mean_db_before']:6.1f} -> {s['mean_db_after']:6.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out")
    ap.add_argument("--kernel-s", type=float, default=4.0, help="half-width of the novelty kernel in seconds")
    ap.add_argument("--ts", action="store_true", help="print BEAT / T0 constants for Remotion")
    ap.add_argument("--bpm", type=float, help="force the tempo (use when the detector picked half / double speed)")
    ap.add_argument("--all", action="store_true", help="list weak section candidates too")
    a = ap.parse_args()
    m = analyze(a.audio, a.kernel_s, a.bpm)
    out = a.out or os.path.splitext(a.audio)[0] + ".musicmap.json"
    json.dump(m, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(m, a.all)
    print(f"  wrote {out}")
    if a.ts:
        print(f"\nexport const BEAT = {m['tempo']['beat_s']};\nexport const T0 = {m['tempo']['first_beat_s']};  // first detected beat, NOT necessarily a bar start")
