#!/usr/bin/env python3
"""build_theme_preset.py: собирает пресеты «Лава» и «Море» из общего исходника анимации и синтезированного звука.

  python build_theme_preset.py lava        # -> presets/lava_loop
  python build_theme_preset.py sea         # -> presets/sea_loop
  python build_theme_preset.py lava --sound-only    # пересобрать только звук и настройки громкости

Что делает:
  1. рисует прозрачные кадры из overlay_themed.html (параметр theme=lava|sea), кодирует в BT.709:
     VP9 с альфой и запасную пару H.264 (RGB + матрица), как у пресета «Кислотная слизь»;
  2. синтезирует звук (tools/sfx_themes.py), выравнивает его по громкости (LUFS) со звуком «Кислоты и шипения»;
  3. режет звук на дорожки вступления и концовки, подбирает усиление по пиковой громкости (momentary LUFS),
     чтобы по умолчанию все три стиля звучали одинаково громко;
  4. пишет preset.json на основе пресета «Кислотная слизь».
Нужны: Node.js + playwright (chromium), ffmpeg, numpy.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PRESETS = HERE.parent
REPO = PRESETS.parent
ACID = PRESETS / "acid_slime_loop"
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(ACID / "source"))
import make_stems as ms  # noqa: E402
import sfx_themes  # noqa: E402

FPS = 60
PARTS = {"intro": (0.0, 0.6), "outro": (2.95, 3.6)}
THEMES = {
    "lava": dict(folder="lava_loop", fn=sfx_themes.v_lava, title="Лава: вступление и плюха",
                 desc="Автомонтаж: в начале ролика стекает раскалённая лава, в конце из центра прилетает огненная плюха и закрывает кадр. "
                      "Звук: гул, густые блопы, пар, треск углей и тяжёлый удар; приглушён и уходит под голос."),
    "lavar": dict(folder="lava_real_loop", fn=sfx_themes.v_lava, title="Лава объёмная: вступление и плюха",
                  desc="Автомонтаж: в начале ролика стекает расплавленная лава (тёмная корка, светящиеся трещины, янтарные капли, языки пламени), "
                       "в конце из центра прилетает огненная плюха и закрывает кадр. Звук как у стиля «Лава»; приглушён и уходит под голос."),
    "sea": dict(folder="sea_loop", fn=sfx_themes.v_sea, title="Море: вступление и плюха",
                desc="Автомонтаж: в начале ролика вода стекает пенной волной, в конце из центра прилетает водяная плюха и закрывает кадр. "
                     "Звук: бегущая вода, пузыри, капли и большой всплеск; приглушён и уходит под голос."),
}


def run(argv, **kw):
    print("$", " ".join(map(str, argv)))
    return subprocess.run([str(a) for a in argv], check=True, **kw)


def lufs(path):
    """Интегральная громкость файла, LUFS."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    s = r.stderr.decode("utf-8", "replace")
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", s.split("Summary:")[-1])[0])


def max_momentary(path):
    """Наибольшая моментальная громкость (окно 400 мс), LUFS."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    m = [float(v) for v in re.findall(r"M:\s*(-?[\d.]+)", r.stderr.decode("utf-8", "replace").split("Summary:")[0])]
    return max(m)


def build_sound(key, spec, root):
    """Звук: синтез -> выравнивание с «Кислотой» -> дорожки -> усиления по умолчанию."""
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "audio").mkdir(exist_ok=True)
    x = spec["fn"]()
    tmp = Path(tempfile.mkdtemp(prefix="theme_snd_"))
    try:
        sfx_themes.save(str(tmp / "raw.wav"), x)
        ref = lufs(ACID / "source" / "loop_sfx.wav")
        new = lufs(tmp / "raw.wav")
        k = 10 ** ((ref - new) / 20)
        print(f"громкость петли {new:.1f} LUFS -> {ref:.1f} LUFS (x{k:.3f})")
        sfx_themes.save(str(root / "source" / "loop_sfx.wav"), (x * k).astype(np.float32))
        sr, y = ms.read(root / "source" / "loop_sfx.wav")
        cut = lambda a, b: y[int(a * sr):int(b * sr)]
        intro = ms.fade(cut(*ms.INTRO), sr, ms.INTRO_FADE_IN, ms.INTRO_FADE_OUT)
        outro = ms.fade(cut(*ms.OUTRO), sr, ms.OUTRO_FADE_IN, ms.OUTRO_FADE_OUT)
        ms.write(root / "audio" / "intro.wav", sr, intro)
        ms.write(root / "audio" / "outro.wav", sr, outro)
        # выравнивание дорожек по пиковой моментальной громкости с «Кислотой»
        d_in = max_momentary(ACID / "audio" / "intro.wav") - max_momentary(root / "audio" / "intro.wav")
        d_out = max_momentary(ACID / "audio" / "outro.wav") - max_momentary(root / "audio" / "outro.wav")
        print(f"поправка усиления: вступление {d_in:+.1f} дБ, концовка {d_out:+.1f} дБ")
        return round(d_in * 2) / 2, round(d_out * 2) / 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_json(key, spec, root, d_in, d_out):
    cfg = json.loads((ACID / "preset.json").read_text(encoding="utf-8"))
    cfg["name"], cfg["title"], cfg["description"] = spec["folder"], spec["title"], spec["desc"]
    cfg["intro"]["audio_gain_db"] = cfg["intro"]["audio_gain_db"] + d_in
    cfg["outro"]["audio_gain_db"] = cfg["outro"]["audio_gain_db"] + d_out
    for name, v in list(cfg["levels"].items()):
        if name != "note":
            cfg["levels"][name] = [v[0] + d_in, v[1] + d_out]
    cfg["intro"]["note"] = "Звук вступления тише всего и со срезом верхов; усиление выровнено по громкости с «Кислотой»."
    (root / "preset.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_overlays(key, root, keep):
    tmp = Path(tempfile.mkdtemp(prefix="theme_overlay_"))
    try:
        for name, (t0, t1) in PARTS.items():
            frames = tmp / name
            run(["node", HERE / "render_overlay.js", HERE / "overlay_themed.html", frames, FPS, t0, t1, f"theme={key}"])
            out = root / name
            out.mkdir(exist_ok=True)
            src = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", frames / "f_%04d.png"]
            bt709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
            m709 = "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int"
            run(src + ["-vf", f"format=rgba,{m709},format=yuva420p"] + bt709 +
                ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-auto-alt-ref", "0",
                 "-row-mt", "1", "-an", out / "overlay.webm"])
            run(src + ["-vf", f"format=rgba,format=rgb24,{m709},format=yuv420p"] + bt709 +
                ["-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", "-an", out / "overlay_rgb.mp4"])
            run(src + ["-vf", "format=rgba,alphaextract,format=gray", "-c:v", "libx264", "-preset", "slow", "-crf", "12",
                       "-pix_fmt", "yuv420p", "-an", out / "overlay_alpha.mp4"])
    finally:
        if keep:
            print("кадры оставлены в", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("theme", choices=sorted(THEMES))
    ap.add_argument("--sound-only", action="store_true")
    ap.add_argument("--keep-frames", action="store_true")
    a = ap.parse_args()
    spec = THEMES[a.theme]
    root = PRESETS / spec["folder"]
    root.mkdir(exist_ok=True)
    d_in, d_out = build_sound(a.theme, spec, root)
    write_json(a.theme, spec, root, d_in, d_out)
    if not a.sound_only:
        build_overlays(a.theme, root, a.keep_frames)
    print("готово:", root)


if __name__ == "__main__":
    main()
