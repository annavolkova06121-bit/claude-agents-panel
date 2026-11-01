#!/usr/bin/env python3
"""gen_sound.py: черновой «сочный» звук для цикла «плюха слизи» (numpy, без внешних файлов).
Все звуки синтезируются: удар, шлепок, хлюпы, всплеск, стекание, капли, пузырьки.
Петля 4,0 с свёрнута по кругу: хвост удара в конце продолжается в начале ролика."""
import math, wave
import numpy as np

SR = 44100
rng = np.random.default_rng(5)


def t_(n): return np.arange(n) / SR
def noise(n): return rng.standard_normal(n).astype(np.float32)


def lp(x, fc):
    """1-полюсный ФНЧ; fc может быть массивом (развёртка)."""
    fc = np.broadcast_to(np.asarray(fc, np.float32), x.shape)
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x)
    s = 0.0
    for i in range(len(x)):
        s = (1 - a[i]) * x[i] + a[i] * s
        y[i] = s
    return y


def hp(x, fc): return x - lp(x, fc)


def bp(x, lo, hi): return lp(hp(x, lo), hi)


def env(n, a=0.002, tau=0.1):
    t = t_(n)
    e = np.exp(-t / tau)
    att = np.minimum(1, t / max(a, 1e-4))
    return (e * att).astype(np.float32)


def sine_glide(n, f0, f1, tau_f=0.05):
    t = t_(n)
    f = f1 + (f0 - f1) * np.exp(-t / tau_f)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph).astype(np.float32)


def thump(n):
    return sine_glide(n, 95, 42, 0.06) * env(n, 0.002, 0.16)


def slap(n):
    return bp(noise(n), 700, 3200) * env(n, 0.001, 0.035)


def body(n):
    return lp(noise(n), 900) * env(n, 0.002, 0.07) * 3


def bloop(n, f0=950, f1=320, tau=0.07):
    return sine_glide(n, f0, f1, 0.03) * env(n, 0.002, tau)


def pop(n=300):
    return bp(noise(n), 1800, 6000) * env(n, 0.0005, 0.006) * 4


def squelch(dur, density, fmin=250, fmax=1200, amp=.5):
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    cnt = int(dur * density)
    for _ in range(cnt):
        p = rng.random() ** 1.7
        i = int(p * n)
        L = int(SR * rng.uniform(0.012, 0.03))
        f0 = rng.uniform(fmin, fmax)
        s = sine_glide(L, f0 * 0.8, f0 * 1.5, 0.01) * env(L, 0.001, rng.uniform(0.006, 0.016))
        s = s[:max(0, min(L, n - i))]
        out[i:i + len(s)] += s * amp * rng.uniform(0.4, 1.0) * (1 - 0.6 * p)
    return out


def add(buf, x, t0, gain=1.0, wrap=True):
    i0 = int(round(t0 * SR))
    n = len(buf)
    for k in range(len(x)):
        j = i0 + k
        if j >= n:
            if not wrap: break
            j %= n
        buf[j] += x[k] * gain
    return buf


def add_fast(buf, x, t0, gain=1.0, wrap=True):
    n = len(buf)
    i0 = int(round(t0 * SR)) % n if wrap else int(round(t0 * SR))
    end = i0 + len(x)
    if end <= n:
        buf[i0:end] += x * gain
    else:
        k = n - i0
        buf[i0:] += x[:k] * gain
        if wrap:
            rest = x[k:]
            buf[:len(rest)] += rest * gain
    return buf


def whoosh(dur=0.42):
    n = int(dur * SR)
    t = t_(n) / dur
    fc = 180 + (5200 - 180) * t ** 2
    x = lp(noise(n), fc) * (t ** 2.2)
    return x * 2.4


def splat_event():
    """удар + шлёпок + хлюпы + брызги, ~1,3 с"""
    n = int(1.3 * SR)
    out = np.zeros(n, np.float32)
    out += thump(n) * 1.0
    out += body(n) * 0.7
    out += slap(n) * 0.6
    sq = squelch(0.55, 120, 260, 1300, 0.55)
    out[:len(sq)] += sq
    sp = hp(noise(n), 4800) * env(n, 0.004, 0.16) * 0.35
    out += sp
    gl = lp(noise(n), 320) * env(n, 0.02, 0.35) * 1.5
    out += gl * 0.5
    return out


def slide_event(dur=1.1):
    n = int(dur * SR)
    t = t_(n) / dur
    am = 0.55 + 0.45 * np.sin(2 * np.pi * 6.5 * t_(n) + 1)
    base = lp(noise(n), 260 + 340 * np.sin(np.pi * t)) * np.sin(np.pi * t) ** 1.2 * am * 3.2
    out = base.astype(np.float32)
    sq = squelch(dur, 22, 280, 900, 0.22)
    out[:len(sq)] += sq
    return out


def normalize(x, peak=0.9):
    x = np.tanh(x * 1.1)
    m = np.max(np.abs(x))
    return (x / max(m, 1e-6) * peak).astype(np.float32)


def save(name, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(name, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def add_splash_extras(buf, t0, wrap=True):
    """Мелкие капли и шлепки о стекло: «смачно разлетается»."""
    for ti in np.sort(t0 + 0.02 + rng.random(22) ** 1.3 * 0.45):
        f0 = rng.uniform(800, 1600)
        add_fast(buf, bloop(int(0.12 * SR), f0, f0 * 0.4, 0.05), ti, rng.uniform(0.18, 0.4), wrap=wrap)
    for dt, g in [(0.05, 0.5), (0.11, 0.45), (0.18, 0.4), (0.26, 0.35), (0.34, 0.3)]:
        add_fast(buf, slap(int(0.06 * SR)) * 2.2, t0 + dt, g, wrap=wrap)


def build_loop():
    LOOP = 4.0
    buf = np.zeros(int(LOOP * SR), np.float32)
    add_fast(buf, whoosh(0.52), 2.96, 0.6)
    add_fast(buf, splat_event(), 3.50, 1.0)
    add_splash_extras(buf, 3.50)
    add_fast(buf, slide_event(1.1), 0.08, 0.6)
    for ti, f in [(0.32, 950), (0.51, 880), (0.64, 1050), (0.83, 820), (0.97, 990)]:
        add_fast(buf, bloop(int(0.22 * SR), f, f * 0.34, 0.07), ti, 0.55)
    for ti in [0.18, 0.27, 0.4, 0.58, 0.72, 0.9]:
        add_fast(buf, pop(), ti, 0.55)
    return normalize(buf)


if __name__ == "__main__":
    loop = build_loop()
    save("loop.wav", loop)
    sp = np.zeros(int(1.95 * SR), np.float32)
    add_fast(sp, whoosh(0.52), 0.0, 0.6, wrap=False)
    add_fast(sp, splat_event(), 0.54, 1.0, wrap=False)
    add_splash_extras(sp, 0.54, wrap=False)
    save("sfx_splat.wav", normalize(sp))
    save("sfx_slide.wav", normalize(slide_event(1.1)))
    dr = np.zeros(int(0.3 * SR), np.float32); add_fast(dr, bloop(int(0.25 * SR), 950, 320, 0.08), 0.01, 1, wrap=False); save("sfx_drip.wav", normalize(dr))
    pp = np.zeros(int(0.12 * SR), np.float32); add_fast(pp, pop(), 0.01, 1, wrap=False); add_fast(pp, pop(260), 0.05, .5, wrap=False); save("sfx_pop.wav", normalize(pp))
    for n in ["loop", "sfx_splat", "sfx_slide", "sfx_drip", "sfx_pop"]:
        with wave.open(n + ".wav") as w:
            d = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768
        print(n, round(w.getnframes() / SR, 2), "s peak", round(float(np.max(np.abs(d))), 2), "rms", round(float(np.sqrt(np.mean(d ** 2))), 3))
