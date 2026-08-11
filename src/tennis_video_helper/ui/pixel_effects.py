"""轻量级像素动画组件，不依赖外部图片资源。"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class PixelMotionRail(QWidget):
    """绘制流水灯、跑动网球小人与像素球的顶部装饰轨道。"""

    def __init__(self, *, animation_enabled: bool = True) -> None:
        super().__init__()
        self.setObjectName("pixelMotionRail")
        self.setAccessibleName("像素流水灯与网球小人动画")
        self.setToolTip("像素流水灯与网球小人；可在“视图”菜单关闭动画")
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._phase = 0
        self._animation_enabled = bool(animation_enabled)
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self.advance_frame)
        if self._animation_enabled:
            self._timer.start()

    @property
    def animation_enabled(self) -> bool:
        return self._animation_enabled

    def set_animation_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._animation_enabled = enabled
        if enabled and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def advance_frame(self) -> None:
        if not self._animation_enabled:
            return
        self._phase = (self._phase + 1) % 4096
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._animation_enabled:
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        dark = bool(getattr(self.window(), "_dark_theme", True))
        background = QColor("#080b10" if dark else "#edf2f6")
        border = QColor("#3d4a57" if dark else "#8c99a5")
        dim = QColor("#26313a" if dark else "#c4ced6")
        text = QColor("#dfe8ed" if dark else "#26323a")
        lime = QColor("#baff39" if dark else "#5f930f")
        cyan = QColor("#24d8ff" if dark else "#007c98")
        magenta = QColor("#ff3b9d" if dark else "#b51e68")

        outer = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(outer, background)
        painter.setPen(QPen(border, 2))
        painter.drawRect(outer)

        self._draw_corner_blocks(painter, lime, cyan, magenta)
        self._draw_led_stream(painter, dim, lime, cyan, magenta)

        label_font = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        label_font.setStyleHint(QFont.StyleHint.Monospace)
        painter.setFont(label_font)
        painter.setPen(text)
        painter.drawText(
            QRect(18, 17, 205, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "PIXEL RALLY // LIVE",
        )

        track_left = 232
        track_right = max(track_left + 1, self.width() - 58)
        track_y = 33
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dim)
        painter.drawRect(track_left, track_y, track_right - track_left, 2)
        for x in range(track_left, track_right, 28):
            painter.setBrush(cyan if (x // 28) % 2 == 0 else magenta)
            painter.drawRect(x, track_y, 6, 2)

        travel = max(1, track_right - track_left + 44)
        runner_x = track_left - 28 + (self._phase * 5) % travel
        self._draw_runner(painter, runner_x, 15, lime, cyan, magenta, text)
        painter.end()

    def _draw_led_stream(
        self,
        painter: QPainter,
        dim: QColor,
        lime: QColor,
        cyan: QColor,
        magenta: QColor,
    ) -> None:
        left = 18
        right = max(left, self.width() - 18)
        step = 10
        count = max(1, (right - left) // step)
        pulse = (self._phase * 2) % count
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(count):
            distance = min((index - pulse) % count, (pulse - index) % count)
            if distance <= 1:
                color = lime
            elif distance == 2:
                color = cyan
            elif distance == 3:
                color = magenta
            else:
                color = dim
            painter.setBrush(color)
            height = 5 if distance <= 1 else 3
            painter.drawRect(left + index * step, 7, 6, height)

    def _draw_corner_blocks(
        self,
        painter: QPainter,
        lime: QColor,
        cyan: QColor,
        magenta: QColor,
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for color, x in ((lime, 5), (cyan, 9), (magenta, 13)):
            painter.setBrush(color)
            painter.drawRect(x, 4, 3, 3)
        right = self.width() - 8
        for color, offset in ((magenta, 0), (cyan, 4), (lime, 8)):
            painter.setBrush(color)
            painter.drawRect(right - offset, self.height() - 8, 3, 3)

    def _draw_runner(
        self,
        painter: QPainter,
        x: int,
        y: int,
        lime: QColor,
        cyan: QColor,
        magenta: QColor,
        text: QColor,
    ) -> None:
        frame = (self._phase // 2) % 2
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(text)
        painter.drawRect(x + 8, y, 5, 5)
        painter.setBrush(lime)
        painter.drawRect(x + 7, y + 5, 7, 8)
        painter.setBrush(cyan)
        painter.drawRect(x + 3, y + 7 + frame * 2, 5, 3)
        painter.drawRect(x + 13, y + 8 - frame * 2, 6, 3)

        painter.setBrush(text)
        if frame == 0:
            painter.drawRect(x + 6, y + 13, 4, 7)
            painter.drawRect(x + 12, y + 13, 4, 5)
            painter.drawRect(x + 15, y + 17, 5, 3)
        else:
            painter.drawRect(x + 7, y + 13, 4, 5)
            painter.drawRect(x + 3, y + 17, 7, 3)
            painter.drawRect(x + 12, y + 13, 4, 7)

        painter.setPen(QPen(magenta, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(x + 20, y + 4, 7, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(magenta)
        painter.drawRect(x + 17, y + 11, 6, 2)

        bounce = (0, -2, -4, -2)[self._phase % 4]
        painter.setBrush(lime)
        painter.drawRect(x + 34, y + 9 + bounce, 4, 4)

