#!/usr/bin/env python3
"""sfx_variants.py: шесть вариантов «сочной» озвучки цикла плюхи (numpy, без внешних файлов).

Главное отличие от первого черновика: у пузырей и капель высота РАСТЁТ на 10–30% по ходу
затухания (как у настоящих пузырей), а не падает: падающие «блупы» звучат как бластеры.
Основа звука: шум, мокрые «чпоки» (кластеры мелких пузырьков), удары, воздух, шипение.
Петля 4,0 с свёрнута по кругу: хвост удара в конце продолжается в начале ролика.
Тайминги те же, что в анимации (ускорена под ваши примеры): сползание 0,04-0,75 с, подлёт 2,95-3,25 с, удар 3,25 с, цикл 3,6 с.
"""
import math
import wave

import numpy as np

SR = 44100
LOOP = 3.6
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


# ---------- общий «план» по времени (цикл 3,6 с) ----------
FLY0, FLY_D = 2.95, 0.30      # подлёт
IMP = 3.25                    # удар
SL0, SL_D = 0.04, 0.70        # сползание плёнки
DRIPS = [.08, .14, .2, .27, .34, .42, .5, .6]
POPS = [.05, .1, .16, .24, .32, .4, .5, .6]
SLAPS = [IMP + .03, IMP + .07, IMP + .12, IMP + .18, IMP + .24]


def hump(n): return np.sin(np.linspace(0, np.pi, n)).astype(np.float32)


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
    add(b, air(r, FLY_D, 220, 1500, 2.0, .35), FLY0)
    cluster(b, r, FLY0 + .04, FLY_D - .05, 8, 160, 400, 2600, .22, .2, 1.6)
    add(b, thump(108, 48, .07, .16, .4, 1.0), IMP)
    add(b, slap(r, 500, 2800, .035, .85), IMP)
    cluster(b, r, IMP, .5, 420, 40, 250, 2300, .5, .22, .7)
    add(b, gloop(r, .5, 260, 5.5, .5, .3), IMP + .02)
    for ti in SLAPS:
        add(b, slap(r, 650, 3000, .028, .5), ti)
        add(b, thump(150, 80, .04, .06, .15, .35), ti)
    add(b, air(r, .4, 80, 420, .6, .45), IMP + .02)
    add(b, gloop(r, SL_D, 320, 6.5, .55, 1.0) * hump(int(SL_D * SR)), SL0)
    cluster(b, r, SL0, SL_D, 130, 30, 280, 1600, .3, .2)
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
    add(b, lp(air(r, FLY_D, 120, 700, 1.8, .4), 900), FLY0)
    add(b, thump(135, 58, .09, .22, .6, 1.0), IMP)
    n = int(.8 * SR); t = np.arange(n) / SR
    wob = np.sin(2 * np.pi * 8.5 * t) * np.exp(-t / .3)
    add(b, lp(noise(r, n), 190) * (.3 + wob) * np.exp(-t / .4) * 5, IMP)
    add(b, slap(r, 300, 1400, .05, .5), IMP)
    cluster(b, r, IMP, .5, 120, 20, 120, 700, .55, .3, .8)
    for ti in SLAPS:
        add(b, lp(slap(r, 300, 1500, .04, .5), 1600), ti)
        add(b, thump(120, 70, .05, .09, .2, .3), ti)
    add(b, gloop(r, SL_D, 210, 4.5, .5, 1.0) * hump(int(SL_D * SR)), SL0)
    for ti in DRIPS:
        add(b, bubble(r.uniform(150, 290), .4, .55, tau=.05), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(500, 900), .3, .22, tau=.02), ti)
    return finish(reverb(b, .3, .14))


def v3_cartoon(seed=13):
    """Мультяшный: весёлый «сплат» и «чпок», упругое дрожание после удара."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    n = int(FLY_D * SR)
    wh = bp(noise(r, n), 500, 2400) * hump(n) ** 2
    add(b, wh * 1.6, FLY0)
    add(b, thump(120, 55, .05, .1, .3, .95), IMP)
    add(b, slap(r, 900, 4200, .03, 1.0), IMP)
    tt = np.arange(int(.16 * SR)) / SR
    chirp = np.sin(2 * np.pi * np.cumsum(190 + 520 * (1 - np.exp(-tt / .04))) / SR) * np.exp(-tt / .07)
    add(b, (chirp * .4).astype(np.float32), IMP + .005)
    tt2 = np.arange(int(.4 * SR)) / SR
    boing = np.sin(2 * np.pi * np.cumsum(210 * (1 + .12 * np.sin(2 * np.pi * 8 * tt2))) / SR) * np.exp(-tt2 / .12)
    add(b, (boing * .2).astype(np.float32), IMP + .05)
    cluster(b, r, IMP, .4, 260, 30, 400, 3000, .45, .35, .8)
    for ti in SLAPS:
        add(b, slap(r, 900, 3800, .022, .55), ti)
        add(b, bubble(r.uniform(500, 800), .7, .4), ti)
    add(b, gloop(r, SL_D, 380, 7.0, .4, .8) * hump(int(SL_D * SR)), SL0)
    for ti in DRIPS:
        add(b, bubble(r.uniform(380, 720), .85, .65, tau=.04), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(1800, 3600), .3, .35), ti)
    return finish(reverb(b, .18, .06))


def v4_asmr(seed=14):
    """АСМР-слайм: плотные мелкие чпоки и тянущиеся нити, без грохота."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    add(b, air(r, FLY_D, 300, 2200, 1.6, .22), FLY0)
    cluster(b, r, FLY0 + .02, FLY_D - .02, 20, 340, 800, 4800, .2, .25, 1.4)
    add(b, thump(95, 55, .06, .12, .3, .4), IMP)
    add(b, slap(r, 500, 2600, .05, .45), IMP)
    cluster(b, r, IMP, .45, 700, 60, 500, 4500, .38, .28, .8)
    for ti in SLAPS:
        add(b, slap(r, 700, 3200, .03, .35), ti)
    add(b, sticky(r, .3, .35), IMP + .05)
    add(b, sticky(r, .25, .3), IMP + .2)
    cluster(b, r, SL0, SL_D + .1, 240, 40, 700, 5200, .24, .25, .7)
    for ti in [.1, .2, .3, .42, .55]:
        add(b, sticky(r, r.uniform(.1, .18), .26), ti)
    for ti in DRIPS:
        add(b, bubble(r.uniform(420, 800), .4, .42), ti)
    return finish(reverb(b, .15, .05), rms_target=.1)


def v5_acid(seed=15):
    """Кислота: шипение и пена, мелкие лопающиеся пузырьки."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    n = int(FLY_D * SR); u = np.linspace(0, 1, n)
    add(b, sizzle(r, FLY_D, 900, 3500, .5) * u ** 1.6, FLY0)
    add(b, thump(88, 46, .06, .13, .3, .85), IMP)
    nn = int(.5 * SR)
    add(b, hp(noise(r, nn), 2800) * np.exp(-np.arange(nn) / SR / .18) * .55, IMP)
    add(b, sizzle(r, .6, 1100, 3000, .4, .3), IMP + .02)
    cluster(b, r, IMP, .45, 450, 60, 600, 4800, .38, .3, .8)
    for ti in SLAPS:
        add(b, slap(r, 900, 4000, .02, .4), ti)
    add(b, sizzle(r, SL_D + .1, 800, 3200, .32, .5) * hump(int((SL_D + .1) * SR)) ** .6, SL0)
    cluster(b, r, SL0, SL_D, 170, 30, 900, 5200, .26, .3, .8)
    for ti in DRIPS:
        add(b, sizzle(r, .07, 1500, 3500, .45, .025), ti)
        add(b, bubble(r.uniform(500, 900), .35, .3), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(2200, 4200), .25, .3), ti)
    return finish(reverb(b, .2, .07))


def v6_cinema(seed=16):
    """Тяжёлый кинематограф: глубокий удар, гул, длинный хвост."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    add(b, lp(air(r, FLY_D, 70, 420, 2.4, .6), 600), FLY0)
    add(b, thump(60, 36, .12, .4, .9, 1.0), IMP)
    nn = int(.8 * SR)
    add(b, lp(noise(r, nn), 140) * np.exp(-np.arange(nn) / SR / .3) * 5, IMP)
    add(b, slap(r, 400, 1800, .05, .6), IMP)
    cluster(b, r, IMP + .02, .5, 120, 15, 150, 900, .5, .22, .7)
    for ti in SLAPS:
        add(b, lp(slap(r, 300, 1500, .04, .45), 1800), ti)
        add(b, thump(90, 50, .05, .1, .2, .3), ti)
    add(b, gloop(r, SL_D, 160, 3.5, .5, 1.0) * hump(int(SL_D * SR)), SL0)
    for ti in DRIPS[::2]:
        add(b, bubble(r.uniform(170, 320), .35, .5, tau=.06), ti)
    for ti in POPS[::2]:
        add(b, bubble(r.uniform(700, 1400), .25, .2, tau=.02), ti)
    return finish(reverb(b, .55, .28), rms_target=.12)


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


def clip(x, t0, dur, fade=.01):
    """Вырезать фрагмент петли (с переносом через шов) с короткими фейдами."""
    i0 = int(t0 * SR); n = int(dur * SR)
    y = np.take(x, (np.arange(n) + i0) % len(x)).astype(np.float32)
    f = int(fade * SR)
    y[:f] *= np.linspace(0, 1, f); y[-f:] *= np.linspace(1, 0, f)
    return y


if __name__ == "__main__":
    for key, title, fn in VARIANTS:
        x = fn()
        save(f"{key}.wav", x)
        print(key, title, "peak", round(float(np.max(np.abs(x))), 2), "rms", round(float(np.sqrt(np.mean(x ** 2))), 3))
    # основной звук страницы цикла = вариант 1; короткие превью-фрагменты из него
    base = v1_wet()
    save("loop.wav", base)
    save("sfx_splat.wav", clip(base, FLY0 - .02, .95))
    save("sfx_slide.wav", clip(base, 0.0, .8))
    r = np.random.default_rng(3)
    d = np.zeros(int(.35 * SR), np.float32); d[:len(bubble(430, .45, 1.0))] += bubble(430, .45, 1.0)
    save("sfx_drip.wav", finish(d))
    p = np.zeros(int(.12 * SR), np.float32); pb = bubble(2400, .25, 1.0); p[:len(pb)] += pb
    save("sfx_pop.wav", finish(p))
