#!/usr/bin/env python3
"""build_font.py: собирает ShortsMarker-Regular.ttf из растровых глифов (source/glyphs) и отступов (source/glyphs.json).

Нужны: Python 3, fonttools, numpy, Pillow и утилита potrace (в PATH).  Запуск:  python build_font.py
Глифы лежат в координатах холста: высота прописной 600 px, базовая линия y=760; каждый PNG обрезан по контуру,
положение (left, top) записано в glyphs.json вместе с отступами lsb/rsb. Чтобы поправить букву, откройте её PNG
в любом растровом редакторе (чёрное = краска), сохраните и запустите сборку заново.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import argparse

import numpy as np
from scipy import ndimage as ndi
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image

HERE = Path(__file__).resolve().parent
# начертания: радиус утолщения контура в пикселях холста (толщина штриха Regular около 70 px) и дополнительный отступ
WEIGHTS = {
    "Regular": dict(r=0, cls=400, style="Regular", family="Shorts Marker"),
    "Bold": dict(r=10, cls=700, style="Bold", family="Shorts Marker"),
    "ExtraBold": dict(r=21, cls=800, style="Regular", family="Shorts Marker ExtraBold", typo=("Shorts Marker", "ExtraBold")),
}
UPM, CAPU = 1000, 700
meta = json.loads((HERE / "glyphs.json").read_text(encoding="utf-8"))
BASEY, CAP = meta["baseline_y"], meta["cap_height_px"]
S = CAPU / CAP


def load_glyph(png, r):
    """PNG глифа; при r>0 контур утолщается на r пикселей (круглая кисть) и слегка сглаживается."""
    im = Image.open(png).convert("L")
    if r <= 0:
        return im
    ink = np.array(im) < 128
    pad = r + 4
    big = np.zeros((ink.shape[0] + 2 * pad, ink.shape[1] + 2 * pad), bool)
    big[pad:-pad, pad:-pad] = ink
    grown = ndi.distance_transform_edt(~big) <= r
    grown = ndi.gaussian_filter(grown.astype(np.float32), 2.0) > 0.5
    return Image.fromarray(np.where(grown, 0, 255).astype("uint8"))


def trace(im, tmp):
    """Растр -> контуры (кубические кривые) через potrace; координаты в пикселях глифа."""
    pad = 6
    big = Image.new("L", (im.size[0] + 2 * pad, im.size[1] + 2 * pad), 255)
    big.paste(im, (pad, pad))
    bmp, svgp = tmp / "g.bmp", tmp / "g.svg"
    big.save(bmp)
    subprocess.run(["potrace", "-s", "-o", str(svgp), str(bmp), "-t", "40", "-a", "1.1", "-O", "0.5", "-u", "10"], check=True)
    svg = svgp.read_text()
    H = float(re.search(r"translate\(0\.?\d*,([\d.]+)\)", svg).group(1))
    d = " ".join(re.findall(r' d="([^"]+)"', svg))
    toks = re.findall(r"[MmLlCcZz]|-?\d+(?:\.\d+)?", d)
    contours, cur, pos, cmd, i = [], None, (0.0, 0.0), None, 0
    P = lambda x, y: (x / 10.0 - pad, (H - y / 10.0) - pad)   # в систему координат обрезанного PNG
    while i < len(toks):
        t = toks[i]
        if t in "MmLlCcZz":
            cmd = t
            i += 1
        if cmd in "Mm":
            x, y = float(toks[i]), float(toks[i + 1]); i += 2
            if cmd == "m":
                x += pos[0]; y += pos[1]
            pos = (x, y); cur = [("M", P(x, y))]; contours.append(cur); cmd = "l" if cmd == "m" else "L"
        elif cmd in "Ll":
            x, y = float(toks[i]), float(toks[i + 1]); i += 2
            if cmd == "l":
                x += pos[0]; y += pos[1]
            pos = (x, y); cur.append(("L", P(x, y)))
        elif cmd in "Cc":
            v = [float(t) for t in toks[i:i + 6]]; i += 6
            if cmd == "c":
                v = [v[0] + pos[0], v[1] + pos[1], v[2] + pos[0], v[3] + pos[1], v[4] + pos[0], v[5] + pos[1]]
            pos = (v[4], v[5]); cur.append(("C", P(v[0], v[1]), P(v[2], v[3]), P(v[4], v[5])))
        elif cmd in "Zz":
            cmd = None
    return contours


def area(c):
    pts = [p for seg in c for p in seg[1:]]
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) / 2


def build_glyph(name, g, tmp, r):
    cont = trace(load_glyph(HERE / "glyphs" / f"{name}.png", r), tmp)
    flip = area(max(cont, key=lambda c: abs(area(c)))) > 0     # внешний контур TrueType идёт по часовой стрелке
    e = 0.45 * r                                                 # утолщённые начертания чуть просторнее
    lsb_n, rsb_n = g["lsb"] - r + e, g["rsb"] - r + e
    ox = lsb_n                                                   # левый край (уже с утолщением) ставится на lsb
    top = g["top"] - r
    pen = TTGlyphPen(None)
    cp = Cu2QuPen(pen, max_err=1.2, reverse_direction=flip)
    X = lambda p: (p[0] + ox) * S
    Y = lambda p: (BASEY - (p[1] + top)) * S
    for c in cont:
        cp.moveTo((X(c[0][1]), Y(c[0][1])))
        for seg in c[1:]:
            if seg[0] == "L":
                cp.lineTo((X(seg[1]), Y(seg[1])))
            else:
                cp.curveTo(*[(X(p), Y(p)) for p in seg[1:]])
        cp.closePath()
    adv = int(round((g["w"] + 2 * r + lsb_n + rsb_n) * S))
    return pen.glyph(), adv, int(round(lsb_n * S))


def build(weight):
    W = WEIGHTS[weight]
    out = HERE.parent / f"ShortsMarker-{weight}.ttf"
    glyphs, adv, lsb, order, cmap_chars = {}, {}, {}, [".notdef", "space"], {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, g in sorted(meta["glyphs"].items()):
            glyphs[name], adv[name], lsb[name] = build_glyph(name, g, tmp, W["r"])
            order.append(name)
            cmap_chars[g["char"]] = name
    glyphs[".notdef"] = TTGlyphPen(None).glyph(); adv[".notdef"] = 500; lsb[".notdef"] = 0
    glyphs["space"] = TTGlyphPen(None).glyph(); adv["space"] = 300; lsb["space"] = 0
    cmap = {0x20: "space", 0xA0: "space"}
    for c in "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯЁ":          # заглавные и строчные -> одни и те же глифы
        if c in cmap_chars:
            cmap[ord(c)] = cmap_chars[c]; cmap[ord(c.lower())] = cmap_chars[c]
    for lat, cyr in {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У"}.items():
        cmap[ord(lat)] = cmap_chars[cyr]; cmap[ord(lat.lower())] = cmap_chars[cyr]      # латинские двойники
    for ch in '0123456789.,!?:;-—()"':
        if ch in cmap_chars:
            cmap[ord(ch)] = cmap_chars[ch]
    cmap[0x2013] = cmap_chars["-"]; cmap[0xAB] = cmap_chars['"']; cmap[0xBB] = cmap_chars['"']
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap); fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({k: (adv[k], lsb[k]) for k in order})
    fb.setupHorizontalHeader(ascent=900, descent=-320)
    full = W["family"] if W["style"] == "Regular" else f'{W["family"]} {W["style"]}'
    fb.setupNameTable({"familyName": W["family"], "styleName": W["style"], "uniqueFontIdentifier": f"ShortsMarker-{weight}",
                       "fullName": full, "psName": f"ShortsMarker-{weight}", "version": "Version 1.000",
                       "copyright": "Letterforms reconstructed from the author's video captions"})
    if "typo" in W:                                                  # типографская семья: «Shorts Marker» + «ExtraBold»
        fb.font["name"].setName(W["typo"][0], 16, 3, 1, 0x409); fb.font["name"].setName(W["typo"][1], 17, 3, 1, 0x409)
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-320, usWinAscent=1000, usWinDescent=360, sCapHeight=CAPU, sxHeight=CAPU,
                fsType=0, achVendID="SHMK", ulUnicodeRange1=0, ulCodePageRange1=(1 << 2) | (1 << 0), usWeightClass=W["cls"])
    if weight == "Bold":
        fb.font["head"].macStyle = 1; fb.font["OS/2"].fsSelection = (fb.font["OS/2"].fsSelection | 0x20) & ~0x40
    fb.setupPost(isFixedPitch=0)
    fb.save(str(out))
    print("шрифт сохранён:", out, "| глифов:", len(order))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weights", nargs="*", default=list(WEIGHTS), help="Regular Bold ExtraBold (по умолчанию все)")
    for w in ap.parse_args().weights:
        build(w)


if __name__ == "__main__":
    sys.exit(main())
