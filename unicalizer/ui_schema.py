"""Описание полей интерфейса: подпись, тип, границы ползунка, подсказка.

Отдельно от params.py, чтобы движок не тащил за собой ничего про интерфейс.

kind:
    bool        — переключатель
    range       — двусторонний ползунок (дробные значения)
    range_int   — двусторонний ползунок (целые)
    int         — одно целое
    choice      — выпадающий список
    text        — строка
    file        — строка + кнопка «Обзор»

bounds — пределы самого ползунка, а не рекомендуемые значения. Внутри них
пользователь выбирает промежуток, из которого разыгрывается каждая копия.
"""

from __future__ import annotations

TABS: list[tuple[str, str, str, list[dict]]] = [
    (
        "audio",
        "Звук",
        "♪",
        [
            {"path": "audio.enabled", "kind": "bool", "label": "Обрабатывать звук",
             "hint": "Выключите, чтобы оставить исходную дорожку нетронутой."},
            {"path": "audio.pitch_semitones", "kind": "range",
             "label": "Сдвиг тона, ± полутона", "bounds": (0, 1.2), "decimals": 2,
             "hint": "Двигает всю спектрограмму по частоте — сильнее всего мешает "
                     "сопоставить звук. Задаётся модуль, вверх или вниз решается "
                     "случайно. 0.35 полутона ≈ 2%, это предел незаметности. "
                     "Не опускайте нижнюю границу к нулю: такие копии останутся без сдвига."},
            {"path": "audio.eq_bands", "kind": "int", "label": "Полос эквалайзера",
             "bounds": (0, 10),
             "hint": "Сколько случайных полос подмешать. 0 — выключить."},
            {"path": "audio.eq_gain_db", "kind": "range", "label": "Усиление полос, дБ",
             "bounds": (-6, 6), "decimals": 2,
             "hint": "До ±2 дБ ухо не ловит, а огибающая спектра меняется."},
            {"path": "audio.eq_freq_hz", "kind": "range", "label": "Частоты полос, Гц",
             "bounds": (40, 16000), "decimals": 0,
             "hint": "Промежуток, из которого выбираются центры полос."},
            {"path": "audio.eq_width_q", "kind": "range", "label": "Ширина полос (Q)",
             "bounds": (0.3, 4.0), "decimals": 2,
             "hint": "Меньше Q — шире полоса."},
            {"path": "audio.hf_noise", "kind": "bool", "label": "ВЧ-шум (неслышимый)",
             "hint": "Подмешивает тон около 16 кГц. Человек его не слышит, "
                     "а в спектре он есть."},
            {"path": "audio.hf_noise_freq_hz", "kind": "range",
             "label": "Частота ВЧ-шума, Гц", "bounds": (14000, 20000), "decimals": 0,
             "hint": "Выше 16 кГц взрослое ухо уже почти ничего не различает. "
                     "Но не поднимайте выше 17 кГц: площадки пережимают звук "
                     "в AAC, а он срезает всё выше ≈17.3 кГц — метка пропадёт "
                     "из выложенного ролика."},
            {"path": "audio.hf_noise_level_db", "kind": "range",
             "label": "Уровень ВЧ-шума, дБ", "bounds": (-70, -25), "decimals": 1,
             "hint": "Чем ближе к нулю, тем заметнее. −50 дБ безопасно."},
            {"path": "audio.spectral", "kind": "bool", "label": "Спектральная обработка",
             "hint": "Перекраивает спектр по частотам. Сильнее всего ломает совпадение "
                     "по аудио-отпечатку."},
            {"path": "audio.spectral_strength", "kind": "range", "label": "Сила спектралки",
             "bounds": (0, 0.4), "decimals": 3,
             "hint": "0.04–0.12 незаметно, выше 0.25 появляется металлический звон."},
            {"path": "audio.micro_echo", "kind": "bool", "label": "Микро-эхо",
             "hint": "Задержка в единицы миллисекунд: слышится слитно с оригиналом, "
                     "но пики спектрограммы съезжают."},
            {"path": "audio.micro_echo_ms", "kind": "range", "label": "Задержка эха, мс",
             "bounds": (1, 30), "decimals": 1,
             "hint": "До 10 мс безопасно. Больше 25 мс слышно как «бочку»."},
            {"path": "audio.micro_echo_decay", "kind": "range", "label": "Затухание эха",
             "bounds": (0.01, 0.4), "decimals": 3,
             "hint": "Громкость отражения относительно основного сигнала."},
            {"path": "audio.highpass_hz", "kind": "range", "label": "Срез низов, Гц",
             "bounds": (10, 200), "decimals": 0,
             "hint": "Убирает инфраниз, которого всё равно не слышно."},
            {"path": "audio.lowpass_hz", "kind": "range", "label": "Срез верхов, Гц",
             "bounds": (12000, 21000), "decimals": 0,
             "hint": "Срезает самый верх основной дорожки. ВЧ-шум подмешивается "
                     "уже после среза и под него не попадает."},
            {"path": "audio.volume_db", "kind": "range", "label": "Громкость, дБ",
             "bounds": (-6, 6), "decimals": 2,
             "hint": "Общий сдвиг уровня."},
            {"path": "audio.limiter", "kind": "bool",
             "label": "Лимитер (защита от перегруза)",
             "hint": "Держите включённым: иначе после эквалайзера возможен клиппинг."},
        ],
    ),
    (
        "speed",
        "Скорость",
        "▶",
        [
            {"path": "speed.enabled", "kind": "bool", "label": "Менять скорость"},
            {"path": "speed.factor", "kind": "range", "label": "Ускорение, ×",
             "bounds": (0.5, 4.0), "decimals": 3,
             "hint": "Итоговая длительность = исходная ÷ значение. 2.1–2.2 по вашей задаче."},
            {"path": "speed.jitter", "kind": "range", "label": "Джиттер темпа, ×",
             "bounds": (0.98, 1.02), "decimals": 4,
             "hint": "Мелкий довесок к ускорению, чтобы длительность копий не совпадала "
                     "до кадра. Применяется к картинке и звуку одновременно, поэтому "
                     "дорожки не разъезжаются."},
            {"path": "speed.preserve_pitch", "kind": "bool",
             "label": "Сохранять высоту голоса",
             "hint": "Включено — голос звучит нормально, просто быстрее. Выключено — "
                     "эффект «бурундуков»: тон уезжает вверх вместе со скоростью."},
        ],
    ),
    (
        "overlay",
        "Оверлей",
        "▣",
        [
            {"path": "overlay.enabled", "kind": "bool", "label": "Накладывать картинку"},
            {"path": "overlay.path", "kind": "file", "label": "Файл картинки",
             "hint": "PNG с прозрачностью или обычный JPG. Своя прозрачность картинки "
                     "перемножается со значением ниже."},
            {"path": "overlay.opacity", "kind": "range", "label": "Непрозрачность",
             "bounds": (0, 0.5), "decimals": 3,
             "hint": "0.03 = 3%: глазом не видно, но каждый пиксель кадра изменён. "
                     "Выше 0.15 картинка становится заметной."},
            {"path": "overlay.mode", "kind": "choice", "label": "Вписывание",
             "choices": ["cover", "fit", "stretch", "tile"],
             "hint": "cover — заполнить с обрезкой, fit — вписать целиком, "
                     "stretch — растянуть, tile — размножить плиткой."},
            {"path": "overlay.drift", "kind": "bool", "label": "Медленный дрейф",
             "hint": "Картинка еле заметно плавает по кадру — копии не совпадают "
                     "покадрово."},
            {"path": "overlay.drift_px", "kind": "range", "label": "Амплитуда дрейфа, px",
             "bounds": (0, 80), "decimals": 1},
            {"path": "overlay.drift_period_s", "kind": "range", "label": "Период дрейфа, с",
             "bounds": (2, 40), "decimals": 1},
            {"path": "overlay.rotate_deg", "kind": "range", "label": "Поворот картинки, °",
             "bounds": (-15, 15), "decimals": 1},
        ],
    ),
    (
        "zoom",
        "Зум",
        "⌕",
        [
            {"path": "zoom.enabled", "kind": "bool", "label": "Включить зум"},
            {"path": "zoom.auto", "kind": "bool",
             "label": "Расставлять зумы автоматически",
             "hint": "Выключите, если задаёте моменты вручную в таблице ниже."},
            {"path": "zoom.auto_count", "kind": "range_int", "label": "Сколько зумов",
             "bounds": (0, 12),
             "hint": "Количество разыгрывается в этих пределах для каждой копии."},
            {"path": "zoom.auto_factor", "kind": "range", "label": "Кратность, ×",
             "bounds": (1.0, 2.5), "decimals": 2,
             "hint": "1.3 — заметный наезд, 1.6 — резкий."},
            {"path": "zoom.auto_dur_s", "kind": "range", "label": "Длительность зума, с",
             "bounds": (0.1, 5.0), "decimals": 2},
            {"path": "zoom.auto_ease", "kind": "choice", "label": "Характер",
             "choices": ["punch", "ease"],
             "hint": "punch — мгновенный рывок и такой же выход, "
                     "ease — плавно наехать и отъехать."},
            {"path": "zoom.auto_margin_s", "kind": "range", "label": "Отступ от краёв, с",
             "bounds": (0, 10), "decimals": 1,
             "hint": "Не ставить зум в самом начале и в самом конце ролика."},
        ],
    ),
    (
        "video_fx",
        "Картинка",
        "◉",
        [
            {"path": "video_fx.enabled", "kind": "bool", "label": "Обрабатывать картинку"},
            {"path": "video_fx.crop_percent", "kind": "range", "label": "Микро-кроп, %",
             "bounds": (0, 10), "decimals": 2,
             "hint": "Срезает края и растягивает обратно. Сдвигает всю сетку пикселей."},
            {"path": "video_fx.rotate_deg", "kind": "range", "label": "Микро-поворот, °",
             "bounds": (-3, 3), "decimals": 2,
             "hint": "До 0.5° глазом не поймать. Кроп при этом увеличивается сам, "
                     "чтобы не показались чёрные уголки."},
            {"path": "video_fx.hflip", "kind": "bool", "label": "Отзеркалить по горизонтали",
             "hint": "Сильно меняет хеши, но зритель это видит. Не включайте, "
                     "если в кадре есть текст."},
            {"path": "video_fx.brightness", "kind": "range", "label": "Яркость",
             "bounds": (-0.15, 0.15), "decimals": 3},
            {"path": "video_fx.contrast", "kind": "range", "label": "Контраст, ×",
             "bounds": (0.8, 1.2), "decimals": 3},
            {"path": "video_fx.saturation", "kind": "range", "label": "Насыщенность, ×",
             "bounds": (0.7, 1.3), "decimals": 3},
            {"path": "video_fx.gamma", "kind": "range", "label": "Гамма, ×",
             "bounds": (0.85, 1.15), "decimals": 3},
            {"path": "video_fx.hue_deg", "kind": "range", "label": "Сдвиг оттенка, °",
             "bounds": (-20, 20), "decimals": 1,
             "hint": "До 4° незаметно на большинстве сюжетов."},
            {"path": "video_fx.grain", "kind": "bool", "label": "Зерно (шум)",
             "hint": "Ломает попиксельное сравнение кадров."},
            {"path": "video_fx.grain_strength", "kind": "range_int", "label": "Сила зерна",
             "bounds": (0, 40),
             "hint": "До 12 почти незаметно, выше 25 виден «песок»."},
            {"path": "video_fx.vignette", "kind": "bool", "label": "Виньетка"},
            {"path": "video_fx.vignette_angle", "kind": "range", "label": "Сила виньетки",
             "bounds": (0, 0.5), "decimals": 3},
            {"path": "video_fx.fps_jitter", "kind": "bool",
             "label": "Менять частоту кадров",
             "hint": "Выбирает частоту рядом с исходной. Меняет тайминги всех кадров, "
                     "но не роняет плавность."},
        ],
    ),
    (
        "encode",
        "Кодек и вывод",
        "⚙",
        [
            {"path": "encode.encoder", "kind": "choice", "label": "Кодировщик",
             "choices": ["auto", "nvenc", "cpu"],
             "hint": "auto — NVENC если видеокарта тянет (в разы быстрее), иначе процессор. "
                     "cpu (x264) даёт лучшее качество на бит, но медленнее."},
            {"path": "encode.quality", "kind": "range",
             "label": "Качество (меньше = лучше)", "bounds": (14, 34), "decimals": 1,
             "hint": "20–23 хорошо для соцсетей, 18 почти без потерь, 28 заметно хуже."},
            {"path": "encode.keyint_jitter", "kind": "bool",
             "label": "Джиттер ключевых кадров",
             "hint": "Меняет структуру потока — файлы отличаются на уровне битстрима."},
            {"path": "encode.keyint", "kind": "range_int",
             "label": "Интервал ключевых кадров", "bounds": (12, 300)},
            {"path": "encode.max_dimension", "kind": "int",
             "label": "Макс. сторона кадра, px", "bounds": (0, 4096),
             "hint": "0 — не менять разрешение. 1080 — ужать под вертикальные форматы."},
            {"path": "encode.strip_metadata", "kind": "bool",
             "label": "Стереть метаданные исходника"},
            {"path": "encode.fake_metadata", "kind": "bool",
             "label": "Записать свои метаданные",
             "hint": "Случайные дата съёмки, марка и модель «камеры», тип контейнера."},
            {"path": "encode.faststart", "kind": "bool",
             "label": "faststart (быстрая отдача)",
             "hint": "Переносит индекс в начало файла — нужно для веб-загрузки."},
            {"path": "output.copies_per_file", "kind": "int", "label": "Копий на файл",
             "bounds": (1, 100),
             "hint": "Сколько разных вариантов сделать из каждого исходника."},
            {"path": "output.pattern", "kind": "text", "label": "Шаблон имени",
             "hint": "{name} — имя исходника, {i} — номер копии, {seed} — сид."},
            {"path": "output.parallel_jobs", "kind": "int", "label": "Параллельных задач",
             "bounds": (1, 4),
             "hint": "По умолчанию считается от числа ядер (четверть от них). Упор идёт "
                     "в процессор, а не в видеокарту: сам кодек занимает лишь около "
                     "десятой части времени, остальное — фильтры. Выше четырёх "
                     "прироста нет, поэтому это и есть предел."},
            {"path": "output.write_report", "kind": "bool", "label": "Писать отчёт .json",
             "hint": "Рядом с каждым файлом сохраняются все разыгранные значения и сид, "
                     "чтобы удачный вариант можно было повторить."},
        ],
    ),
]
