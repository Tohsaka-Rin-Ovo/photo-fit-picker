from __future__ import annotations

import ctypes
import math
import shutil
import sys
from pathlib import Path
from typing import Optional

import qtawesome as qta
from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    QSettings,
    QStandardPaths,
    Qt,
    QThread,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from . import __version__
from .analysis import SUPPORTED_EXTENSIONS, discover_images, load_display_image
from .fileops import (
    execute_organization_plan,
    expand_linked_photo_records,
    move_photo_to_trash,
    move_photos,
    move_selected,
    plan_organization_moves,
    read_history,
    undo_last_move,
)
from .models import (
    AnalysisOptions,
    PhotoGroup,
    PhotoRecord,
    ReviewStatus,
    format_file_size,
)
from .organizer import OrganizationGroup, OrganizationPlan, build_organization_plan
from .session import ReviewSessionStore, ReviewSessionSummary
from .theme import apply_unified_theme
from .worker import AnalysisWorker


ICON_COLOR = "#8e8e93"
ICON_MUTED = "#8e8e93"
ICON_ACCENT = "#32a66a"
ICON_DANGER = "#e0525e"

REVIEW_PRESETS = {
    "conservative": (90, 45, 14),
    "balanced": (84, 90, 22),
    "relaxed": (78, 180, 30),
}


def _icon(
    name: str,
    color: str = ICON_COLOR,
    *,
    active: Optional[str] = None,
) -> QIcon:
    return qta.icon(
        f"mdi6.{name}",
        color=color,
        color_active=active or color,
        color_disabled=ICON_MUTED,
    )


def _setting_bool(settings: QSettings, key: str, default: bool = False) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _reduced_motion() -> bool:
    return _setting_bool(QSettings(), "appearance/reduce_motion")


def _theme_setting(settings: QSettings) -> str:
    value = str(settings.value("appearance/theme", "light"))
    return {"graphite": "light", "black": "dark"}.get(value, value)


def _sync_macos_appearance(mode: str) -> None:
    """Keep the native title bar in the same appearance as the Qt workspace."""
    if sys.platform != "darwin":
        return
    instance = QApplication.instance()
    if isinstance(instance, QApplication) and instance.platformName() != "cocoa":
        return
    try:
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send_address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        if send_address is None:
            return
        send = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(send_address)
        send_pointer = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(send_address)
        send_string = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
        )(send_address)
        ns_string = objc.objc_getClass(b"NSString")
        ns_appearance = objc.objc_getClass(b"NSAppearance")
        ns_application = objc.objc_getClass(b"NSApplication")
        appearance_name = send_string(
            ns_string,
            objc.sel_registerName(b"stringWithUTF8String:"),
            b"NSAppearanceNameDarkAqua" if mode == "dark" else b"NSAppearanceNameAqua",
        )
        appearance = send_pointer(
            ns_appearance,
            objc.sel_registerName(b"appearanceNamed:"),
            appearance_name,
        )
        application = send(
            ns_application,
            objc.sel_registerName(b"sharedApplication"),
        )
        send_pointer(
            application,
            objc.sel_registerName(b"setAppearance:"),
            appearance,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        # Qt still receives a matching palette if the native bridge is unavailable.
        return


def _read_preview(path: Path, target: QSize) -> QImage:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original_size = reader.size()
    if original_size.isValid():
        original_size.scale(target, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(original_size)
    image = reader.read()
    if not image.isNull():
        return image

    try:
        with load_display_image(path) as source:
            fallback = source.convert("RGBA")
            fallback.thumbnail((target.width(), target.height()), Image.Resampling.LANCZOS)
            width, height = fallback.size
            return QImage(
                fallback.tobytes(),
                width,
                height,
                width * 4,
                QImage.Format.Format_RGBA8888,
            ).copy()
    except Exception:
        return QImage()


def _bundled_demo_folder() -> Optional[Path]:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    else:
        root = Path(__file__).resolve().parents[2]
    folder = root / "demo-photos"
    return folder if folder.is_dir() else None


def _prepare_demo_folder() -> Path:
    source = _bundled_demo_folder()
    if source is None:
        raise FileNotFoundError("没有找到内置演示照片")

    cache_root = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    destination = Path(cache_root or Path.home() / ".photo-fit-picker") / "demo-photos"
    destination.mkdir(parents=True, exist_ok=True)
    for photo in source.iterdir():
        if photo.is_file() and photo.suffix.lower() in SUPPORTED_EXTENSIONS:
            shutil.copy2(photo, destination / photo.name)
    return destination


def _confirm_recoverable_trash(parent: QWidget, title: str, message: str) -> bool:
    dialog = QMessageBox(QMessageBox.Icon.Warning, title, message, parent=parent)
    confirm = dialog.addButton("移到回收站", QMessageBox.ButtonRole.AcceptRole)
    confirm.setObjectName("destructiveButton")
    confirm.setStyleSheet(
        "QPushButton { color: #ffffff; background: #b9434e; "
        "border: 1px solid #b9434e; border-radius: 6px; padding: 0 12px; }"
        "QPushButton:hover { background: #a63843; border-color: #a63843; }"
    )
    cancel = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    dialog.exec()
    return dialog.clickedButton() is confirm


class _RippleFeedback:
    def __init__(self, owner: QWidget) -> None:
        self.owner = owner
        self.origin = QPointF()
        self.progress = 1.0
        self.animation = QVariantAnimation(owner)
        self.animation.setDuration(260)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._update)

    def start(self, origin: QPointF) -> None:
        if _reduced_motion():
            self.progress = 1.0
            return
        self.origin = origin
        self.animation.stop()
        self.animation.start()

    def _update(self, value: object) -> None:
        self.progress = float(value)
        self.owner.update()

    def paint(self) -> None:
        if self.progress >= 1.0:
            return
        painter = QPainter(self.owner)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.owner.rect().adjusted(1, 1, -1, -1)), 6, 6)
        painter.setClipPath(clip)
        corners = (
            QPointF(0, 0),
            QPointF(self.owner.width(), 0),
            QPointF(0, self.owner.height()),
            QPointF(self.owner.width(), self.owner.height()),
        )
        radius = max(
            math.hypot(corner.x() - self.origin.x(), corner.y() - self.origin.y())
            for corner in corners
        ) * self.progress
        color = (
            QColor(255, 255, 255)
            if self.owner.objectName() in {"primaryButton", "emptyPrimaryButton"}
            else (
                QColor(255, 255, 255)
                if _theme_setting(QSettings()) == "dark"
                else QColor(44, 57, 68)
            )
        )
        color.setAlpha(int(34 * (1.0 - self.progress)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(self.origin, radius, radius)


class FeedbackButton(QPushButton):
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._ripple = _RippleFeedback(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._ripple.start(event.position())
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        self._ripple.paint()


class FeedbackToolButton(QToolButton):
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._ripple = _RippleFeedback(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._ripple.start(event.position())
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        self._ripple.paint()


class SelectionCheckBox(QCheckBox):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("选择照片")

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(3, 3, 20, 20)
        dark = _theme_setting(QSettings()) == "dark"
        if not self.isEnabled():
            painter.setPen(QPen(QColor("#686970"), 1.5))
            painter.setBrush(QColor("#303136" if dark else "#e1e1e5"))
        elif self.isChecked():
            painter.setPen(QPen(QColor("#d6eaff"), 1.5))
            painter.setBrush(QColor("#43c982" if dark else "#228754"))
        else:
            painter.setPen(QPen(QColor("#b9bac1" if not dark else "#b3b4bb"), 1.5))
            painter.setBrush(QColor("#ffffff" if not dark else "#111214"))
        painter.drawRoundedRect(box, 5, 5)
        if self.isChecked():
            painter.setPen(
                QPen(
                    QColor("#ffffff"),
                    2.2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            check = QPainterPath(QPointF(7.5, 13.2))
            check.lineTo(QPointF(11.2, 17.0))
            check.lineTo(QPointF(18.7, 9.0))
            painter.drawPath(check)


class SettingsSwitch(QCheckBox):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 2, 40, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.isChecked():
            track_color = QColor("#2f9b69")
        elif _theme_setting(QSettings()) == "dark":
            track_color = QColor("#3a3e43")
        else:
            track_color = QColor("#c8ced3")
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 10, 10)
        knob_x = 21 if self.isChecked() else 3
        painter.setBrush(QColor("#f3f5f4"))
        painter.drawEllipse(QRectF(knob_x, 4, 16, 16))


class PhotoCard(QFrame):
    status_changed = Signal()
    selection_changed = Signal()
    open_requested = Signal(object)

    def __init__(
        self,
        photo: PhotoRecord,
        recommended: bool,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.photo = photo
        self.recommended = recommended
        self.setObjectName("photoCard")
        self.setProperty("reviewStatus", photo.status.value)
        self.setFixedWidth(268)
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self._clear_feedback)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        preview_frame.setFixedSize(268, 179)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = PreviewLabel("正在载入…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(268, 179)
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.setToolTip("打开大图预览")
        self.preview.clicked.connect(lambda: self.open_requested.emit(self.photo))
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_frame)

        self.select_box = SelectionCheckBox()
        self.select_box.setObjectName("photoSelect")
        self.select_box.setToolTip("选择照片以执行批量操作")
        self.select_box.setChecked(photo.selected)
        self.select_box.setParent(preview_frame)
        self.select_box.move(232, 10)
        self.select_box.stateChanged.connect(self._selection_changed)
        self.select_box.raise_()

        if recommended:
            badge = QLabel("最佳")
            badge.setObjectName("recommendBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(50, 26)
            badge.setParent(preview_frame)
            badge.move(10, 10)
            badge.raise_()

        self.action_panel = QFrame(preview_frame)
        self.action_panel.setObjectName("cardActions")
        self.action_panel.setFixedSize(76, 36)
        self.action_panel.move(182, 133)
        action_layout = QHBoxLayout(self.action_panel)
        action_layout.setContentsMargins(2, 2, 2, 2)
        action_layout.setSpacing(4)

        self.reject_button = FeedbackToolButton()
        self.reject_button.setIcon(_icon("close", ICON_DANGER))
        self.reject_button.setIconSize(QSize(17, 17))
        self.reject_button.setCheckable(True)
        self.reject_button.setObjectName("rejectButton")
        self.reject_button.setToolTip("排除这张照片")
        self.reject_button.setAccessibleName("排除这张照片")
        self.keep_button = FeedbackToolButton()
        self.keep_button.setIcon(_icon("check", ICON_ACCENT))
        self.keep_button.setIconSize(QSize(18, 18))
        self.keep_button.setCheckable(True)
        self.keep_button.setObjectName("keepButton")
        self.keep_button.setToolTip("保留这张照片")
        self.keep_button.setAccessibleName("保留这张照片")
        self.keep_button.clicked.connect(lambda: self._set_status(ReviewStatus.KEPT))
        self.reject_button.clicked.connect(lambda: self._set_status(ReviewStatus.REJECTED))
        action_layout.addWidget(self.reject_button)
        action_layout.addWidget(self.keep_button)
        self.action_panel.raise_()
        self.action_panel.hide()

        caption = QFrame()
        caption.setObjectName("photoCaption")
        caption_layout = QVBoxLayout(caption)
        caption_layout.setContentsMargins(12, 10, 12, 11)
        caption_layout.setSpacing(5)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        display_name = photo.display_name
        name = QLabel()
        name.setObjectName("photoName")
        name.setToolTip(str(photo.path))
        name.setText(
            name.fontMetrics().elidedText(
                display_name,
                Qt.TextElideMode.ElideMiddle,
                164,
            )
        )
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_row.addWidget(name, 1)

        self.status_label = QLabel("待处理")
        self.status_label.setObjectName("photoStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedHeight(22)
        title_row.addWidget(self.status_label)
        caption_layout.addLayout(title_row)

        details = QLabel(
            f"{photo.captured_at:%m月%d日 %H:%M}  ·  {photo.format_label}"
            f"  ·  {photo.file_size_label}"
        )
        details.setObjectName("photoDetails")
        caption_layout.addWidget(details)
        secondary_text = photo.dimension_label
        if photo.metadata.camera_label:
            secondary_text += f"  ·  {photo.metadata.camera_label}"
        elif photo.metadata.shooting_summary:
            secondary_text += f"  ·  {photo.metadata.shooting_summary}"
        secondary = QLabel()
        secondary.setObjectName("photoSecondaryDetails")
        secondary.setText(
            secondary.fontMetrics().elidedText(
                secondary_text,
                Qt.TextElideMode.ElideRight,
                240,
            )
        )
        secondary.setToolTip(secondary_text)
        caption_layout.addWidget(secondary)
        layout.addWidget(caption)

        self.sync_status()
        self._load_thumbnail()

    def _load_thumbnail(self) -> None:
        image = _read_preview(self.photo.path, QSize(536, 358))
        if image.isNull():
            self.preview.setText("无法预览")
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    def _set_status(self, status: ReviewStatus) -> None:
        self.photo.status = ReviewStatus.PENDING if self.photo.status == status else status
        self.sync_status()
        self.setProperty("feedback", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.feedback_timer.start(170)
        self.status_changed.emit()

    def _selection_changed(self, state: int) -> None:
        self.photo.selected = state == Qt.CheckState.Checked.value
        self.setProperty("selected", self.photo.selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.selection_changed.emit()

    def _clear_feedback(self) -> None:
        self.setProperty("feedback", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def animate_in(self, delay_ms: int) -> None:
        if _reduced_motion():
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(210)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self._finish_entrance)
        self._entrance_animation = animation
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(animation.start)
        self._entrance_timer = timer
        timer.start(delay_ms)

    def _finish_entrance(self) -> None:
        effect = self.graphicsEffect()
        if effect:
            effect.setEnabled(False)

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
            self.action_panel.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.action_panel.hide()
        super().leaveEvent(event)

    def sync_status(self) -> None:
        self.keep_button.setChecked(self.photo.status == ReviewStatus.KEPT)
        self.reject_button.setChecked(self.photo.status == ReviewStatus.REJECTED)
        self.keep_button.setIcon(
            _icon(
                "check",
                "#ffffff" if self.photo.status == ReviewStatus.KEPT else ICON_ACCENT,
            )
        )
        self.reject_button.setIcon(
            _icon(
                "close",
                "#ffffff" if self.photo.status == ReviewStatus.REJECTED else ICON_DANGER,
            )
        )
        status_text = {
            ReviewStatus.PENDING: "待处理",
            ReviewStatus.KEPT: "已保留",
            ReviewStatus.REJECTED: "已排除",
            ReviewStatus.MOVED: "已移动",
            ReviewStatus.TRASHED: "回收站",
        }[self.photo.status]
        self.status_label.setText(status_text)
        self.status_label.setVisible(self.photo.status != ReviewStatus.PENDING)
        self.status_label.setProperty("reviewStatus", self.photo.status.value)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        is_final = self.photo.status in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
        self.keep_button.setEnabled(not is_final)
        self.reject_button.setEnabled(not is_final)
        self.select_box.setEnabled(not is_final)
        if is_final and self.select_box.isChecked():
            self.select_box.blockSignals(True)
            self.select_box.setChecked(False)
            self.select_box.blockSignals(False)
            self.photo.selected = False
        elif self.select_box.isChecked() != self.photo.selected:
            self.select_box.blockSignals(True)
            self.select_box.setChecked(self.photo.selected)
            self.select_box.blockSignals(False)
        self.setProperty("reviewStatus", self.photo.status.value)
        self.setProperty("selected", self.photo.selected)
        self.style().unpolish(self)
        self.style().polish(self)


class PreviewLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PhotoViewer(QDialog):
    status_changed = Signal()
    trash_requested = Signal(object)

    def __init__(
        self,
        group: PhotoGroup,
        start_index: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.group = group
        self.photos = group.photos
        self.index = start_index
        self.setObjectName("photoViewer")
        self.setWindowTitle("照片预览")
        self.setModal(True)
        self.resize(1100, 760)
        self.setMinimumSize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.image_label = QLabel()
        self.image_label.setObjectName("viewerImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 400)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        body.addWidget(self.image_label, 1)

        inspector_scroll = QScrollArea()
        inspector_scroll.setObjectName("viewerInspectorScroll")
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inspector_scroll.setFixedWidth(292)
        inspector = QWidget()
        inspector.setObjectName("viewerInspector")
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(18, 16, 18, 16)
        inspector_layout.setSpacing(10)
        inspector_title = QLabel("照片信息")
        inspector_title.setObjectName("viewerSectionTitle")
        inspector_layout.addWidget(inspector_title)
        self.metadata_grid = QGridLayout()
        self.metadata_grid.setColumnStretch(1, 1)
        self.metadata_grid.setHorizontalSpacing(12)
        self.metadata_grid.setVerticalSpacing(8)
        inspector_layout.addLayout(self.metadata_grid)
        divider = QFrame()
        divider.setObjectName("viewerDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        inspector_layout.addWidget(divider)
        quality_title = QLabel("质量判断")
        quality_title.setObjectName("viewerSectionTitle")
        inspector_layout.addWidget(quality_title)
        self.quality_label = QLabel()
        self.quality_label.setObjectName("viewerQuality")
        self.quality_label.setWordWrap(True)
        inspector_layout.addWidget(self.quality_label)
        self.reason_label = QLabel()
        self.reason_label.setObjectName("viewerReason")
        self.reason_label.setWordWrap(True)
        inspector_layout.addWidget(self.reason_label)
        inspector_layout.addStretch()
        inspector_scroll.setWidget(inspector)
        body.addWidget(inspector_scroll)
        layout.addLayout(body, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.previous_button = FeedbackToolButton()
        self.previous_button.setIcon(_icon("chevron-left"))
        self.previous_button.setIconSize(QSize(20, 20))
        self.previous_button.setToolTip("上一张")
        self.previous_button.clicked.connect(self._previous)
        controls.addWidget(self.previous_button)

        self.next_button = FeedbackToolButton()
        self.next_button.setIcon(_icon("chevron-right"))
        self.next_button.setIconSize(QSize(20, 20))
        self.next_button.setToolTip("下一张")
        self.next_button.clicked.connect(self._next)
        controls.addWidget(self.next_button)

        self.info_label = QLabel()
        self.info_label.setObjectName("viewerInfo")
        controls.addWidget(self.info_label, 1)
        self.trash_button = FeedbackToolButton()
        self.trash_button.setObjectName("trashButton")
        self.trash_button.setIcon(_icon("trash-can-outline", ICON_DANGER))
        self.trash_button.setIconSize(QSize(18, 18))
        self.trash_button.setToolTip("移到系统废纸篓/回收站")
        self.trash_button.clicked.connect(self._request_trash)
        controls.addWidget(self.trash_button)
        self.reject_button = FeedbackButton("排除")
        self.reject_button.setIcon(_icon("close", ICON_DANGER))
        self.reject_button.clicked.connect(lambda: self._set_status(ReviewStatus.REJECTED))
        controls.addWidget(self.reject_button)
        self.keep_button = FeedbackButton("保留")
        self.keep_button.setIcon(_icon("check", "#ffffff"))
        self.keep_button.setObjectName("primaryButton")
        self.keep_button.clicked.connect(lambda: self._set_status(ReviewStatus.KEPT))
        controls.addWidget(self.keep_button)
        layout.addLayout(controls)

        self.shortcuts = [
            QShortcut(QKeySequence(Qt.Key.Key_Left), self),
            QShortcut(QKeySequence(Qt.Key.Key_Right), self),
            QShortcut(QKeySequence("K"), self),
            QShortcut(QKeySequence("X"), self),
        ]
        self.shortcuts[0].activated.connect(self._previous)
        self.shortcuts[1].activated.connect(self._next)
        self.shortcuts[2].activated.connect(lambda: self._set_status(ReviewStatus.KEPT))
        self.shortcuts[3].activated.connect(lambda: self._set_status(ReviewStatus.REJECTED))
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(90)
        self.resize_timer.timeout.connect(self._load_current)
        self._load_current()

    def _metadata_rows(self, photo: PhotoRecord) -> list[tuple[str, str]]:
        metadata = photo.metadata
        rows = [
            ("拍摄时间", photo.captured_at.strftime("%Y年%m月%d日 %H:%M:%S")),
            ("尺寸", f"{photo.dimension_label}  ·  {photo.megapixels:.1f} MP"),
            ("文件", f"{photo.format_label}  ·  {photo.file_size_label}"),
        ]
        optional_rows = [
            ("相机", metadata.camera_label),
            ("镜头", metadata.lens),
            ("拍摄参数", metadata.shooting_summary),
            ("曝光补偿", f"{metadata.exposure_bias:+g} EV" if metadata.exposure_bias is not None else ""),
            ("白平衡", metadata.white_balance),
            ("对焦", metadata.focus_mode),
            ("测光", metadata.metering_mode),
            ("曝光程序", metadata.exposure_program),
            ("闪光灯", metadata.flash),
            ("软件", metadata.software),
            (
                "位置",
                f"{metadata.latitude:.5f}, {metadata.longitude:.5f}"
                if metadata.has_location
                else "",
            ),
        ]
        rows.extend((label, value) for label, value in optional_rows if value)
        rows.extend(metadata.details)
        return rows

    def _populate_inspector(self, photo: PhotoRecord) -> None:
        while self.metadata_grid.count():
            item = self.metadata_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for row, (label_text, value_text) in enumerate(self._metadata_rows(photo)):
            label = QLabel(label_text)
            label.setObjectName("viewerMetadataLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            value = QLabel(value_text)
            value.setObjectName("viewerMetadataValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.metadata_grid.addWidget(label, row, 0)
            self.metadata_grid.addWidget(value, row, 1)

        recommended = self.group.recommended
        self.quality_label.setText(
            f"{photo.quality_summary}\n综合质量 {self.group.score(photo) * 100:.0f} 分"
        )
        self.reason_label.setText(
            "本组推荐 · 清晰度与曝光综合得分最高"
            if photo is recommended
            else "拍摄时间、构图与色彩接近，可与本组推荐照片对比。"
        )

    def _load_current(self) -> None:
        photo = self.photos[self.index]
        target = self.image_label.size()
        if target.width() < 100 or target.height() < 100:
            target = QSize(1000, 650)
        image = _read_preview(photo.path, target)
        if image.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("无法预览此照片")
        else:
            self.image_label.setText("")
            self.image_label.setPixmap(QPixmap.fromImage(image))
        state = {
            ReviewStatus.PENDING: "待审核",
            ReviewStatus.KEPT: "已保留",
            ReviewStatus.REJECTED: "已排除",
            ReviewStatus.MOVED: "已移动",
            ReviewStatus.TRASHED: "已移到回收站",
        }[photo.status]
        self.info_label.setText(
            f"{self.index + 1} / {len(self.photos)}  ·  {photo.display_name}  ·  {state}"
        )
        self._populate_inspector(photo)
        self.previous_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.photos) - 1)
        movable = photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
        self.keep_button.setEnabled(movable)
        self.reject_button.setEnabled(movable)
        self.trash_button.setEnabled(photo.status != ReviewStatus.TRASHED and photo.path.is_file())

    def _previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._load_current()

    def _next(self) -> None:
        if self.index < len(self.photos) - 1:
            self.index += 1
            self._load_current()

    def _set_status(self, status: ReviewStatus) -> None:
        photo = self.photos[self.index]
        if photo.status in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
            return
        photo.status = ReviewStatus.PENDING if photo.status == status else status
        self.status_changed.emit()
        self._load_current()

    def _request_trash(self) -> None:
        self.trash_requested.emit(self.photos[self.index])
        self._load_current()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if hasattr(self, "resize_timer"):
            self.resize_timer.start()


class OrganizationView(QWidget):
    back_requested = Signal()
    apply_requested = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.plan = OrganizationPlan()
        self.setObjectName("organizationView")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("organizationHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        back = FeedbackToolButton()
        back.setObjectName("headerIconButton")
        back.setIcon(_icon("arrow-left"))
        back.setToolTip("返回照片")
        back.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("整理预览")
        title.setObjectName("organizationTitle")
        self.summary = QLabel("尚未生成整理建议")
        self.summary.setObjectName("organizationSummary")
        title_box.addWidget(title)
        title_box.addWidget(self.summary)
        header_layout.addLayout(title_box)
        header_layout.addStretch()
        safety = QLabel("确认前不会移动照片")
        safety.setObjectName("organizationSafety")
        header_layout.addWidget(safety)
        self.apply_button = FeedbackButton("确认并整理")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.setIcon(_icon("folder-move-outline", "#ffffff"))
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(self.plan))
        header_layout.addWidget(self.apply_button)
        root.addWidget(header)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setObjectName("organizationSplitter")
        content.setChildrenCollapsible(False)
        sidebar = QFrame()
        sidebar.setObjectName("organizationSidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 14)
        sidebar_layout.setSpacing(10)
        section = QLabel("建议分组")
        section.setObjectName("sectionTitle")
        sidebar_layout.addWidget(section)
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.group_list.currentItemChanged.connect(self._show_current_group)
        self.group_list.itemSelectionChanged.connect(self._update_actions)
        sidebar_layout.addWidget(self.group_list, 1)
        self.merge_button = FeedbackButton("合并所选分组")
        self.merge_button.setIcon(_icon("set-merge", ICON_MUTED))
        self.merge_button.clicked.connect(self._merge_selected)
        sidebar_layout.addWidget(self.merge_button)
        content.addWidget(sidebar)

        detail = QWidget()
        detail.setObjectName("organizationDetail")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(28, 24, 28, 20)
        detail_layout.setSpacing(12)
        detail_title = QLabel("分组名称")
        detail_title.setObjectName("sectionTitle")
        detail_layout.addWidget(detail_title)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("organizationNameEdit")
        self.name_edit.setPlaceholderText("输入目标文件夹名称")
        self.name_edit.editingFinished.connect(self._rename_current)
        detail_layout.addWidget(self.name_edit)
        self.group_meta = QLabel()
        self.group_meta.setObjectName("organizationGroupMeta")
        self.group_meta.setWordWrap(True)
        detail_layout.addWidget(self.group_meta)
        photos_title_row = QHBoxLayout()
        photos_title = QLabel("组内照片")
        photos_title.setObjectName("sectionTitle")
        photos_title_row.addWidget(photos_title)
        photos_title_row.addStretch()
        self.split_button = FeedbackButton("拆分所选照片")
        self.split_button.setIcon(_icon("call-split", ICON_MUTED))
        self.split_button.clicked.connect(self._split_selected)
        photos_title_row.addWidget(self.split_button)
        detail_layout.addLayout(photos_title_row)
        self.photo_list = QListWidget()
        self.photo_list.setObjectName("organizationPhotoList")
        self.photo_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.photo_list.itemSelectionChanged.connect(self._update_actions)
        detail_layout.addWidget(self.photo_list, 1)
        content.addWidget(detail)
        content.setSizes([300, 980])
        root.addWidget(content, 1)

    def set_plan(self, plan: OrganizationPlan) -> None:
        self.plan = plan
        self._refresh_groups()

    def _refresh_groups(self, selected_id: int = 1) -> None:
        self.group_list.blockSignals(True)
        self.group_list.clear()
        selected_row = 0
        for row, group in enumerate(self.plan.groups):
            item = QListWidgetItem(f"{group.name}\n{len(group.photos)} 张 · {group.date_range}")
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            item.setSizeHint(QSize(0, 58))
            self.group_list.addItem(item)
            if group.id == selected_id:
                selected_row = row
        self.group_list.blockSignals(False)
        count = sum(len(group.photos) for group in self.plan.groups)
        self.summary.setText(f"{count} 张照片 · {len(self.plan.groups)} 个建议文件夹")
        if self.plan.groups:
            self.group_list.setCurrentRow(selected_row)
            self._show_current_group(self.group_list.currentItem())
        else:
            self.name_edit.clear()
            self.group_meta.setText("没有可整理的照片")
            self.photo_list.clear()
        self._update_actions()

    def _current_group(self) -> Optional[OrganizationGroup]:
        item = self.group_list.currentItem()
        if not item:
            return None
        return self.plan.group(int(item.data(Qt.ItemDataRole.UserRole)))

    def _show_current_group(self, _current: Optional[QListWidgetItem], *_args) -> None:
        group = self._current_group()
        self.photo_list.clear()
        if not group:
            return
        self.name_edit.setText(group.name)
        self.group_meta.setText(f"{group.date_range}\n{group.reason}")
        for photo in group.photos:
            item = QListWidgetItem(
                f"{photo.display_name}\n{photo.captured_at:%H:%M:%S}  ·  "
                f"{photo.format_label}  ·  {photo.file_size_label}"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(photo.path))
            preview = _read_preview(photo.path, QSize(88, 56))
            if not preview.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(preview)))
            item.setSizeHint(QSize(0, 64))
            self.photo_list.addItem(item)
        self._update_actions()

    def _rename_current(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.plan.rename(group.id, self.name_edit.text())
        self.name_edit.setText(group.name)
        current = self.group_list.currentItem()
        if current:
            current.setText(f"{group.name}\n{len(group.photos)} 张 · {group.date_range}")

    def _merge_selected(self) -> None:
        ids = [
            int(item.data(Qt.ItemDataRole.UserRole))
            for item in self.group_list.selectedItems()
        ]
        merged = self.plan.merge(ids)
        if merged:
            self._refresh_groups(merged.id)

    def _split_selected(self) -> None:
        group = self._current_group()
        if not group:
            return
        paths = [
            Path(str(item.data(Qt.ItemDataRole.UserRole)))
            for item in self.photo_list.selectedItems()
        ]
        created = self.plan.split(group.id, paths)
        if created:
            self._refresh_groups(created.id)

    def _update_actions(self) -> None:
        self.merge_button.setEnabled(len(self.group_list.selectedItems()) >= 2)
        group = self._current_group()
        selected = len(self.photo_list.selectedItems())
        self.split_button.setEnabled(bool(group) and 0 < selected < len(group.photos))
        self.apply_button.setEnabled(bool(self.plan.groups))


class SettingsView(QWidget):
    back_requested = Signal()
    source_requested = Signal()
    reanalyze_requested = Signal()
    preferences_changed = Signal()

    def __init__(
        self,
        source_folder: Optional[Path],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.preferences = QSettings()
        self.source_folder = source_folder
        self._applying_preset = False
        self.setObjectName("settingsView")

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(224)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 24, 14, 16)
        sidebar_layout.setSpacing(8)

        back_button = FeedbackButton("返回照片")
        back_button.setObjectName("settingsBackButton")
        back_button.setIcon(_icon("arrow-left"))
        back_button.setIconSize(QSize(18, 18))
        back_button.setAccessibleName("返回照片")
        back_button.clicked.connect(self.back_requested.emit)
        sidebar_layout.addWidget(back_button)

        title = QLabel("设置")
        title.setObjectName("settingsTitle")
        sidebar_layout.addWidget(title)

        self.navigation_buttons: list[FeedbackButton] = []
        for index, (text, icon_name) in enumerate(
            (
                ("外观", "palette-outline"),
                ("文件夹", "folder-outline"),
                ("筛选", "tune-variant"),
                ("整理", "folder-marker-outline"),
                ("算法", "chart-bell-curve-cumulative"),
                ("实验功能", "flask-outline"),
            )
        ):
            button = FeedbackButton(text)
            button.setObjectName("settingsNavButton")
            button.setIcon(_icon(icon_name, ICON_MUTED))
            button.setIconSize(QSize(18, 18))
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, row=index: self._select_page(row))
            sidebar_layout.addWidget(button)
            self.navigation_buttons.append(button)
        sidebar_layout.addStretch()

        version = QLabel(f"拾影 {__version__}")
        version.setObjectName("settingsVersion")
        sidebar_layout.addWidget(version)
        root_layout.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("settingsContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(54, 48, 54, 36)
        content_layout.setSpacing(0)
        content_layout.addStretch()

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        self.pages.addWidget(self._build_appearance_page())
        self.pages.addWidget(self._build_folder_page())
        self.pages.addWidget(self._build_review_page())
        self.pages.addWidget(self._build_organization_page())
        self.pages.addWidget(self._build_algorithm_page())
        self.pages.addWidget(self._build_experiments_page())
        self.pages.setMaximumWidth(720)
        content_layout.addWidget(self.pages, 1)
        content_layout.addStretch()
        root_layout.addWidget(content, 1)
        self._select_page(0)

    def _page(self, title: str, hint: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        layout.addWidget(heading)
        description = QLabel(hint)
        description.setObjectName("settingsSectionHint")
        description.setWordWrap(True)
        layout.addWidget(description)
        return page, layout

    def _group(self) -> tuple[QFrame, QVBoxLayout]:
        group = QFrame()
        group.setObjectName("settingsGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        return group, layout

    def _text_block(self, title: str, hint: str = "") -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("settingsRowTitle")
        layout.addWidget(label)
        if hint:
            description = QLabel(hint)
            description.setObjectName("settingsRowHint")
            description.setWordWrap(True)
            layout.addWidget(description)
        return block

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("settingsDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        return divider

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._page("外观", "选择更适合看照片的界面，并控制交互动画。")
        group, group_layout = self._group()

        theme_row = QHBoxLayout()
        theme_row.addWidget(
            self._text_block("界面主题"),
            1,
        )
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("明亮", "light")
        self.theme_combo.addItem("深色", "dark")
        saved_theme = _theme_setting(self.preferences)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(saved_theme)))
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        theme_row.addWidget(self.theme_combo)
        group_layout.addLayout(theme_row)
        group_layout.addWidget(self._divider())

        motion_row = QHBoxLayout()
        motion_row.addWidget(
            self._text_block("减少动画"),
            1,
        )
        self.motion_toggle = SettingsSwitch()
        self.motion_toggle.setObjectName("settingsSwitch")
        self.motion_toggle.setChecked(
            _setting_bool(self.preferences, "appearance/reduce_motion")
        )
        self.motion_toggle.toggled.connect(
            lambda checked: self.preferences.setValue(
                "appearance/reduce_motion",
                checked,
            )
        )
        motion_row.addWidget(self.motion_toggle)
        group_layout.addLayout(motion_row)
        layout.addWidget(group)
        layout.addStretch()
        return page

    def _build_folder_page(self) -> QWidget:
        page, layout = self._page("文件夹", "管理正在审阅的照片和默认输出位置。")
        source_group, source_layout = self._group()
        source_row = QHBoxLayout()
        source_name = str(self.source_folder) if self.source_folder else "尚未选择照片文件夹"
        self.source_path_block = self._text_block("当前照片文件夹", source_name)
        source_row.addWidget(
            self.source_path_block,
            1,
        )
        self.change_source_button = FeedbackButton("更换")
        self.change_source_button.setObjectName("settingsActionButton")
        self.change_source_button.clicked.connect(self.source_requested.emit)
        source_row.addWidget(self.change_source_button)
        source_layout.addLayout(source_row)
        layout.addWidget(source_group)

        destination_group, destination_layout = self._group()
        destination_row = QHBoxLayout()
        destination_row.addWidget(
            self._text_block("默认目标位置"),
            1,
        )
        self.destination_mode = QComboBox()
        self.destination_mode.addItem("照片文件夹内 / 已筛选", "source")
        self.destination_mode.addItem("固定文件夹", "custom")
        saved_mode = str(
            self.preferences.value("folders/destination_mode", "source")
        )
        self.destination_mode.setCurrentIndex(
            max(0, self.destination_mode.findData(saved_mode))
        )
        self.destination_mode.currentIndexChanged.connect(self._destination_mode_changed)
        destination_row.addWidget(self.destination_mode)
        destination_layout.addLayout(destination_row)
        self.custom_destination_divider = self._divider()
        destination_layout.addWidget(self.custom_destination_divider)

        custom_row = QHBoxLayout()
        custom_path = str(self.preferences.value("folders/custom_destination", ""))
        self.destination_path = QLabel(custom_path or "未设置固定文件夹")
        self.destination_path.setObjectName("settingsPath")
        self.destination_path.setWordWrap(True)
        custom_row.addWidget(self.destination_path, 1)
        self.choose_destination = FeedbackButton("选择…")
        self.choose_destination.setObjectName("settingsActionButton")
        self.choose_destination.clicked.connect(self._choose_custom_destination)
        custom_row.addWidget(self.choose_destination)
        destination_layout.addLayout(custom_row)
        layout.addWidget(destination_group)

        safety_group, safety_layout = self._group()
        safety_row = QHBoxLayout()
        safety_icon = QLabel()
        safety_icon.setPixmap(_icon("shield-check-outline", ICON_ACCENT).pixmap(20, 20))
        safety_row.addWidget(safety_icon)
        safety_row.addWidget(
            self._text_block(
                "照片安全",
                "应用不会自动删除照片；手动删除只进入系统回收站，"
                "并始终二次确认。",
            ),
            1,
        )
        safety_layout.addLayout(safety_row)
        layout.addWidget(safety_group)
        layout.addStretch()
        self._sync_destination_controls()
        return page

    def _build_review_page(self) -> QWidget:
        page, layout = self._page("筛选", "调整相似照片成组时使用的判断范围。")
        preset_group, preset_layout = self._group()
        preset_row = QHBoxLayout()
        preset_row.addWidget(
            self._text_block("筛选预设", "从稳妥的连拍识别到更宽松的相似画面归组。"),
            1,
        )
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("保守", "conservative")
        self.preset_combo.addItem("均衡", "balanced")
        self.preset_combo.addItem("宽松", "relaxed")
        self.preset_combo.addItem("自定义", "custom")
        preset = str(self.preferences.value("review/preset", "balanced"))
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(preset)))
        preset_row.addWidget(self.preset_combo)
        preset_layout.addLayout(preset_row)
        layout.addWidget(preset_group)

        group, group_layout = self._group()

        similarity_row = QHBoxLayout()
        similarity_row.addWidget(
            self._text_block("相似度"),
            1,
        )
        self.similarity_value = QLabel()
        self.similarity_value.setObjectName("settingsValue")
        similarity_row.addWidget(self.similarity_value)
        group_layout.addLayout(similarity_row)
        self.similarity_slider = QSlider(Qt.Orientation.Horizontal)
        self.similarity_slider.setRange(70, 95)
        self.similarity_slider.setValue(
            int(self.preferences.value("review/similarity", 84))
        )
        self.similarity_value.setText(f"{self.similarity_slider.value()}%")
        self.similarity_slider.valueChanged.connect(self._similarity_changed)
        group_layout.addWidget(self.similarity_slider)
        group_layout.addWidget(self._divider())

        time_row = QHBoxLayout()
        time_row.addWidget(
            self._text_block("连拍时间范围"),
            1,
        )
        self.time_window = QSpinBox()
        self.time_window.setRange(5, 600)
        self.time_window.setValue(
            int(self.preferences.value("review/time_window", 90))
        )
        self.time_window.setSuffix(" 秒")
        self.time_window.valueChanged.connect(self._time_window_changed)
        time_row.addWidget(self.time_window)
        group_layout.addLayout(time_row)
        layout.addWidget(group)

        self.reanalyze_button = FeedbackButton("重新分析照片")
        self.reanalyze_button.setObjectName("primaryButton")
        self.reanalyze_button.setIcon(_icon("refresh", "#ffffff"))
        self.reanalyze_button.clicked.connect(self.reanalyze_requested.emit)
        layout.addWidget(self.reanalyze_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.set_analysis_available(self.source_folder is not None, False)
        return page

    def _build_algorithm_page(self) -> QWidget:
        page, layout = self._page(
            "算法",
            "调整画面相似度和组内推荐的权重，修改后重新分析才会生效。",
        )
        similarity_group, similarity_layout = self._group()
        color_row = QHBoxLayout()
        color_row.addWidget(
            self._text_block("色彩权重", "提高后，相同构图但色调差异大的照片更难归为一组。"),
            1,
        )
        self.color_weight_value = QLabel()
        self.color_weight_value.setObjectName("settingsValue")
        color_row.addWidget(self.color_weight_value)
        similarity_layout.addLayout(color_row)
        self.color_weight_slider = QSlider(Qt.Orientation.Horizontal)
        self.color_weight_slider.setRange(0, 50)
        self.color_weight_slider.setValue(int(self.preferences.value("algorithm/color_weight", 22)))
        self.color_weight_value.setText(f"{self.color_weight_slider.value()}%")
        self.color_weight_slider.valueChanged.connect(self._color_weight_changed)
        similarity_layout.addWidget(self.color_weight_slider)
        layout.addWidget(similarity_group)

        recommendation_group, recommendation_layout = self._group()
        recommendation_layout.addWidget(
            self._text_block("最佳照片推荐", "权重会自动归一化，不会修改照片本身。")
        )
        self.quality_sliders: dict[str, tuple[QSlider, QLabel]] = {}
        for key, title, default in (
            ("sharpness", "清晰度", 75),
            ("exposure", "曝光", 25),
            ("resolution", "分辨率", 0),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(title), 1)
            value_label = QLabel()
            value_label.setObjectName("settingsValue")
            row.addWidget(value_label)
            recommendation_layout.addLayout(row)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(self.preferences.value(f"algorithm/{key}_weight", default)))
            value_label.setText(str(slider.value()))
            slider.valueChanged.connect(
                lambda value, name=key, label=value_label: self._quality_weight_changed(
                    name, label, value
                )
            )
            recommendation_layout.addWidget(slider)
            self.quality_sliders[key] = (slider, value_label)
        layout.addWidget(recommendation_group)
        layout.addStretch()
        return page

    def _build_organization_page(self) -> QWidget:
        page, layout = self._page(
            "整理",
            "控制本地整理建议如何划分一次旅行或拍摄活动。",
        )
        group, group_layout = self._group()
        gap_row = QHBoxLayout()
        gap_row.addWidget(
            self._text_block("活动间隔", "超过这个时间没有拍摄，就建议创建新的活动文件夹。"),
            1,
        )
        self.organization_gap = QSpinBox()
        self.organization_gap.setRange(30, 720)
        self.organization_gap.setSingleStep(30)
        self.organization_gap.setSuffix(" 分钟")
        self.organization_gap.setValue(
            int(self.preferences.value("organize/gap_minutes", 180))
        )
        self.organization_gap.valueChanged.connect(
            lambda value: self.preferences.setValue("organize/gap_minutes", value)
        )
        gap_row.addWidget(self.organization_gap)
        group_layout.addLayout(gap_row)
        group_layout.addWidget(self._divider())
        radius_row = QHBoxLayout()
        radius_row.addWidget(
            self._text_block("GPS 地点半径", "相距超过该范围的照片会建议放入不同地点。"),
            1,
        )
        self.organization_radius = QSpinBox()
        self.organization_radius.setRange(1, 50)
        self.organization_radius.setSuffix(" km")
        self.organization_radius.setValue(
            int(self.preferences.value("organize/gps_radius_km", 2))
        )
        self.organization_radius.valueChanged.connect(
            lambda value: self.preferences.setValue("organize/gps_radius_km", value)
        )
        radius_row.addWidget(self.organization_radius)
        group_layout.addLayout(radius_row)
        layout.addWidget(group)

        privacy_group, privacy_layout = self._group()
        privacy_row = QHBoxLayout()
        privacy_icon = QLabel()
        privacy_icon.setPixmap(_icon("map-marker-check-outline", ICON_ACCENT).pixmap(20, 20))
        privacy_row.addWidget(privacy_icon)
        privacy_row.addWidget(
            self._text_block(
                "位置隐私",
                "当前版本只在本机比较坐标，不联网查询地点名称。",
            ),
            1,
        )
        privacy_layout.addLayout(privacy_row)
        layout.addWidget(privacy_group)
        layout.addStretch()
        return page

    def _build_experiments_page(self) -> QWidget:
        page, layout = self._page(
            "实验功能",
            "这些本地算法可以随时关闭，不会上传或改写照片。",
        )
        group, group_layout = self._group()
        hash_row = QHBoxLayout()
        hash_row.addWidget(
            self._text_block("画面哈希", "差异哈希更关注结构；均值哈希对整体明暗变化更敏感。"),
            1,
        )
        self.hash_method_combo = QComboBox()
        self.hash_method_combo.addItem("差异哈希", "difference")
        self.hash_method_combo.addItem("均值哈希（实验）", "average")
        hash_method = str(self.preferences.value("algorithm/hash_method", "difference"))
        self.hash_method_combo.setCurrentIndex(
            max(0, self.hash_method_combo.findData(hash_method))
        )
        self.hash_method_combo.currentIndexChanged.connect(self._hash_method_changed)
        hash_row.addWidget(self.hash_method_combo)
        group_layout.addLayout(hash_row)
        group_layout.addWidget(self._divider())

        duplicate_row = QHBoxLayout()
        duplicate_row.addWidget(
            self._text_block("识别完全重复", "仅对文件大小相同的候选计算 SHA-256，可识别跨日期副本。"),
            1,
        )
        self.exact_duplicate_toggle = SettingsSwitch()
        self.exact_duplicate_toggle.setChecked(
            _setting_bool(self.preferences, "algorithm/exact_duplicates", True)
        )
        self.exact_duplicate_toggle.toggled.connect(self._exact_duplicates_changed)
        duplicate_row.addWidget(self.exact_duplicate_toggle)
        group_layout.addLayout(duplicate_row)
        layout.addWidget(group)
        layout.addStretch()
        return page

    def _select_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for row, button in enumerate(self.navigation_buttons):
            button.setChecked(row == index)

    def set_source_folder(self, source_folder: Optional[Path]) -> None:
        self.source_folder = source_folder
        labels = self.source_path_block.findChildren(QLabel, "settingsRowHint")
        if labels:
            labels[0].setText(
                str(source_folder) if source_folder else "尚未选择照片文件夹"
            )

    def set_analysis_available(self, has_source: bool, is_running: bool) -> None:
        self.reanalyze_button.setEnabled(has_source and not is_running)
        self.change_source_button.setEnabled(not is_running)

    def refresh_preferences(self) -> None:
        theme = _theme_setting(self.preferences)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme)))
        self.theme_combo.blockSignals(False)

        destination_mode = str(
            self.preferences.value("folders/destination_mode", "source")
        )
        self.destination_mode.blockSignals(True)
        self.destination_mode.setCurrentIndex(
            max(0, self.destination_mode.findData(destination_mode))
        )
        self.destination_mode.blockSignals(False)
        destination = str(self.preferences.value("folders/custom_destination", ""))
        self.destination_path.setText(destination or "未设置固定文件夹")
        self._sync_destination_controls()

        similarity = int(self.preferences.value("review/similarity", 84))
        self.similarity_slider.blockSignals(True)
        self.similarity_slider.setValue(similarity)
        self.similarity_slider.blockSignals(False)
        self.similarity_value.setText(f"{self.similarity_slider.value()}%")

        time_window = int(self.preferences.value("review/time_window", 90))
        self.time_window.blockSignals(True)
        self.time_window.setValue(time_window)
        self.time_window.blockSignals(False)

        gap_minutes = int(self.preferences.value("organize/gap_minutes", 180))
        self.organization_gap.blockSignals(True)
        self.organization_gap.setValue(gap_minutes)
        self.organization_gap.blockSignals(False)
        gps_radius = int(self.preferences.value("organize/gps_radius_km", 2))
        self.organization_radius.blockSignals(True)
        self.organization_radius.setValue(gps_radius)
        self.organization_radius.blockSignals(False)

        preset = str(self.preferences.value("review/preset", "balanced"))
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(preset)))
        self.preset_combo.blockSignals(False)

        color_weight = int(self.preferences.value("algorithm/color_weight", 22))
        self.color_weight_slider.blockSignals(True)
        self.color_weight_slider.setValue(color_weight)
        self.color_weight_slider.blockSignals(False)
        self.color_weight_value.setText(f"{color_weight}%")

        for key, (_slider, _label) in self.quality_sliders.items():
            default = {"sharpness": 75, "exposure": 25, "resolution": 0}[key]
            value = int(self.preferences.value(f"algorithm/{key}_weight", default))
            slider, label = self.quality_sliders[key]
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            label.setText(str(value))

        hash_method = str(self.preferences.value("algorithm/hash_method", "difference"))
        self.hash_method_combo.blockSignals(True)
        self.hash_method_combo.setCurrentIndex(
            max(0, self.hash_method_combo.findData(hash_method))
        )
        self.hash_method_combo.blockSignals(False)
        self.exact_duplicate_toggle.blockSignals(True)
        self.exact_duplicate_toggle.setChecked(
            _setting_bool(self.preferences, "algorithm/exact_duplicates", True)
        )
        self.exact_duplicate_toggle.blockSignals(False)

    def _theme_changed(self) -> None:
        theme = str(self.theme_combo.currentData())
        self.preferences.setValue("appearance/theme", theme)
        instance = QApplication.instance()
        if isinstance(instance, QApplication):
            apply_theme(instance, theme)

    def _similarity_changed(self, value: int) -> None:
        self.similarity_value.setText(f"{value}%")
        self.preferences.setValue("review/similarity", value)
        self._mark_custom_preset()

    def _time_window_changed(self, value: int) -> None:
        self.preferences.setValue("review/time_window", value)
        self._mark_custom_preset()

    def _preset_changed(self) -> None:
        preset = str(self.preset_combo.currentData())
        self.preferences.setValue("review/preset", preset)
        values = REVIEW_PRESETS.get(preset)
        if values is None:
            return
        similarity, time_window, color_weight = values
        self._applying_preset = True
        self.similarity_slider.setValue(similarity)
        self.time_window.setValue(time_window)
        self.color_weight_slider.setValue(color_weight)
        self._applying_preset = False
        self.preferences_changed.emit()

    def _mark_custom_preset(self) -> None:
        if self._applying_preset or not hasattr(self, "preset_combo"):
            return
        custom_index = self.preset_combo.findData("custom")
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(custom_index)
        self.preset_combo.blockSignals(False)
        self.preferences.setValue("review/preset", "custom")
        self.preferences_changed.emit()

    def _color_weight_changed(self, value: int) -> None:
        self.color_weight_value.setText(f"{value}%")
        self.preferences.setValue("algorithm/color_weight", value)
        self._mark_custom_preset()

    def _quality_weight_changed(self, key: str, label: QLabel, value: int) -> None:
        label.setText(str(value))
        self.preferences.setValue(f"algorithm/{key}_weight", value)
        self.preferences_changed.emit()

    def _hash_method_changed(self) -> None:
        self.preferences.setValue(
            "algorithm/hash_method",
            self.hash_method_combo.currentData(),
        )
        self.preferences_changed.emit()

    def _exact_duplicates_changed(self, checked: bool) -> None:
        self.preferences.setValue("algorithm/exact_duplicates", checked)
        self.preferences_changed.emit()

    def _destination_mode_changed(self) -> None:
        self.preferences.setValue(
            "folders/destination_mode",
            self.destination_mode.currentData(),
        )
        self._sync_destination_controls()
        self.preferences_changed.emit()

    def _sync_destination_controls(self) -> None:
        is_custom = self.destination_mode.currentData() == "custom"
        self.custom_destination_divider.setVisible(is_custom)
        self.destination_path.setVisible(is_custom)
        self.choose_destination.setVisible(is_custom)

    def _choose_custom_destination(self) -> None:
        current = str(self.preferences.value("folders/custom_destination", ""))
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择保留照片的默认文件夹",
            current or str(Path.home()),
        )
        if selected:
            self.preferences.setValue("folders/custom_destination", selected)
            self.destination_path.setText(selected)
            self.preferences_changed.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("拾影 · 照片筛选")
        self.resize(1280, 820)
        self.setMinimumSize(920, 640)
        self.setAcceptDrops(True)

        self.preferences = QSettings()
        self.source_folder: Optional[Path] = None
        self.destination_folder: Optional[Path] = None
        self.similarity_threshold = 84
        self.time_window_seconds = 90
        self.analysis_options = AnalysisOptions()
        self.destination_mode = "source"
        self._load_preferences()
        state_location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        state_root = Path(state_location or Path.home() / ".photo-fit-picker")
        self.session_store = ReviewSessionStore(state_root / "review-sessions")
        self.latest_session: Optional[ReviewSessionSummary] = (
            self.session_store.latest()
        )
        self.groups: list[PhotoGroup] = []
        self.visible_groups: list[PhotoGroup] = []
        self.cards: list[PhotoCard] = []
        self._grid_columns = 0
        self._settings_return_index = 0
        self.analysis_thread: Optional[QThread] = None
        self.analysis_worker: Optional[AnalysisWorker] = None

        self._build_ui()
        self.session_save_timer = QTimer(self)
        self.session_save_timer.setSingleShot(True)
        self.session_save_timer.setInterval(350)
        self.session_save_timer.timeout.connect(self._save_session_now)
        self.grid_resize_timer = QTimer(self)
        self.grid_resize_timer.setSingleShot(True)
        self.grid_resize_timer.setInterval(45)
        self.grid_resize_timer.timeout.connect(self._reflow_cards)
        self._build_shortcuts()
        self._show_empty_state()

    def _build_ui(self) -> None:
        self.root_stack = QStackedWidget()
        self.root_stack.setObjectName("rootStack")

        self.workspace = QWidget()
        self.workspace.setObjectName("appRoot")
        root_layout = QVBoxLayout(self.workspace)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.undo_button = FeedbackToolButton()
        self.undo_button.setObjectName("toolbarIconButton")
        self.undo_button.setIcon(_icon("undo-variant"))
        self.undo_button.setIconSize(QSize(19, 19))
        self.undo_button.setToolTip("撤销上一次移动")
        self.undo_button.clicked.connect(self._undo_move)

        self.organize_button = FeedbackButton("整理")
        self.organize_button.setObjectName("sidebarUtilityButton")
        self.organize_button.setIcon(_icon("folder-marker-outline"))
        self.organize_button.setToolTip("预览智能整理建议")
        self.organize_button.clicked.connect(self._open_organization)

        self.move_button = FeedbackButton("移动保留项")
        self.move_button.setIcon(_icon("export-variant", "#ffffff"))
        self.move_button.setIconSize(QSize(18, 18))
        self.move_button.setObjectName("primaryButton")
        self.move_button.clicked.connect(self._move_kept)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.sidebar = self._build_sidebar()
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self._build_content())
        self.main_splitter.setSizes([232, 1048])
        root_layout.addWidget(self.main_splitter, 1)

        self.root_stack.addWidget(self.workspace)
        self.settings_view = SettingsView(self.source_folder, self)
        self.settings_view.back_requested.connect(self._close_settings)
        self.settings_view.source_requested.connect(self._choose_source_from_settings)
        self.settings_view.reanalyze_requested.connect(self._reanalyze_from_settings)
        self.settings_view.preferences_changed.connect(self._settings_changed)
        self.root_stack.addWidget(self.settings_view)
        self.organization_view = OrganizationView(self)
        self.organization_view.back_requested.connect(self._close_organization)
        self.organization_view.apply_requested.connect(self._confirm_organization)
        self.root_stack.addWidget(self.organization_view)
        self.setCentralWidget(self.root_stack)
        status = QStatusBar()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.hide()
        status.addPermanentWidget(self.progress)
        self.cancel_analysis_button = FeedbackToolButton()
        self.cancel_analysis_button.setObjectName("analysisCancelButton")
        self.cancel_analysis_button.setIcon(_icon("close"))
        self.cancel_analysis_button.setIconSize(QSize(15, 15))
        self.cancel_analysis_button.setToolTip("取消当前分析")
        self.cancel_analysis_button.setAccessibleName("取消当前分析")
        self.cancel_analysis_button.clicked.connect(self._cancel_analysis)
        self.cancel_analysis_button.hide()
        status.addPermanentWidget(self.cancel_analysis_button)
        self.setStatusBar(status)

    def _load_preferences(self) -> None:
        self.similarity_threshold = max(
            70,
            min(95, int(self.preferences.value("review/similarity", 84))),
        )
        self.time_window_seconds = max(
            5,
            min(600, int(self.preferences.value("review/time_window", 90))),
        )
        self.analysis_options = AnalysisOptions(
            similarity_threshold=self.similarity_threshold / 100.0,
            time_window_seconds=self.time_window_seconds,
            color_weight=max(
                0.0,
                min(0.5, int(self.preferences.value("algorithm/color_weight", 22)) / 100.0),
            ),
            hash_method=str(self.preferences.value("algorithm/hash_method", "difference")),
            detect_exact_duplicates=_setting_bool(
                self.preferences, "algorithm/exact_duplicates", True
            ),
            sharpness_weight=max(
                0.0, int(self.preferences.value("algorithm/sharpness_weight", 75)) / 100.0
            ),
            exposure_weight=max(
                0.0, int(self.preferences.value("algorithm/exposure_weight", 25)) / 100.0
            ),
            resolution_weight=max(
                0.0, int(self.preferences.value("algorithm/resolution_weight", 0)) / 100.0
            ),
        )
        self.destination_mode = str(
            self.preferences.value("folders/destination_mode", "source")
        )
        custom_destination = str(
            self.preferences.value("folders/custom_destination", "")
        )
        if self.destination_mode == "custom":
            self.destination_folder = (
                Path(custom_destination) if custom_destination else None
            )
        elif self.source_folder:
            self.destination_folder = self.source_folder / "已筛选"
        else:
            self.destination_folder = None

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(224)
        sidebar.setMaximumWidth(252)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(8)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(6, 0, 6, 14)
        brand_layout.setSpacing(9)
        mark = QLabel()
        mark.setObjectName("appMark")
        mark.setPixmap(_icon("camera-iris", ICON_ACCENT).pixmap(20, 20))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(32, 32)
        brand_layout.addWidget(mark)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("拾影")
        title.setObjectName("appTitle")
        self.source_label = QLabel("本地照片筛选")
        self.source_label.setObjectName("sourceLabel")
        self.source_label.setMaximumWidth(148)
        title_box.addWidget(title)
        title_box.addWidget(self.source_label)
        brand_layout.addLayout(title_box, 1)
        layout.addWidget(brand)

        self.folder_button = FeedbackButton("照片文件夹")
        self.folder_button.setObjectName("sidebarButton")
        self.folder_button.setIcon(_icon("folder-open-outline"))
        self.folder_button.setIconSize(QSize(18, 18))
        self.folder_button.clicked.connect(self._choose_source)
        layout.addWidget(self.folder_button)

        self.sidebar_review_panel = QWidget()
        review_layout = QVBoxLayout(self.sidebar_review_panel)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(10)

        progress_header = QHBoxLayout()
        progress_title = QLabel("审片进度")
        progress_title.setObjectName("sectionTitle")
        progress_header.addWidget(progress_title)
        progress_header.addStretch()
        self.progress_count = QLabel("0 / 0")
        self.progress_count.setObjectName("progressCount")
        progress_header.addWidget(self.progress_count)
        review_layout.addLayout(progress_header)

        self.review_progress = QProgressBar()
        self.review_progress.setObjectName("reviewProgress")
        self.review_progress.setTextVisible(False)
        self.review_progress.setRange(0, 1)
        self.review_progress.setValue(0)
        review_layout.addWidget(self.review_progress)

        filter_title = QLabel("照片组")
        filter_title.setObjectName("sectionTitle")
        review_layout.addWidget(filter_title)
        self.group_filter = QComboBox()
        self.group_filter.addItem("全部照片组", "all")
        self.group_filter.addItem("只看待审核", "pending")
        self.group_filter.addItem("已有保留", "kept")
        self.group_filter.addItem("相似组", "similar")
        self.group_filter.currentIndexChanged.connect(self._apply_group_filter)
        review_layout.addWidget(self.group_filter)

        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self._show_group_at_row)
        review_layout.addWidget(self.group_list, 1)

        self.summary_label = QLabel("尚未分析照片")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)
        review_layout.addWidget(self.summary_label)
        layout.addWidget(self.sidebar_review_panel, 100)
        layout.addStretch(1)

        layout.addWidget(self.organize_button)

        self.settings_button = FeedbackButton("设置")
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setIcon(_icon("cog-outline", ICON_MUTED))
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setCheckable(True)
        self.settings_button.clicked.connect(self._open_settings)
        layout.addWidget(self.settings_button)
        return sidebar

    def _build_content(self) -> QWidget:
        self.content_stack = QStackedWidget()

        empty = QWidget()
        empty.setObjectName("emptyState")
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(9)
        icon = QLabel()
        icon.setObjectName("emptyIcon")
        icon.setPixmap(_icon("image-multiple-outline", "#71767d").pixmap(66, 66))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon)
        empty_title = QLabel("选一批照片，开始筛选")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_hint = QLabel("拖入文件夹，或从电脑中选择")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint)
        self.resume_button = FeedbackButton("继续上次筛选")
        self.resume_button.setObjectName("emptyPrimaryButton")
        self.resume_button.setIcon(_icon("history", "#ffffff"))
        self.resume_button.setIconSize(QSize(19, 19))
        self.resume_button.clicked.connect(self._resume_last_session)
        self.resume_detail = QLabel()
        self.resume_detail.setObjectName("resumeDetail")
        self.resume_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(
            self.resume_detail,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.empty_choose_button = FeedbackButton("选择其他照片文件夹")
        self.empty_choose_button.setObjectName("emptySecondaryButton")
        self.empty_choose_button.setIcon(_icon("folder-open-outline"))
        self.empty_choose_button.setIconSize(QSize(19, 19))
        self.empty_choose_button.clicked.connect(self._choose_source)
        self.demo_button = FeedbackButton("试用演示照片")
        self.demo_button.setObjectName("quietButton")
        self.demo_button.setIcon(_icon("image-outline", ICON_MUTED))
        self.demo_button.clicked.connect(self._load_demo_photos)
        self.demo_button.setVisible(_bundled_demo_folder() is not None)
        empty_actions = QHBoxLayout()
        empty_actions.setSpacing(8)
        empty_actions.addWidget(self.resume_button)
        empty_actions.addWidget(self.empty_choose_button)
        empty_layout.addLayout(empty_actions)
        empty_layout.addSpacing(2)
        empty_layout.addWidget(self.demo_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.content_stack.addWidget(empty)

        review = QWidget()
        review.setObjectName("reviewWorkspace")
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(22, 18, 22, 16)
        review_layout.setSpacing(16)
        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("reviewToolbar")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        group_text = QVBoxLayout()
        group_text.setSpacing(2)
        self.group_title = QLabel("照片组")
        self.group_title.setObjectName("groupTitle")
        self.group_meta = QLabel("")
        self.group_meta.setObjectName("groupMeta")
        group_text.addWidget(self.group_title)
        group_text.addWidget(self.group_meta)
        toolbar.addLayout(group_text)
        toolbar.addStretch()

        self.previous_group_button = FeedbackToolButton()
        self.previous_group_button.setObjectName("toolbarIconButton")
        self.previous_group_button.setIcon(_icon("chevron-left"))
        self.previous_group_button.setIconSize(QSize(20, 20))
        self.previous_group_button.setToolTip("上一组")
        self.previous_group_button.clicked.connect(self._show_previous_group)
        toolbar.addWidget(self.previous_group_button)

        self.next_group_button = FeedbackToolButton()
        self.next_group_button.setObjectName("toolbarIconButton")
        self.next_group_button.setIcon(_icon("chevron-right"))
        self.next_group_button.setIconSize(QSize(20, 20))
        self.next_group_button.setToolTip("下一组")
        self.next_group_button.clicked.connect(self._show_next_group)
        toolbar.addWidget(self.next_group_button)

        select_group = FeedbackToolButton()
        select_group.setObjectName("toolbarIconButton")
        select_group.setIcon(_icon("selection-multiple"))
        select_group.setIconSize(QSize(19, 19))
        select_group.setToolTip("选择本组")
        select_group.setAccessibleName("选择本组")
        select_group.clicked.connect(self._select_current_group)
        toolbar.addWidget(select_group)

        group_menu = QMenu(self)
        keep_all_action = group_menu.addAction("保留整组")
        keep_all_action.triggered.connect(
            lambda: self._set_current_group(ReviewStatus.KEPT)
        )
        reject_all_action = group_menu.addAction("排除整组")
        reject_all_action.triggered.connect(
            lambda: self._set_current_group(ReviewStatus.REJECTED)
        )
        group_menu.addSeparator()
        reset_group_action = group_menu.addAction("重置为待审核")
        reset_group_action.triggered.connect(
            lambda: self._set_current_group(ReviewStatus.PENDING)
        )
        self.group_more_button = FeedbackToolButton()
        self.group_more_button.setObjectName("toolbarIconButton")
        self.group_more_button.setIcon(_icon("dots-horizontal"))
        self.group_more_button.setIconSize(QSize(20, 20))
        self.group_more_button.setToolTip("更多本组操作")
        self.group_more_button.setMenu(group_menu)
        self.group_more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(self.group_more_button)

        toolbar.addWidget(self.undo_button)

        self.recommend_button = FeedbackButton("保留最佳并继续")
        self.recommend_button.setIcon(_icon("check-bold", "#ffffff"))
        self.recommend_button.setIconSize(QSize(18, 18))
        self.recommend_button.setObjectName("primaryButton")
        self.recommend_button.clicked.connect(self._keep_recommended_and_advance)
        toolbar.addWidget(self.recommend_button)
        toolbar.addWidget(self.move_button)
        review_layout.addWidget(toolbar_frame)

        self.photo_scroll = QScrollArea()
        self.photo_scroll.setWidgetResizable(True)
        self.photo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.photo_grid_host = QWidget()
        self.photo_grid_host.setObjectName("photo_grid_host")
        self.photo_grid = QGridLayout(self.photo_grid_host)
        self.photo_grid.setContentsMargins(0, 0, 0, 0)
        self.photo_grid.setSpacing(16)
        self.photo_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.photo_scroll.setWidget(self.photo_grid_host)
        review_layout.addWidget(self.photo_scroll, 1)
        self.batch_bar = QFrame()
        self.batch_bar.setObjectName("batchBar")
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(12, 8, 12, 8)
        batch_layout.setSpacing(8)
        self.batch_count = QLabel("已选择 0 张")
        self.batch_count.setObjectName("batchCount")
        batch_layout.addWidget(self.batch_count)
        batch_layout.addStretch()
        clear_selection = FeedbackToolButton()
        clear_selection.setObjectName("batchIconButton")
        clear_selection.setIcon(_icon("close"))
        clear_selection.setIconSize(QSize(18, 18))
        clear_selection.setToolTip("清除选择")
        clear_selection.setAccessibleName("清除选择")
        clear_selection.clicked.connect(self._clear_selection)
        batch_layout.addWidget(clear_selection)
        batch_reject = FeedbackButton("标为排除")
        batch_reject.setIcon(_icon("close", ICON_DANGER))
        batch_reject.clicked.connect(
            lambda: self._set_selected_status(ReviewStatus.REJECTED)
        )
        batch_layout.addWidget(batch_reject)
        batch_keep = FeedbackButton("标为保留")
        batch_keep.setIcon(_icon("check", ICON_ACCENT))
        batch_keep.clicked.connect(lambda: self._set_selected_status(ReviewStatus.KEPT))
        batch_layout.addWidget(batch_keep)
        batch_trash = FeedbackToolButton()
        batch_trash.setObjectName("trashButton")
        batch_trash.setIcon(_icon("trash-can-outline", ICON_DANGER))
        batch_trash.setIconSize(QSize(18, 18))
        batch_trash.setToolTip("将所选照片移到系统回收站")
        batch_trash.clicked.connect(self._confirm_trash_selected)
        batch_layout.addWidget(batch_trash)
        batch_move = FeedbackButton("移动所选")
        batch_move.setObjectName("primaryButton")
        batch_move.setIcon(_icon("export-variant", "#ffffff"))
        batch_move.clicked.connect(self._move_explicit_selection)
        batch_layout.addWidget(batch_move)
        review_layout.addWidget(self.batch_bar)
        self.batch_bar.hide()
        self.content_stack.addWidget(review)

        analysis = QWidget()
        analysis.setObjectName("analysisView")
        analysis_layout = QVBoxLayout(analysis)
        analysis_layout.setContentsMargins(48, 48, 48, 48)
        analysis_layout.addStretch()
        self.analysis_panel = QFrame()
        self.analysis_panel.setObjectName("analysisPanel")
        self.analysis_panel.setMaximumWidth(560)
        panel_layout = QVBoxLayout(self.analysis_panel)
        panel_layout.setContentsMargins(28, 26, 28, 24)
        panel_layout.setSpacing(10)
        analysis_icon = QLabel()
        analysis_icon.setObjectName("analysisIcon")
        analysis_icon.setPixmap(_icon("image-search-outline", ICON_ACCENT).pixmap(32, 32))
        panel_layout.addWidget(analysis_icon)
        self.analysis_title = QLabel("正在分析照片")
        self.analysis_title.setObjectName("analysisTitle")
        panel_layout.addWidget(self.analysis_title)
        self.analysis_detail = QLabel("正在准备照片列表…")
        self.analysis_detail.setObjectName("analysisDetail")
        self.analysis_detail.setWordWrap(True)
        panel_layout.addWidget(self.analysis_detail)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setObjectName("analysisProgress")
        self.analysis_progress.setTextVisible(False)
        progress_row.addWidget(self.analysis_progress, 1)
        self.analysis_count = QLabel("0 / 0")
        self.analysis_count.setObjectName("analysisCount")
        progress_row.addWidget(self.analysis_count)
        panel_layout.addLayout(progress_row)
        self.analysis_cancel_button = FeedbackButton("取消分析")
        self.analysis_cancel_button.setObjectName("analysisPanelCancel")
        self.analysis_cancel_button.setIcon(_icon("close"))
        self.analysis_cancel_button.clicked.connect(self._cancel_analysis)
        panel_layout.addWidget(
            self.analysis_cancel_button,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        analysis_layout.addWidget(
            self.analysis_panel,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        analysis_layout.addStretch()
        self.content_stack.addWidget(analysis)

        return self.content_stack

    def _build_shortcuts(self) -> None:
        open_action = QAction(self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._choose_source)
        self.addAction(open_action)
        select_all_action = QAction(self)
        select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_action.triggered.connect(self._select_current_group)
        self.addAction(select_all_action)
        clear_action = QAction(self)
        clear_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        clear_action.triggered.connect(self._handle_escape)
        self.addAction(clear_action)

    def _show_empty_state(self) -> None:
        self.sidebar.show()
        self.folder_button.hide()
        self.sidebar_review_panel.hide()
        self.undo_button.hide()
        self.organize_button.hide()
        self.move_button.hide()
        self.settings_button.setChecked(False)
        self.content_stack.setCurrentIndex(0)
        self.move_button.setText("移动保留项")
        self.move_button.setEnabled(False)
        self.undo_button.setEnabled(False)
        self._refresh_resume_ui()

    def _refresh_resume_ui(self) -> None:
        self.latest_session = self.session_store.latest()
        has_session = self.latest_session is not None
        self.resume_button.setVisible(has_session)
        self.resume_detail.setVisible(has_session)
        if self.latest_session:
            summary = self.latest_session
            self.resume_detail.setText(
                f"{summary.source.name}  ·  "
                f"已审核 {summary.reviewed_count} / {summary.total_count}"
            )
            self.resume_detail.setToolTip(str(summary.source))
        self.empty_choose_button.setText(
            "选择其他照片文件夹" if has_session else "选择照片文件夹"
        )
        self.empty_choose_button.setObjectName(
            "emptySecondaryButton" if has_session else "emptyPrimaryButton"
        )
        self.empty_choose_button.setIcon(
            _icon(
                "folder-open-outline",
                ICON_MUTED if has_session else "#ffffff",
            )
        )
        self.empty_choose_button.style().unpolish(self.empty_choose_button)
        self.empty_choose_button.style().polish(self.empty_choose_button)

    def _resume_last_session(self) -> None:
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        summary = self.session_store.latest()
        if not summary:
            self._refresh_resume_ui()
            return
        self._set_source(summary.source)
        self._start_analysis()

    def _schedule_session_save(self) -> None:
        if self.source_folder and self.groups:
            self.session_save_timer.start()

    def _save_session_now(self) -> None:
        if not self.source_folder or not self.groups:
            return
        try:
            self.latest_session = self.session_store.save(
                self.source_folder,
                self._all_photos(),
            )
        except OSError as exc:
            self.statusBar().showMessage(f"无法保存筛选进度：{exc}", 8000)

    def _set_analysis_busy(self, busy: bool) -> None:
        self.folder_button.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.sidebar_review_panel.setEnabled(not busy)
        self.organize_button.setEnabled(not busy and bool(self.groups))
        self.settings_view.set_analysis_available(
            self.source_folder is not None,
            busy,
        )
        self.progress.setVisible(busy)
        self.cancel_analysis_button.setVisible(busy)
        self.cancel_analysis_button.setEnabled(busy)
        self.analysis_cancel_button.setEnabled(busy)
        if busy:
            self.content_stack.setCurrentIndex(2)
        else:
            self.content_stack.setCurrentIndex(1 if self.groups else 0)
        if not busy:
            self._update_summary()

    def _cancel_analysis(self) -> None:
        if not self.analysis_worker:
            return
        self.analysis_worker.cancel()
        self.cancel_analysis_button.setEnabled(False)
        self.analysis_cancel_button.setEnabled(False)
        self.analysis_detail.setText("正在安全停止分析…")
        self.statusBar().showMessage("正在取消分析…")

    def _open_settings(self) -> None:
        if self.root_stack.currentWidget() is self.settings_view:
            self.settings_button.setChecked(True)
            return
        self._settings_return_index = 1 if self.groups else 0
        self.settings_view.set_source_folder(self.source_folder)
        self.settings_view.refresh_preferences()
        self.settings_view.set_analysis_available(
            self.source_folder is not None,
            self.analysis_thread is not None and self.analysis_thread.isRunning(),
        )
        self.settings_button.setChecked(True)
        self.statusBar().hide()
        self.root_stack.setCurrentWidget(self.settings_view)

    def _open_organization(self) -> None:
        if (
            not self.groups
            or (self.analysis_thread and self.analysis_thread.isRunning())
        ):
            return
        gap_minutes = int(self.preferences.value("organize/gap_minutes", 180))
        gps_radius = float(self.preferences.value("organize/gps_radius_km", 2))
        plan = build_organization_plan(
            self._all_photos(),
            gap_minutes=gap_minutes,
            gps_radius_km=gps_radius,
        )
        self.organization_view.set_plan(plan)
        self.statusBar().hide()
        self.root_stack.setCurrentWidget(self.organization_view)

    def _close_organization(self) -> None:
        self.root_stack.setCurrentWidget(self.workspace)
        self.statusBar().show()
        self._apply_group_filter()

    def _confirm_organization(self, plan: OrganizationPlan) -> None:
        if not plan.groups:
            return
        if not self.destination_folder:
            self._choose_destination()
            if not self.destination_folder:
                return
        planned = plan_organization_moves(plan, self.destination_folder)
        if not planned:
            QMessageBox.information(self, "没有可移动文件", "整理计划中的照片已不存在。")
            return
        photo_count = sum(len(group.photos) for group in plan.groups)
        photo_size = format_file_size(
            sum(photo.file_size for group in plan.groups for photo in group.photos)
        )
        linked_count = max(0, len(planned) - photo_count)
        linked_text = f"，另含 {linked_count} 个关联文件" if linked_count else ""
        answer = QMessageBox.question(
            self,
            "确认执行整理",
            f"将 {photo_count} 张照片（约 {photo_size}）{linked_text}整理到：\n"
            f"{self.destination_folder}\n\n"
            f"将创建 {len(plan.groups)} 个建议文件夹。不会删除或覆盖任何文件，"
            "完成后可使用撤销按钮恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = execute_organization_plan(plan, self.destination_folder)
        except OSError as exc:
            QMessageBox.critical(self, "整理未完成", str(exc))
            return
        self._close_organization()
        self.statusBar().showMessage(
            f"已整理 {photo_count} 张照片，共移动 {len(moved)} 个文件",
            10000,
        )
        self._refresh_group_labels()
        self._update_summary()
        self._schedule_session_save()

    def _close_settings(self) -> None:
        self._load_preferences()
        self._update_destination_ui()
        self.settings_button.setChecked(False)
        self.root_stack.setCurrentWidget(self.workspace)
        self.statusBar().show()
        if self.groups and self._settings_return_index == 1:
            self._apply_group_filter()
        else:
            self._show_empty_state()

    def _settings_changed(self) -> None:
        self._load_preferences()
        self._update_destination_ui()

    def _choose_source_from_settings(self) -> None:
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        selected = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if not selected:
            return
        self._close_settings()
        self._set_source(Path(selected))
        self._start_analysis()

    def _reanalyze_from_settings(self) -> None:
        if not self.source_folder:
            return
        self._close_settings()
        self._start_analysis()

    def _handle_escape(self) -> None:
        if self.root_stack.currentWidget() is self.settings_view:
            self._close_settings()
        elif self.root_stack.currentWidget() is self.organization_view:
            self._close_organization()
        else:
            self._clear_selection()

    def _update_destination_ui(self) -> None:
        if self.destination_folder:
            self.move_button.setToolTip(
                f"将保留照片移动到：{self.destination_folder}"
            )
            self.settings_button.setToolTip(
                f"设置 · 当前目标：{self.destination_folder}"
            )
        else:
            self.move_button.setToolTip("移动前选择保留照片的目标文件夹")
            self.settings_button.setToolTip("设置")

    def _choose_source(self) -> None:
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        selected = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if selected:
            self._set_source(Path(selected))
            self._start_analysis()

    def _load_demo_photos(self) -> None:
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        try:
            folder = _prepare_demo_folder()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "演示照片不可用",
                f"无法准备演示照片：{exc}",
            )
            return
        self._set_source(folder)
        self._start_analysis()

    def _set_source(self, folder: Path) -> None:
        folder = folder.resolve()
        source_changed = bool(
            self.source_folder and self.source_folder.resolve() != folder
        )
        if source_changed:
            self._save_session_now()
            self.groups.clear()
            self.visible_groups.clear()
            self.group_list.clear()
            self._clear_grid()
            self._show_empty_state()
        self.source_folder = folder
        self.settings_view.set_source_folder(folder)
        self.source_label.setText(folder.name)
        self.source_label.setToolTip(str(folder))
        self.folder_button.setText(
            self.folder_button.fontMetrics().elidedText(
                folder.name,
                Qt.TextElideMode.ElideMiddle,
                150,
            )
        )
        self.folder_button.setToolTip(str(folder))
        self.folder_button.show()
        if self.destination_mode == "source":
            self.destination_folder = folder / "已筛选"
        self._update_destination_ui()
        self.statusBar().showMessage("已选择照片文件夹，正在准备分析", 5000)

    def _choose_destination(self) -> None:
        start = str(self.destination_folder or self.source_folder or Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择已筛选照片保存位置",
            start,
        )
        if selected:
            self.destination_folder = Path(selected)
            self.destination_mode = "custom"
            self.preferences.setValue("folders/destination_mode", "custom")
            self.preferences.setValue("folders/custom_destination", selected)
            self._update_destination_ui()
            self.undo_button.setEnabled(True)
            self.statusBar().showMessage(f"已筛选照片将移动到：{selected}", 5000)

    def _start_analysis(self) -> None:
        if not self.source_folder:
            return
        if self.analysis_thread and self.analysis_thread.isRunning():
            self.statusBar().showMessage("已有照片分析正在进行", 4000)
            return
        try:
            paths = discover_images(self.source_folder)
        except OSError as exc:
            QMessageBox.critical(self, "无法读取照片文件夹", str(exc))
            return
        if self.destination_folder:
            destination = self.destination_folder.resolve()
            paths = [path for path in paths if destination not in path.resolve().parents]
        if not paths:
            QMessageBox.information(
                self,
                "没有照片",
                "该文件夹中没有找到支持的照片。",
            )
            return

        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.show()
        self.analysis_progress.setRange(0, len(paths))
        self.analysis_progress.setValue(0)
        self.analysis_count.setText(f"0 / {len(paths)}")
        self.analysis_detail.setText(
            f"正在准备 {len(paths)} 张照片，本过程只读取文件，不会移动或删除照片。"
        )
        self.statusBar().showMessage(f"准备分析 {len(paths)} 张照片…")

        thread = QThread(self)
        worker = AnalysisWorker(
            paths,
            self.analysis_options,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._analysis_progress)
        worker.finished.connect(self._analysis_finished)
        worker.failed.connect(self._analysis_failed)
        worker.cancelled.connect(self._analysis_cancelled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._analysis_thread_finished)
        self.analysis_thread = thread
        self.analysis_worker = worker
        self._set_analysis_busy(True)
        thread.start()

    def _analysis_progress(self, current: int, total: int, filename: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.analysis_progress.setMaximum(total)
        self.analysis_progress.setValue(current)
        self.analysis_count.setText(f"{current} / {total}")
        self.analysis_detail.setText(filename)
        self.statusBar().showMessage(f"正在分析 {current}/{total}：{filename}")

    def _analysis_finished(
        self,
        groups: list[PhotoGroup],
        failures: list[tuple[Path, str]],
    ) -> None:
        restored = 0
        if self.source_folder:
            restored = self.session_store.restore(
                self.source_folder,
                [photo for group in groups for photo in group.photos],
            )
        self.groups = groups
        self._apply_group_filter()
        photo_count = sum(len(group.photos) for group in groups)
        similar_count = sum(len(group.photos) > 1 for group in groups)
        restored_text = f"，恢复 {restored} 项审核决定" if restored else ""
        self.statusBar().showMessage(
            f"分析完成：{photo_count} 张照片，{similar_count} 个相似组{restored_text}",
            8000,
        )
        self._save_session_now()
        if failures:
            details = "\n".join(
                f"{path.name}：{message.splitlines()[0]}"
                for path, message in failures[:6]
            )
            if len(failures) > 6:
                details += f"\n另有 {len(failures) - 6} 个文件…"
            QMessageBox.warning(
                self,
                "部分照片未能读取",
                f"有 {len(failures)} 个文件未能读取，"
                "其他照片已正常完成分析。\n\n"
                f"{details}",
            )

    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(self, "分析失败", message)
        self.statusBar().showMessage("分析失败", 5000)

    def _analysis_cancelled(self) -> None:
        self.statusBar().showMessage("分析已取消", 5000)

    def _analysis_thread_finished(self) -> None:
        self.analysis_thread = None
        self.analysis_worker = None
        self._set_analysis_busy(False)

    def _apply_group_filter(self) -> None:
        settings_open = self.root_stack.currentWidget() is self.settings_view
        mode = self.group_filter.currentData()
        if mode == "pending":
            self.visible_groups = [group for group in self.groups if not group.reviewed]
        elif mode == "kept":
            self.visible_groups = [group for group in self.groups if group.kept_count]
        elif mode == "similar":
            self.visible_groups = [group for group in self.groups if len(group.photos) > 1]
        else:
            self.visible_groups = list(self.groups)

        self.group_list.blockSignals(True)
        self.group_list.clear()
        for group in self.visible_groups:
            item = QListWidgetItem(self._group_label(group))
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            self.group_list.addItem(item)
        self.group_list.blockSignals(False)

        if self.visible_groups:
            self.sidebar.show()
            self.group_list.setCurrentRow(0)
            if not settings_open:
                self.folder_button.show()
                self.sidebar_review_panel.show()
                self.undo_button.show()
                self.organize_button.show()
                self.move_button.show()
                self.content_stack.setCurrentIndex(1)
                QTimer.singleShot(0, self._reflow_cards)
        elif self.groups:
            self.sidebar.show()
            self._clear_grid()
            self.group_title.setText("当前筛选条件下没有照片组")
            self.group_meta.setText("")
            self._update_group_navigation()
            if not settings_open:
                self.folder_button.show()
                self.sidebar_review_panel.show()
                self.undo_button.show()
                self.organize_button.show()
                self.move_button.show()
                self.content_stack.setCurrentIndex(1)
                QTimer.singleShot(0, self._reflow_cards)
        else:
            if not settings_open:
                self._show_empty_state()
        self._update_summary()

    def _group_label(self, group: PhotoGroup) -> str:
        marker = "✓   " if group.reviewed else ""
        kept = f"  ·  保留 {group.kept_count}" if group.kept_count else ""
        return f"{marker}{group.id:02d}   {len(group.photos)} 张{kept}"

    def _show_group_at_row(self, row: int) -> None:
        if row < 0 or row >= len(self.visible_groups):
            return
        group = self.visible_groups[row]
        self._clear_grid()
        self.group_title.setText(f"照片组 {group.id:02d}")
        self.group_meta.setText(
            f"{row + 1} / {len(self.visible_groups)}  ·  {len(group.photos)} 张"
        )
        recommended = group.recommended
        columns = max(1, self.photo_scroll.viewport().width() // 280)
        self._grid_columns = columns
        for index, photo in enumerate(group.photos):
            card = PhotoCard(photo, photo is recommended)
            card.status_changed.connect(self._review_changed)
            card.selection_changed.connect(self._selection_changed)
            card.open_requested.connect(self._open_viewer)
            self.cards.append(card)
            self.photo_grid.addWidget(card, index // columns, index % columns)
            card.animate_in(min(index, 8) * 28)
        self._update_group_navigation()

    def _update_group_navigation(self) -> None:
        row = self.group_list.currentRow()
        count = len(self.visible_groups)
        has_group = 0 <= row < count
        self.previous_group_button.setEnabled(has_group and row > 0)
        self.next_group_button.setEnabled(has_group and row < count - 1)
        self.group_more_button.setEnabled(has_group)
        self.recommend_button.setEnabled(
            has_group and self.visible_groups[row].recommended is not None
        )

    def _show_previous_group(self) -> None:
        row = self.group_list.currentRow()
        if row > 0:
            self.group_list.setCurrentRow(row - 1)

    def _show_next_group(self) -> None:
        row = self.group_list.currentRow()
        if 0 <= row < len(self.visible_groups) - 1:
            self.group_list.setCurrentRow(row + 1)

    def _reflow_cards(self) -> None:
        if not self.cards:
            return
        columns = max(1, self.photo_scroll.viewport().width() // 280)
        if columns == self._grid_columns:
            return
        self._grid_columns = columns
        for index, card in enumerate(self.cards):
            self.photo_grid.removeWidget(card)
            self.photo_grid.addWidget(card, index // columns, index % columns)

    def _clear_grid(self) -> None:
        while self.photo_grid.count():
            item = self.photo_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.cards.clear()

    def _current_group(self) -> Optional[PhotoGroup]:
        row = self.group_list.currentRow()
        if 0 <= row < len(self.visible_groups):
            return self.visible_groups[row]
        return None

    def _set_current_group(self, status: ReviewStatus) -> None:
        group = self._current_group()
        if not group:
            return
        for photo in group.photos:
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
                photo.status = status
        for card in self.cards:
            card.sync_status()
        self._review_changed()

    def _all_photos(self) -> list[PhotoRecord]:
        return [photo for group in self.groups for photo in group.photos]

    def _selected_photos(self) -> list[PhotoRecord]:
        return [photo for photo in self._all_photos() if photo.selected]

    def _selection_changed(self) -> None:
        selected = self._selected_photos()
        self.batch_count.setText(f"已选择 {len(selected)} 张")
        self.batch_bar.setVisible(bool(selected))

    def _select_current_group(self) -> None:
        group = self._current_group()
        if not group:
            return
        for photo in group.photos:
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
                photo.selected = True
        for card in self.cards:
            card.sync_status()
        self._selection_changed()

    def _clear_selection(self) -> None:
        for photo in self._all_photos():
            photo.selected = False
        for card in self.cards:
            card.sync_status()
        self._selection_changed()

    def _set_selected_status(self, status: ReviewStatus) -> None:
        selected = self._selected_photos()
        for photo in selected:
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
                photo.status = status
        for card in self.cards:
            card.sync_status()
        self._refresh_group_labels()
        self._update_summary()
        self._schedule_session_save()

    def _open_viewer(self, photo: PhotoRecord) -> None:
        group = self._current_group()
        if not group:
            return
        viewer = PhotoViewer(group, group.photos.index(photo), self)
        viewer.status_changed.connect(self._review_changed)
        viewer.trash_requested.connect(self._confirm_trash)
        viewer.exec()
        for card in self.cards:
            card.sync_status()

    def _keep_recommended(self) -> None:
        group = self._current_group()
        if not group or not group.recommended:
            return
        for photo in group.photos:
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
                photo.status = (
                    ReviewStatus.KEPT if photo is group.recommended else ReviewStatus.REJECTED
                )
        for card in self.cards:
            card.sync_status()
        self._review_changed()

    def _keep_recommended_and_advance(self) -> None:
        row = self.group_list.currentRow()
        if row < 0:
            return
        self._keep_recommended()
        if self.group_filter.currentData() == "pending":
            self._apply_group_filter()
            return
        if row < len(self.visible_groups) - 1:
            self.group_list.setCurrentRow(row + 1)
        else:
            self.statusBar().showMessage("已经处理到最后一组", 4000)

    def _review_changed(self) -> None:
        row = self.group_list.currentRow()
        group = self._current_group()
        if group and row >= 0:
            self.group_list.item(row).setText(self._group_label(group))
        self._update_summary()
        self._schedule_session_save()

    def _refresh_group_labels(self) -> None:
        for row, group in enumerate(self.visible_groups):
            item = self.group_list.item(row)
            if item:
                item.setText(self._group_label(group))

    def _confirm_trash(self, photo: PhotoRecord) -> None:
        confirmed = _confirm_recoverable_trash(
            self,
            "确认移到回收站",
            f"确定要将这张照片移到系统废纸篓/回收站吗？\n\n{photo.path}\n\n"
            "这不是永久删除，可从系统废纸篓/回收站恢复。",
        )
        if not confirmed:
            return
        try:
            source = move_photo_to_trash(photo)
        except OSError as exc:
            QMessageBox.critical(self, "无法移到回收站", str(exc))
            return
        self.statusBar().showMessage(f"已移到系统回收站：{source.name}", 8000)
        for card in self.cards:
            if card.photo is photo:
                card.sync_status()
        self._refresh_group_labels()
        self._update_summary()
        self._schedule_session_save()

    def _confirm_trash_selected(self) -> None:
        selected = self._selected_photos()
        if not selected:
            return
        confirmed = _confirm_recoverable_trash(
            self,
            "确认批量移到回收站",
            f"确定要将选中的 {len(selected)} 张照片移到"
            f"系统废纸篓/回收站吗？共约 "
            f"{format_file_size(sum(photo.file_size for photo in selected))}。\n\n"
            "这不是永久删除，可从系统废纸篓/回收站恢复。",
        )
        if not confirmed:
            return
        moved_count = 0
        errors: list[str] = []
        for photo in selected:
            try:
                move_photo_to_trash(photo)
                moved_count += 1
            except OSError as exc:
                errors.append(f"{photo.display_name}：{exc}")
        self.statusBar().showMessage(
            f"已将 {moved_count} 张照片移到系统回收站",
            8000,
        )
        for card in self.cards:
            card.sync_status()
        self._selection_changed()
        self._refresh_group_labels()
        self._update_summary()
        self._schedule_session_save()
        if errors:
            QMessageBox.warning(
                self,
                "部分照片未能处理",
                "\n".join(errors[:8]),
            )

    def _move_explicit_selection(self) -> None:
        selected = self._selected_photos()
        if not selected:
            return
        start = str(self.destination_folder or self.source_folder or Path.home())
        destination = QFileDialog.getExistingDirectory(
            self,
            f"将 {len(selected)} 张照片移动到…",
            start,
        )
        if not destination:
            return
        destination_path = Path(destination)
        linked_records = expand_linked_photo_records(self._all_photos(), selected)
        if any(
            photo.path.resolve().parent == destination_path.resolve()
            for photo in linked_records
        ):
            QMessageBox.warning(
                self,
                "请选择其他文件夹",
                "目标文件夹不能与所选照片当前所在的文件夹相同。",
            )
            return
        linked_count = max(0, len(linked_records) - len(selected))
        linked_text = f"（含 {linked_count} 张关联 RAW/JPEG）" if linked_count else ""
        move_size = format_file_size(sum(photo.file_size for photo in linked_records))
        answer = QMessageBox.question(
            self,
            "确认批量移动",
            f"将选中的 {len(selected)} 张照片{linked_text}（约 {move_size}）移动到：\n"
            f"{destination_path}\n\n"
            "同名 XMP sidecar 会一同移动；"
            "移动后可通过顶部撤销按钮恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = move_photos(linked_records, destination_path)
        except OSError as exc:
            QMessageBox.critical(self, "批量移动未完成", str(exc))
            for card in self.cards:
                card.sync_status()
            self._selection_changed()
            return
        self.destination_folder = destination_path
        self._update_destination_ui()
        self.statusBar().showMessage(f"已移动 {len(moved)} 个文件", 8000)
        for card in self.cards:
            card.sync_status()
        self._selection_changed()
        self._refresh_group_labels()
        self._update_summary()
        self._schedule_session_save()

    def _update_summary(self) -> None:
        photos = [photo for group in self.groups for photo in group.photos]
        kept = sum(photo.status == ReviewStatus.KEPT for photo in photos)
        reviewed = sum(photo.status != ReviewStatus.PENDING for photo in photos)
        similar = sum(len(group.photos) > 1 for group in self.groups)
        trashed = sum(photo.status == ReviewStatus.TRASHED for photo in photos)
        if photos:
            extra = f" · 回收站 {trashed}" if trashed else ""
            self.summary_label.setText(f"保留 {kept} · 相似组 {similar}{extra}")
            self.progress_count.setText(f"{reviewed} / {len(photos)}")
            self.review_progress.setRange(0, len(photos))
            self.review_progress.setValue(reviewed)
        else:
            self.summary_label.setText("尚未分析照片")
            self.progress_count.setText("0 / 0")
            self.review_progress.setRange(0, 1)
            self.review_progress.setValue(0)
        self.move_button.setText(f"移动 {kept} 张" if kept else "移动保留项")
        self.move_button.setEnabled(kept > 0)
        self.move_button.setVisible(kept > 0)
        has_history = bool(
            self.destination_folder and read_history(self.destination_folder)
        )
        self.undo_button.setEnabled(has_history)
        self.undo_button.setVisible(has_history)

    def _move_kept(self) -> None:
        photos = [photo for group in self.groups for photo in group.photos]
        kept = [photo for photo in photos if photo.status == ReviewStatus.KEPT]
        if not kept:
            return
        if not self.destination_folder:
            self._choose_destination()
            if not self.destination_folder:
                return
        linked_records = expand_linked_photo_records(photos, kept)
        if any(
            photo.path.resolve().parent == self.destination_folder.resolve()
            for photo in linked_records
        ):
            QMessageBox.warning(
                self,
                "请选择其他文件夹",
                "目标文件夹不能与保留照片当前所在的文件夹相同。",
            )
            return
        move_size = format_file_size(sum(photo.file_size for photo in linked_records))
        answer = QMessageBox.question(
            self,
            "确认移动照片",
            f"将 {len(kept)} 张照片（约 {move_size}）移动到：\n"
            f"{self.destination_folder}\n\n"
            "移动后可以使用左上角的撤销按钮恢复。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = move_selected(photos, self.destination_folder)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "移动未完成",
                f"文件移动过程中发生错误：\n{exc}",
            )
            self._update_summary()
            return
        self.statusBar().showMessage(f"已移动 {len(moved)} 个文件", 8000)
        self._refresh_group_labels()
        self._update_summary()
        self._show_group_at_row(self.group_list.currentRow())
        self._schedule_session_save()

    def _undo_move(self) -> None:
        if not self.destination_folder:
            return
        restored, errors = undo_last_move(self.destination_folder)
        if restored:
            by_destination = {
                Path(entry.destination): (Path(entry.source), entry.previous_status)
                for entry in restored
            }
            for group in self.groups:
                for photo in group.photos:
                    if photo.path in by_destination:
                        source, previous_status = by_destination[photo.path]
                        photo.path = source
                        try:
                            photo.status = ReviewStatus(previous_status)
                        except ValueError:
                            photo.status = ReviewStatus.KEPT
            self.statusBar().showMessage(f"已恢复 {len(restored)} 张照片到原位置", 8000)
            self._refresh_group_labels()
            self._show_group_at_row(self.group_list.currentRow())
            self._update_summary()
            self._schedule_session_save()
        elif not errors:
            QMessageBox.information(
                self,
                "没有可撤销操作",
                "该文件夹中没有可撤销的移动记录。",
            )
        if errors:
            QMessageBox.warning(self, "部分文件未恢复", "\n".join(errors[:8]))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.analysis_thread and self.analysis_thread.isRunning():
            event.ignore()
            return
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if self.analysis_thread and self.analysis_thread.isRunning():
            event.ignore()
            return
        local_paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not local_paths:
            return
        folder = next((path for path in local_paths if path.is_dir()), None)
        if folder is None:
            image = next(
                (path for path in local_paths if path.suffix.lower() in SUPPORTED_EXTENSIONS),
                None,
            )
            folder = image.parent if image else None
        if folder:
            self._set_source(folder)
            self._start_analysis()
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.session_save_timer.stop()
        self._save_session_now()
        if self.analysis_thread and self.analysis_thread.isRunning() and self.analysis_worker:
            self.analysis_worker.cancel()
            self.analysis_thread.quit()
            if not self.analysis_thread.wait(5000):
                self.statusBar().showMessage("正在安全停止照片分析，请稍候…")
                event.ignore()
                return
        event.accept()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if hasattr(self, "grid_resize_timer"):
            self.grid_resize_timer.start()


def apply_theme(app: QApplication, theme_mode: Optional[str] = None) -> None:
    mode = theme_mode or _theme_setting(QSettings())
    mode = {"graphite": "light", "black": "dark"}.get(mode, mode)
    _sync_macos_appearance(mode)
    apply_unified_theme(app, mode)
