"""Проверки ключевых свойств движка.

Тесты не полагаются на готовые файлы: всё нужное собирается ffmpeg-ом на месте,
поэтому набор запускается на любой машине.

    python tests/test_smoke.py

Проверяется не «программа не упала», а измеримые величины: точная частота тона
после сдвига, яркость кадра во время зума, длительность и синхрон дорожек.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unicalizer import engine, ffmpeg_builder, probe  # noqa: E402
from unicalizer.params import DEFAULT_PARAMS, PRESETS, Roller, load_preset_file  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="unicalizer-tests-"))
FAILURES: list[str] = []


# ---------------------------------------------------------------- помощники

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK ' if ok else 'ПЛОХО'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def near(label: str, got: float, want: float, tol: float, unit: str = "") -> None:
    check(label, abs(got - want) <= tol,
          f"получено {got:.3f}{unit}, ожидалось {want:.3f}{unit} (±{tol}{unit})")


def ffmpeg(*args: str) -> None:
    done = subprocess.run([probe.tool("ffmpeg"), "-y", "-loglevel", "error", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    assert done.returncode == 0, done.stderr[-800:]


def render(params: dict, source: Path, name: str, seed: int = 7) -> Path:
    out = TMP / name
    built = ffmpeg_builder.build(probe.probe(source), str(out), params, seed)
    args = [a for a in built.args if a not in ("-progress", "pipe:1", "-nostats")]
    done = subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert done.returncode == 0, f"{name}: {done.stderr[-900:]}"
    return out


def bare(**sections) -> dict:
    """Пресет, где выключено всё, кроме явно включённого."""
    p = copy.deepcopy(DEFAULT_PARAMS)
    p["audio"].update(enabled=False, hf_noise=False)
    p["speed"].update(enabled=False, jitter=[1.0, 1.0])
    p["video_fx"].update(enabled=False, fps_jitter=False)
    p["zoom"]["enabled"] = False
    p["overlay"]["enabled"] = False
    p["encode"].update(fake_metadata=False, encoder="cpu", quality=[24, 24])
    for name, values in sections.items():
        p[name].update(values)
    return p


def luma(path: Path) -> list[float]:
    """Средняя яркость каждого кадра."""
    done = subprocess.run(
        [probe.tool("ffprobe"), "-v", "error", "-f", "lavfi",
         "-i", f"movie={path.name},signalstats",
         "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
         "-of", "csv=p=0"],
        capture_output=True, text=True, cwd=str(path.parent))
    return [float(x.strip(",")) for x in done.stdout.split() if x.strip(",")]


# ---------------------------------------------------------------- фикстуры

def build_fixtures() -> dict[str, Path]:
    tone = TMP / "tone.mp4"          # 440 Гц + цветные полосы, 8 с
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=8",
           "-f", "lavfi", "-t", "8", "-i", "sine=frequency=440:sample_rate=48000",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(tone))

    square = TMP / "square.mp4"      # белый квадрат на чёрном — мера зума
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x640:d=6:r=30",
           "-f", "lavfi", "-i", "color=c=white:s=160x160:d=6:r=30",
           "-f", "lavfi", "-t", "6", "-i", "sine=frequency=300",
           "-filter_complex", "[0:v][1:v]overlay=(W-w)/2:(H-h)/2[v]",
           "-map", "[v]", "-map", "2:a", "-c:v", "libx264",
           "-preset", "ultrafast", "-c:a", "aac", str(square))

    black = TMP / "black.mp4"        # сплошной чёрный — мера прозрачности
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x320:d=3:r=30",
           "-f", "lavfi", "-t", "3", "-i", "anullsrc=r=48000:cl=stereo",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(black))

    white = TMP / "white.png"
    ffmpeg("-f", "lavfi", "-i", "color=c=white:size=320x320,format=rgba",
           "-frames:v", "1", str(white))

    silent = TMP / "silent.mp4"      # без звуковой дорожки
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=4",
           "-c:v", "libx264", "-preset", "ultrafast", "-an", str(silent))

    return {"tone": tone, "square": square, "black": black,
            "white": white, "silent": silent}


# ---------------------------------------------------------------- проверки

def test_pitch(f: dict) -> None:
    """Сдвиг тона должен давать ровно заданную частоту."""
    try:
        import numpy as np
    except ImportError:
        print("[ПРОП] сдвиг тона — нужен numpy")
        return

    def peak(path: Path) -> float:
        raw = subprocess.run(
            [probe.tool("ffmpeg"), "-v", "error", "-i", str(path),
             "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
            capture_output=True).stdout
        data = np.frombuffer(raw, dtype=np.float32)[48000:48000 * 4]
        spectrum = np.abs(np.fft.rfft(data * np.hanning(len(data))))
        freqs = np.fft.rfftfreq(len(data), 1 / 48000)
        mask = (freqs >= 100) & (freqs <= 5000)
        return float(freqs[mask][np.argmax(spectrum[mask])])

    semitones = 0.5
    params = bare(audio={"enabled": True, "pitch_semitones": [semitones, semitones],
                         "eq_bands": 0, "spectral": False, "micro_echo": False,
                         "hf_noise": False, "volume_db": [0, 0], "limiter": False,
                         "highpass_hz": [0, 0], "lowpass_hz": [0, 0]})
    got = peak(render(params, f["tone"], "pitch.mp4"))
    up, down = 440 * 2 ** (semitones / 12), 440 * 2 ** (-semitones / 12)
    check("сдвиг тона попадает в заданную величину",
          min(abs(got - up), abs(got - down)) <= 4,
          f"{got:.1f} Гц (вверх {up:.1f} / вниз {down:.1f})")


def test_zoom(f: dict) -> None:
    """Зум должен срабатывать в заданную секунду и на заданную кратность."""
    params = bare(zoom={"enabled": True, "auto": False, "events": [
        {"start": 2.0, "dur": 1.0, "factor": 2.0, "ease": "punch", "x": 0.5, "y": 0.5}]})
    values = luma(render(params, f["square"], "zoom.mp4"))
    if len(values) < 150:
        check("зум: кадры прочитаны", False, f"кадров {len(values)}")
        return
    base = values[30]                       # 1-я секунда — до наезда
    during = values[75]                     # 2.5-я секунда — внутри окна
    after = values[135]                     # 4.5-я секунда — после
    # Белый квадрат 160x160 на кадре 640x640 занимает 6.25%, при ×2 — 25%.
    near("зум ×2: яркость во время наезда", during, 70.75, 3)
    near("зум: яркость до наезда", base, 29.69, 2)
    near("зум: яркость после наезда", after, 29.69, 2)


def test_manual_zoom_no_overlap() -> None:
    """Пересекающиеся ручные зумы не должны складываться в кратности."""
    p = copy.deepcopy(DEFAULT_PARAMS)
    p["zoom"] = {"enabled": True, "auto": False, "events": [
        {"start": 2.0, "dur": 3.0, "factor": 1.5},
        {"start": 3.0, "dur": 3.0, "factor": 1.5},
        {"start": 4.0, "dur": 3.0, "factor": 1.5},
    ]}
    events = ffmpeg_builder.plan_zoom_events(p, Roller(p, 1), 20.0)
    overlaps = sum(1 for a, b in zip(events, events[1:])
                   if a.start + a.duration > b.start)
    peak, t = 1.0, 0.0
    while t < 20.0:
        peak = max(peak, 1.0 + sum(e.factor - 1 for e in events
                                   if e.start <= t <= e.start + e.duration))
        t += 0.02
    check("ручные зумы не накладываются", overlaps == 0, f"наложений {overlaps}")
    check("кратность не раздувается", peak <= 1.55, f"пик ×{peak:.2f}")


def test_overlay(f: dict) -> None:
    """Прозрачность наложения должна совпадать с формулой смешивания."""
    for opacity in (0.05, 0.25):
        params = bare(overlay={"enabled": True, "path": str(f["white"]),
                               "mode": "stretch", "drift": False,
                               "opacity": [opacity, opacity], "rotate_deg": [0, 0]})
        values = luma(render(params, f["black"], f"ov{int(opacity * 100)}.mp4"))
        got = sum(values) / len(values)
        near(f"наложение белого на {opacity:.0%}", got, 16 + opacity * (235 - 16), 2.5)


def test_speed_and_sync(f: dict) -> None:
    """Ускорение меняет длительность, дорожки остаются синхронными."""
    factor = 2.15
    params = bare(speed={"enabled": True, "factor": [factor, factor],
                         "jitter": [1.0, 1.0], "preserve_pitch": True})
    out = render(params, f["tone"], "speed.mp4")
    info = probe.probe(out)
    near("длительность после ускорения", info.duration, 8 / factor, 0.15, " с")

    def stream_duration(kind: str) -> float:
        done = subprocess.run(
            [probe.tool("ffprobe"), "-v", "error", "-select_streams", kind,
             "-show_entries", "stream=duration", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True)
        return float(done.stdout.strip() or 0)

    drift = abs(stream_duration("a:0") - stream_duration("v:0"))
    check("видео и звук не разъезжаются", drift < 0.10, f"расхождение {drift * 1000:.0f} мс")


def test_speed_off(f: dict) -> None:
    """Снятая галочка скорости не должна менять длительность вообще."""
    params = bare()
    out = render(params, f["tone"], "nospeed.mp4")
    near("скорость выключена — длительность цела", probe.probe(out).duration, 8.0, 0.12, " с")


def test_silent_source(f: dict) -> None:
    """Видео без звука получает синтезированную тишину, а не падает."""
    out = render(bare(audio={"enabled": True}), f["silent"], "silent_out.mp4")
    info = probe.probe(out)
    check("видео без звука обработано", info.has_audio and info.duration > 0,
          f"звук: {info.has_audio}, {info.duration:.2f} с")


def test_even_dimensions(f: dict) -> None:
    """Нечётные стороны кадра приводятся к чётным — иначе libx264 падает."""
    info = probe.probe(f["tone"])
    info.width, info.height = 641, 361
    built = ffmpeg_builder.build(info, str(TMP / "odd.mp4"), bare(), 5)
    check("нечётный кадр приведён к чётному",
          built.report["output_resolution"] == "640x360",
          built.report["output_resolution"])


def test_roller_robustness() -> None:
    """Мусор и перевёрнутые границы в пресете не должны ронять обработку."""
    p = {"a": {"inv": [10, 2], "bad": ["x", "y"], "int_inv": [9, 1], "int_bad": ["q", 1]}}
    r = Roller(p, 5)
    try:
        values = (r.num("a.inv"), r.num("a.bad", 7.0),
                  r.integer("a.int_inv"), r.integer("a.int_bad", 3))
        ok = 2 <= values[0] <= 10 and values[1] == 7.0 and 1 <= values[2] <= 9
    except Exception as exc:                                  # noqa: BLE001
        ok, values = False, exc
    check("перевёрнутые границы и мусор пережёваны", ok, str(values))


def test_bad_pattern(f: dict) -> None:
    """Ошибка в шаблоне имени не должна ронять всю партию."""
    ok = True
    for pattern in ("{nam}_x", "{0}", "a{b"):
        p = copy.deepcopy(DEFAULT_PARAMS)
        p["output"]["pattern"] = pattern
        try:
            jobs, _ = engine.plan_jobs([str(f["tone"])], str(TMP / "pat"), p)
            ok = ok and bool(jobs)
        except Exception:                                     # noqa: BLE001
            ok = False
    check("битый шаблон имени не роняет партию", ok)


def test_preset_bom() -> None:
    """Пресет, сохранённый с BOM, должен читаться."""
    path = TMP / "bom.json"
    path.write_text(json.dumps({"params": {"speed": {"factor": [3, 3]}}}),
                    encoding="utf-8-sig")
    try:
        got = load_preset_file(path)["speed"]["factor"] == [3, 3]
    except Exception:                                         # noqa: BLE001
        got = False
    check("пресет с BOM читается", got)


def test_output_dir_guard(f: dict) -> None:
    """Совпадение папки вывода с папкой исходников должно замечаться."""
    same = engine.sources_inside([str(f["tone"])], str(TMP))
    other = engine.sources_inside([str(f["tone"])], str(TMP / "elsewhere"))
    check("совпадение папок замечено", len(same) == 1 and len(other) == 0,
          f"в своей папке {len(same)}, в чужой {len(other)}")


def test_presets_build(f: dict) -> None:
    """Все встроенные пресеты должны собираться и кодировать."""
    for name in PRESETS:
        p = copy.deepcopy(PRESETS[name])
        p["encode"]["encoder"] = "cpu"
        p["encode"]["quality"] = [26, 26]
        try:
            out = render(p, f["tone"], f"preset_{abs(hash(name))}.mp4")
            ok = probe.probe(out).duration > 0
        except Exception as exc:                              # noqa: BLE001
            ok, out = False, exc
        check(f"пресет «{name[:24]}» кодирует", ok)


# ---------------------------------------------------------------- запуск

def main() -> int:
    print(f"временная папка: {TMP}\n")
    try:
        probe.tool("ffmpeg")
    except probe.FFmpegNotFound as exc:
        print(f"ffmpeg не найден: {exc}")
        return 2

    fixtures = build_fixtures()
    test_pitch(fixtures)
    test_zoom(fixtures)
    test_manual_zoom_no_overlap()
    test_overlay(fixtures)
    test_speed_and_sync(fixtures)
    test_speed_off(fixtures)
    test_silent_source(fixtures)
    test_even_dimensions(fixtures)
    test_roller_robustness()
    test_bad_pattern(fixtures)
    test_preset_bom()
    test_output_dir_guard(fixtures)
    test_presets_build(fixtures)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО {len(FAILURES)}:")
        for item in FAILURES:
            print("   ", item)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
