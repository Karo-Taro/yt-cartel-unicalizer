"""Сборка одной ffmpeg-команды: все эффекты за один проход.

Граф входов:
    [0]  исходное видео
    [1]  картинка-оверлей          (если включён оверлей)
    [2]  сгенерированный ВЧ-шум    (если включён)
    [n]  anullsrc                  (если у исходника нет звука)

Всё считается за один вызов ffmpeg — промежуточные файлы не пишутся.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .params import Roller
from .probe import MediaInfo, filter_available, nvenc_available, tool

# Частоты кадров, которые площадки принимают без переделки.
SAFE_FPS = (24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)

# NTSC-частоты дробные, и записывать их как 29.97 нельзя: за минуту набегает
# заметный сдвиг. ffmpeg принимает точную дробь.
_FPS_EXACT = {29.97: "30000/1001", 59.94: "60000/1001"}


def _fps_arg(value: float) -> str:
    return _FPS_EXACT.get(round(value, 2), _f(value, 4))


def pick_fps(source_fps: float, roller: Roller, jitter: bool,
             manual: list | None = None) -> float:
    """Частота кадров для копии.

    Джиттер выбирает только из значений, близких к исходным. Тянуть 25 кадров
    до 60 бессмысленно: файл распухает, а кадры просто дублируются; ронять
    60 до 24 — терять плавность.
    """
    snapped = min(SAFE_FPS, key=lambda value: abs(value - source_fps))
    if not jitter:
        return snapped
    if manual:
        return float(roller.pick(manual))
    # Вверх подниматься безопасно (кадры продублируются), вниз — нет: срезав
    # 30 кадров до 24, получим видимый рывок в движении.
    nearby = [value for value in SAFE_FPS
              if source_fps * 0.92 <= value <= source_fps * 1.25]
    return float(roller.pick(sorted(set(nearby) | {snapped})))

# Теги make/model/com.android.version муксер mp4 молча выбрасывает, если не
# передать -movflags use_metadata_tags. Тег encoder он в любом случае
# перезапишет своей подписью, поэтому подделывать его бесполезно.
# Наборы держим согласованными: айфон не пишет com.android.version.
_CAMERAS = [
    ("Apple", "iPhone 15 Pro", None),
    ("Apple", "iPhone 14", None),
    ("Apple", "iPhone 13 Pro", None),
    ("Apple", "iPhone 12", None),
    ("samsung", "SM-S918B", "13"),
    ("samsung", "SM-A546E", "14"),
    ("Xiaomi", "23021RAA2Y", "13"),
    ("Google", "Pixel 8", "14"),
    ("Google", "Pixel 7a", "13"),
    ("OnePlus", "CPH2451", "13"),
]
_HANDLERS_VIDEO = [
    "VideoHandle", "VideoHandler", "Core Media Video",
    "ISO Media file produced by Google Inc.",
]
_HANDLERS_AUDIO = ["SoundHandle", "SoundHandler", "Core Media Audio"]
_BRANDS = ["isom", "mp42", "avc1", "iso6"]


@dataclass
class ZoomEvent:
    start: float          # секунда в ИТОГОВОМ (уже ускоренном) видео
    duration: float
    factor: float
    ease: str = "punch"   # punch | ease
    fx: float = 0.5       # точка фокуса по X, 0..1
    fy: float = 0.5


@dataclass
class BuildResult:
    args: list[str]
    report: dict[str, Any]
    out_duration: float
    zoom_events: list[ZoomEvent] = field(default_factory=list)


# ---------------------------------------------------------------- утилиты

def _f(value: float, digits: int = 5) -> str:
    """Число для фильтра: без экспоненты, точка как разделитель, без хвостовых нулей."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-", "-0") else "0"


def _even(value: float) -> int:
    """h264 требует чётные стороны кадра."""
    return max(2, int(round(value / 2)) * 2)


def _atempo_chain(factor: float) -> list[str]:
    """atempo меняет темп, не трогая высоту тона.

    Формально в ffmpeg 7 он принимает до 100×, но качество на больших значениях
    заметно хуже, поэтому раскладываем на множители не больше 2.
    """
    if abs(factor - 1.0) < 1e-4:
        return []
    parts: list[str] = []
    remaining = factor
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-4:
        parts.append(f"atempo={_f(remaining, 6)}")
    return parts


# ---------------------------------------------------------------- зум

def plan_zoom_events(params: dict, roller: Roller, out_duration: float) -> list[ZoomEvent]:
    """Список зумов для этой копии: либо заданный вручную, либо разыгранный."""
    zoom = params.get("zoom", {})
    if not zoom.get("enabled", False) or out_duration <= 0.2:
        return []

    manual = zoom.get("events") or []
    if manual and not zoom.get("auto", True):
        events = []
        for item in manual:
            try:
                start = float(item.get("start", 0))
                duration = float(item.get("dur", 0.6))
                factor = float(item.get("factor", 1.3))
                fx = float(item.get("x", 0.5))
                fy = float(item.get("y", 0.5))
            except (TypeError, ValueError):
                continue          # мусор в таблице не должен ронять всю партию
            if start >= out_duration or duration <= 0 or factor < 1.0:
                continue
            events.append(ZoomEvent(
                start=max(0.0, start),
                duration=min(duration, out_duration - start),
                factor=factor,
                ease=str(item.get("ease", "punch")),
                fx=min(1.0, max(0.0, fx)),
                fy=min(1.0, max(0.0, fy)),
            ))
        return _resolve_overlaps(sorted(events, key=lambda e: e.start))

    margin = roller.num("zoom.auto_margin_s", 1.0)
    count = roller.integer("zoom.auto_count", 2)
    usable = out_duration - 2 * margin
    if usable <= 0.5 or count <= 0:
        return []

    ease = roller.text("zoom.auto_ease", "punch")
    dur_wanted = roller.num("zoom.auto_dur_s", 0.8)

    # Сколько зумов реально помещается без наложения. Каждому нужен свой зум
    # плюс небольшой зазор, иначе окна перекрываются, а zoompan складывает их
    # кратности — на коротком ролике из двух ×1.3 получался бы один ×1.7.
    # Поэтому число из пресета урезаем до того, что влезает в доступное время.
    min_dur = min(0.3, dur_wanted)
    gap = 0.15
    fits = max(1, int(usable // (min_dur + gap)))
    count = min(count, fits)

    events: list[ZoomEvent] = []
    # Делим доступное время на равные окна и ставим по одному зуму в каждое —
    # так они не слипаются в кучу, но моменты всё равно случайны.
    slot = usable / count
    for index in range(count):
        # Зум не длиннее слота минус зазор — гарантия, что соседние окна
        # не перекрываются ни при каком розыгрыше момента внутри слота.
        duration = max(0.2, min(dur_wanted, slot - gap))
        slot_start = margin + index * slot
        start = slot_start + roller.uniform(0, max(0.0, slot - duration - gap))
        events.append(ZoomEvent(
            start=round(start, 3),
            duration=round(duration, 3),
            factor=round(roller.num("zoom.auto_factor", 1.3), 4),
            ease=ease,
            fx=round(roller.uniform(0.35, 0.65), 3),
            fy=round(roller.uniform(0.35, 0.65), 3),
        ))
    return events


def _resolve_overlaps(events: list[ZoomEvent]) -> list[ZoomEvent]:
    """Подрезает зумы так, чтобы их окна не перекрывались.

    zoompan складывает кратности всех активных в этот момент событий: два
    наложенных ×1.5 дают ×2.0, а не ×1.5. В автоматическом режиме окна
    разводятся при планировании, но вручную человек легко задаст
    пересекающиеся — тогда наезд получался куда резче задуманного.
    Здесь более раннее событие обрезается по началу следующего.
    """
    gap = 0.05
    result: list[ZoomEvent] = []
    for index, event in enumerate(events):
        end = event.start + event.duration
        if index + 1 < len(events):
            limit = events[index + 1].start - gap
            if end > limit:
                event.duration = limit - event.start
        if event.duration > 0.05:
            result.append(event)
    return result


def zoom_expression(events: list[ZoomEvent]) -> str:
    """Кусочная функция зума от времени для zoompan.

    Вне событий даёт ровно 1.0 (кадр не трогается), внутри — нужную кратность.
    Для 'punch' — прямоугольник (мгновенный рывок), для 'ease' — полуволна
    синуса, то есть плавный наезд и такой же отъезд.
    """
    if not events:
        return "1"
    terms = []
    for event in events:
        start, end = event.start, event.start + event.duration
        gain = event.factor - 1.0
        window = f"between(it,{_f(start)},{_f(end)})"
        if event.ease == "ease" and event.duration > 0.05:
            shape = f"sin(PI*(it-{_f(start)})/{_f(event.duration)})"
            terms.append(f"{window}*{_f(gain)}*{shape}")
        else:
            terms.append(f"{window}*{_f(gain)}")
    return "1+" + "+".join(terms)


def _zoom_focus_expression(events: list[ZoomEvent], axis: str) -> str:
    """Точка фокуса зума. Между событиями значение не важно (zoom=1)."""
    if not events:
        return "0"
    dimension = "iw" if axis == "x" else "ih"
    focus = events[0].fx if axis == "x" else events[0].fy
    expression = _f(focus)
    for event in events[1:]:
        value = event.fx if axis == "x" else event.fy
        start, end = event.start, event.start + event.duration
        expression = f"if(between(it,{_f(start)},{_f(end)}),{_f(value)},{expression})"
    return f"({dimension}-{dimension}/zoom)*({expression})"


def _rotation_filter(radians: float) -> str:
    """Поворот кадра на маленький угол — через perspective, а не rotate.

    Оба фильтра дают одну и ту же картинку (проверено по SSIM: 0.995 при
    типичных 0.5°), но rotate считает каждый кадр заметно дороже. На замере
    он забирал больше половины всего процессорного времени цепочки, тогда
    как perspective решает ту же задачу примерно вдвое дешевле — а процессор
    здесь и есть узкое место, кодек занимает лишь десятую часть.

    perspective с sense=source ждёт координаты ТОЧЕК ИСХОДНИКА, которые
    должны попасть в углы результата. То есть углы кадра, повёрнутые на тот
    же угол в обратную сторону относительно центра.
    """
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    # Половины сторон записываем выражениями от W и H: так фильтр не зависит
    # от того, какой на входе размер кадра.
    hw, hh = "(W/2)", "(H/2)"
    c, s = _f(cos_a, 8), _f(sin_a, 8)
    points = [
        (f"{hw}*(1-{c})-{hh}*{s}", f"{hh}*(1-{c})+{hw}*{s}"),   # верх-лево
        (f"{hw}*(1+{c})-{hh}*{s}", f"{hh}*(1-{c})-{hw}*{s}"),   # верх-право
        (f"{hw}*(1-{c})+{hh}*{s}", f"{hh}*(1+{c})+{hw}*{s}"),   # низ-лево
        (f"{hw}*(1+{c})+{hh}*{s}", f"{hh}*(1+{c})-{hw}*{s}"),   # низ-право
    ]
    coords = ":".join(f"x{i}={x}:y{i}={y}" for i, (x, y) in enumerate(points))
    return f"perspective={coords}:interpolation=linear:sense=source"


# ---------------------------------------------------------------- видео

def _video_chain(
    info: MediaInfo,
    params: dict,
    roller: Roller,
    out_fps: float,
    events: list[ZoomEvent],
    speed_factor: float,
) -> tuple[list[str], int, int]:
    fx = params.get("video_fx", {})
    chain: list[str] = []

    # 1. Скорость. setpts сжимает временные метки, fps приводит поток к ровной сетке.
    # Значение разыграно один раз в build() и то же самое уходит в звук — иначе
    # картинка и звук разъедутся.
    if abs(speed_factor - 1.0) > 1e-4:
        chain.append(f"setpts=PTS/{_f(speed_factor, 6)}")
    chain.append(f"fps={_fps_arg(out_fps)}")

    width, height = info.width, info.height
    limit = int(params.get("encode", {}).get("max_dimension", 0) or 0)
    if limit and max(width, height) > limit:
        ratio = limit / max(width, height)
        target_w, target_h = width * ratio, height * ratio
    else:
        target_w, target_h = width, height
    # Стороны кадра всегда чётные. h264 с yuv420 не кодирует нечётный размер:
    # libx264 падает с «height not divisible by 2», а NVENC молча его прощает —
    # без этого исходник вроде 641x361 (кроп, запись экрана) ронял CPU-кодек.
    target_w, target_h = _even(target_w), _even(target_h)

    if fx.get("enabled", True):
        # 2. Микро-поворот. Держим исходный размер кадра: искажённые края,
        #    которые при этом появляются, срежет следующий шаг.
        angle = roller.num("video_fx.rotate_deg", 0.0)
        radians = math.radians(angle)
        if abs(angle) > 0.01:
            chain.append(_rotation_filter(radians))

        # 3. Микро-кроп. Обязательно с запасом на поворот, иначе в кадре
        #    останутся чёрные клинья от предыдущего шага. Кроп снимает по
        #    crop/2 с каждой стороны, а поворот съедает до H*sin(a) по ширине —
        #    отсюда двойка, и ещё 15% сверху на всякий случай.
        crop = roller.num("video_fx.crop_percent", 1.0) / 100.0
        needed = 2 * abs(math.sin(radians)) * (max(width, height) / min(width, height))
        crop = min(0.25, max(crop, needed * 1.15))
        if crop > 0.0005:
            keep = 1.0 - crop
            chain.append(
                f"crop=iw*{_f(keep)}:ih*{_f(keep)}:"
                f"(iw-iw*{_f(keep)})/2:(ih-ih*{_f(keep)})/2"
            )

        if roller.flag("video_fx.hflip", False):
            chain.append("hflip")

    # 4. Возврат к целевому размеру (после кропа/поворота).
    chain.append(f"scale={target_w}:{target_h}:flags=lanczos")
    chain.append("setsar=1")

    # 5. Зум. zoompan умеет менять кратность покадрово по времени (it).
    #    d=1 и явный fps не дают ему дублировать кадры.
    if events:
        chain.append(
            f"zoompan=z='{zoom_expression(events)}'"
            f":x='{_zoom_focus_expression(events, 'x')}'"
            f":y='{_zoom_focus_expression(events, 'y')}'"
            f":d=1:s={target_w}x{target_h}:fps={_fps_arg(out_fps)}"
        )

    if fx.get("enabled", True):
        # 6. Цвет.
        brightness = roller.num("video_fx.brightness", 0.0)
        contrast = roller.num("video_fx.contrast", 1.0)
        saturation = roller.num("video_fx.saturation", 1.0)
        gamma = roller.num("video_fx.gamma", 1.0)
        if any(abs(v - d) > 1e-4 for v, d in
               ((brightness, 0.0), (contrast, 1.0), (saturation, 1.0), (gamma, 1.0))):
            chain.append(
                f"eq=brightness={_f(brightness)}:contrast={_f(contrast)}"
                f":saturation={_f(saturation)}:gamma={_f(gamma)}"
            )
        hue = roller.num("video_fx.hue_deg", 0.0)
        if abs(hue) > 0.05:
            chain.append(f"hue=h={_f(hue)}")

        # 7. Зерно — после цвета, чтобы коррекция его не сгладила.
        if roller.flag("video_fx.grain", False):
            strength = roller.integer("video_fx.grain_strength", 6)
            if strength > 0:
                chain.append(f"noise=alls={strength}:allf=t+u")

        if roller.flag("video_fx.vignette", False):
            chain.append(f"vignette=angle={_f(roller.num('video_fx.vignette_angle', 0.1))}")

    return chain, target_w, target_h


def _overlay_chain(
    params: dict, roller: Roller, width: int, height: int
) -> tuple[list[str], str, str]:
    """Готовит картинку и возвращает (цепочка, выражение x, выражение y)."""
    overlay = params.get("overlay", {})
    chain = ["format=rgba"]

    angle = roller.num("overlay.rotate_deg", 0.0)
    if abs(angle) > 0.05:
        radians = math.radians(angle)
        chain.append(
            f"rotate={_f(radians, 7)}:ow=rotw({_f(radians, 7)})"
            f":oh=roth({_f(radians, 7)}):c=black@0"
        )

    mode = roller.text("overlay.mode", "cover")
    drift = roller.flag("overlay.drift", False)
    amplitude = roller.num("overlay.drift_px", 0.0) if drift else 0.0
    # При дрейфе картинка должна быть больше кадра, иначе из-под неё выглянут края.
    margin = int(math.ceil(amplitude)) if drift else 0
    box_w, box_h = width + 2 * margin, height + 2 * margin

    if mode == "cover":
        chain.append(f"scale={box_w}:{box_h}:force_original_aspect_ratio=increase")
        chain.append(f"crop={box_w}:{box_h}")
    elif mode == "fit":
        chain.append(f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease")
        chain.append(f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=black@0")
    elif mode == "tile":
        # tile склеивает последовательность кадров, поэтому сначала размножаем
        # единственный кадр картинки фильтром loop.
        columns, rows = 3, 3
        chain.append(f"scale={_even(box_w / columns)}:{_even(box_h / rows)}")
        chain.append(f"loop=loop={columns * rows - 1}:size=1:start=0")
        chain.append(f"tile={columns}x{rows}")
        chain.append(f"scale={box_w}:{box_h}")
    else:  # stretch
        chain.append(f"scale={box_w}:{box_h}")

    opacity = max(0.0, min(1.0, roller.num("overlay.opacity", 0.05)))
    # colorchannelmixer=aa УМНОЖАЕТ существующую альфу, поэтому собственная
    # прозрачность PNG сохраняется, а не затирается.
    chain.append(f"colorchannelmixer=aa={_f(opacity)}")

    if drift and amplitude > 0.5:
        period = max(1.0, roller.num("overlay.drift_period_s", 10.0))
        phase = roller.uniform(0, 6.283)
        x_expr = f"-{margin}+{_f(amplitude)}*sin(2*PI*t/{_f(period)}+{_f(phase)})"
        y_expr = f"-{margin}+{_f(amplitude)}*cos(2*PI*t/{_f(period * 1.37)}+{_f(phase)})"
    else:
        x_expr, y_expr = f"-{margin}", f"-{margin}"

    return chain, x_expr, y_expr


# ---------------------------------------------------------------- звук

def _audio_chain(
    params: dict, roller: Roller, speed_factor: float, source_rate: int
) -> list[str]:
    audio = params.get("audio", {})
    speed = params.get("speed", {})
    chain: list[str] = []

    # 1. Ускорение. atempo тянет время, не трогая высоту тона; asetrate —
    #    как ускоренная плёнка, вместе с тоном.
    if abs(speed_factor - 1.0) > 1e-4:
        if speed.get("preserve_pitch", True):
            chain += _atempo_chain(speed_factor)
        else:
            # Считать надо от РЕАЛЬНОЙ частоты дискретизации исходника:
            # подставишь сюда 48000 на файле с 44100 — и ускорение уедет
            # в 48000/44100 раза мимо заданного.
            chain.append(f"asetrate={int(round(source_rate * speed_factor))}")
            chain.append(f"aresample={source_rate}")

    if not audio.get("enabled", True):
        return chain

    # 2. Сдвиг тона без изменения длительности. Разыгрывается модуль,
    #    направление — вверх или вниз — выбирается отдельно.
    semitones = abs(roller.num("audio.pitch_semitones", 0.0)) * roller.pick((-1, 1))
    if abs(semitones) > 0.005:
        chain += _pitch_chain(2 ** (semitones / 12.0), source_rate)

    # 3. Случайный эквалайзер: каждая полоса — свой центр, ширина и усиление.
    bands = int(audio.get("eq_bands", 0) or 0)
    for _ in range(bands):
        frequency = roller.num("audio.eq_freq_hz", 1000.0)
        width = roller.num("audio.eq_width_q", 1.2)
        gain = roller.num("audio.eq_gain_db", 0.0)
        if abs(gain) < 0.02:
            continue
        chain.append(
            f"equalizer=f={_f(frequency, 2)}:width_type=q:w={_f(width)}:g={_f(gain)}"
        )

    # 4. Спектральная обработка: лёгкая частотно-зависимая раскачка амплитуд.
    #    Двигает пики спектрограммы там, где обычный эквалайзер оставил бы их на месте.
    if roller.flag("audio.spectral", False):
        strength = roller.num("audio.spectral_strength", 0.08)
        if strength > 0.005:
            phase = roller.uniform(0, 6.283)
            # real/imag — это имена опций, а внутри выражений части спектра
            # называются re и im. Каждая масштабирует саму себя: иначе ломается
            # фаза и звук превращается в металлический звон.
            envelope = f"(1+{_f(strength)}*sin(b/7+{_f(phase)}))"
            chain.append(
                f"afftfilt=real='re*{envelope}':imag='im*{envelope}'"
                f":win_size=512:overlap=0.75"
            )

    # 5. Микро-эхо: слышится слитно с оригиналом, но спектр уже другой.
    if roller.flag("audio.micro_echo", False):
        delay = roller.num("audio.micro_echo_ms", 6.0)
        decay = roller.num("audio.micro_echo_decay", 0.1)
        if delay > 0.5 and decay > 0.005:
            # Выходное усиление гасим на величину отражения, иначе сумма
            # прямого и задержанного сигнала уходит в перегруз.
            chain.append(
                f"aecho=1:{_f(1.0 / (1.0 + decay))}:{_f(delay, 2)}:{_f(decay)}"
            )

    highpass = roller.num("audio.highpass_hz", 0.0)
    if highpass > 10:
        chain.append(f"highpass=f={_f(highpass, 1)}")
    lowpass = roller.num("audio.lowpass_hz", 0.0)
    if 1000 < lowpass < 22000:
        chain.append(f"lowpass=f={_f(lowpass, 1)}")

    volume = roller.num("audio.volume_db", 0.0)
    if abs(volume) > 0.02:
        chain.append(f"volume={_f(volume)}dB")

    return chain


def _pitch_chain(ratio: float, source_rate: int) -> list[str]:
    """Сдвиг высоты тона без изменения длительности.

    Основной путь — rubberband: он держит длительность до отсчёта. Но эта
    библиотека собрана далеко не в каждом ffmpeg, и на чужой машине программа
    падала с «No such filter: rubberband». Поэтому есть запасной путь на
    встроенных фильтрах: ускоряем воспроизведение (тон уезжает вверх вместе
    со скоростью), а потом возвращаем прежний темп, не трогая тон.

    Запасной вариант даже чище по спектру и быстрее, но длительность гуляет
    на единицы миллисекунд — на синхрон это не влияет.
    """
    if filter_available("rubberband"):
        return [f"rubberband=pitch={_f(ratio, 7)}:pitchq=quality"]
    return [
        f"asetrate={int(round(source_rate * ratio))}",
        f"aresample={source_rate}",
    ] + _atempo_chain(1.0 / ratio)


def _noise_source(roller: Roller, duration: float) -> str:
    """lavfi-источник неслышимого ВЧ-сигнала."""
    frequency = roller.num("audio.hf_noise_freq_hz", 17500.0)
    length = max(1.0, duration + 1.0)
    return f"sine=frequency={_f(frequency, 1)}:sample_rate=48000:duration={_f(length, 3)}"


# ---------------------------------------------------------------- метаданные

def _metadata_args(params: dict, roller: Roller) -> list[str]:
    encode = params.get("encode", {})
    args: list[str] = []
    if encode.get("strip_metadata", True):
        args += ["-map_metadata", "-1"]
    if encode.get("fake_metadata", True):
        year = roller.randint(2023, 2026)
        month, day = roller.randint(1, 12), roller.randint(1, 28)
        hour, minute, second = roller.randint(6, 23), roller.randint(0, 59), roller.randint(0, 59)
        make, model, android = roller.pick(_CAMERAS)
        args += [
            "-metadata", f"creation_time={year}-{month:02d}-{day:02d}"
                         f"T{hour:02d}:{minute:02d}:{second:02d}.000000Z",
            "-metadata", f"make={make}",
            "-metadata", f"model={model}",
            "-metadata:s:v", f"handler_name={roller.pick(_HANDLERS_VIDEO)}",
            "-metadata:s:a", f"handler_name={roller.pick(_HANDLERS_AUDIO)}",
            "-brand", roller.pick(_BRANDS),
        ]
        if android:
            args += ["-metadata", f"com.android.version={android}"]
    return args


def _encoder_args(params: dict, roller: Roller, out_fps: float) -> list[str]:
    encode = params.get("encode", {})
    quality = int(round(roller.num("encode.quality", 22)))
    quality = max(10, min(38, quality))

    keyint = roller.integer("encode.keyint", 60) if encode.get("keyint_jitter", True) \
        else int(round(out_fps * 2))
    keyint = max(12, keyint)

    choice = encode.get("encoder", "auto")
    use_nvenc = choice == "nvenc" or (choice == "auto" and nvenc_available())

    if use_nvenc:
        args = [
            "-c:v", "h264_nvenc",
            "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
            "-profile:v", "high", "-rc-lookahead", "20",
            "-spatial-aq", "1", "-aq-strength", str(roller.randint(7, 12)),
            "-bf", str(roller.randint(2, 4)),
        ]
    else:
        args = [
            "-c:v", "libx264",
            "-preset", roller.pick(["veryfast", "faster", "fast"]),
            "-crf", str(quality),
            "-profile:v", "high",
            "-bf", str(roller.randint(2, 4)),
        ]
    args += ["-g", str(keyint), "-pix_fmt", "yuv420p"]
    return args


# ---------------------------------------------------------------- сборка

def build(
    info: MediaInfo,
    out_path: str,
    params: dict,
    seed: int,
) -> BuildResult:
    roller = Roller(params, seed)

    speed = params.get("speed", {})
    if speed.get("enabled", True):
        speed_factor = roller.num("speed.factor", 1.0)
        # Джиттер входит в общий коэффициент: и картинка, и звук растягиваются
        # на одну и ту же величину, поэтому длительности всегда совпадают.
        speed_factor *= roller.num("speed.jitter", 1.0)
    else:
        # Выключенная скорость значит именно выключенную: джиттер тоже молчит,
        # иначе снятая галочка всё равно меняла бы длительность на полпроцента.
        speed_factor = 1.0
    speed_factor = max(0.25, min(8.0, speed_factor))
    out_duration = info.duration / speed_factor if info.duration else 0.0

    fx = params.get("video_fx", {})
    out_fps = pick_fps(
        info.fps, roller,
        jitter=bool(fx.get("fps_jitter", True)),
        manual=fx.get("fps_choices") or None,
    )

    events = plan_zoom_events(params, roller, out_duration)

    overlay = params.get("overlay", {})
    overlay_on = bool(overlay.get("enabled")) and bool(overlay.get("path"))
    audio_on = params.get("audio", {}).get("enabled", True)
    noise_on = audio_on and bool(params.get("audio", {}).get("hf_noise"))

    # ------------------------------------------------------------ входы
    args: list[str] = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
    args += ["-i", info.path]

    index = 1
    overlay_index = audio_index = noise_index = None
    if overlay_on:
        overlay_index = index
        args += ["-i", str(overlay["path"])]
        index += 1
    if not info.has_audio:
        audio_index = index
        args += ["-f", "lavfi", "-t", _f(max(1.0, info.duration), 3),
                 "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        index += 1
    if noise_on:
        noise_index = index
        args += ["-f", "lavfi", "-i", _noise_source(roller, out_duration)]
        index += 1

    # ------------------------------------------------------------ граф
    graph: list[str] = []
    video_chain, width, height = _video_chain(
        info, params, roller, out_fps, events, speed_factor
    )
    graph.append("[0:v]" + ",".join(video_chain) + "[v0]")

    video_label = "[v0]"
    if overlay_on:
        ov_chain, x_expr, y_expr = _overlay_chain(params, roller, width, height)
        graph.append(f"[{overlay_index}:v]" + ",".join(ov_chain) + "[ovl]")
        graph.append(
            f"[v0][ovl]overlay=x='{x_expr}':y='{y_expr}'"
            f":eof_action=repeat:format=auto[v1]"
        )
        video_label = "[v1]"

    graph.append(f"{video_label}format=yuv420p[vout]")

    audio_source = "[0:a]" if info.has_audio else f"[{audio_index}:a]"
    source_rate = info.audio_samplerate if info.has_audio else 48000
    audio_chain = _audio_chain(params, roller, speed_factor, source_rate)
    audio_label = "[a0]"
    graph.append(audio_source + (",".join(audio_chain) if audio_chain else "anull") + "[a0]")

    if noise_on:
        level_db = roller.num("audio.hf_noise_level_db", -46.0)
        graph.append(
            f"[{noise_index}:a]volume={_f(level_db)}dB,"
            f"aformat=channel_layouts=stereo[hf]"
        )
        # normalize=0 обязательно: иначе amix поделит громкость на число входов.
        graph.append(f"[a0][hf]amix=inputs=2:duration=first:normalize=0[a1]")
        audio_label = "[a1]"

    samplerate = roller.choice("encode.audio_samplerate", 48000)
    tail = [f"aresample={samplerate}"]
    if roller.flag("audio.limiter", True):
        tail.append("alimiter=limit=0.97:level=0")
    graph.append(f"{audio_label}" + ",".join(tail) + "[aout]")

    args += ["-filter_complex", ";".join(graph)]
    args += ["-map", "[vout]", "-map", "[aout]"]

    # ------------------------------------------------------------ кодек
    args += _encoder_args(params, roller, out_fps)
    bitrate = roller.choice("encode.audio_bitrate_kbps", 160)
    args += ["-c:a", "aac", "-b:a", f"{bitrate}k", "-ar", str(samplerate), "-ac", "2"]
    args += _metadata_args(params, roller)
    # use_metadata_tags обязателен: без него mp4-муксер молча выбрасывает
    # make/model и всё, что не входит в его короткий список известных тегов.
    movflags = ["+use_metadata_tags"]
    if params.get("encode", {}).get("faststart", True):
        movflags.append("+faststart")
    args += ["-movflags", "".join(movflags)]
    # Пробный прогон: короткий кусок, чтобы быстро посмотреть настройки.
    preview = float(params.get("output", {}).get("preview_seconds", 0) or 0)
    if preview > 0:
        args += ["-t", _f(preview, 3)]
        out_duration = min(out_duration, preview) if out_duration else preview

    args += ["-progress", "pipe:1", "-nostats", out_path]

    report = {
        "seed": seed,
        "source": info.path,
        "output": out_path,
        "source_duration": round(info.duration, 3),
        "output_duration": round(out_duration, 3),
        "source_resolution": f"{info.width}x{info.height}",
        "output_resolution": f"{width}x{height}",
        "output_fps": out_fps,
        "speed_factor": round(speed_factor, 4),
        "zoom_events": [vars(event) for event in events],
        "rolled": roller.rolled,
    }
    return BuildResult(args=args, report=report, out_duration=out_duration,
                       zoom_events=events)
