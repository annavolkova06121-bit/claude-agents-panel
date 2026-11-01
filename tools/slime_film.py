#!/usr/bin/env python3
"""slime_film.py: слизь на объективе как плёнка с толщиной (numpy + Pillow).

Кадр = функция времени t в петле 4,0 с. Считается физически обоснованно:
  - толщина плёнки из маски формы (подушка + валик на кромке + капли толще + пузырьки-линзы);
  - нормали из градиента толщины;
  - преломление: картинка за слизью смещается по наклону поверхности;
  - поглощение (закон Бера): толстое темнее и зеленее, тонкое прозрачнее;
  - рассеяние: светлая лаймовая подсветка внутри слизи;
  - блики: ключевой свет + отражение «окон» + френель по краям.
Динамическая прозрачность: множитель толщины меняется по ходу анимации.
  начало: по мере стекания плёнка истончается, выше линии стекания она тоньше всего;
  конец: плюха растекается и густеет, к шву прозрачность минимальна.
"""
import math
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from slime_text import blur, smooth

W, H = 360, 640
K = W / 270.0              # масштаб из «условных» координат 270x480
SS = 2                     # суперсэмплинг при рисовании масок
LOOP, INTRO_END, SPLAT0, IMPACT, FULL = 4.0, 1.1, 3.28, 3.56, 3.92
PI2 = 2 * math.pi


def c01(x): return min(max(x, 0.0), 1.0)
def sm(x): x = c01(x); return x * x * (3 - 2 * x)
def eo(x): x = c01(x); return 1 - (1 - x) ** 3
def ei(x): x = c01(x); return x ** 3


rng = np.random.default_rng(77)
TONGUES = [(8 + i * 254 / 10 + (rng.random() - .5) * 12, 9 + rng.random() * 16, 20 + rng.random() * 55, rng.random() * .25) for i in range(11)]
RUNNERS = [dict(x=10 + rng.random() * 250, ts=.28 + rng.random() * .55, r=5 + rng.random() * 6, g=500 + rng.random() * 500) for _ in range(14)]
SPL = [dict(a=rng.random() * PI2, v=120 + rng.random() * 300, r=3 + rng.random() * 6) for _ in range(20)]
FING = rng.random(3) * 6
BUBBLES = [dict(x=rng.random() * 270, y=rng.random() * 480, r=3 + rng.random() ** 2 * 10, ph=rng.random() * PI2,
                k=1 + int(rng.random() * 2), a=3 + rng.random() * 8) for _ in range(26)]
_n = rng.standard_normal((H, W)).astype(np.float32)
_m = rng.standard_normal((H, W)).astype(np.float32)
_a, _b = blur(_n, 20.0), blur(_m, 55.0)
LOWF = _a / np.max(np.abs(_a)) * .55 + _b / np.max(np.abs(_b)) * .9
LOWF = LOWF / np.max(np.abs(LOWF))


def surf(x, t, L, amp):
    x = np.asarray(x, np.float64)
    y = L + amp * np.sin(x * .045 + t * 6) + amp * .5 * np.sin(x * .1 - t * 4.5)
    for xk, w, F, o in TONGUES:
        e = math.sin(math.pi * c01((t - .1 - o) / .7))
        if e > 0:
            d = (x - xk) / w
            y = y - F * e * np.exp(-d * d)
    return y


def S(p):  # условные координаты -> пиксели суперсэмплинга
    return (p[0] * K * SS, p[1] * K * SS)


def teardrop_pts(x, y0, y, r):
    cy = max(y0, y - 2.4 * r)
    pts = [(x - .3 * r, y0), (x + .3 * r, y0)]
    for i in range(1, 13):
        u = i / 12
        a = (1 - u) ** 2, 2 * u * (1 - u), u ** 2
        pts.append((a[0] * (x + .3 * r) + a[1] * (x + .34 * r) + a[2] * (x + .95 * r),
                    a[0] * y0 + a[1] * cy + a[2] * (y - .7 * r)))
    for i in range(0, 25):
        ang = -.35 + (math.pi + .7) * i / 24
        pts.append((x + math.cos(ang) * r, y + math.sin(ang) * r))
    for i in range(1, 13):
        u = i / 12
        a = (1 - u) ** 2, 2 * u * (1 - u), u ** 2
        pts.append((a[0] * (x - .95 * r) + a[1] * (x - .34 * r) + a[2] * (x - .3 * r),
                    a[0] * (y - .7 * r) + a[1] * cy + a[2] * y0))
    return pts


def blob_pts(cx, cy, r, fing):
    pts = []
    for k in range(96):
        th = k / 96 * PI2
        f = (math.sin(5 * th + FING[0]) + .6 * math.sin(9 * th + FING[1]) + .4 * math.sin(14 * th + FING[2])) / 2
        pts.append((cx + math.cos(th) * r * (1 + fing * f), cy + math.sin(th) * r * (1 + fing * f)))
    return pts


def masks(t):
    """Возвращает (M, D, info): M форма слизи, D капли и нити (утолщаются), info для динамики."""
    Mi = Image.new("L", (W * SS, H * SS), 0)
    Di = Image.new("L", (W * SS, H * SS), 0)
    dm, dd = ImageDraw.Draw(Mi), ImageDraw.Draw(Di)
    info = {"kind": "none"}
    if t < INTRO_END:
        pl = c01((t - .1) / .95)
        L = -50 + sm(pl) * 630
        amp = 8 * (1 - pl * .5)
        if L <= 540:
            xs = np.arange(-6, 276, 4.0)
            ys = surf(xs, t, L, amp)
            dm.polygon([S(p) for p in [(-6, 520)] + list(zip(xs, ys)) + [(276, 520)]], fill=255)
            info = dict(kind="run", L=L, amp=amp, pl=pl)
            for r in RUNNERS:
                if t < r["ts"]:
                    continue
                a = t - r["ts"]
                L0 = -50 + sm(c01((r["ts"] - .1) / .95)) * 630
                y0 = float(surf([r["x"]], r["ts"], L0, 8)[0]) + 4
                y = y0 + .5 * r["g"] * a * a
                sy = float(surf([r["x"]], t, L, amp)[0])
                if y > sy - 2 or y > 500:
                    continue
                pts = [S(p) for p in teardrop_pts(r["x"], y0, y, r["r"])]
                dm.polygon(pts, fill=255)
                dd.polygon(pts, fill=255)
    elif t < SPLAT0:
        pass
    elif t < IMPACT:
        f = (t - SPLAT0) / (IMPACT - SPLAT0)
        pts = [S(p) for p in blob_pts(135, 480 * .47 - (1 - f) * 14, 6 + 58 * ei(f), .06)]
        dm.polygon(pts, fill=255)
        info = dict(kind="fly", f=f)
    elif t < FULL:
        s = (t - IMPACT) / (FULL - IMPACT)
        Rr = 64 + (RM - 64) * eo(s)
        dm.polygon([S(p) for p in blob_pts(135, 480 * .47, Rr, .26 * (1 - s * .7))], fill=255)
        tau = t - IMPACT
        if tau < .5:
            for p in SPL:
                vx, vy = math.cos(p["a"]) * p["v"], math.sin(p["a"]) * p["v"] + 500 * tau
                x = 135 + math.cos(p["a"]) * p["v"] * tau
                y = 480 * .47 + math.sin(p["a"]) * p["v"] * tau + .5 * 500 * tau * tau
                r = p["r"] * (1 - tau / .55)
                if r < .6 or x < -30 or x > 300 or y > 510:
                    continue
                sp, ang = math.hypot(vx, vy), math.atan2(vy, vx)
                Ln = r * (1 + min(1.6, sp / 260))
                ca, sa = math.cos(ang), math.sin(ang)
                ell = [(x + (Ln * math.cos(u)) * ca - (r * math.sin(u)) * sa,
                        y + (Ln * math.cos(u)) * sa + (r * math.sin(u)) * ca) for u in np.linspace(0, PI2, 28)]
                tail = [(x + (-Ln * .4) * ca - (-r * .55) * sa, y + (-Ln * .4) * sa + (-r * .55) * ca),
                        (x + (-Ln * 1.5) * ca, y + (-Ln * 1.5) * sa),
                        (x + (-Ln * .4) * ca - (r * .55) * sa, y + (-Ln * .4) * sa + (r * .55) * ca)]
                for shp in (ell, tail):
                    dm.polygon([S(q) for q in shp], fill=255)
                    dd.polygon([S(q) for q in shp], fill=255)
                if tau < .16:
                    lw = max(1.5, r * .5 * (1 - tau / .16)) * K * SS
                    dm.line([S((135, 480 * .47)), S((x, y))], fill=255, width=int(lw))
                    dd.line([S((135, 480 * .47)), S((x, y))], fill=255, width=int(lw))
        info = dict(kind="splat", s=s)
    else:
        Mi = Image.new("L", (W * SS, H * SS), 255)
        info = dict(kind="full")
    M = np.asarray(Mi.resize((W, H), Image.BOX), np.float32) / 255
    D = np.asarray(Di.resize((W, H), Image.BOX), np.float32) / 255
    return M, D, info


RM = math.hypot(135, 240) * 1.3
YY, XX = np.mgrid[0:H, 0:W]


def gain(t, info):
    """Динамическая прозрачность: множитель толщины плёнки."""
    if info["kind"] == "run":
        g_top = 1 - .78 * sm(info["pl"])
        sx = surf(np.arange(W) / K, t, info["L"], info["amp"]) * K
        depth = YY - sx[None, :]
        return (g_top + (1 - g_top) * smooth(depth / (.38 * H), 0, 1)).astype(np.float32)
    if info["kind"] == "fly":
        return 0.85
    if info["kind"] == "splat":
        return .62 + .38 * eo(info["s"])
    return 1.0


def bubble_height(M, t):
    h = np.zeros((H, W), np.float32)
    ring = np.zeros((H, W), np.float32)
    for b in BUBBLES:
        x = (b["x"] + math.sin(PI2 * t / LOOP * b["k"] + b["ph"]) * b["a"]) * K
        y = (b["y"] + math.cos(PI2 * t / LOOP * b["k"] + b["ph"]) * b["a"]) * K
        r = b["r"] * K
        x0, x1, y0, y1 = int(x - r - 2), int(x + r + 3), int(y - r - 2), int(y + r + 3)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) - x, np.arange(y0, y1) - y)
        d = np.sqrt(gx * gx + gy * gy)
        dome = np.sqrt(np.clip(1 - (d / r) ** 2, 0, 1))
        h[y0:y1, x0:x1] = np.maximum(h[y0:y1, x0:x1], dome * (.28 + .03 * r))
        ring[y0:y1, x0:x1] = np.maximum(ring[y0:y1, x0:x1], smooth(1 - np.abs(d - r) / 1.6, 0, 1))
    return h * (M > .6), ring * (M > .6)


def windows(rx, ry):
    def box(x0, x1, y0, y1, f=.07):
        return smooth((rx - x0) / f, 0, 1) * smooth((x1 - rx) / f, 0, 1) * smooth((ry - y0) / f, 0, 1) * smooth((y1 - ry) / f, 0, 1)
    return np.maximum(box(-.78, -.26, -.88, -.30), box(.16, .52, -.92, -.50))


def make_bg(t):
    """Заглушка кадра: тёмно-зелёный фон с лицом (потом будет настоящее видео)."""
    img = Image.new("RGB", (W, H))
    arr = np.zeros((H, W, 3), np.float32)
    u = (XX - W * .8) / (W * 1.0)
    v = (YY - H * .35) / (H * .7)
    d = np.clip(np.sqrt(u * u + v * v), 0, 1)[..., None]
    arr[:] = (1 - d) * np.array([30, 78, 40], np.float32) + d * np.array([5, 11, 6], np.float32)
    img = Image.fromarray(arr.astype(np.uint8))
    dr = ImageDraw.Draw(img)
    sx, sy = W / 100, H / 177.78
    dr.polygon([(-4 * sx, 178 * sy), (4 * sx, 120 * sy), (50 * sx, 112 * sy), (96 * sx, 120 * sy), (104 * sx, 178 * sy)], fill=(18, 48, 26), outline=(198, 255, 0))
    dr.ellipse((29 * sx, 40 * sy, 71 * sx, 92 * sy), fill=(27, 74, 30), outline=(198, 255, 0))
    for ex in (42, 58):
        dr.ellipse(((ex - 2.2) * sx, (62 - 2.2) * sy, (ex + 2.2) * sx, (62 + 2.2) * sy), fill=(233, 255, 138))
    mh = 3 * (.25 + 1.0 * abs(math.sin(t * 11)))
    dr.ellipse((43.5 * sx, (80 - mh) * sy, 56.5 * sx, (80 + mh) * sy), fill=(5, 11, 6), outline=(198, 255, 0))
    return np.asarray(img, np.float32)


CAPS = {"jp": ["惑星を選べ", "ここで", "1年", "生き延びろ", "できるか", "答えは", "最後に", "ある"],
        "ru": ["Выбери", "планету", "и выживи", "здесь", "целый год", "ответ", "в конце", "ролика"],
        "en": ["Pick", "a planet", "and survive", "a year", "here", "the answer", "is at", "the end"]}


def shade(t, bg):
    M, D, info = masks(t)
    Ms = blur(M, 1.0)
    G = gain(t, info)
    prof = smooth((blur(M, 9.0) - .5) * 2, 0, 1) ** .9
    edge = np.clip(Ms - blur(M, 3.2), 0, 1)
    dfac = (1 - info["s"]) ** 1.5 if info["kind"] == "splat" else 1.0
    T = 1.8 * prof + 2.2 * blur(edge, 1.2) + (1.1 * blur(D, 4.5) + .7 * blur(D, 1.6)) * dfac
    T = T * (1 + .62 * LOWF) * Ms
    bh, ring = bubble_height(M, t)
    T = (T + bh * 1.2) * G
    T = T * (1 + .5 * ring * (M > .6))
    Hf = blur(T, 1.7)
    gy, gx = np.gradient(Hf)
    KG = 14.0
    nx, ny = -gx * KG, -gy * KG
    nz = 1 / np.sqrt(1 + nx * nx + ny * ny)
    nx, ny = nx * nz, ny * nz
    # преломление картинки за слизью
    refr = 8.0
    ix = np.clip((XX - nx * Hf * refr).astype(np.int32), 0, W - 1)
    iy = np.clip((YY - ny * Hf * refr).astype(np.int32), 0, H - 1)
    bgr = bg[iy, ix]
    # поглощение и рассеяние
    sigma = np.array([2.6, .9, 3.0], np.float32)
    trans = np.exp(-Hf[..., None] * sigma)
    sw = (1 - np.exp(-Hf * 1.25))[..., None]
    thick = smooth(Hf / 2.2, 0, 1)[..., None]
    scol = (1 - thick) * np.array([205, 250, 40], np.float32) + thick * np.array([66, 214, 10], np.float32)
    Ld = np.array([-.45, -.6, .66], np.float32)
    Ld /= np.linalg.norm(Ld)
    diff = np.clip(nx * Ld[0] + ny * Ld[1] + nz * Ld[2], 0, 1)
    lit = (.62 + .52 * diff)[..., None]
    col = bgr * trans * (1 - sw) + scol * lit * sw
    # блики: ключ + окна + френель
    Hv = Ld + np.array([0, 0, 1], np.float32)
    Hv /= np.linalg.norm(Hv)
    spec = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0, 1) ** 80 * 1.3
    rx, ry = 2 * nz * nx, 2 * nz * ny
    F = .15 + .85 * (1 - nz) ** 3
    env = windows(rx, ry) * F * 1.7 + .25 * (1 - (ry * .5 + .5)) * F
    col = col + ((spec + env) * 255)[..., None]
    a = np.clip(Ms * 1.0, 0, 1)[..., None]
    out = bg * (1 - a) + col * a
    return np.clip(out, 0, 255), info


def render(t, lang="jp", font="MPLUSRounded1c-Black.ttf"):
    bg = make_bg(t)
    out, info = shade(t, bg)
    # камера: вздрагивание на ударе
    if IMPACT <= t < IMPACT + .28:
        q = 1 - (t - IMPACT) / .28
        dx, dy = int(math.sin((t - IMPACT) * 90) * 5 * K * q), int(math.cos((t - IMPACT) * 70) * 4 * K * q)
        p = 8
        pad = np.pad(out, ((p, p), (p, p), (0, 0)), mode="edge")
        out = pad[p + dy:p + dy + H, p + dx:p + dx + W]
    img = Image.fromarray(out.astype(np.uint8))
    ci = min(7, int(t / .45))
    text = CAPS[lang][ci]
    f = ImageFont.truetype(font, int(W * .08 * (1.15 if lang == "jp" else .9)))
    d = ImageDraw.Draw(img)
    d.text((W / 2, H * .66), text, font=f, fill=(198, 255, 0) if ci == 0 else (255, 255, 255),
           anchor="mm", stroke_width=int(W * .018), stroke_fill=(0, 0, 0))
    return np.asarray(img)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default="MPLUSRounded1c-Black.ttf")
    ap.add_argument("--lang", default="jp")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--video")
    ap.add_argument("--audio")
    ap.add_argument("--png", nargs="*", type=float, help="времена для одиночных кадров")
    a = ap.parse_args()
    if a.png:
        for tt in a.png:
            Image.fromarray(render(tt, a.lang, a.font)).save(f"film_{tt:.2f}.png")
    if a.video:
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(a.fps), "-i", "-"]
        if a.audio:
            cmd += ["-i", a.audio]
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p"]
        if a.audio:
            cmd += ["-c:a", "libopus", "-b:a", "64k", "-shortest"]
        cmd += [a.video]
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        n = int(LOOP * a.fps)
        for k in range(n):
            pr.stdin.write(render(k / a.fps, a.lang, a.font).tobytes())
            sys.stdout.write(f"\r{k + 1}/{n}")
            sys.stdout.flush()
        pr.stdin.close()
        pr.wait()
