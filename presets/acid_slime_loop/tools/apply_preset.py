#!/usr/bin/env python3
"""apply_preset.py: накладывает пресет «Кислотная слизь» на готовый ролик.

Что делает:
  * в начале ролика поверх первых ~0,6 с накладывает кислотную плёнку, которая стекает и открывает кадр;
  * в конце ролика поверх последних ~0,67 с накладывает плюху, которая прилетает из центра и закрывает кадр;
  * подмешивает звук «Кислота и шипение»: вступление приглушено (по умолчанию -14 дБ, со срезом верхов),
    концовка -12 дБ, а под голосом основной дорожки звук пресета прижимается ещё на 4-5 дБ
    (sidechain-ducking). Основная дорожка не меняется, на выходе стоит страховочный лимитер.
Длина ролика не меняется. Картинка вне окон 0-0,62 с и последних 0,67 с остаётся как была (но
пережимается кодером, см. --vargs).

Только стандартная библиотека Python 3.8+ и ffmpeg (>= 4.4 желательно).

Примеры:
  python apply_preset.py in.mp4 out.mp4
  python apply_preset.py in.mp4 out.mp4 --level quiet          # тише (loud = громче)
  python apply_preset.py in.mp4 out.mp4 --intro-db -20 --outro-db -12
  python apply_preset.py in.mp4 out.mp4 --no-outro
  python apply_preset.py --check                      # проверка ffmpeg и файлов пресета
Из кода монтажа:
  sys.path.insert(0, r"C:\\ShortsFactory\\presets\\acid_slime_loop\\tools")
  from apply_preset import apply_preset
  apply_preset("jobs/ID/final_edit.mp4", "jobs/ID/final_slime.mp4")
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parent.parent
WIN_FFMPEG_DIR = Path(r"C:\ShortsFactory\ffmpeg\bin")


# ---------------------------------------------------------------- поиск ffmpeg и проверка возможностей
def find_tool(name, explicit=None, hint_dir=None):
    """ffmpeg/ffprobe: аргумент -> папка рядом с указанным ffmpeg -> переменная окружения ->
    C:\\ShortsFactory\\ffmpeg\\bin -> PATH."""
    suffix = ".exe" if os.name == "nt" else ""
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            p = p / (name + suffix)
        if p.exists():
            return str(p)
        raise FileNotFoundError(f"{name}: не найден по пути {explicit}")
    if hint_dir:
        p = Path(hint_dir) / (name + suffix)
        if p.exists():
            return str(p)
    env = os.environ.get(name.upper())
    if env and Path(env).exists():
        return env
    exe = WIN_FFMPEG_DIR / (name + ".exe")
    if exe.exists():
        return str(exe)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} не найден (укажите --ffmpeg или переменную окружения {name.upper()})")


def _tools(ffmpeg=None, ffprobe=None):
    ff = find_tool("ffmpeg", ffmpeg)
    return ff, find_tool("ffprobe", ffprobe, hint_dir=Path(ff).parent)


def _out(argv):
    r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return r.stdout.decode("utf-8", "replace")


def capabilities(ffmpeg):
    """Какие возможности есть в этой сборке ffmpeg (от них зависит схема сборки)."""
    base = [ffmpeg, "-hide_banner"]
    dec, flt = _out(base + ["-decoders"]), _out(base + ["-filters"])
    amix = _out(base + ["-h", "filter=amix"])
    return {
        "libvpx_vp9": "libvpx-vp9" in dec,          # прозрачность WebM читает только он
        "alphamerge": " alphamerge " in flt,
        "sidechaincompress": " sidechaincompress " in flt,
        "alimiter": " alimiter " in flt,
        "highshelf": " highshelf " in flt,
        "amix_normalize": "normalize" in amix,
    }


def probe(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe не смог прочитать {path}: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    d = json.loads(r.stdout.decode("utf-8", "replace"))
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"), None)
    a = next((s for s in d["streams"] if s.get("codec_type") == "audio"), None)
    if v is None:
        raise RuntimeError(f"в {path} нет видеодорожки")
    dur = float(d["format"].get("duration") or v.get("duration") or 0)
    num, _, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    info = {"width": int(v["width"]), "height": int(v["height"]), "fps": fps, "duration": dur, "audio": None,
            "audio_duration": float(a["duration"]) if a is not None and a.get("duration") not in (None, "N/A") else None}
    if a is not None:
        ch = int(a.get("channels") or 2)
        layout = a.get("channel_layout") or {1: "mono", 2: "stereo"}.get(ch, "stereo")
        info["audio"] = {"sample_rate": int(a.get("sample_rate") or 48000), "channels": ch, "layout": layout}
    return info


# ---------------------------------------------------------------- настройки
ALIASES = {"acid": "acid_slime_loop", "toxic": "acid_slime_loop", "lava": "lava_loop", "lavar": "lava_real_loop", "lava3d": "lava_real_loop", "sea": "sea_loop"}


def resolve_preset(name=None):
    """Папка пресета: путь к папке или короткое имя (acid, lava, sea) среди соседних пресетов."""
    if not name:
        return PRESET_DIR
    p = Path(name)
    if (p / "preset.json").exists():
        return p
    for cand in (PRESET_DIR.parent / ALIASES.get(name, name), PRESET_DIR.parent / (name + "_loop")):
        if (cand / "preset.json").exists():
            return cand
    known = sorted(d.name for d in PRESET_DIR.parent.iterdir() if (d / "preset.json").exists())
    raise FileNotFoundError(f"пресет «{name}» не найден; доступны: {', '.join(known)} (или укажите путь к папке)")


def load_preset(preset_dir=None):
    pd = resolve_preset(preset_dir)
    cfg = json.loads((pd / "preset.json").read_text(encoding="utf-8"))
    cfg["_dir"] = pd
    return cfg


def _num(x):
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


def build_commands(src, dst, cfg, media, caps, tmp_wav, *, ffmpeg="ffmpeg", intro=True, outro=True,
                   intro_db=None, outro_db=None, duck=None, overlay="auto", vargs=None, aargs=None, level=None):
    """Собирает две команды ffmpeg. Чистая функция: ничего не запускает (удобно проверять и печатать).

    1) звук: основная дорожка + звуки пресета (громкость, срез верхов, ducking, лимитер) -> временный WAV;
    2) картинка: оверлеи поверх видео, кодирование видео и звука из готового WAV.
    Раздельные проходы нужны, чтобы звук и картинка не мешали друг другу в одном графе ffmpeg:
    на ffmpeg 6.1 в общем графе звук мог обрезаться на 0,1-0,2 с раньше конца ролика."""
    pd = cfg["_dir"]
    W, H, L = media["width"], media["height"], media["duration"]
    A = media["audio"]
    sr = A["sample_rate"] if A else 48000
    layout = A["layout"] if A else "stereo"
    nch = A["channels"] if A else 2

    if level is not None:
        if level not in cfg.get("levels", {}) or level == "note":
            raise ValueError(f"нет уровня громкости «{level}»; доступны: " + ", ".join(k for k in cfg.get("levels", {}) if k != "note"))
        lv = cfg["levels"][level]
        intro_db = lv[0] if intro_db is None else intro_db
        outro_db = lv[1] if outro_db is None else outro_db
    use_intro = intro and cfg["intro"].get("enabled", True)
    use_outro = outro and cfg["outro"].get("enabled", True)
    if not (use_intro or use_outro):
        raise ValueError("и вступление, и концовка выключены: накладывать нечего")
    d_in, d_out = cfg["intro"]["duration_s"], cfg["outro"]["duration_s"]
    if use_intro and use_outro and L < d_in + d_out + 0.2:
        raise ValueError(f"ролик слишком короткий ({L:.2f} с): вступление и концовка перекрываются")
    if L < max(d_in if use_intro else 0, d_out if use_outro else 0):
        raise ValueError(f"ролик слишком короткий ({L:.2f} с)")

    # --- способ чтения прозрачности
    if overlay == "auto":
        overlay = "alpha" if caps["libvpx_vp9"] else "pair"
    if overlay == "alpha" and not caps["libvpx_vp9"]:
        raise ValueError("в этой сборке ffmpeg нет декодера libvpx-vp9: используйте --overlay pair")
    if overlay == "pair" and not caps["alphamerge"]:
        raise ValueError("в этой сборке ffmpeg нет фильтра alphamerge")

    # ============ проход 1: звук -> временный WAV ============
    a_in = [([], str(src))] if A else [(["-f", "lavfi", "-t", f"{L:.3f}"], f"anullsrc=r={sr}:cl={layout}")]
    a_ch = []

    def a_add(path):
        a_in.append(([], str(path)))
        return len(a_in) - 1

    mix = cfg["mix"]
    duck_cfg = dict(mix["duck"])
    if duck is not None:
        duck_cfg["enabled"] = bool(duck)
    do_duck = duck_cfg.get("enabled", True) and caps["sidechaincompress"]
    fmt = f"aformat=sample_rates={sr}:channel_layouts={layout}"
    sfx_labels = []

    def sfx_stream(part, tag, gain_db, start_s):
        p = cfg[part]
        i = a_add(pd / p["audio"])
        f = [fmt]
        shelf = p.get("audio_hf_shelf_db", 0)
        if shelf and caps["highshelf"]:
            f.append(f"highshelf=f=5000:g={_num(shelf)}")
        f.append(f"volume={_num(gain_db)}dB")
        if start_s > 0:
            f.append("adelay=" + "|".join([_num(start_s * 1000)] * nch))
        a_ch.append(f"[{i}:a]{','.join(f)}[{tag}]")
        sfx_labels.append(f"[{tag}]")

    if use_intro:
        sfx_stream("intro", "ia", cfg["intro"]["audio_gain_db"] if intro_db is None else intro_db, 0.0)
    if use_outro:
        sfx_stream("outro", "oa", cfg["outro"]["audio_gain_db"] if outro_db is None else outro_db, max(0.0, L - d_out))

    main_a = "[0:a]"
    norm = ":normalize=0" if caps["amix_normalize"] else ""
    if len(sfx_labels) == 2:
        a_ch.append(f"{sfx_labels[0]}{sfx_labels[1]}amix=inputs=2:duration=longest:dropout_transition=0{norm}[sfx]")
        sfx = "[sfx]"
    else:
        sfx = sfx_labels[0]
    if do_duck and A:
        a_ch.append(f"{main_a}asplit=2[am][ac]")
        a_ch.append(f"{sfx}[ac]sidechaincompress=threshold={_num(duck_cfg['threshold'])}:ratio={_num(duck_cfg['ratio'])}"
                    f":attack={_num(duck_cfg['attack_ms'])}:release={_num(duck_cfg['release_ms'])}:makeup=1[sfxd]")
        am, sfx = "[am]", "[sfxd]"
    else:
        am = main_a
    tail = "" if caps["amix_normalize"] else ",volume=2"   # старый amix сам делит громкость на число входов
    lim = mix.get("limiter", {})
    last = f"{am}{sfx}amix=inputs=2:duration=longest:dropout_transition=0{norm}{tail}"
    if lim.get("enabled", True) and caps["alimiter"]:
        last += (f",alimiter=limit={_num(lim.get('limit', 0.97))}:attack={_num(lim.get('attack_ms', 1))}"
                 f":release={_num(lim.get('release_ms', 60))}:level=0")
    a_ch.append(last + "[aout]")
    audio_argv = [ffmpeg, "-hide_banner", "-y"]
    for pre, path in a_in:
        audio_argv += pre + ["-i", path]
    audio_argv += ["-filter_complex", ";".join(a_ch), "-map", "[aout]", "-c:a", "pcm_s16le", "-ar", str(sr), str(tmp_wav)]

    # ============ проход 2: картинка и кодирование ============
    v_in = [([], str(src))]
    v_ch = []

    def v_add(pre, path):
        v_in.append((pre, str(path)))
        return len(v_in) - 1

    scale = ""
    if (W, H) != (cfg["frame"]["width"], cfg["frame"]["height"]):
        scale = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,crop={W}:{H},"

    def overlay_stream(part, tag, start_s):
        p = cfg[part]
        if overlay == "alpha":
            i = v_add(["-c:v", "libvpx-vp9"], pd / p["overlay_alpha"])
            head = f"[{i}:v]"
        else:
            i = v_add([], pd / p["overlay_rgb"])
            j = v_add([], pd / p["overlay_matte"])
            v_ch.append(f"[{i}:v][{j}:v]alphamerge[{tag}m]")
            head = f"[{tag}m]"
        v_ch.append(f"{head}{scale}format=yuva420p,setpts=PTS-STARTPTS+{_num(start_s)}/TB[{tag}]")
        return f"[{tag}]"

    cur = "[0:v]"
    if use_intro:
        ov = overlay_stream("intro", "iov", 0.0)
        v_ch.append(f"{cur}{ov}overlay=0:0:format=yuv420:eof_action=pass[v1]")
        cur = "[v1]"
    if use_outro:
        ov = overlay_stream("outro", "oov", max(0.0, L - d_out))
        v_ch.append(f"{cur}{ov}overlay=0:0:format=yuv420:eof_action=pass[v2]")
        cur = "[v2]"
    v_ch.append(f"{cur}format=yuv420p[vout]")
    k = v_add([], tmp_wav)                                  # готовый звук подключаем как обычный вход
    enc = cfg["encode"]
    video_argv = [ffmpeg, "-hide_banner", "-y"]
    for pre, path in v_in:
        video_argv += pre + ["-i", path]
    video_argv += ["-filter_complex", ";".join(v_ch), "-map", "[vout]", "-map", f"{k}:a"]
    video_argv += list(vargs) if vargs else list(enc["video"])
    video_argv += list(aargs) if aargs else list(enc["audio"])
    video_argv += list(enc.get("container", [])) if str(dst).lower().endswith((".mp4", ".mov", ".m4v")) else []
    video_argv += [str(dst)]
    notes = {"overlay_mode": overlay, "duck": bool(do_duck and A), "has_audio": bool(A)}
    return [audio_argv, video_argv], notes


# ---------------------------------------------------------------- запуск
def _printable(argv):
    return subprocess.list2cmdline(argv) if os.name == "nt" else " ".join(shlex.quote(a) for a in argv)


def apply_preset(src, dst, preset_dir=None, *, intro=True, outro=True, intro_db=None, outro_db=None,
                 duck=None, overlay="auto", ffmpeg=None, ffprobe=None, vargs=None, aargs=None,
                 level=None, dry_run=False, verbose=False, log=print):
    """Накладывает пресет на src и пишет результат в dst. Возвращает путь к dst."""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise FileNotFoundError(src)
    if src.resolve() == dst.resolve():
        raise ValueError("выходной файл не должен совпадать с входным")
    cfg = load_preset(preset_dir)
    ff, fp = _tools(ffmpeg, ffprobe)
    caps = capabilities(ff)
    media = probe(fp, src)
    missing = [k for k in ("sidechaincompress", "alimiter", "amix_normalize", "highshelf") if not caps[k]]
    if missing:
        log("! В этой сборке ffmpeg нет: " + ", ".join(missing) + " (пресет подстроится, но проверьте качество звука)")
    opts = dict(ffmpeg=ff, intro=intro, outro=outro, intro_db=intro_db, outro_db=outro_db, duck=duck,
                overlay=overlay, vargs=vargs, aargs=aargs, level=level)
    if dry_run:
        cmds, _ = build_commands(src, dst, cfg, media, caps, Path("mix_tmp.wav"), **opts)
        for c in cmds:
            log(_printable(c))
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="slime_preset_") as tmp:
        cmds, notes = build_commands(src, dst, cfg, media, caps, Path(tmp) / "mix.wav", **opts)
        log(f"Пресет {cfg['name']}: {src.name} -> {dst.name} ({media['width']}x{media['height']}, {media['fps']:.2f} fps, "
            f"{media['duration']:.2f} с; оверлей: {notes['overlay_mode']}, ducking: {'да' if notes['duck'] else 'нет'})")
        for step, argv in zip(("звук", "картинка и кодирование"), cmds):
            r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if r.returncode != 0:
                tail = "\n".join(r.stderr.decode("utf-8", "replace").splitlines()[-40:])
                raise RuntimeError(f"ffmpeg завершился с кодом {r.returncode} на шаге «{step}»\nКоманда:\n{_printable(argv)}\n{tail}")
            if verbose:
                log(r.stderr.decode("utf-8", "replace"))
    out = probe(fp, dst)
    if abs(out["duration"] - media["duration"]) > 0.25:
        raise RuntimeError(f"длина результата {out['duration']:.2f} с не совпала с исходной {media['duration']:.2f} с")
    if out.get("audio_duration") and out["audio_duration"] < out["duration"] - 0.12:
        raise RuntimeError(f"звук результата короче видео: {out['audio_duration']:.2f} с против {out['duration']:.2f} с")
    log(f"Готово: {dst} ({dst.stat().st_size / 1e6:.1f} МБ, {out['duration']:.2f} с)")
    return dst


def check(ffmpeg=None, ffprobe=None, preset_dir=None):
    """Проверка установки: файлы пресета и возможности ffmpeg. Возвращает True, если всё в порядке."""
    ok = True
    cfg = load_preset(preset_dir)
    pd = cfg["_dir"]
    print(f"Пресет: {cfg['title']} (v{cfg['version']}), папка {pd}")
    for part in ("intro", "outro"):
        for key in ("overlay_alpha", "overlay_rgb", "overlay_matte", "audio"):
            p = pd / cfg[part][key]
            print(f"  {'OK ' if p.exists() else 'НЕТ'} {part}.{key}: {cfg[part][key]}")
            ok &= p.exists()
    ff, fp = _tools(ffmpeg, ffprobe)
    print("ffmpeg:", ff, "| ffprobe:", fp)
    caps = capabilities(ff)
    notes = {
        "libvpx_vp9": "прозрачный WebM (иначе возьмётся пара RGB+матрица на H.264, это тоже работает)",
        "alphamerge": "склейка пары RGB+матрица",
        "sidechaincompress": "приглушение звука пресета под голосом (иначе только фиксированное усиление)",
        "alimiter": "страховочный лимитер",
        "highshelf": "срез верхов у звука вступления",
        "amix_normalize": "точное смешивание без авто-делителя громкости",
    }
    for k, v in caps.items():
        print(f"  {'OK ' if v else '-- '} {k}: {notes[k]}")
    ok &= caps["libvpx_vp9"] or caps["alphamerge"]
    print("Итог:", "всё готово" if ok else "есть проблемы, см. строки НЕТ")
    return bool(ok)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Накладывает пресет «Кислотная слизь» (вступление и плюха) на ролик")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--preset", help="стиль: acid (токсичный, по умолчанию), lava, sea или путь к папке пресета")
    ap.add_argument("--level", choices=["quiet", "normal", "loud"],
                    help="быстрый выбор громкости: quiet (-20/-16 дБ), normal (-14/-12, по умолчанию), loud (-8/-7)")
    ap.add_argument("--intro-db", type=float, help="усиление звука вступления, дБ (перекрывает --level; в пресете -14)")
    ap.add_argument("--outro-db", type=float, help="усиление звука концовки, дБ (перекрывает --level; в пресете -12; 0 = исходная громкость)")
    ap.add_argument("--no-intro", action="store_true", help="без вступления")
    ap.add_argument("--no-outro", action="store_true", help="без концовки")
    ap.add_argument("--no-duck", action="store_true", help="не прижимать звук пресета под голосом")
    ap.add_argument("--overlay", choices=["auto", "alpha", "pair"], default="auto",
                    help="как читать прозрачность: alpha = WebM (libvpx), pair = RGB+матрица на H.264, auto = по возможностям ffmpeg")
    ap.add_argument("--ffmpeg", help="путь к ffmpeg(.exe) или к папке с ним")
    ap.add_argument("--ffprobe", help="путь к ffprobe(.exe) или к папке с ним")
    ap.add_argument("--vargs", help="свои параметры видеокодера вместо preset.json, одной строкой, "
                                    "напр. \"-c:v h264_nvenc -preset p5 -cq 21 -pix_fmt yuv420p\"")
    ap.add_argument("--aargs", help="свои параметры аудиокодера, напр. \"-c:a aac -b:a 256k\"")
    ap.add_argument("--dry-run", action="store_true", help="только напечатать команду ffmpeg")
    ap.add_argument("--verbose", action="store_true", help="показать вывод ffmpeg")
    ap.add_argument("--check", action="store_true", help="проверить файлы пресета и возможности ffmpeg")
    a = ap.parse_args(argv)
    if a.check:
        return 0 if check(a.ffmpeg, a.ffprobe, a.preset) else 1
    if not a.input or not a.output:
        ap.error("нужны входной и выходной файлы")
    try:
        apply_preset(a.input, a.output, a.preset, intro=not a.no_intro, outro=not a.no_outro,
                     level=a.level, intro_db=a.intro_db, outro_db=a.outro_db, duck=False if a.no_duck else None,
                     overlay=a.overlay, ffmpeg=a.ffmpeg, ffprobe=a.ffprobe,
                     vargs=shlex.split(a.vargs, posix=(os.name != "nt")) if a.vargs else None,
                     aargs=shlex.split(a.aargs, posix=(os.name != "nt")) if a.aargs else None,
                     dry_run=a.dry_run, verbose=a.verbose)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print("ОШИБКА:", e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
