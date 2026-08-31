"""Свои виджеты: переключатель, двусторонний ползунок, раздел-аккордеон, строка задачи.

Стандартные элементы Qt выглядят как системная форма из нулевых, поэтому всё,
что бросается в глаза, нарисовано или собрано вручную.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .theme import C


class Toggle(QWidget):
    """Переключатель вместо галочки: понятнее и не выглядит как форма из Windows 98."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()
        self.toggled.emit(value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        track = QRectF(0, 2, self.width(), self.height() - 4)
        painter.setPen(Qt.NoPen)
        if self._offset > 0.01:
            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0, QColor(C.accent))
            gradient.setColorAt(1, QColor(C.accent3))
            off = QColor(C.track)
            off.setAlphaF(1 - self._offset)
            painter.setBrush(gradient)
            painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
            painter.setBrush(off)
        else:
            painter.setBrush(QColor(C.track))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        radius = self.height() / 2 - 4
        travel = self.width() - 2 * radius - 8
        cx = 4 + radius + travel * self._offset
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPoint(int(cx), self.height() // 2), int(radius), int(radius))


class RangeSlider(QWidget):
    """Ползунок с двумя ручками: «от» и «до» одним движением.

    Каждый параметр уникализации — это промежуток, из которого для каждой копии
    берётся своё число. Два поля ввода этого не показывают, а полоса — показывает.
    """

    changed = Signal(float, float)

    def __init__(self, lo: float, hi: float, minimum: float, maximum: float,
                 decimals: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.minimum, self.maximum = float(minimum), float(maximum)
        if self.maximum <= self.minimum:
            self.maximum = self.minimum + 1.0
        self.decimals = decimals
        self._lo, self._hi = self._clamp(lo), self._clamp(hi)
        if self._lo > self._hi:
            self._lo, self._hi = self._hi, self._lo
        self._drag: str | None = None
        self._hover: str | None = None
        self.setFixedHeight(28)
        self.setMinimumWidth(140)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def _clamp(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, float(value)))

    def values(self) -> tuple[float, float]:
        return round(self._lo, self.decimals), round(self._hi, self.decimals)

    def setValues(self, lo: float, hi: float) -> None:
        lo, hi = self._clamp(lo), self._clamp(hi)
        self._lo, self._hi = min(lo, hi), max(lo, hi)
        self.update()

    def setBounds(self, minimum: float, maximum: float) -> None:
        self.minimum, self.maximum = float(minimum), float(maximum)
        self.setValues(self._lo, self._hi)

    @property
    def _margin(self) -> int:
        return 9

    def _x_of(self, value: float) -> float:
        span = self.maximum - self.minimum
        usable = self.width() - 2 * self._margin
        return self._margin + usable * (value - self.minimum) / span

    def _value_of(self, x: float) -> float:
        usable = max(1, self.width() - 2 * self._margin)
        ratio = (x - self._margin) / usable
        return self._clamp(self.minimum + ratio * (self.maximum - self.minimum))

    def _nearest(self, x: float) -> str:
        return "lo" if abs(x - self._x_of(self._lo)) <= abs(x - self._x_of(self._hi)) else "hi"

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._drag = self._nearest(event.position().x())
        self._apply(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._drag:
            self._apply(x)
            return
        near = self._nearest(x)
        hover = near if abs(x - self._x_of(self._lo if near == "lo" else self._hi)) < 14 else None
        if hover != self._hover:
            self._hover = hover
            self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None

    def leaveEvent(self, _event) -> None:
        self._hover = None
        self.update()

    def wheelEvent(self, event) -> None:
        step = (self.maximum - self.minimum) / 100
        delta = step if event.angleDelta().y() > 0 else -step
        self.setValues(self._lo + delta, self._hi + delta)
        self.changed.emit(*self.values())

    def _apply(self, x: float) -> None:
        value = self._value_of(x)
        if self._drag == "lo":
            self._lo = min(value, self._hi)
        else:
            self._hi = max(value, self._lo)
        self.update()
        self.changed.emit(*self.values())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        middle = self.height() / 2

        rail = QRectF(self._margin, middle - 2.5, self.width() - 2 * self._margin, 5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(C.track))
        painter.drawRoundedRect(rail, 2.5, 2.5)

        x_lo, x_hi = self._x_of(self._lo), self._x_of(self._hi)
        span = QRectF(x_lo, middle - 2.5, max(1.0, x_hi - x_lo), 5)
        gradient = QLinearGradient(rail.left(), 0, rail.right(), 0)
        gradient.setColorAt(0, QColor(C.accent))
        gradient.setColorAt(1, QColor(C.accent3))
        painter.setBrush(gradient)
        painter.drawRoundedRect(span, 2.5, 2.5)

        for name, x in (("lo", x_lo), ("hi", x_hi)):
            active = self._drag == name or self._hover == name
            radius = 8.0 if active else 6.5
            if active:
                glow = QColor(C.accent)
                glow.setAlpha(60)
                painter.setBrush(glow)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPoint(int(x), int(middle)),
                                    int(radius) + 5, int(radius) + 5)
            painter.setPen(QPen(QColor(C.accent2), 2))
            painter.setBrush(QColor(C.handle))
            painter.drawEllipse(QPoint(int(x), int(middle)), int(radius), int(radius))


class Card(QFrame):
    """Панель со скруглением и мягкой тенью."""

    def __init__(self, parent: QWidget | None = None, padding: int = 16,
                 shadow: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(10)
        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(26)
            effect.setOffset(0, 5)
            effect.setColor(QColor(0, 0, 0, 80))
            self.setGraphicsEffect(effect)

    def body(self) -> QVBoxLayout:
        return self.layout()


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setObjectName("sectionTitle")


class Accordion(QFrame):
    """Сворачиваемый раздел: заголовок, краткая сводка справа, тело внутри.

    Настроек больше шестидесяти. Показывать их все сразу — то самое «всё
    перемешано»: свёрнутый раздел с одной строкой сводки читается за секунду.
    """

    def __init__(self, title: str, icon: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("accordion")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.head = QPushButton()
        self.head.setObjectName("accordionHead")
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.clicked.connect(self.toggle)
        head_row = QHBoxLayout(self.head)
        head_row.setContentsMargins(16, 13, 16, 13)
        head_row.setSpacing(10)

        if icon:
            mark = QLabel(icon)
            mark.setStyleSheet(f"color: {C.accent2}; font-size: 14px;")
            mark.setFixedWidth(18)
            head_row.addWidget(mark)

        caption = QLabel(title)
        caption.setObjectName("accordionTitle")
        head_row.addWidget(caption)
        head_row.addStretch(1)

        self.summary = QLabel("")
        self.summary.setObjectName("accordionSummary")
        head_row.addWidget(self.summary)

        self.chevron = QLabel("▾")
        self.chevron.setObjectName("chevron")
        self.chevron.setFixedWidth(14)
        head_row.addWidget(self.chevron)
        outer.addWidget(self.head)

        self.content = QWidget()
        self.content.setVisible(False)
        self.body_layout = QVBoxLayout(self.content)
        self.body_layout.setContentsMargins(16, 2, 16, 16)
        self.body_layout.setSpacing(14)
        outer.addWidget(self.content)

    def body(self) -> QVBoxLayout:
        return self.body_layout

    def setSummary(self, text: str) -> None:
        self.summary.setText(text)

    def isExpanded(self) -> bool:
        return self.content.isVisible()

    def setExpanded(self, value: bool) -> None:
        self.content.setVisible(value)
        self.chevron.setText("▴" if value else "▾")

    def toggle(self) -> None:
        self.setExpanded(not self.isExpanded())


class NavItem(QPushButton):
    """Пункт левого меню."""

    def __init__(self, icon: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(f"  {icon}   {title}", parent)
        self.setObjectName("navItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)


class JobRow(QWidget):
    """Строка очереди: имя, заливка прогресса, статус и проценты."""

    STATUS_COLORS = {
        "ожидает": C.muted,
        "работает": C.accent2,
        "готово": C.success,
        "ошибка": C.danger,
        "отменено": C.warning,
    }

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._status = "ожидает"
        self._progress = 0.0
        self.setFixedHeight(48)
        self.setCursor(Qt.PointingHandCursor)

    def update_state(self, status: str, progress: float) -> None:
        self._status, self._progress = status, progress
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 2, self.width(), self.height() - 4)

        path = QPainterPath()
        path.addRoundedRect(rect, 9, 9)
        painter.fillPath(path, QColor(C.surface2))

        colour = QColor(self.STATUS_COLORS.get(self._status, C.muted))
        if self._progress > 0:
            painter.save()
            painter.setClipPath(path)
            fill = QRectF(rect.left(), rect.top(),
                          rect.width() * min(1.0, self._progress), rect.height())
            tint = QColor(colour)
            tint.setAlpha(40)
            painter.fillRect(fill, tint)
            painter.restore()

        painter.setPen(QPen(colour, 3))
        painter.drawLine(int(rect.left() + 2), int(rect.top() + 9),
                         int(rect.left() + 2), int(rect.bottom() - 9))

        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.setPen(QColor(C.text))
        metrics = QFontMetrics(font)
        room = max(60, self.width() - 130)
        painter.drawText(QRect(14, 7, room, 18), Qt.AlignVCenter | Qt.AlignLeft,
                         metrics.elidedText(self._title, Qt.ElideMiddle, room))

        painter.setPen(QColor(C.muted))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRect(14, 25, room, 16), Qt.AlignVCenter | Qt.AlignLeft,
                         self._status)

        painter.setPen(colour)
        painter.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        painter.drawText(QRect(self.width() - 108, 7, 94, 34),
                         Qt.AlignVCenter | Qt.AlignRight,
                         f"{int(self._progress * 100)}%")


class Spinner(QWidget):
    """Тонкая полоса общего прогресса."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(6)

    def setValue(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(C.track))
        painter.drawRoundedRect(rect, 3, 3)
        if self._value <= 0:
            return
        gradient = QLinearGradient(0, 0, rect.width(), 0)
        gradient.setColorAt(0, QColor(C.accent))
        gradient.setColorAt(1, QColor(C.accent3))
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(0, 0, rect.width() * self._value,
                                       rect.height()), 3, 3)


class DropZone(QFrame):
    """Пунктирная область «перетащите сюда» под списком файлов."""

    dropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(74)
        self._hover = False

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            self._hover = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event) -> None:
        self._hover = False
        self.update()

    def dropEvent(self, event) -> None:
        self._hover = False
        self.update()
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.dropped.emit(paths)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)

        pen = QPen(QColor(C.accent if self._hover else C.border), 1.4, Qt.DashLine)
        painter.setPen(pen)
        if self._hover:
            tint = QColor(C.accent)
            tint.setAlpha(22)
            painter.setBrush(tint)
        else:
            painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 11, 11)

        painter.setPen(QColor(C.text2 if self._hover else C.muted))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(rect, Qt.AlignCenter,
                         "Перетащите видео или папку сюда\nлибо нажмите, чтобы выбрать")
