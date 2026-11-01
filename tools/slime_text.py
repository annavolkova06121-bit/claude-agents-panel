#!/usr/bin/env python3
"""slime_text.py: кислотные буквы в стиле «Колба + подтёки».

Только numpy и Pillow, без браузера и видеокарты. Кадр = функция времени t:
    frame = Slime(text, font).render(t)      # RGBA uint8, H x W x 4

Анимация (по умолчанию 2,4 с):
  0,15-1,25 с  жидкость поднимается внутри «стеклянных» букв, на поверхности волна, внутри пузырьки
  1,2-2,4 с    из нижних краёв букв вытягиваются подтёки и срываются каплями
Два стиля заливки: 'flat' (мультяшный) и 'gloss' (глянцевый, подсветка по рельефу).
"""
import argparse
import math
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def ease_out(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def blur(a, s):
    """Гауссово размытие без scipy и OpenCV (две прохода по осям)."""
    if s <= 0:
        return a
    r = int(math.ceil(s * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k = (k / k.sum()).astype(np.float32)
    p = np.pad(a, ((0, 0), (r, r)), mode="edge")
    out = np.zeros_like(a, dtype=np.float32)
    for i, w in enumerate(k):
        out += w * p[:, i:i + a.shape[1]]
    p = np.pad(out, ((r, r), (0, 0)), mode="edge")
    out2 = np.zeros_like(out)
    for i, w in enumerate(k):
        out2 += w * p[i:i + a.shape[0], :]
    return out2


def goo(m, s=4.0):
    """Размытие + порог: скругляет углы и сливает близкие формы."""
    return smooth(blur(m, s), 0.40, 0.60)


def shift(a, dx, dy):
    out = np.zeros_like(a)
    h, w = a.shape
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = \
        a[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def over(dst_rgb, dst_a, src_rgb, src_a):
    out_a = src_a + dst_a * (1 - src_a)
    out_rgb = (src_rgb * src_a[..., None] + dst_rgb * (dst_a * (1 - src_a))[..., None]) / np.maximum(out_a, 1e-5)[..., None]
    return out_rgb, out_a


class Slime:
    def __init__(self, text, font_path, width=800, height=450, style="flat",
                 color=(79, 217, 26), seed=7):
        self.W, self.H, self.style = width, height, style
        self.color = np.array(color, np.float32)
        self.rng = np.random.default_rng(seed)
        self._layout(text, font_path)
        self.glass = goo(self.m, 2.0)
        inner = smooth(blur(self.glass, 3.0), 0.58, 0.86)
        self.rim = np.clip(self.glass - inner, 0, 1)
        self._anchors()
        self._bubbles()

    # ---- раскладка текста ----
    def _layout(self, text, font_path):
        W, H = self.W, self.H
        probe = Image.new("L", (10, 10))
        d0 = ImageDraw.Draw(probe)

        def fit(lines):
            size = 400
            while size > 20:
                f = ImageFont.truetype(font_path, size)
                w = max(d0.textbbox((0, 0), l, font=f)[2] for l in lines)
                if w <= W * 0.88 and len(lines) * size * 1.12 <= H * 0.62:
                    break
                size -= 4
            return size

        text = text.upper()
        lines = [text]
        size = fit(lines)
        words = text.split(" ")
        if len(words) > 1:
            best, bd = 1, 1e9
            for i in range(1, len(words)):
                a, b = len(" ".join(words[:i])), len(" ".join(words[i:]))
                if abs(a - b) < bd:
                    best, bd = i, abs(a - b)
            l2 = [" ".join(words[:best]), " ".join(words[best:])]
            s2 = fit(l2)
            if s2 > size:
                size, lines = s2, l2
        self.size = size
        f = ImageFont.truetype(font_path, size)
        img = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(img)
        lh = size * 1.12
        cy = H * 0.42
        y0 = cy - lh * (len(lines) - 1) / 2
        for i, l in enumerate(lines):
            d.text((W / 2, y0 + i * lh), l, font=f, fill=255, anchor="mm")
        self.m = np.asarray(img, np.float32) / 255
        ys, xs = np.nonzero(self.m > 0.5)
        self.x0, self.x1, self.y0, self.y1 = xs.min(), xs.max(), ys.min(), ys.max()

    # ---- подтёки: точки на нижних краях букв ----
    def _anchors(self):
        B = self.m > 0.5
        below_empty = ~np.roll(B, -1, axis=0)
        flat = B & below_empty
        for dx in (-4, 4):
            flat &= np.roll(B, dx, axis=1) & np.roll(below_empty, dx, axis=1)
        ys, xs = np.nonzero(flat)
        idx = self.rng.permutation(len(xs))
        min_d = self.size * 0.2
        out = []
        for i in idx:
            x, y = int(xs[i]), int(ys[i])
            if all((x - o["x"]) ** 2 + (y - o["y"]) ** 2 >= min_d ** 2 for o in out):
                r = self.rng.random()
                out.append(dict(x=x, y=y, w=max(7.0, min(24.0, self.size * (0.045 + 0.04 * r))),
                                L=self.size * (0.16 + 0.32 * self.rng.random()),
                                ts=1.15 + self.rng.random() * 0.55))
            if len(out) >= 16:
                break
        self.anchors = out

    def _bubbles(self):
        out = []
        h = self.y1 - self.y0
        for _ in range(42):
            out.append(dict(x=self.rng.uniform(self.x0, self.x1), y=self.rng.uniform(self.y0, self.y1),
                            r=self.size * self.rng.uniform(0.03, 0.075), sp=self.rng.uniform(40, 110),
                            h=h))
        self.bub = out

    # ---- детали кадра ----
    def _drips(self, t):
        img = Image.new("L", (self.W, self.H), 0)
        d = ImageDraw.Draw(img)
        for a in self.anchors:
            p = (t - a["ts"]) / 0.75
            if p <= 0:
                continue
            L = a["L"] * (ease_out(p) if p < 1 else 1 - 0.55 * smooth(np.float32(p - 1), 0, 0.8))
            x, y, w = a["x"], a["y"], a["w"]
            d.rounded_rectangle((x - w / 2, y - 3, x + w / 2, y + L), radius=w / 2, fill=255)
            d.ellipse((x - w * 0.95, y - 7, x + w * 0.95, y + 7), fill=255)
            if p >= 1:
                q = t - a["ts"] - 0.75
                yy = y + a["L"] * 0.95 + 520 * q * q
                if yy < self.H + 20:
                    r = w * 0.55
                    d.ellipse((x - r, yy - r * 1.2, x + r, yy + r * 1.2), fill=255)
        return np.asarray(img, np.float32) / 255

    def _region(self, t):
        p = min(max((t - 0.15) / 1.1, 0), 1)
        e = p * p * (3 - 2 * p)
        ytop = self.y1 + 14 - e * (self.y1 - self.y0 + 30)
        amp = 7 * (1 - 0.4 * p)
        xs = np.arange(self.W, dtype=np.float32)
        surf = ytop + amp * np.sin(xs * 0.045 + 6 * t) + amp * 0.5 * np.sin(xs * 0.1 - 4.5 * t)
        yy = np.arange(self.H, dtype=np.float32)[:, None]
        return smooth(yy - surf[None, :], -1.5, 1.5)

    # ---- главный кадр ----
    def render(self, t):
        W, H = self.W, self.H
        liquid_src = np.clip(self.m * self._region(t) + self._drips(t), 0, 1)
        Lq = goo(liquid_src, 2.3)
        rgb = np.zeros((H, W, 3), np.float32)
        a = np.zeros((H, W), np.float32)
        # стекло
        rgb, a = over(rgb, a, np.broadcast_to(np.array([12, 48, 20], np.float32), (H, W, 3)), self.glass * 0.40)
        # контур жидкости
        dil = smooth(blur(Lq, 2.2), 0.15, 0.45)
        outline = np.clip(dil - Lq, 0, 1)
        dark = self.color * 0.42
        rgb, a = over(rgb, a, np.broadcast_to(dark, (H, W, 3)), outline)
        # заливка
        if self.style == "gloss":
            hgt = blur(Lq, 5.5)
            gy, gx = np.gradient(hgt)
            K = 16.0
            nx, ny, nz = -gx * K, -gy * K, np.ones_like(gx)
            n = np.sqrt(nx * nx + ny * ny + nz * nz)
            nx, ny, nz = nx / n, ny / n, nz / n
            Lv = np.array([-0.45, -0.6, 0.66], np.float32)
            Lv /= np.linalg.norm(Lv)
            Hv = Lv + np.array([0, 0, 1], np.float32)
            Hv /= np.linalg.norm(Hv)
            diff = np.clip(nx * Lv[0] + ny * Lv[1] + nz * Lv[2], 0, 1)
            spec = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0, 1) ** 42
            col = self.color[None, None, :] * (0.32 + 0.95 * diff)[..., None] + spec[..., None] * 235
            rgb, a = over(rgb, a, np.clip(col, 0, 255), Lq)
        else:
            rgb, a = over(rgb, a, np.broadcast_to(self.color, (H, W, 3)), Lq)
            low = np.clip(Lq - shift(Lq, 0, -11), 0, 1)
            rgb, a = over(rgb, a, np.broadcast_to(self.color * 0.7, (H, W, 3)), blur(low, 1.0) * Lq)
            top = np.clip(Lq - shift(Lq, 0, 5), 0, 1)
            rgb, a = over(rgb, a, np.broadcast_to(np.array([233, 255, 138], np.float32), (H, W, 3)), top * 0.9)
            lin = smooth(blur(Lq, 4.0), 0.7, 0.9)
            hl = np.clip(lin - shift(lin, 9, 11), 0, 1)
            rgb, a = over(rgb, a, np.full((H, W, 3), 255, np.float32), blur(hl, 1.0) * 0.9)
        # пузырьки
        bub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bub)
        for b in self.bub:
            y = b["y"] - t * b["sp"]
            span = b["h"] + 30
            y = self.y0 + ((y - self.y0) % span) - 10
            x = b["x"] + math.sin(t * 2 + b["x"]) * 2
            xi, yi = int(x), int(y)
            if not (0 <= xi < W and 0 <= yi < H) or Lq[yi, xi] < 0.97:
                continue
            r = b["r"] * (1 + 0.05 * math.sin(t * 2 + b["x"]))
            bd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 38), outline=(255, 255, 255, 170), width=2)
            bd.ellipse((x - r * 0.62, y - r * 0.68, x - r * 0.08, y - r * 0.32), fill=(255, 255, 255, 230))
        B = np.asarray(bub, np.float32)
        rgb, a = over(rgb, a, B[..., :3], B[..., 3] / 255 * Lq)
        # ободок стекла поверх
        rgb, a = over(rgb, a, np.broadcast_to(np.array([160, 255, 120], np.float32), (H, W, 3)), self.rim * 0.85)
        out = np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)
        return out


def background(w, h):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((x - w / 2) / (w * 0.7)) ** 2 + ((y - h * 0.1) / (h * 0.9)) ** 2)
    k = np.clip(d, 0, 1)[..., None]
    return (1 - k) * np.array([18, 48, 26], np.float32) + k * np.array([5, 11, 6], np.float32)


def to_rgb(rgba, bg):
    a = rgba[..., 3:4].astype(np.float32) / 255
    return np.clip(rgba[..., :3] * a + bg * (1 - a), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--font", required=True)
    ap.add_argument("--style", default="flat", choices=["flat", "gloss"])
    ap.add_argument("--size", default="800x450")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--dur", type=float, default=2.4)
    ap.add_argument("--video", help="webm/mp4 с тёмным фоном для просмотра")
    ap.add_argument("--png", help="RGBA PNG одного кадра")
    ap.add_argument("--t", type=float, default=2.0)
    ap.add_argument("--jpg", help="кадр на тёмном фоне (JPEG)")
    a = ap.parse_args()
    w, h = map(int, a.size.split("x"))
    s = Slime(a.text, a.font, w, h, a.style)
    bg = background(w, h)
    if a.png:
        Image.fromarray(s.render(a.t), "RGBA").save(a.png)
    if a.jpg:
        Image.fromarray(to_rgb(s.render(a.t), bg)).save(a.jpg, quality=82)
    if a.video:
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
               "-r", str(a.fps), "-i", "-", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34",
               "-pix_fmt", "yuv420p", a.video]
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(int(a.dur * a.fps)):
            pr.stdin.write(to_rgb(s.render(i / a.fps), bg).tobytes())
        pr.stdin.close()
        pr.wait()


if __name__ == "__main__":
    main()
