#!/usr/bin/env python3
"""caption.py: подписи шрифтом Shorts Marker в нескольких стилях (нужны только Pillow и numpy).

Начертания: regular, bold, extrabold. Стили:
  цвета:  classic (белый), yellow (#FAC50C как в вашем видео), green, red, blue, pink
  темы:   acid (токсичный: салатовый градиент, пузыри), lava (лава: огненный градиент, корка и трещины, угольки),
          sea (море: градиент от пены к глубине, световые блики воды, пузыри)
  тень:   shadow=True добавляет мягкую тень под буквами (у любого стиля)

  python caption.py "ПРИВЕТ" out.png --style lava --weight extrabold --shadow
В коде:
  from caption import render_caption
  render_caption("ЗАТЫКАЕТ", style="acid", weight="bold", shadow=True).save("word.png")   # RGBA с прозрачным фоном
Размеры: кегль 143 px даёт высоту прописной около 100 px в кадре 1080x1920 (так в исходном видео).
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
WEIGHTS = {"regular": "ShortsMarker-Regular.ttf", "bold": "ShortsMarker-Bold.ttf", "extrabold": "ShortsMarker-ExtraBold.ttf"}
OUTLINE_PER_SIZE = 0.063          # обводка: 9 px при кегле 143, как в видео
BLACK = (0, 0, 0)


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# --- стили: fill = сплошной цвет или список остановок градиента [(позиция 0..1 сверху вниз, '#hex'), ...]
STYLES = {
    "classic": dict(fill="#FFFFFF", outline="#000000"),
    "yellow":  dict(fill="#FAC50C", outline="#000000"),
    "green":   dict(fill="#43E05A", outline="#000000"),
    "red":     dict(fill="#FF4338", outline="#000000"),
    "blue":    dict(fill="#38A6FF", outline="#000000"),
    "pink":    dict(fill="#FF5CAA", outline="#000000"),
    "acid": dict(fill=[(0, "#f5ff3a"), (.5, "#c4ff12"), (1, "#33ff1a")], outline="#0a2e0a", glow=("#c8ff00", .55), tex="bubbles", shadow_color="#031a03"),
    "lava": dict(fill=[(0, "#fff0a0"), (.3, "#ffb61e"), (.65, "#ff5a0f"), (1, "#c81a06")], outline="#2a0802", glow=("#ff6a00", .6), tex="crust", shadow_color="#1a0300"),
    "sea":  dict(fill=[(0, "#d2fbff"), (.4, "#2cc0f4"), (1, "#0a54c8")], outline="#041f4d", glow=("#46d2ff", .55), tex="caustics", shadow_color="#02112e"),
}


def _noise(w, h, scale, seed):
    rng = np.random.default_rng(seed)
    a = rng.random((h // scale + 3, w // scale + 3)).astype(np.float32)
    im = Image.fromarray((a * 255).astype("uint8")).resize((w, h), Image.BICUBIC)
    return np.asarray(im, np.float32) / 255


def _gradient(w, h, stops, y0, y1):
    ys = np.clip((np.arange(h) - y0) / max(1, y1 - y0), 0, 1)
    pos = [s[0] for s in stops]
    cols = np.array([hexc(s[1]) for s in stops], np.float32)
    col = np.stack([np.interp(ys, pos, cols[:, k]) for k in range(3)], 1)
    return np.repeat(col[:, None, :], w, 1)


def _texture(kind, rgb, w, h, size, seed=7):
    """Рисует поверх градиента узор темы; возвращает RGB-массив."""
    img = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).convert("RGBA")
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rng = np.random.default_rng(seed)
    u = size / 143.0
    if kind == "bubbles":
        for _ in range(int(w * h / (3200 * u * u))):
            r = rng.uniform(3, 11) * u; x, y = rng.uniform(0, w), rng.uniform(0, h)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 40), outline=(255, 255, 255, 150), width=max(1, int(1.5 * u)))
            d.ellipse([x - r * .55, y - r * .6, x - r * .1, y - r * .3], fill=(255, 255, 255, 220))
    elif kind == "crust":
        n1 = _noise(w, h, max(6, int(14 * u)), seed) * .65 + _noise(w, h, max(3, int(6 * u)), seed + 1) * .35
        rim = ((n1 > .605) & (n1 <= .632))
        crust = (n1 > .632)
        a = np.zeros((h, w, 4), np.uint8)
        a[crust] = (78, 14, 4, 205)
        a[rim] = (255, 196, 70, 255)
        ov = Image.alpha_composite(ov, Image.fromarray(a))
        d = ImageDraw.Draw(ov)
        for _ in range(int(w * h / (1500 * u * u))):
            x, y = rng.uniform(0, w), rng.uniform(0, h); r = rng.uniform(.7, 1.6) * u
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 235, 140, 230))
    elif kind == "caustics":
        n1 = _noise(w, h, max(8, int(18 * u)), seed) * 7
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        v = np.sin(xx / (11 * u) + n1) + np.sin(yy / (8 * u) - n1 * .7) + np.sin((xx + yy) / (15 * u) + n1 * 1.3)
        line = np.clip(1 - np.abs(v) / .42, 0, 1) ** 1.6
        a = np.zeros((h, w, 4), np.uint8); a[..., :3] = 255; a[..., 3] = (line * 150).astype(np.uint8)
        ov = Image.alpha_composite(ov, Image.fromarray(a))
        d = ImageDraw.Draw(ov)
        for _ in range(int(w * h / (6000 * u * u))):
            r = rng.uniform(2, 6) * u; x, y = rng.uniform(0, w), rng.uniform(0, h)
            d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, 170), width=max(1, int(1.2 * u)))
    return np.asarray(Image.alpha_composite(img, ov).convert("RGB"), np.float32)


def render_caption(text, style="classic", weight="bold", size=143, shadow=False, accent=False):
    """RGBA-картинка с подписью. accent=True красит заливку в жёлтый (#FAC50C) вместо стиля."""
    st = dict(STYLES["yellow" if accent and style == "classic" else style])
    font = ImageFont.truetype(str(HERE / WEIGHTS[weight]), size)
    ow = max(1, int(round(size * OUTLINE_PER_SIZE)))
    mg = int(size * 0.5)                                              # поля под тень и свечение
    l, t, r, b = font.getbbox(text, stroke_width=ow, anchor="ls")
    W, H = r - l + 2 * mg, b - t + 2 * mg
    pos = (mg - l, mg - t)
    fill_m = Image.new("L", (W, H), 0); ImageDraw.Draw(fill_m).text(pos, text, font=font, anchor="ls", fill=255)
    outer_m = Image.new("L", (W, H), 0); ImageDraw.Draw(outer_m).text(pos, text, font=font, anchor="ls", fill=255, stroke_width=ow)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if shadow:
        sc = hexc(st.get("shadow_color", "#000000"))
        dx, dy, bl = int(size * .03), int(size * .055), max(1, int(size * .018))
        sh = ImageChops.offset(outer_m, dx, dy).filter(ImageFilter.GaussianBlur(bl))
        out = Image.alpha_composite(out, Image.merge("RGBA", [Image.new("L", (W, H), c) for c in sc] + [sh.point(lambda v: int(v * .6))]))
    if "glow" in st:
        gc, ga = st["glow"]
        gl = outer_m.filter(ImageFilter.GaussianBlur(max(2, int(size * .06)))).point(lambda v: min(255, int(v * 1.4 * ga)))
        out = Image.alpha_composite(out, Image.merge("RGBA", [Image.new("L", (W, H), c) for c in hexc(gc)] + [gl]))
    oc = hexc(st["outline"])
    out = Image.alpha_composite(out, Image.merge("RGBA", [Image.new("L", (W, H), c) for c in oc] + [outer_m]))
    ys = np.where(np.asarray(fill_m).any(1))[0]
    y0, y1 = (ys.min(), ys.max()) if len(ys) else (0, H)
    if isinstance(st["fill"], str):
        rgb = np.broadcast_to(np.array(hexc(st["fill"]), np.float32), (H, W, 3)).copy()
    else:
        rgb = _gradient(W, H, st["fill"], y0, y1)
    if "tex" in st:
        rgb = _texture(st["tex"], rgb, W, H, size)
    # блик: светлая полоса в верхней трети букв
    gloss = np.clip(1 - (np.arange(H) - y0) / max(1, (y1 - y0) * .45), 0, 1)[:, None, None] * 38
    rgb = np.clip(rgb + gloss, 0, 255)
    fill_img = Image.fromarray(rgb.astype("uint8"), "RGB").convert("RGBA"); fill_img.putalpha(fill_m)
    out = Image.alpha_composite(out, fill_img)
    bbox = out.getbbox()
    return out.crop(bbox) if bbox else out


def main():
    ap = argparse.ArgumentParser(description="Подпись шрифтом Shorts Marker")
    ap.add_argument("text")
    ap.add_argument("out")
    ap.add_argument("--style", default="classic", choices=sorted(STYLES))
    ap.add_argument("--weight", default="bold", choices=sorted(WEIGHTS))
    ap.add_argument("--size", type=int, default=143, help="кегль, px (143 = высота прописной 100 px)")
    ap.add_argument("--shadow", action="store_true", help="добавить мягкую тень")
    ap.add_argument("--accent", action="store_true", help="жёлтая заливка #FAC50C (для стиля classic)")
    a = ap.parse_args()
    render_caption(a.text, a.style, a.weight, a.size, a.shadow, a.accent).save(a.out)
    print("сохранено:", a.out)


if __name__ == "__main__":
    main()
