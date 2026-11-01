#!/usr/bin/env python3
"""make_stems.py: нарезает утверждённый звук цикла («Кислота и шипение», loop_sfx.wav, 3,6 с)
на две дорожки для автомонтажа: вступление (0-0,9 с) и концовка (2,95-3,6 с).

Дорожки сохраняют исходный уровень (пик концовки около -0,7 дБFS); приглушение делает
apply_preset.py по настройкам preset.json, поэтому уровень можно менять без перенарезки.
Срезы петли сглажены: вступление плавно нарастает (в петле здесь был хвост предыдущего
удара, в монтаже его нет), концовка плавно затухает (на конце ролика хвост обрывается).

Запуск:  python make_stems.py            (из папки source/, нужен numpy)
"""
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "loop_sfx.wav"

INTRO = (0.0, 0.90)      # сползание плёнки: шипение, капли, пузырьки
OUTRO = (2.95, 3.60)     # подлёт, удар, брызги
INTRO_FADE_IN, INTRO_FADE_OUT = 0.060, 0.060
OUTRO_FADE_IN, OUTRO_FADE_OUT = 0.004, 0.120


def read(p):
    with wave.open(str(p), "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        assert sw == 2, "ожидается 16 бит"
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return sr, x


def write(p, sr, x):
    y = np.clip(x, -1, 1)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())


def fade(x, sr, fin, fout):
    x = x.copy()
    a, b = int(fin * sr), int(fout * sr)
    if a:
        x[:a] *= np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if b:
        x[-b:] *= np.cos(np.linspace(0, np.pi / 2, b)) ** 2
    return x


def stat(name, x):
    pk = 20 * np.log10(np.abs(x).max() + 1e-9)
    rms = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
    print(f"{name}: {len(x)} отсчётов, пик {pk:.1f} дБFS, RMS {rms:.1f} дБFS")


def main():
    sr, x = read(SRC)
    cut = lambda a, b: x[int(a * sr):int(b * sr)]
    intro = fade(cut(*INTRO), sr, INTRO_FADE_IN, INTRO_FADE_OUT)
    outro = fade(cut(*OUTRO), sr, OUTRO_FADE_IN, OUTRO_FADE_OUT)
    (ROOT / "audio").mkdir(exist_ok=True)
    write(ROOT / "audio" / "intro.wav", sr, intro)
    write(ROOT / "audio" / "outro.wav", sr, outro)
    stat("intro", intro)
    stat("outro", outro)


if __name__ == "__main__":
    main()
