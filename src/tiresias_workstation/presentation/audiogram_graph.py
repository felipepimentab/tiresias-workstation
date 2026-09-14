"""Render stored air-conduction thresholds without changing domain data.

Uses audiometric conventions: octave spacing, hearing level increasing down,
red circles for the right ear and blue crosses for the left ear.
"""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from tiresias_workstation.domain.fittings import Audiogram


class AudiogramGraph(QWidget):
    """Display both ears with distinguishable colors and air-conduction symbols."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create a resizable graph owned by the inspection tab."""
        super().__init__(parent)
        self._audiogram: Audiogram | None = None
        self.setObjectName("audiogramGraph")
        self.setAccessibleName("Audiogram graph")
        self.setMinimumSize(340, 340)

    def sizeHint(self) -> QSize:
        """Suggest enough space for audiometric grid labels and the legend."""
        return QSize(620, 580)

    def set_audiogram(self, audiogram: Audiogram | None) -> None:
        """Replace the selected thresholds, or clear a stale selection.

        Args:
            audiogram: Immutable frequencies in Hz and thresholds in dB HL.
        """
        self._audiogram = audiogram
        self.setAccessibleDescription(
            "Left ear: blue crosses. Right ear: red circles. Frequency in Hz "
            "increases left to right; hearing level in dB HL increases downward. "
            "Exact thresholds are available in the Values tab."
        )
        self.update()

    def paintEvent(self, event) -> None:
        """Paint the current record with equal octave / 20 dB grid proportions."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        foreground = QColor("#354052")
        painter.setPen(foreground)
        audio = self._audiogram
        if audio is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Select an audiogram to view its graph.")
            return

        low_octave = min(0, math.floor(math.log2(audio.frequencies_hz[0]) - math.log2(125)))
        high_octave = max(6, math.ceil(math.log2(audio.frequencies_hz[-1]) - math.log2(125)))
        levels = audio.left_levels_db_hl + audio.right_levels_db_hl
        low_level = min(-10, math.floor(min(levels) / 10) * 10)
        high_level = max(120, math.ceil(max(levels) / 10) * 10)
        octaves = high_octave - low_octave
        level_span = high_level - low_level
        unit = min((self.width() - 100) / octaves,
                   (self.height() - 115) / (level_span / 20))
        width, height = unit * octaves, unit * level_span / 20
        plot = QRectF(65 + (self.width() - 100 - width) / 2, 48, width, height)

        def x_position(frequency: float) -> float:
            return plot.left() + (math.log2(frequency) - math.log2(125) - low_octave) * unit

        def y_position(level: float) -> float:
            return plot.top() + (level - low_level) / level_span * height

        font = painter.font()
        font.setPointSizeF(9)
        painter.setFont(font)
        for level in range(low_level, high_level + 1, 10):
            y = y_position(level)
            painter.setPen(QPen(QColor("#a9b2bf" if level == 0 else "#dce1e8"), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(foreground)
            painter.drawText(QRectF(plot.left() - 36, y - 9, 29, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(level))
        for octave in range(low_octave, high_octave + 1):
            frequency = 125 * 2.0 ** octave
            x = x_position(frequency)
            painter.setPen(QPen(QColor("#dce1e8"), 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(foreground)
            label = f"{frequency / 1000:g}k" if frequency >= 1000 else f"{frequency:g}"
            painter.drawText(QRectF(x - 25, plot.top() - 24, 50, 18),
                             Qt.AlignmentFlag.AlignCenter, label)
        painter.drawText(QRectF(plot.left(), 2, width, 20),
                         Qt.AlignmentFlag.AlignCenter, "Frequency (Hz)")
        painter.save()
        painter.translate(18, plot.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-height / 2, -12, height, 24),
                         Qt.AlignmentFlag.AlignCenter, "Hearing level (dB HL)")
        painter.restore()
        painter.setPen(QPen(QColor("#a9b2bf"), 1))
        painter.drawRect(plot)

        # Draw both lines before the symbols so coincident ears stay legible.
        ears = ((audio.right_levels_db_hl, QColor("#cf303e"), False),
                (audio.left_levels_db_hl, QColor("#2369c9"), True))
        for thresholds, color, cross in ears:
            path = QPainterPath()
            for index, (frequency, level) in enumerate(zip(audio.frequencies_hz, thresholds)):
                point = QPointF(x_position(frequency), y_position(level))
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            style = Qt.PenStyle.DashLine if cross else Qt.PenStyle.SolidLine
            painter.setPen(QPen(color, 1.6, style))
            painter.drawPath(path)
        for thresholds, color, cross in ears:
            painter.setPen(QPen(color, 2))
            for frequency, level in zip(audio.frequencies_hz, thresholds):
                self._draw_symbol(painter, QPointF(x_position(frequency), y_position(level)), cross)
        for offset, (_, color, cross), label in zip(
            (0, 155), reversed(ears), ("Left ear", "Right ear")
        ):
            point = QPointF(plot.center().x() - 125 + offset, plot.bottom() + 33)
            painter.setPen(QPen(color, 2))
            self._draw_symbol(painter, point, cross)
            painter.drawText(QRectF(point.x() + 13, point.y() - 10, 105, 20),
                             Qt.AlignmentFlag.AlignVCenter, label)
        painter.end()

    @staticmethod
    def _draw_symbol(painter: QPainter, point: QPointF, cross: bool) -> None:
        """Draw open symbols so overlapping ears remain distinguishable."""
        radius = 5
        if cross:
            painter.drawLine(point + QPointF(-radius, -radius), point + QPointF(radius, radius))
            painter.drawLine(point + QPointF(-radius, radius), point + QPointF(radius, -radius))
        else:
            painter.drawEllipse(point, radius, radius)
