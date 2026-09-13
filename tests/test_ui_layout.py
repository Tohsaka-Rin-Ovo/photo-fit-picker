import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from photo_fit_picker.ui import (
    ZoomablePhotoArea,
    _clamped_thumbnail_size,
    _normalized_view_mode,
    _photo_grid_columns,
)


def test_view_preferences_are_normalized() -> None:
    assert _normalized_view_mode("compact") == "compact"
    assert _normalized_view_mode("unexpected") == "large"
    assert _clamped_thumbnail_size("80") == 120
    assert _clamped_thumbnail_size(999) == 320
    assert _clamped_thumbnail_size("invalid") == 268


def test_grid_columns_follow_view_mode_and_available_width() -> None:
    assert _photo_grid_columns(900, "compact", 168) == 4
    assert _photo_grid_columns(900, "large", 268) == 3
    assert _photo_grid_columns(900, "list", 136) == 1
    assert _photo_grid_columns(40, "compact", 168) == 1


def test_photo_area_switches_between_fit_and_actual_size() -> None:
    app = QApplication.instance() or QApplication([])
    area = ZoomablePhotoArea()
    area.resize(400, 300)
    area.show()
    app.processEvents()
    pixmap = QPixmap(800, 600)
    pixmap.fill(QColor("white"))

    area.set_photo(pixmap)
    fit_percent = area.zoom_percent
    assert area.fit_mode
    assert fit_percent < 100

    QTest.mouseDClick(area.image_label, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert area.zoom_percent == 100
    assert not area.fit_mode

    area.toggle_actual_size()
    assert area.fit_mode
    assert area.zoom_percent == fit_percent
    area.close()
