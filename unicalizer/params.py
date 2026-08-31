"""Модель параметров уникализации + пресеты.

Здесь описано ЧТО можно менять. Как это превращается в ffmpeg — в ffmpeg_builder.py.
Каждый параметр-диапазон задаётся парой (min, max); для конкретной копии из него
берётся случайное значение по сиду, поэтому все копии отличаются, но воспроизводимы.
"""

from __future__ import annotations

import copy
import json
import os
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


def _default_jobs() -> int:
    """Сколько роликов гнать одновременно.

    Узкое место — не видеокарта, а фильтры на процессоре: замер показал, что
    сам кодек занимает лишь около десятой части времени. Поэтому число задач
    считаем от ядер, а не от NVENC. На 16 ядрах четыре задачи дают +18% к
    выработке против двух; больше четырёх выигрыша уже не приносит.
    """
    cores = os.cpu_count() or 4
    return max(1, min(4, cores // 4))


# ---------------------------------------------------------------- параметры

def _rng_pair(lo: float, hi: float) -> list[float]:
    return [lo, hi]


DEFAULT_PARAMS: dict[str, Any] = {
    # ---------------------------------------------------------------- звук
    "audio": {
        "enabled": True,
        # Модуль сдвига высоты тона в полутонах (rubberband); знак случайный.
        # Именно модуль, а не диапазон вокруг нуля: при розыгрыше от -0.35 до
        # +0.35 половина копий получала бы сдвиг около нуля, то есть впустую.
        # 0.2 полутона ≈ 1.2%, 0.35 ≈ 2.0% — верхняя граница незаметности.
        "pitch_semitones": _rng_pair(0.18, 0.35),
        # Случайный параметрический эквалайзер: сколько полос и насколько сильно.
        "eq_bands": 4,
        "eq_gain_db": _rng_pair(-1.8, 1.8),
        "eq_freq_hz": _rng_pair(120, 9000),
        "eq_width_q": _rng_pair(0.7, 2.2),
        # Неслышимый ВЧ-шум (двигает спектрограмму, ухо его не берёт).
        # Потолок 17 кГц выбран по замеру: площадки жмут звук в AAC, а он
        # режет верх примерно на 17.3 кГц при 128 кбит/с. Метка на 17.5 кГц
        # в выложенном ролике просто исчезает.
        "hf_noise": True,
        "hf_noise_freq_hz": _rng_pair(15800, 17000),
        "hf_noise_level_db": _rng_pair(-52, -42),
        # Спектральная обработка (afftfilt) — самая «злая» для фингерпринта.
        "spectral": True,
        "spectral_strength": _rng_pair(0.04, 0.12),
        # Микро-эхо: сдвигает пики спектрограммы, на 3–8 мс не слышно.
        "micro_echo": True,
        "micro_echo_ms": _rng_pair(3, 9),
        "micro_echo_decay": _rng_pair(0.05, 0.14),
        # Срез самых низов/верхов — меняет огибающую спектра.
        "highpass_hz": _rng_pair(20, 55),
        "lowpass_hz": _rng_pair(18500, 20000),
        # Общая громкость и защита от клиппинга.
        "volume_db": _rng_pair(-1.0, 0.6),
        "limiter": True,
    },

    # ---------------------------------------------------------------- скорость
    "speed": {
        "enabled": True,
        # Основное требование: x2.1–2.2.
        "factor": _rng_pair(2.10, 2.20),
        # Мелкий довесок к ускорению. Применяется и к картинке, и к звуку —
        # иначе дорожки разъедутся тем сильнее, чем длиннее ролик.
        "jitter": _rng_pair(0.995, 1.005),
        # Сохранять высоту голоса при ускорении (иначе «бурундуки»).
        "preserve_pitch": True,
    },

    # ---------------------------------------------------------------- оверлей
    "overlay": {
        "enabled": False,
        "path": "",
        # Прозрачность накладываемой картинки. 0.03 = практически невидимо.
        "opacity": _rng_pair(0.025, 0.07),
        # cover — растянуть с обрезкой, fit — вписать, stretch — растянуть, tile — плиткой.
        "mode": "cover",
        # Медленный дрейф оверлея: не даёт склеить кадры попиксельно.
        "drift": True,
        "drift_px": _rng_pair(6, 22),
        "drift_period_s": _rng_pair(7, 18),
        # Случайный поворот картинки, чтобы копии не совпадали.
        "rotate_deg": _rng_pair(-4, 4),
    },

    # ---------------------------------------------------------------- зум
    "zoom": {
        "enabled": True,
        # Ручные события: [{"start": 3.5, "dur": 0.8, "factor": 1.35, "ease": "punch",
        #                   "x": 0.5, "y": 0.5}]
        # start/dur — в секундах ИТОГОВОГО (уже ускоренного) видео.
        "events": [],
        # Если ручных событий нет — расставить случайные.
        "auto": True,
        "auto_count": [2, 4],
        "auto_factor": _rng_pair(1.18, 1.45),
        "auto_dur_s": _rng_pair(0.5, 1.4),
        # punch — мгновенный рывок, ease — плавный наезд/отъезд.
        "auto_ease": "punch",
        # Не ставить зум в первые/последние N секунд.
        "auto_margin_s": 1.0,
    },

    # ---------------------------------------------------------------- картинка
    "video_fx": {
        "enabled": True,
        # Микро-кроп с обратным растягиванием: срезает 0.5–2.5% кадра.
        "crop_percent": _rng_pair(0.6, 2.5),
        # Микро-поворот (градусы). Заметен только на очень контрастных линиях.
        "rotate_deg": _rng_pair(-0.5, 0.5),
        # Зеркалить по горизонтали (сильно меняет хеши, но видно зрителю).
        "hflip": False,
        # Цветокоррекция в пределах «не видно глазом».
        "brightness": _rng_pair(-0.025, 0.025),
        "contrast": _rng_pair(0.97, 1.04),
        "saturation": _rng_pair(0.95, 1.06),
        "gamma": _rng_pair(0.97, 1.03),
        "hue_deg": _rng_pair(-3.5, 3.5),
        # Плёночное зерно — ломает попиксельное сравнение.
        "grain": True,
        "grain_strength": [4, 12],
        # Лёгкое затемнение краёв.
        "vignette": False,
        "vignette_angle": _rng_pair(0.05, 0.16),
        # Микро-изменение частоты кадров. Пустой список — выбирать автоматически
        # из значений, близких к исходной частоте ролика.
        "fps_jitter": True,
        "fps_choices": [],
    },

    # ---------------------------------------------------------------- кодек
    "encode": {
        # auto | nvenc | cpu
        "encoder": "auto",
        # Качество: чем меньше, тем лучше картинка и больше файл.
        "quality": _rng_pair(20, 24),
        # Джиттер длины GOP — меняет структуру битстрима.
        "keyint_jitter": True,
        "keyint": [48, 120],
        "audio_bitrate_kbps": [128, 160, 192],
        "audio_samplerate": [44100, 48000],
        # Убрать все исходные метаданные и записать свои, случайные.
        "strip_metadata": True,
        "fake_metadata": True,
        "faststart": True,
        # Максимальная сторона кадра (0 = не трогать).
        "max_dimension": 0,
    },

    # ---------------------------------------------------------------- вывод
    "output": {
        "copies_per_file": 1,
        # {name} — имя исходника, {i} — номер копии, {seed} — сид
        "pattern": "{name}_uniq{i}",
        "container": "mp4",
        "write_report": True,
        "parallel_jobs": _default_jobs(),
    },
}


PRESETS: dict[str, dict[str, Any]] = {}


def _preset(name: str, **overrides) -> None:
    """Регистрирует пресет как набор точечных правок поверх DEFAULT_PARAMS."""
    p = copy.deepcopy(DEFAULT_PARAMS)
    for dotted, value in overrides.items():
        section, key = dotted.split(".", 1)
        p[section][key] = value
    PRESETS[name] = p


_preset(
    "Лёгкая (максимум качества)",
    **{
        "audio.pitch_semitones": _rng_pair(0.10, 0.20),
        "audio.eq_bands": 2,
        "audio.eq_gain_db": _rng_pair(-0.9, 0.9),
        "audio.spectral": False,
        "speed.factor": _rng_pair(1.0, 1.0),
        "zoom.auto_count": [1, 2],
        "zoom.auto_factor": _rng_pair(1.10, 1.22),
        "video_fx.crop_percent": _rng_pair(0.4, 1.0),
        "video_fx.grain_strength": [3, 6],
        "video_fx.rotate_deg": _rng_pair(-0.2, 0.2),
        "encode.quality": _rng_pair(19, 21),
    },
)

_preset("Средняя (баланс)")

_preset(
    "Жёсткая (максимум уникальности)",
    **{
        "audio.pitch_semitones": _rng_pair(0.30, 0.55),
        "audio.eq_bands": 6,
        "audio.eq_gain_db": _rng_pair(-3.0, 3.0),
        "audio.spectral_strength": _rng_pair(0.10, 0.22),
        "audio.micro_echo_ms": _rng_pair(5, 16),
        "zoom.auto_count": [3, 6],
        "zoom.auto_factor": _rng_pair(1.25, 1.6),
        "video_fx.crop_percent": _rng_pair(1.5, 4.0),
        "video_fx.rotate_deg": _rng_pair(-0.9, 0.9),
        "video_fx.hue_deg": _rng_pair(-6, 6),
        "video_fx.grain_strength": [10, 22],
        "video_fx.vignette": True,
        "encode.quality": _rng_pair(22, 26),
    },
)


# ---------------------------------------------------------------- розыгрыш

@dataclass
class Roll:
    """Конкретные значения, разыгранные для одной копии."""

    seed: int
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, path: str, default: Any = None) -> Any:
        return self.values.get(path, default)


class Roller:
    """Превращает диапазоны параметров в конкретные числа по сиду.

    Один и тот же сид + один и тот же пресет всегда дают одну и ту же копию,
    поэтому удачный вариант можно повторить, указав сид из отчёта.
    """

    def __init__(self, params: dict[str, Any], seed: int) -> None:
        self.params = params
        self.seed = seed
        self._rnd = random.Random(seed)
        self.rolled: dict[str, Any] = {}

    def _raw(self, path: str, default: Any = None) -> Any:
        section, key = path.split(".", 1)
        return self.params.get(section, {}).get(key, default)

    def num(self, path: str, default: float = 0.0) -> float:
        """Случайное число из диапазона [min, max], записанное в отчёт.

        Границы приводятся к порядку: пресет можно отредактировать руками,
        и перевёрнутый диапазон не должен ломать обработку.
        """
        raw = self._raw(path)
        try:
            if raw is None:
                value = float(default)
            elif isinstance(raw, (list, tuple)) and len(raw) == 2:
                lo, hi = float(raw[0]), float(raw[1])
                if lo > hi:
                    lo, hi = hi, lo
                value = lo if lo == hi else self._rnd.uniform(lo, hi)
            else:
                value = float(raw)
        except (TypeError, ValueError):
            value = float(default)
        self.rolled[path] = round(value, 6)
        return value

    def integer(self, path: str, default: int = 0) -> int:
        raw = self._raw(path)
        try:
            if raw is None:
                value = int(default)
            elif isinstance(raw, (list, tuple)) and len(raw) == 2:
                lo, hi = int(raw[0]), int(raw[1])
                if lo > hi:
                    lo, hi = hi, lo
                value = self._rnd.randint(lo, hi)
            else:
                value = int(raw)
        except (TypeError, ValueError):
            value = int(default)
        self.rolled[path] = value
        return value

    def choice(self, path: str, default: Any = None) -> Any:
        raw = self._raw(path)
        if not isinstance(raw, (list, tuple)) or not raw:
            value = default
        else:
            value = self._rnd.choice(list(raw))
        self.rolled[path] = value
        return value

    def flag(self, path: str, default: bool = False) -> bool:
        raw = self._raw(path)
        value = bool(default if raw is None else raw)
        self.rolled[path] = value
        return value

    def text(self, path: str, default: str = "") -> str:
        raw = self._raw(path)
        value = default if raw is None else str(raw)
        self.rolled[path] = value
        return value

    def uniform(self, lo: float, hi: float) -> float:
        """Свободный розыгрыш, не привязанный к параметру (для авто-зумов)."""
        return self._rnd.uniform(lo, hi)

    def randint(self, lo: int, hi: int) -> int:
        return self._rnd.randint(lo, hi)

    def pick(self, seq):
        return self._rnd.choice(list(seq))


# ---------------------------------------------------------------- хранение

def merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Аккуратно накладывает patch на base, не теряя незаданных ключей."""
    out = copy.deepcopy(base)
    for section, values in (patch or {}).items():
        if isinstance(values, dict) and isinstance(out.get(section), dict):
            out[section].update(values)
        else:
            out[section] = values
    return out


def load_preset_file(path: str | Path) -> dict[str, Any]:
    # utf-8-sig, а не utf-8: блокнот Windows и часть редакторов пишут BOM,
    # и обычный json.loads на нём спотыкается.
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return merge(DEFAULT_PARAMS, data.get("params", data))


def save_preset_file(path: str | Path, params: dict[str, Any], name: str = "") -> None:
    payload = {"name": name or Path(path).stem, "params": params}
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
