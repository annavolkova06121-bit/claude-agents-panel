#!/usr/bin/env python3
"""sfx_variants.py: шесть вариантов «сочной» озвучки цикла плюхи (numpy, без внешних файлов).

Главное отличие от первого черновика: у пузырей и капель высота РАСТЁТ на 10–30% по ходу
затухания (как у настоящих пузырей), а не падает: падающие «блупы» звучат как бластеры.
Основа звука: шум, мокрые «чпоки» (кластеры мелких пузырьков), удары, воздух, шипение.
Петля 4,0 с свёрнута по кругу: хвост удара в конце продолжается в начале ролика.
Тайминги те же, что в анимации: сползание 0,08-1,2 с, подлёт 2,96-3,48 с, удар 3,50 с.
"""
import math
import wave

import numpy as np

SR = 44100
LOOP = 4.0
N = int(LOOP * SR)


# ---------- фильтры и утилиты ----------
def _conv(x, h):
    n = len(x) + len(h) - 1
    nf = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(h, nf), nf)[:len(x)]
    return y.astype(np.float32)


def lp(x, fc):
    a = math.exp(-2 * math.pi * fc / SR)
    L = int(min(max(len(x), 16), max(16, 8 / (1 - a))))
    h = ((1 - a) * a ** np.arange(L)).astype(np.float32)
    return _conv(x, h)


def hp(x, fc): return x - lp(x, fc)
def bp(x, lo, hi): return lp(lp(hp(hp(x, lo), lo), hi), hi)


def lp_sweep(x, fc):
    """ФНЧ с меняющейся частотой среза (медленные развёртки)."""
    a = np.exp(-2 * np.pi * np.asarray(fc, np.float32) / SR)
    y = np.empty_like(x)
    s = 0.0
    for i in range(len(x)):
        s = (1 - a[i]) * x[i] + a[i] * s
        y[i] = s
    return y


def noise(r, n): return r.standard_normal(n).astype(np.float32)


def add(buf, x, t0, gain=1.0):
    """Сложить звук в петлю с переносом хвоста в начало."""
    n = len(buf)
    i0 = int(round(t0 * SR)) % n
    end = i0 + len(x)
    if end <= n:
        buf[i0:end] += x * gain
    else:
        k = n - i0
        buf[i0:] += x[:k] * gain
        rest = x[k:]
        buf[:len(rest)] += rest * gain


def reverb(buf, rt60=.4, wet=.2, seed=3):
    """Круговая свёртка: хвост реверберации переходит через шов петли."""
    r = np.random.default_rng(seed)
    n = int(rt60 * 1.3 * SR)
    t = np.arange(n) / SR
    h = noise(r, n) * np.exp(-t * 6.9 / rt60)
    h = lp(h, 5000).astype(np.float32)
    h /= np.sqrt(np.sum(h * h)) + 1e-9
    hh = np.zeros(len(buf), np.float32)
    hh[:n] = h[:len(buf)]
    y = np.fft.irfft(np.fft.rfft(buf) * np.fft.rfft(hh), len(buf)).astype(np.float32)
    return buf * (1 - wet * .5) + y * wet


# ---------- кирпичики ----------
def bubble(f0, rise=.2, amp=1.0, tau=None):
    """Пузырь: затухающая синусоида с РАСТУЩЕЙ высотой (формула Миннаэрта: меньше пузырь, выше тон)."""
    tau = tau or 0.011 * (1000 / f0) ** .9
    n = int(tau * 6 * SR)
    t = np.arange(n) / SR
    f = f0 * (1 + rise * (1 - np.exp(-t / (tau * .6))))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / tau)
    s[:int(.0008 * SR)] *= np.linspace(0, 1, int(.0008 * SR))
    return (s * amp).astype(np.float32)


def cluster(buf, r, t0, dur, rate0, rate1, flo, fhi, amp, rise=.2, curve=1.0):
    """Мокрое «чпоканье»: пуассоновский рой мелких пузырьков, плотность меняется от rate0 к rate1."""
    n = int(dur * 2000)
    ts = np.linspace(0, 1, n)
    rate = rate0 + (rate1 - rate0) * ts ** curve
    p = rate / 2000.0
    hits = r.random(n) < p
    for k in np.nonzero(hits)[0]:
        f0 = math.exp(r.uniform(math.log(flo), math.log(fhi)))
        a = amp * math.exp(r.normal(0, .45)) * (1 - .35 * ts[k])
        add(buf, bubble(f0, rise * r.uniform(.6, 1.4), a), t0 + ts[k] * dur)


def thump(f0, f1, tau_f, tau_a, dur=.5, amp=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t / tau_f)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / tau_a)
    s[:int(.002 * SR)] *= np.linspace(0, 1, int(.002 * SR))
    return (s * amp).astype(np.float32)


def slap(r, lo, hi, tau, amp=1.0, dur=.12):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = bp(noise(r, n), lo, hi) * np.exp(-t / tau)
    x[:int(.0008 * SR)] *= np.linspace(0, 1, int(.0008 * SR))
    return (x * amp * 5).astype(np.float32)


def air(r, dur, lo, hi, curve=2.0, amp=.5):
    """Воздух/гул с нарастающей громкостью и открывающимся фильтром (без тональных свистов)."""
    n = int(dur * SR)
    u = np.linspace(0, 1, n)
    x = lp_sweep(noise(r, n), lo + (hi - lo) * u ** 1.5)
    return (x * u ** curve * amp * 3).astype(np.float32)


def gloop(r, dur, fc, am_hz, amp=.6, tau=.3):
    """Низкая вязкая масса с дрожанием."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    am = .55 + .45 * np.sin(2 * np.pi * am_hz * t + r.uniform(0, 6))
    x = lp(noise(r, n), fc) * am * np.exp(-t / tau)
    return (x * amp * 4).astype(np.float32)


def sizzle(r, dur, rate, fc, amp=.3, decay=None):
    """Шипение: высокочастотный шум, прерываемый случайными «затворами»."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    gate = (r.random(int(dur * rate) + 2) < .5).astype(np.float32)
    g = np.repeat(gate, int(SR / rate) + 1)[:n]
    g = lp(g, rate * .8)
    x = hp(noise(r, n), fc) * (.4 + g)
    if decay:
        x = x * np.exp(-t / decay)
    return (x * amp).astype(np.float32)


def sticky(r, dur, amp=.3):
    """Тянущаяся липкая нить: шум, чья полоса сужается к концу, с мелкой дрожью."""
    n = int(dur * SR)
    u = np.linspace(0, 1, n)
    x = lp_sweep(hp(noise(r, n), 900), 5200 - 3800 * u)
    x *= (.5 + .5 * np.abs(np.sin(2 * np.pi * (28 - 10 * u) * np.arange(n) / SR))) * np.sin(np.pi * u) ** .8
    return (x * amp * 3).astype(np.float32)


# ---------- общий «план» по времени ----------
DRIPS = [.24, .33, .41, .5, .6, .7, .83, .95]
POPS = [.13, .21, .3, .43, .55, .66, .8, .92, 1.04]
SLAPS = [3.55, 3.61, 3.68, 3.76, 3.84]


def finish(buf, rms_target=.11, peak=.92):
    x = np.tanh(buf * 1.05)
    act = np.abs(x) > .01
    rms = np.sqrt(np.mean(x[act] ** 2)) if act.any() else 1
    x = x * (rms_target / max(rms, 1e-6))
    x = np.tanh(x * 1.2)
    x = x / max(np.max(np.abs(x)), 1e-6) * peak
    return x.astype(np.float32)


# ---------- варианты ----------
def v1_wet(seed=11):
    """Влажный шлёп: живой, плотный, как ладонь в густом геле."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    add(b, air(r, .54, 220, 1500, 2.0, .35), 2.96)
    cluster(b, r, 3.05, .43, 8, 150, 400, 2600, .22, .2, 1.6)
    add(b, thump(108, 48, .07, .16, .4, 1.0), 3.50)
    add(b, slap(r, 500, 2800, .035, .85), 3.50)
    cluster(b, r, 3.50, .6, 420, 40, 250, 2300, .5, .22, .7)
    add(b, gloop(r, .6, 260, 5.5, .5, .35), 3.52)
    for ti in SLAPS:
        add(b, slap(r, 650, 3000, .028, .5), ti)
        add(b, thump(150, 80, .04, .06, .15, .35), ti)
    add(b, air(r, .5, 80, 420, .6, .45)[::1], 3.52)
    add(b, gloop(r, 1.05, 320, 4.5, .55, 1.2) * np.sin(np.linspace(0, np.pi, int(1.05 * SR))), .08)
    cluster(b, r, .08, 1.1, 90, 25, 280, 1600, .3, .2)
    for ti in DRIPS:
        add(b, bubble(r.uniform(330, 560), .45, .5), ti)
        add(b, slap(r, 500, 1800, .02, .18), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(1500, 3200), .25, .28), ti)
    return finish(reverb(b, .22, .08))


def v2_jelly(seed=12):
    """Желе: мягкое, округлое, с дрожанием массы."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    add(b, lp(air(r, .54, 120, 700, 1.8, .4), 900), 2.96)
    add(b, thump(135, 58, .09, .22, .6, 1.0), 3.50)
    n = int(.9 * SR); t = np.arange(n) / SR
    wob = np.sin(2 * np.pi * 7.5 * t) * np.exp(-t / .38)
    add(b, lp(noise(r, n), 190) * (.3 + wob) * np.exp(-t / .5) * 5, 3.50)
    add(b, slap(r, 300, 1400, .05, .5), 3.50)
    cluster(b, r, 3.50, .6, 120, 20, 120, 700, .55, .3, .8)
    for ti in SLAPS:
        add(b, lp(slap(r, 300, 1500, .04, .5), 1600), ti)
        add(b, thump(120, 70, .05, .09, .2, .3), ti)
    add(b, gloop(r, 1.1, 210, 3.5, .5, 1.0) * np.sin(np.linspace(0, np.pi, int(1.1 * SR))), .08)
    for ti in DRIPS:
        add(b, bubble(r.uniform(150, 290), .4, .55, tau=.06), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(500, 900), .3, .22, tau=.025), ti)
    return finish(reverb(b, .3, .14))


def v3_cartoon(seed=13):
    """Мультяшный: весёлый «сплат» и «чпок», упругое дрожание после удара."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    n = int(.5 * SR); u = np.linspace(0, 1, n)
    wh = bp(noise(r, n), 500, 2400) * np.sin(np.pi * u ** .8) ** 2
    add(b, wh * 1.6, 2.98)
    add(b, thump(120, 55, .05, .1, .3, .95), 3.50)
    add(b, slap(r, 900, 4200, .03, 1.0), 3.50)
    tt = np.arange(int(.2 * SR)) / SR
    chirp = np.sin(2 * np.pi * np.cumsum(190 + 520 * (1 - np.exp(-tt / .05))) / SR) * np.exp(-tt / .09)
    add(b, (chirp * .45).astype(np.float32) * (np.random.default_rng(1).standard_normal(len(tt)) * .0 + 1), 3.505)
    tt2 = np.arange(int(.5 * SR)) / SR
    boing = np.sin(2 * np.pi * np.cumsum(210 * (1 + .12 * np.sin(2 * np.pi * 7 * tt2))) / SR) * np.exp(-tt2 / .16)
    add(b, (boing * .22).astype(np.float32), 3.56)
    cluster(b, r, 3.50, .5, 260, 30, 400, 3000, .45, .35, .8)
    for ti in SLAPS:
        add(b, slap(r, 900, 3800, .022, .55), ti)
        add(b, bubble(r.uniform(500, 800), .7, .4), ti)
    add(b, gloop(r, 1.0, 380, 6.0, .4, 1.0) * np.sin(np.linspace(0, np.pi, int(1.0 * SR))), .1)
    for ti in DRIPS:
        add(b, bubble(r.uniform(380, 720), .85, .65, tau=.045), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(1800, 3600), .3, .35), ti)
    return finish(reverb(b, .18, .06))


def v4_asmr(seed=14):
    """АСМР-слайм: плотные мелкие чпоки и тянущиеся нити, без грохота."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    add(b, air(r, .54, 300, 2200, 1.6, .22), 2.96)
    cluster(b, r, 2.98, .52, 20, 320, 800, 4800, .2, .25, 1.4)
    add(b, thump(95, 55, .06, .12, .3, .4), 3.50)
    add(b, slap(r, 500, 2600, .05, .45), 3.50)
    cluster(b, r, 3.50, .55, 700, 60, 500, 4500, .38, .28, .8)
    for ti in SLAPS:
        add(b, slap(r, 700, 3200, .03, .35), ti)
    add(b, sticky(r, .45, .35), 3.56)
    add(b, sticky(r, .35, .3), 3.78)
    cluster(b, r, .06, 1.25, 220, 40, 700, 5200, .24, .25, .7)
    for ti in [.2, .36, .52, .72, .9, 1.05]:
        add(b, sticky(r, r.uniform(.14, .26), .26), ti)
    for ti in DRIPS:
        add(b, bubble(r.uniform(420, 800), .4, .42), ti)
    return finish(reverb(b, .15, .05), rms_target=.1)


def v5_acid(seed=15):
    """Кислота: шипение и пена, мелкие лопающиеся пузырьки."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    n = int(.54 * SR); u = np.linspace(0, 1, n)
    add(b, sizzle(r, .54, 900, 3500, .5) * u ** 1.6, 2.96)
    add(b, thump(88, 46, .06, .13, .3, .85), 3.50)
    add(b, hp(noise(r, int(.6 * SR)), 2800) * np.exp(-np.arange(int(.6 * SR)) / SR / .22) * .55, 3.50)
    add(b, sizzle(r, .9, 1100, 3000, .4, .35), 3.52)
    cluster(b, r, 3.50, .6, 450, 60, 600, 4800, .38, .3, .8)
    for ti in SLAPS:
        add(b, slap(r, 900, 4000, .02, .4), ti)
    add(b, sizzle(r, 1.2, 800, 3200, .32, .6) * np.sin(np.linspace(0, np.pi, int(1.2 * SR))) ** .6, .08)
    cluster(b, r, .08, 1.2, 160, 30, 900, 5200, .26, .3, .8)
    for ti in DRIPS:
        add(b, sizzle(r, .09, 1500, 3500, .45, .03), ti)
        add(b, bubble(r.uniform(500, 900), .35, .3), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(2200, 4200), .25, .3), ti)
    return finish(reverb(b, .2, .07))


def v6_cinema(seed=16):
    """Тяжёлый кинематограф: глубокий удар, гул, длинный хвост."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    add(b, lp(air(r, .54, 70, 420, 2.4, .6), 600), 2.96)
    add(b, thump(60, 36, .12, .45, 1.0, 1.0), 3.50)
    add(b, lp(noise(r, int(.9 * SR)), 140) * np.exp(-np.arange(int(.9 * SR)) / SR / .35) * 5, 3.50)
    add(b, slap(r, 400, 1800, .05, .6), 3.50)
    cluster(b, r, 3.52, .6, 120, 15, 150, 900, .5, .22, .7)
    for ti in SLAPS:
        add(b, lp(slap(r, 300, 1500, .04, .45), 1800), ti)
        add(b, thump(90, 50, .05, .1, .2, .3), ti)
    add(b, gloop(r, 1.1, 160, 3.0, .5, 1.0) * np.sin(np.linspace(0, np.pi, int(1.1 * SR))), .08)
    for ti in DRIPS[::2]:
        add(b, bubble(r.uniform(170, 320), .35, .5, tau=.07), ti)
    for ti in POPS[::2]:
        add(b, bubble(r.uniform(700, 1400), .25, .2, tau=.02), ti)
    return finish(reverb(b, .6, .3), rms_target=.12)


VARIANTS = [
    ("v1_wet", "Влажный шлёп", v1_wet),
    ("v2_jelly", "Желе", v2_jelly),
    ("v3_cartoon", "Мультяшный", v3_cartoon),
    ("v4_asmr", "АСМР-слайм", v4_asmr),
    ("v5_acid", "Кислота и шипение", v5_acid),
    ("v6_cinema", "Тяжёлый кинематограф", v6_cinema),
]


def save(name, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(name, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    for key, title, fn in VARIANTS:
        x = fn()
        save(f"{key}.wav", x)
        print(key, title, "peak", round(float(np.max(np.abs(x))), 2), "rms", round(float(np.sqrt(np.mean(x ** 2))), 3))
