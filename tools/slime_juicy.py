#!/usr/bin/env python3
"""slime_juicy.py: статичные «сочные» кислотные буквы для субтитров и заголовков.

Без анимации построения: слово появляется сразу и выглядит готовым. Плотная заливка
с градиентом, глянец, толстая тёмная кромка, свечение, короткие подтёки, пузырьки.
Использование:
    from slime_juicy import Juicy
    rgba = Juicy("惑星を選べ", "MPLUSRounded1c-Black.ttf", palette="lime").render()
"""
import numpy as np
from PIL import Image, ImageDraw

from slime_text import Slime, blur, goo, over, shift, smooth

PALETTES = {
    "lime":   dict(top=(236, 255, 96), bot=(104, 232, 18), outline=(8, 36, 6), glow=(176, 255, 0)),
    "toxic":  dict(top=(150, 255, 104), bot=(26, 204, 44), outline=(4, 30, 10), glow=(60, 255, 40)),
    "yellow": dict(top=(255, 255, 120), bot=(186, 238, 0), outline=(30, 40, 0), glow=(226, 255, 0)),
}


class Juicy(Slime):
    def __init__(self, text, font_path, width=1000, height=420, palette="lime",
                 seed=7, drip=(0.06, 0.13), outline=7.0, glow=18.0):
        super().__init__(text, font_path, width, height, "gloss", seed=seed)
        self.pal = {k: np.array(v, np.float32) for k, v in PALETTES[palette].items()}
        self.outline, self.glow = outline, glow
        for a in self.anchors:
            a["L"] = self.size * (drip[0] + drip[1] * self.rng.random())

    def _static_drips(self):
        img = Image.new("L", (self.W, self.H), 0)
        d = ImageDraw.Draw(img)
        for a in self.anchors:
            x, y, w, L = a["x"], a["y"], a["w"], a["L"] * 0.85
            d.rounded_rectangle((x - w / 2, y - 3, x + w / 2, y + L), radius=w / 2, fill=255)
            d.ellipse((x - w * 0.95, y - 7, x + w * 0.95, y + 7), fill=255)
        return np.asarray(img, np.float32) / 255

    def render(self, pad=24):
        W, H = self.W, self.H
        P = self.pal
        Lq = goo(np.clip(self.m + self._static_drips(), 0, 1), 2.0)
        rgb = np.zeros((H, W, 3), np.float32)
        a = np.zeros((H, W), np.float32)
        full = lambda c: np.broadcast_to(c, (H, W, 3))
        glow = np.clip(blur(Lq, self.glow) * 1.7, 0, 1) * 0.75
        rgb, a = over(rgb, a, full(P["glow"]), glow)
        ol = smooth(blur(Lq, self.outline * 0.7), 0.06, 0.40)
        rgb, a = over(rgb, a, full(P["outline"]), np.clip(ol - Lq, 0, 1))
        # заливка: вертикальный градиент + подсветка по рельефу
        ty = np.clip((np.arange(H, dtype=np.float32) - self.y0) / max(1, self.y1 - self.y0), 0, 1)[:, None, None]
        base = P["top"][None, None, :] * (1 - ty) + P["bot"][None, None, :] * ty
        gy, gx = np.gradient(blur(Lq, 5.0))
        K = 18.0
        nx, ny, nz = -gx * K, -gy * K, np.ones_like(gx)
        n = np.sqrt(nx * nx + ny * ny + nz * nz)
        nx, ny, nz = nx / n, ny / n, nz / n
        Lv = np.array([-0.45, -0.6, 0.66], np.float32)
        Lv /= np.linalg.norm(Lv)
        Hv = Lv + np.array([0, 0, 1], np.float32)
        Hv /= np.linalg.norm(Hv)
        diff = np.clip(nx * Lv[0] + ny * Lv[1] + nz * Lv[2], 0, 1)
        spec = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0, 1) ** 38
        col = base * (0.62 + 0.62 * diff)[..., None] + spec[..., None] * 240
        rgb, a = over(rgb, a, np.clip(col, 0, 255), Lq)
        # внутренняя тёмная кромка для объёма
        inner = Lq - smooth(blur(Lq, 3.2), 0.62, 0.92)
        rgb, a = over(rgb, a, full(P["bot"] * 0.5), np.clip(inner, 0, 1) * 0.55)
        # блик по верхней кромке
        top = np.clip(Lq - shift(Lq, 0, 7), 0, 1)
        rgb, a = over(rgb, a, full(np.array([255, 255, 220], np.float32)), blur(top, 1.2) * 0.55)
        # пузырьки
        bub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bub)
        for b in self.bub[:22]:
            x, y, r = b["x"], b["y"], b["r"] * 0.8
            if Lq[int(y), int(x)] < 0.97:
                continue
            bd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 40), outline=(255, 255, 255, 190), width=2)
            bd.ellipse((x - r * 0.62, y - r * 0.68, x - r * 0.08, y - r * 0.32), fill=(255, 255, 255, 235))
        B = np.asarray(bub, np.float32)
        rgb, a = over(rgb, a, B[..., :3], B[..., 3] / 255 * Lq)
        out = np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)
        ys, xs = np.nonzero(out[..., 3] > 6)
        y0, y1 = max(0, ys.min() - 2), min(H, ys.max() + 3)
        x0, x1 = max(0, xs.min() - 2), min(W, xs.max() + 3)
        return out[y0:y1, x0:x1]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--font", required=True)
    ap.add_argument("--palette", default="lime", choices=list(PALETTES))
    ap.add_argument("--out", default="caption.png")
    a = ap.parse_args()
    Image.fromarray(Juicy(a.text, a.font, palette=a.palette).render(), "RGBA").save(a.out)
