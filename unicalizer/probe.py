"""Поиск ffmpeg/ffprobe, чтение свойств видео, определение доступности NVENC."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VIDEO_EXTS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg",
    ".wmv", ".flv", ".ts", ".m2ts", ".3gp", ".mts",
}

# Чтобы при запуске из .pyw не мигали чёрные окна консоли.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class FFmpegNotFound(RuntimeError):
    pass


def _bundled(name: str) -> str | None:
    """ffmpeg.exe рядом с программой имеет приоритет над системным.

    В собранном приложении считать путь от __file__ нельзя: исходник лежит
    внутри архива. Поэтому у замороженной сборки смотрим и рядом с самим exe,
    и во временной папке распаковки, куда PyInstaller кладёт вложенные файлы.
    """
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        unpacked = getattr(sys, "_MEIPASS", None)
        if unpacked:
            roots.append(Path(unpacked))
    roots.append(Path(__file__).resolve().parent.parent)

    suffix = ".exe" if sys.platform == "win32" else ""
    for root in roots:
        for folder in (root, root / "bin", root / "ffmpeg" / "bin"):
            candidate = folder / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return None


@lru_cache(maxsize=None)
def tool(name: str) -> str:
    found = _bundled(name) or shutil.which(name)
    if not found:
        if sys.platform == "darwin":
            raise FFmpegNotFound(
                f"Не найден {name}. Установите его командой:  brew install ffmpeg"
            )
        raise FFmpegNotFound(
            f"Не найден {name}. Установите ffmpeg и добавьте в PATH, "
            f"либо положите {name}.exe в папку bin рядом с программой."
        )
    return found


def run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    audio_samplerate: int
    video_codec: str
    rotation: int

    @property
    def is_vertical(self) -> bool:
        return self.height >= self.width


def probe(path: str | Path) -> MediaInfo:
    """Свойства файла. Длительность берётся из контейнера, иначе из видеопотока."""
    path = str(path)
    result = run([
        tool("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe не смог прочитать файл:\n{result.stderr.strip()}")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("В файле нет видеодорожки.")

    duration = 0.0
    for candidate in (data.get("format", {}).get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue
    if duration <= 0:
        duration = _duration_by_decode(path)

    fps = 30.0
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        num, _, den = rate.partition("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        pass
    if not 1.0 <= fps <= 240.0:
        fps = 30.0

    rotation = 0
    for entry in video.get("side_data_list", []) or []:
        if "rotation" in entry:
            try:
                rotation = int(float(entry["rotation"])) % 360
            except (TypeError, ValueError):
                pass

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    # ffmpeg сам применяет поворот при декодировании, поэтому меняем местами
    # стороны, чтобы дальше в цепочке считать по фактическому кадру.
    if rotation in (90, 270):
        width, height = height, width

    return MediaInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        has_audio=audio is not None,
        audio_samplerate=int(audio.get("sample_rate", 48000)) if audio else 48000,
        video_codec=str(video.get("codec_name", "")),
        rotation=rotation,
    )


def _duration_by_decode(path: str) -> float:
    """Запасной путь: досчитать длительность декодированием (для битых контейнеров)."""
    result = run([
        tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
        "-count_packets", "-show_entries",
        "stream=nb_read_packets,avg_frame_rate", "-print_format", "json", path,
    ], timeout=600)
    try:
        stream = json.loads(result.stdout)["streams"][0]
        num, _, den = str(stream["avg_frame_rate"]).partition("/")
        fps = float(num) / float(den or 1)
        return int(stream["nb_read_packets"]) / fps
    except Exception:
        return 0.0


@lru_cache(maxsize=None)
def filter_available(name: str) -> bool:
    """Есть ли такой фильтр в этой сборке ffmpeg.

    Большинство фильтров встроены, но часть требует внешних библиотек —
    например rubberband собран далеко не везде. Без проверки программа
    падала бы на чужом компьютере с «No such filter».
    """
    try:
        result = run([tool("ffmpeg"), "-hide_banner", "-filters"], timeout=30)
        if result.returncode != 0:
            return False
        # Строки вида " ..C rubberband        A->A       Apply time-stretching..."
        # Имя — во второй колонке. Искать подстроку по всей строке нельзя:
        # название фильтра встречается и в описаниях других фильтров, и тогда
        # отсутствующий фильтр посчитается доступным.
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == name:
                return True
        return False
    except Exception:
        return False


@lru_cache(maxsize=1)
def ffmpeg_version() -> tuple[int, int]:
    """Версия ffmpeg как (major, minor). При неудаче — (0, 0).

    Часть возможностей появилась не сразу: переменная времени 'it' у zoompan,
    пресеты p1-p7 у NVENC, ключ use_metadata_tags. На сборках старше 4.4
    программа выдаст невнятную ошибку от ffmpeg, поэтому лучше предупредить.
    """
    try:
        result = run([tool("ffmpeg"), "-hide_banner", "-version"], timeout=20)
        first = (result.stdout or "").splitlines()[0]
        # "ffmpeg version 7.1.1-essentials_build-..." или "ffmpeg version n6.0"
        token = first.split()[2].lstrip("n")
        major, _, rest = token.partition(".")
        minor = rest.partition(".")[0]
        return int(major), int(minor or 0)
    except Exception:
        return (0, 0)


@lru_cache(maxsize=1)
def encoder_available(name: str = "libx264") -> bool:
    """Есть ли кодировщик в сборке. libx264 нужен как запасной путь всегда."""
    try:
        result = run([tool("ffmpeg"), "-hide_banner", "-encoders"], timeout=30)
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == name:
                return True
        return False
    except Exception:
        return False


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """Проверяем не по списку кодеков, а реальной пробной кодировкой.

    Кодек может быть собран в ffmpeg, но не работать: старый драйвер, занятые
    сессии NVENC, ноутбучная гибридная графика. Дешёвый прогон 1 кадра честнее.
    """
    try:
        result = run([
            tool("ffmpeg"), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
            "-c:v", "h264_nvenc", "-frames:v", "1",
            "-f", "null", os.devnull,
        ], timeout=40)
        return result.returncode == 0
    except Exception:
        return False


def list_videos(folder: str | Path, recursive: bool = False) -> list[str]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    walker = folder.rglob("*") if recursive else folder.glob("*")
    files = [
        str(p) for p in walker
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    ]
    return sorted(files, key=str.lower)
