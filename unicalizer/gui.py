"""Окно программы: левое меню, страница запуска, очередь и помощь."""

from __future__ import annotations

import copy
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from . import config, engine, help_text, probe
from .params import DEFAULT_PARAMS, PRESETS, load_preset_file, merge, save_preset_file
from .theme import C, QSS
from .ui_schema import TABS
from .widgets import (
    Accordion, Card, DropZone, JobRow, NavItem, RangeSlider, SectionTitle,
    Spinner, Toggle,
)

APP_TITLE = "Video Unicalizer"
APP_SUBTITLE = "массовая уникализация видео"
BRAND_SUBTITLE = "уникализация видео"
CHANNEL_URL = "https://t.me/YT_cartell"

VIDEO_FILTER = ("Видео (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.ts "
                "*.mpg *.mpeg *.3gp);;Все файлы (*.*)")
IMAGE_FILTER = "Картинки (*.png *.jpg *.jpeg *.webp *.bmp);;Все файлы (*.*)"

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def default_output_dir() -> Path:
    """Куда складывать результат, если пользователь не выбрал папку сам.

    У собранного приложения путь от исходника ведёт внутрь самой сборки —
    писать туда нельзя: при переустановке всё пропадёт, а в Program Files
    ещё и прав не хватит. Поэтому берём пользовательскую папку с видео.
    """
    if getattr(sys, "frozen", False):
        # Папка с видео называется по-разному: Movies на macOS, Videos на Windows.
        for name in ("Movies", "Videos") if sys.platform == "darwin" else ("Videos",):
            folder = Path.home() / name
            if folder.is_dir():
                return folder / "Video Unicalizer"
        return Path.home() / "Video Unicalizer"
    return Path(__file__).resolve().parent.parent / "output"


def app_icon() -> QIcon:
    """Иконка приложения во всех размерах, что есть в assets."""
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256, 512):
        path = ASSETS / f"icon_{size}.png"
        if path.is_file():
            icon.addFile(str(path))
    if icon.isNull() and (ASSETS / "icon.png").is_file():
        icon.addFile(str(ASSETS / "icon.png"))
    return icon


class Bridge(QObject):
    """Мост из рабочих потоков в поток интерфейса.

    Qt запрещает трогать виджеты не из главного потока, поэтому движок шлёт
    сигналы, а перерисовкой занимается уже сам интерфейс.
    """

    job_changed = Signal(object)
    logged = Signal(str)
    finished = Signal(object)
    planned = Signal(object)
    tools = Signal(object)


# ---------------------------------------------------------------- поле

class Field(QWidget):
    """Одна настройка: подпись, элемент управления, подсказка."""

    changed = Signal()

    def __init__(self, spec: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.kind = spec["kind"]
        self.path = spec["path"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(12)
        outer.addLayout(row)

        if self.kind == "bool":
            self.control = Toggle()
            self.control.toggled.connect(self._notify)
            label = QLabel(spec["label"])
            label.setObjectName("fieldLabel")
            row.addWidget(self.control)
            row.addWidget(label, 1)
            indent = 54
        else:
            label = QLabel(spec["label"])
            label.setObjectName("fieldLabel")
            label.setFixedWidth(186)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            row.addWidget(label)
            row.addWidget(self._build_control(spec), 1)
            indent = 198

        hint = spec.get("hint")
        if hint:
            note = QLabel(hint)
            note.setObjectName("hint")
            note.setWordWrap(True)
            note.setContentsMargins(indent, 0, 0, 0)
            outer.addWidget(note)

    def _notify(self, *_args) -> None:
        """Источники шлют разные аргументы (bool, str, пару чисел) — глотаем их."""
        self.changed.emit()

    def _build_control(self, spec: dict) -> QWidget:
        kind = self.kind
        if kind in ("range", "range_int"):
            low, high = spec.get("bounds", (0, 1))
            decimals = 0 if kind == "range_int" else spec.get("decimals", 2)
            box = QWidget()
            line = QHBoxLayout(box)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)

            self.slider = RangeSlider(low, high, low, high, decimals)
            self.badge_lo = self._badge()
            self.badge_hi = self._badge()
            line.addWidget(self.badge_lo)
            line.addWidget(self.slider, 1)
            line.addWidget(self.badge_hi)

            self.slider.changed.connect(self._refresh_badges)
            self.slider.changed.connect(self._notify)
            self.badge_lo.editingFinished.connect(self._from_badges)
            self.badge_hi.editingFinished.connect(self._from_badges)
            self.control = self.slider
            return box

        if kind == "int":
            self.control = QSpinBox()
            low, high = spec.get("bounds", (0, 9999))
            self.control.setRange(int(low), int(high))
            self.control.setFixedWidth(110)
            self.control.setAlignment(Qt.AlignCenter)
            self.control.valueChanged.connect(self._notify)
            return self._left(self.control)

        if kind == "choice":
            self.control = QComboBox()
            self.control.addItems(spec["choices"])
            self.control.setFixedWidth(160)
            self.control.currentTextChanged.connect(self._notify)
            return self._left(self.control)

        if kind == "file":
            wrapper = QWidget()
            line = QHBoxLayout(wrapper)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            self.control = QLineEdit()
            self.control.setPlaceholderText("картинка не выбрана")
            self.control.textChanged.connect(self._notify)
            browse = QPushButton("Обзор…")
            browse.setFixedWidth(92)
            browse.clicked.connect(self._browse)
            line.addWidget(self.control, 1)
            line.addWidget(browse)
            return wrapper

        self.control = QLineEdit()
        self.control.textChanged.connect(self._notify)
        return self.control

    @staticmethod
    def _left(widget: QWidget) -> QWidget:
        wrapper = QWidget()
        line = QHBoxLayout(wrapper)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(widget)
        line.addStretch(1)
        return wrapper

    def _badge(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("valueBadge")
        edit.setFixedWidth(66)
        edit.setAlignment(Qt.AlignCenter)
        return edit

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Картинка для наложения",
                                              "", IMAGE_FILTER)
        if path:
            self.control.setText(path)

    def _format(self, value: float) -> str:
        decimals = self.slider.decimals
        return f"{value:.{decimals}f}" if decimals else str(int(round(value)))

    def _refresh_badges(self, *_args) -> None:
        low, high = self.slider.values()
        self.badge_lo.setText(self._format(low))
        self.badge_hi.setText(self._format(high))

    def _from_badges(self) -> None:
        try:
            low = float(self.badge_lo.text().replace(",", "."))
            high = float(self.badge_hi.text().replace(",", "."))
        except ValueError:
            self._refresh_badges()
            return
        # Введённое вручную значение может выходить за пределы ползунка —
        # расширяем шкалу, а не обрезаем то, что человек напечатал.
        self.slider.setBounds(min(self.slider.minimum, low, high),
                              max(self.slider.maximum, low, high))
        self.slider.setValues(low, high)
        self._refresh_badges()
        self.changed.emit()

    def value(self) -> Any:
        if self.kind == "bool":
            return self.control.isChecked()
        if self.kind == "range":
            return list(self.slider.values())
        if self.kind == "range_int":
            low, high = self.slider.values()
            return [int(round(low)), int(round(high))]
        if self.kind == "int":
            return self.control.value()
        if self.kind == "choice":
            return self.control.currentText()
        return self.control.text()

    def setValue(self, value: Any) -> None:
        if self.kind == "bool":
            self.control.setChecked(bool(value))
        elif self.kind in ("range", "range_int"):
            if isinstance(value, (list, tuple)) and len(value) == 2:
                low, high = float(value[0]), float(value[1])
            else:
                low = high = float(value)
            self.slider.setBounds(min(self.slider.minimum, low, high),
                                  max(self.slider.maximum, low, high))
            self.slider.setValues(low, high)
            self._refresh_badges()
        elif self.kind == "int":
            self.control.setValue(int(value))
        elif self.kind == "choice":
            index = self.control.findText(str(value))
            self.control.setCurrentIndex(max(0, index))
        else:
            self.control.setText(str(value))


# ---------------------------------------------------------------- зумы

class ZoomDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Зум")
        self.setMinimumWidth(420)
        self.setStyleSheet(QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        initial = initial or {}
        self.fields: dict[str, QLineEdit] = {}
        for key, title, default in (
            ("start", "Старт, с", "3.0"),
            ("dur", "Длительность, с", "0.8"),
            ("factor", "Кратность (1.3 = +30%)", "1.35"),
            ("x", "Фокус X  (0 лево … 1 право)", "0.5"),
            ("y", "Фокус Y  (0 верх … 1 низ)", "0.5"),
        ):
            edit = QLineEdit(str(initial.get(key, default)))
            edit.setFixedWidth(120)
            self.fields[key] = edit
            form.addRow(title, edit)

        self.ease = QComboBox()
        self.ease.addItems(["punch", "ease"])
        self.ease.setCurrentText(str(initial.get("ease", "punch")))
        self.ease.setFixedWidth(120)
        form.addRow("Характер", self.ease)
        layout.addLayout(form)

        note = QLabel("Время отсчитывается по итоговому ролику — то есть уже после "
                      "ускорения. punch даёт мгновенный рывок, ease — плавный наезд "
                      "и такой же отъезд.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.result_data: dict | None = None

    def _accept(self) -> None:
        try:
            values = {k: float(e.text().replace(",", "."))
                      for k, e in self.fields.items()}
        except ValueError:
            QMessageBox.warning(self, "Нужны числа", "Во все поля впишите числа.")
            return
        if values["dur"] <= 0 or values["factor"] < 1.0:
            QMessageBox.warning(self, "Не сходится",
                                "Длительность должна быть больше нуля, "
                                "а кратность — не меньше единицы.")
            return
        values["ease"] = self.ease.currentText()
        self.result_data = values
        self.accept()


# ---------------------------------------------------------------- окно

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # Восстанавливаем прошлую сессию: настройки не сбрасываются между запусками.
        self._saved = config.load()
        start_params = self._saved.get("params")
        self.params: dict[str, Any] = (
            merge(DEFAULT_PARAMS, start_params) if isinstance(start_params, dict)
            else copy.deepcopy(DEFAULT_PARAMS)
        )
        self.fields: dict[str, Field] = {}
        self.sections: dict[str, Accordion] = {}
        self.sources: list[str] = []
        self.jobs: list[engine.Job] = []
        self.rows: dict[int, JobRow] = {}
        self.zoom_events: list[dict] = []
        self._run_started_at: float | None = None
        self._planning = False

        self.bridge = Bridge()
        self.bridge.job_changed.connect(self._on_job)
        self.bridge.logged.connect(self.log)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.planned.connect(self._on_planned)
        self.bridge.tools.connect(self._on_tools)
        self.runner = engine.Runner(
            on_job=self.bridge.job_changed.emit,
            on_log=self.bridge.logged.emit,
            on_finish=self.bridge.finished.emit,
        )

        self._build()
        self._load_into_fields(self.params)
        self._restore_session()
        self._refresh_summaries()
        self.setAcceptDrops(True)
        QTimer.singleShot(80, self._check_tools)

    def _restore_session(self) -> None:
        """Возвращает пресет, папку и число копий из прошлого запуска."""
        preset = self._saved.get("preset")
        if preset and preset in PRESETS:
            self.preset_box.blockSignals(True)
            self.preset_box.setCurrentText(preset)
            self.preset_box.blockSignals(False)
        out_dir = self._saved.get("out_dir")
        if out_dir:
            self.out_dir.setText(out_dir)
            self.out_dir.setCursorPosition(0)

    def _snapshot(self) -> dict:
        """Собирает состояние сессии для сохранения на диск."""
        return {
            "params": self._collect(),
            "preset": self.preset_box.currentText(),
            "out_dir": self.out_dir.text(),
        }

    def _remember(self) -> None:
        config.save(self._snapshot())

    # ------------------------------------------------------------ каркас

    def _build(self) -> None:
        self.setWindowTitle(f"{APP_TITLE} — {APP_SUBTITLE}")
        self.setWindowIcon(app_icon())
        self.resize(1320, 900)
        self.setMinimumSize(1080, 700)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._sidebar())

        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._topbar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_run())
        self.stack.addWidget(self._page_queue())
        self.stack.addWidget(self._page_help())
        column.addWidget(self.stack, 1)
        shell.addWidget(right, 1)

        self._go(0)

    def _sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(238)
        column = QVBoxLayout(panel)
        column.setContentsMargins(14, 18, 14, 16)
        column.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel()
        logo = ASSETS / "icon_64.png"
        if logo.is_file():
            mark.setPixmap(QPixmap(str(logo)).scaled(
                34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            mark.setText("▶")
            mark.setStyleSheet(f"color: {C.accent2}; font-size: 22px; font-weight: 700;")
        brand.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        name = QLabel(APP_TITLE)
        name.setObjectName("brandName")
        sub = QLabel(BRAND_SUBTITLE)
        sub.setObjectName("brandSub")
        titles.addWidget(name)
        titles.addWidget(sub)
        brand.addLayout(titles)
        brand.addStretch(1)
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {C.muted}; font-size: 12px;")
        brand.addWidget(self.dot)
        column.addLayout(brand)
        column.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_items: list[NavItem] = []
        for index, (icon, title) in enumerate(
                (("▷", "Запуск"), ("≡", "Очередь"), ("?", "Помощь"))):
            item = NavItem(icon, title)
            item.clicked.connect(lambda _c=False, i=index: self._go(i))
            self.nav_group.addButton(item, index)
            self.nav_items.append(item)
            column.addWidget(item)

        column.addStretch(1)

        self.side_status = QLabel("проверяю ffmpeg…")
        self.side_status.setObjectName("sideNote")
        self.side_status.setWordWrap(True)
        column.addWidget(self.side_status)

        link = QLabel(f'<a href="{CHANNEL_URL}" style="color:{C.muted};'
                      f'text-decoration:none">t.me/YT_cartell</a>')
        link.setObjectName("sideLink")
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignCenter)
        column.addSpacing(8)
        column.addWidget(link)
        return panel

    def _topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(58)
        row = QHBoxLayout(bar)
        row.setContentsMargins(26, 0, 26, 0)
        self.page_title = QLabel("Запуск")
        self.page_title.setObjectName("pageTitle")
        row.addWidget(self.page_title)
        row.addStretch(1)
        self.top_hint = QLabel("")
        self.top_hint.setObjectName("hint")
        row.addWidget(self.top_hint)
        return bar

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_items[index].setChecked(True)
        self.page_title.setText(("Запуск", "Очередь", "Помощь")[index])

    @staticmethod
    def _scroll_page(inner: QWidget, width: int = 880) -> QScrollArea:
        """Оборачивает содержимое в прокрутку и держит его по центру."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(26, 22, 26, 28)
        row.addStretch(1)
        inner.setMaximumWidth(width)
        inner.setMinimumWidth(620)
        row.addWidget(inner, 1)
        row.addStretch(1)
        area.setWidget(holder)
        return area

    # ------------------------------------------------------------ страница запуска

    def _page_run(self) -> QWidget:
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)

        hero = QVBoxLayout()
        hero.setSpacing(2)
        title = QLabel("Что уникализируем?")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Добавьте ролики, выберите пресет — из каждого получится "
                          "нужное число непохожих копий")
        subtitle.setObjectName("heroSub")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        hero.addWidget(title)
        hero.addWidget(subtitle)
        column.addLayout(hero)
        column.addSpacing(6)

        self.drop = DropZone()
        self.drop.dropped.connect(self._take_paths)
        self.drop.clicked.connect(self._add_files)
        column.addWidget(self.drop)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setMaximumHeight(150)
        self.file_list.setVisible(False)
        column.addWidget(self.file_list)

        self.file_bar = QWidget()
        bar = QHBoxLayout(self.file_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        self.count_label = QLabel("файлов: 0")
        self.count_label.setObjectName("hint")
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        for text, slot in (("Добавить файлы", self._add_files),
                           ("Добавить папку", self._add_folder),
                           ("Убрать", self._remove_selected),
                           ("Очистить", self._clear_files)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        self.file_bar.setVisible(False)
        column.addWidget(self.file_bar)

        # --- основные настройки одной строкой
        setup = Card(padding=16)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        setup.body().addLayout(grid)

        grid.addWidget(self._mini_label("Пресет"), 0, 0)
        self.preset_box = QComboBox()
        self.preset_box.addItems(list(PRESETS))
        self.preset_box.setCurrentText("Средняя (баланс)")
        self.preset_box.currentTextChanged.connect(self._apply_preset)
        grid.addWidget(self.preset_box, 1, 0)

        grid.addWidget(self._mini_label("Копий из каждого"), 0, 1)
        self.copies_box = QSpinBox()
        self.copies_box.setRange(1, 100)
        self.copies_box.setValue(1)
        self.copies_box.setAlignment(Qt.AlignCenter)
        self.copies_box.setFixedWidth(110)
        grid.addWidget(self.copies_box, 1, 1)

        # Путь занимает всю ширину отдельной строкой: втиснутый в колонку рядом
        # с пресетом, он показывает «C:\Users\...\Desk…» и толку от него нет.
        grid.addWidget(self._mini_label("Куда сохранять"), 2, 0, 1, 3)
        out_row = QWidget()
        out_line = QHBoxLayout(out_row)
        out_line.setContentsMargins(0, 0, 0, 0)
        out_line.setSpacing(6)
        self.out_dir = QLineEdit(str(default_output_dir()))
        # Длинный путь иначе показывается «хвостом», и не видно, куда пишем.
        self.out_dir.setCursorPosition(0)
        browse = QPushButton("…")
        browse.setFixedWidth(38)
        browse.clicked.connect(self._choose_out)
        show = QPushButton("Открыть")
        show.setFixedWidth(84)
        show.clicked.connect(self._open_out)
        out_line.addWidget(self.out_dir, 1)
        out_line.addWidget(browse)
        out_line.addWidget(show)
        grid.addWidget(out_row, 3, 0, 1, 3)
        grid.setRowMinimumHeight(2, 26)
        self.preset_box.setMinimumWidth(200)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 0)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for text, slot in (("Загрузить пресет…", self._load_preset),
                           ("Сохранить пресет…", self._save_preset)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        setup.body().addLayout(preset_row)
        column.addWidget(setup)

        # --- кнопки запуска
        self.start_button = QPushButton("Запустить уникализацию")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(lambda: self._start(False))
        column.addWidget(self.start_button)

        line = QHBoxLayout()
        line.setSpacing(8)
        self.preview_button = QPushButton("Проба на 15 секундах")
        self.preview_button.setObjectName("ghost")
        self.preview_button.clicked.connect(lambda: self._start(True))
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        line.addWidget(self.preview_button, 1)
        line.addWidget(self.cancel_button)
        column.addLayout(line)

        self.progress = Spinner()
        column.addWidget(self.progress)
        self.status_label = QLabel("Готов к работе")
        self.status_label.setObjectName("hint")
        self.status_label.setAlignment(Qt.AlignCenter)
        column.addWidget(self.status_label)

        column.addSpacing(10)
        heading = SectionTitle("Тонкая настройка")
        column.addWidget(heading)
        note = QLabel("Разделы свёрнуты: в строке справа видно, что в них сейчас "
                          "включено. Открывайте только тот, который правите.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        column.addWidget(note)

        for key, title, icon, specs in TABS:
            section = Accordion(title, icon)
            self.sections[key] = section
            body = section.body()
            for spec in specs:
                field = Field(spec)
                field.changed.connect(self._refresh_summaries)
                self.fields[spec["path"]] = field
                body.addWidget(field)
                divider = QFrame()
                divider.setFixedHeight(1)
                divider.setStyleSheet(f"background: {C.border_soft};")
                body.addWidget(divider)
            if key == "zoom":
                body.addWidget(self._zoom_editor())
            column.addWidget(section)

        column.addStretch(1)
        return self._scroll_page(inner)

    @staticmethod
    def _mini_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _zoom_editor(self) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 4, 0, 0)
        column.setSpacing(8)
        column.addWidget(SectionTitle("Зумы вручную"))

        note = QLabel("Работает, когда выключен переключатель «расставлять "
                      "автоматически». Время указывается по итоговому ролику: если "
                      "исходник 60 с и стоит ×2, итог длится 30 с, и зум на 10-й "
                      "секунде придётся на середину.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        column.addWidget(note)

        self.zoom_table = QTableWidget(0, 6)
        self.zoom_table.setHorizontalHeaderLabels(
            ["Старт, с", "Длит., с", "Кратность", "Характер", "Фокус X", "Фокус Y"])
        self.zoom_table.verticalHeader().setVisible(False)
        self.zoom_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.zoom_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.zoom_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.zoom_table.setMinimumHeight(140)
        self.zoom_table.doubleClicked.connect(self._edit_zoom)
        column.addWidget(self.zoom_table)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        for text, slot in (("Добавить", self._add_zoom), ("Изменить", self._edit_zoom),
                           ("Удалить", self._remove_zoom), ("Очистить", self._clear_zooms)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        column.addLayout(buttons)
        return box

    # ------------------------------------------------------------ очередь

    def _page_queue(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(26, 20, 26, 24)
        column.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(SectionTitle("Задачи"))
        head.addStretch(1)
        tip = QLabel("двойной клик по строке — открыть файл или показать ошибку")
        tip.setObjectName("hint")
        head.addWidget(tip)
        column.addLayout(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.queue_layout = QVBoxLayout(holder)
        self.queue_layout.setContentsMargins(0, 0, 8, 0)
        self.queue_layout.setSpacing(6)
        self.empty_note = QLabel("Пока пусто. Задачи появятся здесь после запуска.")
        self.empty_note.setObjectName("hint")
        self.empty_note.setAlignment(Qt.AlignCenter)
        self.queue_layout.addWidget(self.empty_note)
        self.queue_layout.addStretch(1)
        area.setWidget(holder)
        column.addWidget(area, 3)

        column.addWidget(SectionTitle("Лог"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        column.addWidget(self.log_view, 1)
        return page

    # ------------------------------------------------------------ помощь

    def _page_help(self) -> QWidget:
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(help_text.html())
        # Строки шире примерно 90 знаков читаются заметно хуже, поэтому текст
        # держим в колонке и центруем, а не растягиваем на всю ширину окна.
        browser.setMaximumWidth(940)
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(26, 20, 26, 24)
        row.addStretch(1)
        row.addWidget(browser, 6)
        row.addStretch(1)
        return wrapper

    # ------------------------------------------------------------ файлы

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self._take_paths([u.toLocalFile() for u in event.mimeData().urls()
                          if u.toLocalFile()])

    def _take_paths(self, paths: list[str]) -> None:
        found: list[str] = []
        for path in paths:
            if Path(path).is_dir():
                found.extend(probe.list_videos(path, recursive=True))
            elif Path(path).suffix.lower() in probe.VIDEO_EXTS:
                found.append(path)
        if found:
            self._extend(found)
        else:
            self.log("[!] Среди перетащенного не нашлось видеофайлов.")

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите видео", "", VIDEO_FILTER)
        self._extend(paths)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка с видео")
        if not folder:
            return
        found = probe.list_videos(folder, recursive=True)
        if not found:
            QMessageBox.information(self, "Пусто", "В папке не нашлось видеофайлов.")
            return
        self._extend(found)

    def _extend(self, paths) -> None:
        known = {p.lower() for p in self.sources}
        added = 0
        for path in paths:
            if path.lower() in known:
                continue
            known.add(path.lower())
            self.sources.append(path)
            self.file_list.addItem(Path(path).name)
            self.file_list.item(self.file_list.count() - 1).setToolTip(path)
            added += 1
        self._refresh_count()
        if added:
            self.log(f"Добавлено файлов: {added}")

    def _remove_selected(self) -> None:
        for index in sorted((i.row() for i in self.file_list.selectedIndexes()),
                            reverse=True):
            self.file_list.takeItem(index)
            del self.sources[index]
        self._refresh_count()

    def _clear_files(self) -> None:
        self.file_list.clear()
        self.sources.clear()
        self._refresh_count()

    def _refresh_count(self) -> None:
        has = bool(self.sources)
        self.file_list.setVisible(has)
        self.file_bar.setVisible(has)
        self.count_label.setText(f"файлов: {len(self.sources)}")

    def _choose_out(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Куда складывать результат")
        if folder:
            self.out_dir.setText(folder)
            self.out_dir.setCursorPosition(0)

    def _open_out(self) -> None:
        folder = Path(self.out_dir.text())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------ зумы

    def _add_zoom(self) -> None:
        dialog = ZoomDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.result_data:
            self.zoom_events.append(dialog.result_data)
            self._refresh_zooms()

    def _edit_zoom(self) -> None:
        row = self.zoom_table.currentRow()
        if not 0 <= row < len(self.zoom_events):
            return
        dialog = ZoomDialog(self, self.zoom_events[row])
        if dialog.exec() == QDialog.Accepted and dialog.result_data:
            self.zoom_events[row] = dialog.result_data
            self._refresh_zooms()

    def _remove_zoom(self) -> None:
        row = self.zoom_table.currentRow()
        if 0 <= row < len(self.zoom_events):
            del self.zoom_events[row]
            self._refresh_zooms()

    def _clear_zooms(self) -> None:
        self.zoom_events.clear()
        self._refresh_zooms()

    def _refresh_zooms(self) -> None:
        self.zoom_events.sort(key=lambda e: e["start"])
        self.zoom_table.setRowCount(len(self.zoom_events))
        for row, event in enumerate(self.zoom_events):
            for column, value in enumerate((event["start"], event["dur"],
                                            event["factor"], event["ease"],
                                            event["x"], event["y"])):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.zoom_table.setItem(row, column, item)
        self._refresh_summaries()

    # ------------------------------------------------------------ параметры

    def _load_into_fields(self, params: dict) -> None:
        for path, field in self.fields.items():
            section, key = path.split(".", 1)
            value = params.get(section, {}).get(key)
            if value is not None:
                field.setValue(value)
        self.zoom_events = [dict(e) for e in params.get("zoom", {}).get("events") or []]
        self.copies_box.setValue(int(params.get("output", {}).get("copies_per_file", 1)))
        self._refresh_zooms()

    def _collect(self) -> dict:
        params = copy.deepcopy(self.params)
        for path, field in self.fields.items():
            section, key = path.split(".", 1)
            params.setdefault(section, {})[key] = field.value()
        params.setdefault("zoom", {})["events"] = [dict(e) for e in self.zoom_events]
        params.setdefault("output", {})["copies_per_file"] = self.copies_box.value()
        self.params = params
        return params

    def _apply_preset(self, name: str) -> None:
        preset = PRESETS.get(name)
        if preset:
            self.params = copy.deepcopy(preset)
            self._load_into_fields(self.params)
            self._refresh_summaries()
            self.log(f"Пресет: {name}")

    def _load_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Пресет", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.params = load_preset_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Не открылось", str(exc))
            return
        self._load_into_fields(self.params)
        self._refresh_summaries()
        self.log(f"Пресет загружен: {Path(path).name}")

    def _save_preset(self) -> None:
        params = self._collect()
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить пресет",
                                              "мой пресет.json", "JSON (*.json)")
        if path:
            save_preset_file(path, params, Path(path).stem)
            self.log(f"Пресет сохранён: {Path(path).name}")

    # ------------------------------------------------------------ сводки

    def _value(self, path: str, default=None):
        field = self.fields.get(path)
        return field.value() if field else default

    def _pair(self, path: str, digits: int = 2) -> str:
        low, high = self._value(path, [0, 0])
        if abs(low - high) < 10 ** -(digits + 1):
            return f"{low:.{digits}f}"
        return f"{low:.{digits}f}–{high:.{digits}f}"

    def _refresh_summaries(self) -> None:
        """Короткая строка справа в заголовке каждого раздела."""
        if not self.sections:
            return

        if self._value("audio.enabled"):
            parts = [f"тон ±{self._pair('audio.pitch_semitones')}"]
            bands = int(self._value("audio.eq_bands", 0) or 0)
            if bands:
                parts.append(f"эквалайзер {bands}")
            if self._value("audio.spectral"):
                parts.append("спектралка")
            if self._value("audio.hf_noise"):
                parts.append("ВЧ-шум")
            self.sections["audio"].setSummary(" • ".join(parts))
        else:
            self.sections["audio"].setSummary("не трогаем звук")

        if self._value("speed.enabled"):
            pitch = "тон сохраняем" if self._value("speed.preserve_pitch") else "бурундуки"
            self.sections["speed"].setSummary(
                f"×{self._pair('speed.factor')} • {pitch}")
        else:
            self.sections["speed"].setSummary("без ускорения")

        if self._value("overlay.enabled"):
            name = Path(str(self._value("overlay.path", ""))).name or "файл не выбран"
            low, high = self._value("overlay.opacity", [0, 0])
            self.sections["overlay"].setSummary(
                f"{name} • {low * 100:.1f}–{high * 100:.1f}%")
        else:
            self.sections["overlay"].setSummary("выключен")

        if not self._value("zoom.enabled"):
            self.sections["zoom"].setSummary("выключен")
        elif self._value("zoom.auto"):
            low, high = self._value("zoom.auto_count", [0, 0])
            count = f"{low}" if low == high else f"{low}–{high}"
            self.sections["zoom"].setSummary(
                f"авто {count} шт • ×{self._pair('zoom.auto_factor')}")
        else:
            self.sections["zoom"].setSummary(f"вручную: {len(self.zoom_events)} шт")

        if self._value("video_fx.enabled"):
            parts = [f"кроп {self._pair('video_fx.crop_percent', 1)}%"]
            if self._value("video_fx.grain"):
                parts.append("зерно")
            if self._value("video_fx.hflip"):
                parts.append("зеркало")
            if self._value("video_fx.vignette"):
                parts.append("виньетка")
            self.sections["video_fx"].setSummary(" • ".join(parts))
        else:
            self.sections["video_fx"].setSummary("не трогаем картинку")

        self.sections["encode"].setSummary(
            f"{self._value('encode.encoder', 'auto')} • "
            f"качество {self._pair('encode.quality', 0)}")

    # ------------------------------------------------------------ запуск

    def _check_tools(self) -> None:
        """Опрос ffmpeg — в отдельном потоке.

        Проверка NVENC делает настоящее пробное кодирование, а опрос списка
        фильтров и кодеков — ещё три запуска ffmpeg. На потоке интерфейса это
        подвешивало окно почти на секунду при каждом старте.
        """
        def probe_tools() -> None:
            try:
                probe.tool("ffmpeg")
                probe.tool("ffprobe")
            except probe.FFmpegNotFound as exc:
                self.bridge.tools.emit({"error": str(exc)})
                return
            self.bridge.tools.emit({
                "nvenc": probe.nvenc_available(),
                "version": probe.ffmpeg_version(),
                "x264": probe.encoder_available("libx264"),
            })

        threading.Thread(target=probe_tools, daemon=True).start()

    def _on_tools(self, info: dict) -> None:
        if info.get("error"):
            self.side_status.setText("ffmpeg не найден — обработка невозможна")
            self.side_status.setStyleSheet(f"color: {C.danger};")
            self.dot.setStyleSheet(f"color: {C.danger}; font-size: 12px;")
            QMessageBox.critical(self, "Нет ffmpeg", info["error"])
            return

        if info.get("nvenc"):
            self.side_status.setText("NVENC доступен\nкодирую на видеокарте")
            self.dot.setStyleSheet(f"color: {C.success}; font-size: 12px;")
        else:
            self.side_status.setText("NVENC недоступен\nкодирую на процессоре")
            self.dot.setStyleSheet(f"color: {C.warning}; font-size: 12px;")

        major, minor = info.get("version", (0, 0))
        if major and (major, minor) < (4, 4):
            self.log(f"[!] ffmpeg {major}.{minor} слишком старый: части возможностей "
                     f"(зум по времени, пресеты видеокарты) в нём ещё нет. "
                     f"Нужна версия 4.4 или новее.")
        if not info.get("x264", True):
            self.log("[!] В этой сборке ffmpeg нет кодировщика libx264 — "
                     "без него не на чем кодировать, если видеокарта откажет.")

    def _start(self, preview: bool) -> None:
        # Пока идёт подготовка, кнопки уже погашены, но горячая клавиша или
        # второй быстрый клик всё равно способны сюда попасть — тогда партия
        # запланировалась бы дважды и копии подрались за одни и те же имена.
        if self.runner.running or self._planning:
            return
        if not self.sources:
            QMessageBox.information(self, "Нет файлов",
                                    "Сначала добавьте видео — перетащите их в окно "
                                    "или нажмите «Добавить файлы».")
            return

        params = self._collect()
        overlay = params.get("overlay", {})
        if overlay.get("enabled") and not Path(overlay.get("path", "")).is_file():
            QMessageBox.critical(self, "Нет картинки",
                                 "Оверлей включён, но файл картинки не выбран "
                                 "или не найден. Загляните в раздел «Оверлей».")
            return

        # Копия списка, а не он сам: подготовка идёт в отдельном потоке, а
        # человек тем временем волен добавлять и убирать файлы в окне.
        sources = list(self.sources[:1] if preview else self.sources)
        if preview:
            params = merge(params, {"output": dict(params["output"],
                                                   copies_per_file=1,
                                                   preview_seconds=15,
                                                   pattern="{name}_ПРОБА")})

        # Папка вывода не должна совпадать с папкой исходников: на следующем
        # запуске программа подхватит собственные копии и пойдёт по кругу.
        clashing = engine.sources_inside(sources, self.out_dir.text())
        if clashing:
            answer = QMessageBox.question(
                self, "Результат ляжет к исходникам",
                "\n\n".join([
                    f"{len(clashing)} из {len(sources)} роликов лежат прямо "
                    f"в папке вывода.",
                    "При следующем запуске программа подхватит уже готовые "
                    "копии и начнёт уникализировать их повторно.",
                    "Лучше выбрать отдельную папку. Всё равно продолжить?",
                ]),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return

        # Запомнили настройки перед запуском: даже если программу закроют
        # прямо в процессе, при следующем открытии всё будет как было.
        self._remember()

        # Подготовка задач читает каждый файл через ffprobe. На папке в сотни
        # роликов это ощутимо, поэтому уводим в поток, чтобы окно не подвисало.
        out_dir = self.out_dir.text()
        self._planning = True
        self._abort_plan = False
        self.start_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Читаю файлы…")

        def prepare() -> None:
            try:
                jobs, problems = engine.plan_jobs(sources, out_dir, params)
                self.bridge.planned.emit((jobs, problems, params))
            except Exception as exc:
                self.bridge.planned.emit(("error", str(exc), None))

        threading.Thread(target=prepare, daemon=True).start()

    def _on_planned(self, payload) -> None:
        self._planning = False
        jobs, problems, params = payload

        if self._abort_plan:
            self._abort_plan = False
            self.start_button.setEnabled(True)
            self.preview_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Отменено до начала обработки")
            self.log("Подготовка прервана, обработка не запускалась.")
            return

        if jobs == "error":
            self.start_button.setEnabled(True)
            self.preview_button.setEnabled(True)
            self.status_label.setText("Готов к работе")
            QMessageBox.critical(self, "Ошибка", str(problems))
            return
        for problem in problems:
            self.log(f"[пропущен] {problem}")
        if not jobs:
            self.start_button.setEnabled(True)
            self.preview_button.setEnabled(True)
            self.status_label.setText("Готов к работе")
            QMessageBox.critical(self, "Нечего делать",
                                 "Ни один файл не удалось прочитать. "
                                 "Подробности в логе на странице «Очередь».")
            return

        self.jobs = jobs
        self._run_started_at = None
        self._rebuild_queue(jobs)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"В работе: {len(jobs)} задач")
        self.log(f"Старт: задач {len(jobs)}, потоков "
                 f"{params['output'].get('parallel_jobs', 2)}")
        self._go(1)
        self.runner.start(jobs, params)

    def _rebuild_queue(self, jobs: list[engine.Job]) -> None:
        # Сносим только строки задач. Раньше цикл шёл по индексам и первым же
        # делом уничтожал надпись «пока пусто», которая лежит в той же колонке,
        # — после первого запуска она превращалась в мёртвый объект.
        for index in reversed(range(self.queue_layout.count())):
            widget = self.queue_layout.itemAt(index).widget()
            if isinstance(widget, JobRow):
                self.queue_layout.takeAt(index)
                widget.deleteLater()
        self.empty_note.setVisible(not jobs)
        self.rows.clear()
        for job in jobs:
            row = JobRow(job.title)
            row.mouseDoubleClickEvent = lambda _e, j=job: self._open_job(j)
            self.rows[id(job)] = row
            self.queue_layout.insertWidget(self.queue_layout.count() - 1, row)

    def _cancel(self) -> None:
        # Отменять нужно и на этапе подготовки: он читает каждый файл через
        # ffprobe, и на папке в сотни роликов это заметное ожидание, которое
        # раньше нельзя было прервать — кнопка отмены была недоступна.
        if self._planning:
            self._abort_plan = True
            self.log("Отмена: подготовка будет прервана.")
            self.status_label.setText("Отмена…")
            return
        if self.runner.running:
            self.runner.cancel()
            self.log("Отмена…")
            self.status_label.setText("Отмена…")

    def _open_job(self, job: engine.Job) -> None:
        if job.status == "готово" and Path(job.out_path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.out_path))
        elif job.status == "ошибка":
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle(f"Не получилось: {Path(job.source).name}")
            box.setText(job.error or "ffmpeg не сказал ничего внятного.")
            retry = box.addButton("Повторить", QMessageBox.AcceptRole)
            box.addButton("Закрыть", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is retry:
                self._retry_job(job)
        else:
            QMessageBox.information(self, "Задача",
                                    f"{job.title}\n\nСейчас: {job.status}\n"
                                    f"Сид: {job.seed}")

    def _retry_job(self, job: engine.Job) -> None:
        """Перезапускает одну упавшую задачу с тем же сидом и настройками.

        Строки очереди остаются кликабельными и пока идёт подготовка новой
        партии, а она считается в отдельном потоке — в этот момент runner ещё
        не «работает». Без проверки на подготовку повтор успевал стартовать,
        а следом стартовала и подготовленная партия: два ffmpeg писали в один
        файл и портили его, причём обе задачи рапортовали «готово».
        """
        if self.runner.running or self._planning:
            self.log("Сейчас идёт обработка — повтор будет доступен после неё.")
            return
        job.status = "ожидает"
        job.progress = 0.0
        job.error = ""
        self.jobs = [job]
        self._run_started_at = None
        self._rebuild_queue(self.jobs)
        self.start_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.log(f"Повтор: {job.title}")
        self._go(1)
        self.runner.start(self.jobs, self._collect())

    # ------------------------------------------------------------ события

    def _on_job(self, job: engine.Job) -> None:
        row = self.rows.get(id(job))
        if row is not None:
            row.update_state(job.status, job.progress)
        if not self.jobs:
            return
        done = sum(1 for j in self.jobs if j.status in ("готово", "ошибка", "отменено"))
        overall = sum(j.progress for j in self.jobs) / len(self.jobs)
        self.progress.setValue(overall)

        # Оценка оставшегося времени: засекаем момент, когда пошёл реальный
        # прогресс, и линейно экстраполируем. Пока прогресса нет — просто счётчик.
        eta = ""
        if 0.02 < overall < 0.999:
            if self._run_started_at is None:
                self._run_started_at = time.monotonic()
            else:
                elapsed = time.monotonic() - self._run_started_at
                remaining = elapsed / overall * (1 - overall)
                eta = "  •  осталось ~" + self._format_eta(remaining)
        self.top_hint.setText(f"{done} из {len(self.jobs)}{eta}")
        if done < len(self.jobs):
            self.status_label.setText(f"В работе: {done} из {len(self.jobs)}{eta}")

    @staticmethod
    def _format_eta(seconds: float) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds} с"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} мин {sec:02d} с"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} ч {minutes:02d} мин"

    def _on_finished(self, jobs: list[engine.Job]) -> None:
        self.start_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        done = sum(1 for j in jobs if j.status == "готово")
        failed = sum(1 for j in jobs if j.status == "ошибка")
        cancelled = sum(1 for j in jobs if j.status == "отменено")
        parts = [f"готово {done}"]
        if failed:
            parts.append(f"ошибок {failed}")
        if cancelled:
            parts.append(f"отменено {cancelled}")
        summary = ", ".join(parts)
        self.status_label.setText(f"Завершено: {summary}")
        self.log(f"Завершено: {summary}")

    def log(self, text: str) -> None:
        # Обработка идёт в потоках и шлёт сигналы; если окно уже закрывают,
        # виджеты Qt могут быть уничтожены раньше, чем придёт последний сигнал.
        try:
            self.log_view.appendPlainText(text.rstrip())
            self.empty_note.setVisible(not self.rows)
        except RuntimeError:
            pass

    def closeEvent(self, event) -> None:
        if self.runner.running:
            answer = QMessageBox.question(self, "Ещё идёт обработка",
                                          "Задачи не закончены. Прервать и выйти?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.runner.cancel()
        # Запоминаем настройки на следующий запуск.
        self._remember()
        event.accept()


def main() -> None:
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("unicalizer.app")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    # setApplicationDisplayName здесь не нужен: Qt дописывает его к заголовку
    # окна через дефис, и получается «… — уникализация видео - Video Unicalizer».
    app.setWindowIcon(app_icon())
    app.setStyleSheet(QSS)
    app.setFont(QFont("Segoe UI", 10))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
