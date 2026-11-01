#!/usr/bin/env python3
"""selftest.py: проверка пресета на этом компьютере (нужны только Python и ffmpeg).

Делает тестовый ролик 1080x1920 (синий фон, тон 220 Гц с уровнем речи (около -15 дБFS RMS) как «голос»), накладывает пресет и проверяет:
  1. первый и последний кадры закрыты кислотной массой (зелёные);
  2. середина ролика не тронута (цвет совпадает с исходником);
  3. длина и дорожки не изменились;
  4. звук не клиппует, середина по громкости как в исходнике, а в окнах пресета звук добавлен;
  5. приглушение под голосом работает (громкость вступления с «голосом» ниже, чем без него).
Запуск:  python selftest.py [--ffmpeg путь]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_preset as ap  # noqa: E402

W, H, FPS, DUR = 1080, 1920, 30, 3.0


def run(argv):
    r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-500:])
    return r


def mean_rgb(ff, path, t):
    """Средний цвет кадра в момент t (масштабируем до 1x1 пикселя; цвет читаем как BT.709, как плееры)."""
    r = run([ff, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
             "-vf", "scale=1:1:flags=area:in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    return tuple(r.stdout[:3])


def volume(ff, path, t0, t1):
    """(средняя, пиковая) громкость в окне, дБ."""
    r = subprocess.run([ff, "-hide_banner", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(path), "-vn",
                        "-af", "volumedetect", "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    s = r.stdout.decode("utf-8", "replace")
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", s)
    p = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", s)
    f = lambda x: float("-inf") if x is None or x.group(1) == "-inf" else float(x.group(1))
    return f(m), f(p)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--ffmpeg")
    a.add_argument("--keep", action="store_true", help="не удалять временные файлы")
    o = a.parse_args()
    ff, fp = ap._tools(o.ffmpeg)
    tmp = Path(tempfile.mkdtemp(prefix="slime_selftest_"))
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(("OK   " if ok else "СБОЙ ") + name + (f": {detail}" if detail else ""))

    src, dst, dst_nd = tmp / "src.mp4", tmp / "out.mp4", tmp / "out_noduck.mp4"
    run([ff, "-hide_banner", "-y", "-f", "lavfi", "-i", f"color=c=0x2a4a7a:s={W}x{H}:r={FPS}:d={DUR}",
         "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={DUR}", "-af", "volume=6dB",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", "-c:a", "aac", "-b:a", "192k", str(src)])
    ap.apply_preset(src, dst, ffmpeg=o.ffmpeg, log=lambda *_: None)
    ap.apply_preset(src, dst_nd, duck=False, ffmpeg=o.ffmpeg, log=lambda *_: None)

    m_in, m_out = ap.probe(fp, src), ap.probe(fp, dst)
    check("длина не изменилась", abs(m_in["duration"] - m_out["duration"]) < 0.1, f"{m_in['duration']:.2f} -> {m_out['duration']:.2f} с")
    check("размер и звук на месте", (m_out["width"], m_out["height"]) == (W, H) and m_out["audio"] is not None)

    first, last = mean_rgb(ff, dst, 0.0), mean_rgb(ff, dst, DUR - 1.5 / FPS)
    green = lambda c: c[1] > 190 and c[2] < 130 and c[1] > c[2] + 80
    check("первый кадр закрыт массой", green(first), f"RGB {first}")
    check("последний кадр закрыт массой", green(last), f"RGB {last}")
    mid_in, mid_out = mean_rgb(ff, src, 1.5), mean_rgb(ff, dst, 1.5)
    check("середина не тронута", max(abs(x - y) for x, y in zip(mid_in, mid_out)) <= 4, f"{mid_in} -> {mid_out}")

    base_mid = volume(ff, src, 1.2, 1.8)
    out_mid = volume(ff, dst, 1.2, 1.8)
    check("громкость середины прежняя", abs(base_mid[0] - out_mid[0]) < 1.5, f"{base_mid[0]:.1f} -> {out_mid[0]:.1f} дБ")
    whole = volume(ff, dst, 0, DUR)
    check("нет клиппинга", whole[1] <= -0.3, f"пик {whole[1]:.1f} дБ")
    i_src, i_duck, i_free = volume(ff, src, 0.0, 0.9), volume(ff, dst, 0.0, 0.9), volume(ff, dst_nd, 0.0, 0.9)
    check("звук вступления добавлен", i_free[1] > i_src[1] + 0.5 or i_free[0] > i_src[0] + 0.3,
          f"пик {i_src[1]:.1f} -> {i_free[1]:.1f} дБ")
    check("приглушение под голосом работает", i_duck[1] < i_free[1] - 1.0 or i_duck[0] < i_free[0] - 1.0,
          f"с ducking {i_duck[0]:.1f}/{i_duck[1]:.1f}, без {i_free[0]:.1f}/{i_free[1]:.1f} дБ (средняя/пик)")
    if not o.keep:
        for f in (src, dst, dst_nd):
            f.unlink(missing_ok=True)
        tmp.rmdir()
    print(f"\n{sum(results)}/{len(results)} проверок пройдено" + (" — пресет работает" if all(results) else " — есть сбои"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
