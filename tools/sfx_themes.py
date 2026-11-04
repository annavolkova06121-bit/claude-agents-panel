#!/usr/bin/env python3
"""sfx_themes.py: звук цикла для стилей «Лава» и «Море» (numpy, без внешних файлов).

Тайминги те же, что у «Кислоты и шипения» (sfx_variants.py): сползание 0,04-0,75 с, подлёт 2,95-3,25 с,
удар 3,25 с, цикл 3,6 с; петля свёрнута по кругу, хвост удара переходит в начало.
Принципы те же: пузыри с РАСТУЩЕЙ высотой (Миннаэрт), шум, пуассоновские рои пузырьков, круговая реверберация.

Лава: низкий гул, густые «блопы» (низкая частота, длинное затухание), пар (шипение), треск углей, тяжёлый удар.
Море: бегущая вода (полосовой шум с дрожанием), булькающие пузыри, «плинки» капель, шипящая волна, всплеск.

Запуск:  python sfx_themes.py [папка_вывода]   -> lava_loop.wav, sea_loop.wav
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfx_variants import (SR, N, FLY0, FLY_D, IMP, SL0, SL_D, DRIPS, POPS, SLAPS,  # noqa: E402
                          add, bubble, bp, cluster, finish, gloop, hp, hump, lp, noise, reverb, save,
                          sizzle, slap, thump, lp_sweep)


def crackle(buf, r, t0, dur, n, amp, lo=2500):
    """Треск углей: короткие резкие щелчки, плотность спадает со временем."""
    for _ in range(n):
        ti = t0 + dur * r.random() ** 1.6
        m = int(r.uniform(.0012, .004) * SR)
        c = hp(noise(r, m), lo) * np.exp(-np.arange(m) / SR / r.uniform(.0006, .0016))
        add(buf, (c * amp * r.uniform(.25, 1.0) * 9).astype(np.float32), ti)


def sweep_noise(r, dur, f0, f1, curve=2.0, amp=.5):
    """Шум, у которого срез ФНЧ плавно уходит от f0 к f1, громкость нарастает (свист подлёта)."""
    n = int(dur * SR)
    u = np.linspace(0, 1, n)
    x = lp_sweep(noise(r, n), f0 + (f1 - f0) * u ** 1.4)
    return (x * u ** curve * amp * 3).astype(np.float32)


def v_lava(seed=21):
    """Лава: гул, густые блопы, пар, треск, тяжёлый удар."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    # --- подлёт: нарастающий рёв с паром и треском
    add(b, sweep_noise(r, FLY_D, 250, 2600, 2.0, .5), FLY0)
    add(b, sizzle(r, FLY_D, 700, 2600, .35) * np.linspace(0, 1, int(FLY_D * SR)) ** 1.8, FLY0)
    crackle(b, r, FLY0 + .06, FLY_D - .06, 16, .35)
    # --- удар: тяжёлый бас, густой шлепок, пар, пузыри и треск
    add(b, thump(70, 34, .07, .2, .55, 1.0), IMP)
    nn = int(.35 * SR)
    add(b, bp(noise(r, nn), 180, 1800) * np.exp(-np.arange(nn) / SR / .11) * 1.1, IMP)
    ns = int(.6 * SR)
    add(b, hp(noise(r, ns), 2300) * np.exp(-np.arange(ns) / SR / .22) * .5, IMP + .01)
    add(b, sizzle(r, .6, 500, 2600, .34, .3), IMP + .03)
    cluster(b, r, IMP, .5, 260, 40, 140, 800, .5, .15, .8)
    crackle(b, r, IMP, .5, 46, .5)
    for ti in SLAPS:
        add(b, slap(r, 250, 1800, .03, .5), ti)
    add(b, gloop(r, .5, 160, 5, .9, .22), IMP + .02)
    # --- вступление: гул, густые блопы, пар, углики
    add(b, gloop(r, SL_D + .15, 150, 6, .7, .45) * hump(int((SL_D + .15) * SR)) ** .5, SL0)
    add(b, sizzle(r, SL_D + .1, 450, 2600, .3, .5) * hump(int((SL_D + .1) * SR)) ** .7, SL0)
    cluster(b, r, SL0, SL_D, 70, 14, 130, 520, .5, .15, .8)
    crackle(b, r, SL0 + .02, SL_D - .1, 28, .38)
    for ti in DRIPS:
        add(b, bubble(r.uniform(150, 280), .12, .55), ti)
        add(b, sizzle(r, .09, 600, 2600, .4, .035), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(700, 1500), .2, .3), ti)
        crackle(b, r, ti, .02, 2, .3)
    return finish(reverb(b, .28, .09))


def v_sea(seed=22):
    """Море: бегущая вода, булькающие пузыри, капли, шипящая волна, большой всплеск."""
    r = np.random.default_rng(seed)
    b = np.zeros(N, np.float32)
    # --- подлёт: вода «летит» (свист), капли
    add(b, sweep_noise(r, FLY_D, 500, 4200, 2.0, .45), FLY0)
    add(b, sizzle(r, FLY_D, 1200, 4500, .22) * np.linspace(0, 1, int(FLY_D * SR)) ** 1.6, FLY0)
    # --- удар: большой всплеск
    add(b, thump(95, 52, .05, .12, .3, .42), IMP)
    nn = int(.3 * SR)
    add(b, lp(noise(r, nn), 9000) * np.exp(-np.arange(nn) / SR / .07) * 1.0, IMP)
    nb = int(.7 * SR)
    add(b, bp(noise(r, nb), 300, 3500) * np.exp(-np.arange(nb) / SR / .2) * .9, IMP + .01)
    add(b, hp(noise(r, nb), 3500) * np.exp(-np.arange(nb) / SR / .25) * .4, IMP + .02)
    cluster(b, r, IMP, .55, 800, 90, 350, 3600, .42, .35, .8)
    for _ in range(34):                                   # разлетающиеся капли
        add(b, bubble(r.uniform(1400, 4500), .5, r.uniform(.12, .35)), IMP + .03 + .6 * r.random() ** 1.5)
    for ti in SLAPS:
        add(b, slap(r, 600, 5000, .02, .35), ti)
    # --- вступление: вода стекает, бульканье, плинки
    ln = int((SL_D + .15) * SR)
    flow = bp(noise(r, ln), 500, 5500) * (.55 + .45 * lp(noise(r, ln), 18) * 6).clip(0, 1.4)
    add(b, flow * hump(ln) ** .7 * .5, SL0)
    add(b, gloop(r, SL_D, 420, 3.2, .22, .5), SL0)
    cluster(b, r, SL0, SL_D, 230, 40, 300, 2600, .36, .35, .8)
    for ti in DRIPS:
        add(b, bubble(r.uniform(900, 2200), .5, .5), ti)
    for ti in POPS:
        add(b, bubble(r.uniform(2500, 5200), .3, .3), ti)
    return finish(reverb(b, .22, .07))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("lava_loop.wav", v_lava), ("sea_loop.wav", v_sea)):
        x = fn()
        save(str(out / name), x)
        print(name, "peak", round(float(np.max(np.abs(x))), 2), "rms", round(float(np.sqrt(np.mean(x ** 2))), 3))
