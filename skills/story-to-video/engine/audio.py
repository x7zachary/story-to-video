"""TTS + mix for a manifest project.

  python audio.py <slug> tts   generate per-segment narration (edge-tts) with word boundaries; lexicon applied
  python audio.py <slug> mix   ambience + bells + per-shot SFX + narration -> audio/mix.wav (~ -16..-18 LUFS)

Per-shot `sfx` tags (list of "water", "fire", "wind") are synthesized with numpy; they are NOT verified by ear
(the agent cannot listen) - only their level is checked with ebur128.
"""
import asyncio
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

SR = 48000


# ------------------------------------------------------------------ TTS
def tts_text(m, text):
    for k, v in m["tts_replace"].items():
        assert len(k) == len(v), "replacements must keep length (subtitle timing)"
        text = text.replace(k, v)
    return text


async def _synth(m, seg, force):
    import edge_tts
    v = m["voices"][seg["speaker"]]
    out = os.path.join(m["root"], "audio")
    os.makedirs(out, exist_ok=True)
    mp3, wj = os.path.join(out, seg["id"] + ".mp3"), os.path.join(out, seg["id"] + ".words.json")
    if os.path.exists(mp3) and os.path.exists(wj) and not force:
        return
    for attempt in range(8):
        try:
            com = edge_tts.Communicate(tts_text(m, seg["text"]), v["voice"], rate=v["rate"], pitch=v["pitch"], boundary="WordBoundary")
            words, audio = [], bytearray()
            async for ch in com.stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    words.append({"text": ch["text"], "start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7})
            if not audio:
                raise RuntimeError("no audio")
            open(mp3, "wb").write(audio)
            json.dump(words, open(wj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"{seg['id']} {v['voice']} words={len(words)}", flush=True)
            return
        except Exception as e:
            print(f"{seg['id']} attempt {attempt}: {e}", flush=True)
            await asyncio.sleep(5 + 5 * attempt)
    raise SystemExit(f"TTS failed: {seg['id']}")


def tts(m, force=False):
    async def go():
        for seg in m["segments"]:
            if seg.get("speaker"):
                await _synth(m, seg, force)
    asyncio.run(go())


# ------------------------------------------------------------------ synthesis
def bandpass(x, lo, hi):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1 / (1 + (lo / np.maximum(f, 1e-3)) ** 4) / (1 + (f / hi) ** 4)
    return np.fft.irfft(spec * gain, n=len(x))


def bell(rng, dur=10.0, f0=98.0):
    t = np.arange(int(dur * SR)) / SR
    ratios = [0.5, 1.0, 1.183, 1.506, 2.0, 2.514, 2.662, 3.011, 4.166, 5.433]
    amps = [0.35, 1.0, 0.6, 0.45, 0.5, 0.3, 0.25, 0.2, 0.12, 0.08]
    decays = [9, 7, 5, 4.5, 3.5, 2.5, 2.2, 1.8, 1.2, 0.8]
    y = np.zeros_like(t)
    for r, a, d in zip(ratios, amps, decays):
        f = f0 * r
        y += a * np.exp(-t / d) * (np.sin(2 * np.pi * f * t) + 0.6 * np.sin(2 * np.pi * (f + 0.7) * t + 1.3))
    strike = rng.standard_normal(int(0.03 * SR)) * np.exp(-np.arange(int(0.03 * SR)) / (0.006 * SR))
    y[:len(strike)] += 0.4 * strike
    y *= np.minimum(1, t / 0.004)
    return y / np.abs(y).max()


def ambience(rng, n, endcard_start=None):
    t = np.arange(n) / SR
    y = np.zeros(n)
    for f, a, lfo in [(73.42, 0.5, 0.05), (110.0, 0.35, 0.07), (146.83, 0.2, 0.043), (220.0, 0.08, 0.061)]:
        env = 0.65 + 0.35 * np.sin(2 * np.pi * lfo * t + rng.uniform(0, 6.28))
        y += a * env * (np.sin(2 * np.pi * f * t) + np.sin(2 * np.pi * (f + 0.25) * t + 0.9))
    if endcard_start is not None:
        ramp = np.clip((t - (endcard_start - 6)) / 6, 0, 1)
        y += ramp * 0.12 * (np.sin(2 * np.pi * 293.66 * t) + 0.7 * np.sin(2 * np.pi * 440.0 * t))
    y /= np.abs(y).max()
    wind = bandpass(rng.standard_normal(n), 60.0, 400.0)
    swell = 0.5 + 0.5 * np.sin(2 * np.pi * 0.031 * t) * np.sin(2 * np.pi * 0.017 * t + 1)
    return 0.8 * y + 0.35 * wind / np.abs(wind).max() * swell


def sfx(kind, seconds, rng):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    if kind == "water":       # lapping: band noise with slow amplitude waves
        x = bandpass(rng.standard_normal(n), 250, 1800)
        return x / np.abs(x).max() * (0.55 + 0.45 * np.sin(2 * np.pi * 0.23 * t) ** 2)
    if kind == "fire":        # low rumble + sparse crackle clicks
        x = 0.4 * bandpass(rng.standard_normal(n), 40, 300)
        for c in rng.integers(0, n - 400, int(seconds * 9)):
            x[c:c + 300] += rng.standard_normal(300) * np.exp(-np.arange(300) / 40) * rng.uniform(0.3, 1.0)
        return x / np.abs(x).max()
    if kind == "wind":
        x = bandpass(rng.standard_normal(n), 80, 700)
        return x / np.abs(x).max() * (0.5 + 0.5 * np.sin(2 * np.pi * 0.11 * t + 1))
    raise ValueError(kind)


def mix(m, slug):
    tl = m["timeline"]
    root = m["root"]
    rng = np.random.default_rng(7)
    n = int((tl["total"] + 0.5) * SR)
    voice = np.zeros(n)
    for seg in tl["segments"]:
        raw = subprocess.check_output([config.FFMPEG, "-v", "error", "-i", os.path.join(root, "audio", seg["file"]), "-ac", "1",
                                       "-ar", str(SR), "-f", "f32le", "-"])
        x = np.frombuffer(raw, dtype=np.float32)
        i = int(seg["start"] * SR)
        voice[i:i + len(x)] += x[: n - i]
    voice /= np.abs(voice).max()
    amb = ambience(rng, n, tl["endcard"]["start"] if tl.get("endcard") else None) * 10 ** (-21 / 20)
    bells = np.zeros(n)
    b = bell(rng)
    for bt in tl["bells"]:
        i = int(bt * SR)
        bells[i:i + len(b)] += b[: n - i]
    bells *= 10 ** (-9 / 20)
    fx = np.zeros(n)
    srng = np.random.default_rng(11)         # separate stream: adding SFX never changes the ambience/bell noise
    for s in m["shots"]:
        for kind in s.get("sfx", []):
            for sp in s["spans"]:
                a, b2 = max(0.0, sp["start"] - 0.6), min(tl["total"], sp["end"] + 0.6)
                seg = sfx(kind, b2 - a, srng)
                ramp = np.minimum(1, np.minimum(np.arange(len(seg)), len(seg) - np.arange(len(seg))) / (0.6 * SR))
                i = int(a * SR)
                fx[i:i + len(seg)] += seg[: n - i] * ramp[: n - i]
    fx *= 10 ** (-27 / 20)
    out = voice + amb + bells + fx
    fi, fo = int(1.5 * SR), int(3.0 * SR)
    out[:fi] *= np.linspace(0, 1, fi)
    out[-fo:] *= np.linspace(1, 0, fo)
    out /= np.abs(out).max() * 1.12
    raw_path = os.path.join(root, "audio", "mix_raw.f32")
    out.astype(np.float32).tofile(raw_path)
    wav = os.path.join(root, "audio", "mix.wav")
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", raw_path,
                           "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", wav])
    os.remove(raw_path)
    print("wrote", wav)
    return wav


if __name__ == "__main__":
    slug, cmd = sys.argv[1], sys.argv[2]
    m = config.load_manifest(slug)
    if cmd == "tts":
        tts(m, "--force" in sys.argv)
    elif cmd == "mix":
        mix(m, slug)
