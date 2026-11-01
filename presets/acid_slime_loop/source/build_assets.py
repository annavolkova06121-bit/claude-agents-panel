#!/usr/bin/env python3
"""build_assets.py: пересобирает файлы пресета из исходников (нужно, только если меняется анимация или звук).

Что нужно: Node.js с пакетом playwright (chromium), ffmpeg, numpy (для нарезки звука).
Порядок:
  1. render_overlay.js рисует прозрачные кадры из overlay_source.html (1080x1920, 60 к/с):
       вступление  t = 0 ... 0,6 с   (плёнка стекает, дальше кадр пустой)
       концовка    t = 2,95 ... 3,6 с (подлёт из центра, удар, кадр закрыт)
  2. ffmpeg кодирует (цвет в BT.709): VP9 с альфой (overlay.webm) и запасную пару H.264 (RGB + матрица прозрачности).
  3. make_stems.py режет звук loop_sfx.wav на audio/intro.wav и audio/outro.wav.
Звук loop_sfx.wav создан tools/sfx_variants.py (вариант v5_acid, «Кислота и шипение»).

Запуск (из любой папки):  python build_assets.py [--keep-frames]
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FPS = 60
PARTS = {"intro": (0.0, 0.6), "outro": (2.95, 3.6)}


def run(argv):
    print("$", " ".join(map(str, argv)))
    subprocess.run(argv, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-frames", action="store_true")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="slime_overlay_"))
    try:
        for name, (t0, t1) in PARTS.items():
            frames = tmp / name
            run(["node", HERE / "render_overlay.js", HERE / "overlay_source.html", frames, FPS, t0, t1])
            out = ROOT / name
            out.mkdir(exist_ok=True)
            src = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", frames / "f_%04d.png"]
            # принудительно RGBA: у полностью непрозрачных кадров PNG бывает без альфа-канала.
            # Цвет кодируем матрицей BT.709 и помечаем её: плееры показывают HD-ролики именно так,
            # и слизь выглядит ровно в тех цветах, что на странице с анимацией.
            bt709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
            m709 = "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int"
            run(src + ["-vf", f"format=rgba,{m709},format=yuva420p"] + bt709 +
                ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
                 "-auto-alt-ref", "0", "-row-mt", "1", "-an", out / "overlay.webm"])
            run(src + ["-vf", f"format=rgba,format=rgb24,{m709},format=yuv420p"] + bt709 +
                ["-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", "-an", out / "overlay_rgb.mp4"])
            run(src + ["-vf", "format=rgba,alphaextract,format=gray", "-c:v", "libx264", "-preset", "slow", "-crf", "12",
                       "-pix_fmt", "yuv420p", "-an", out / "overlay_alpha.mp4"])
        run([sys.executable, HERE / "make_stems.py"])
    finally:
        if a.keep_frames:
            print("кадры оставлены в", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
