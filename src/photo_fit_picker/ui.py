from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
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
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PIL import Image, ImageOps

from .analysis import SUPPORTED_EXTENSIONS, discover_images
from .fileops import move_photo_to_trash, move_photos, move_selected, undo_last_move
from .models import PhotoGroup, PhotoRecord, ReviewStatus
from .worker import AnalysisWorker


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
        with Image.open(path) as source:
            fallback = ImageOps.exif_transpose(source).convert("RGBA")
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
            if self.owner.objectName() == "primaryButton"
            else QColor(25, 39, 34)
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
        if not self.isEnabled():
            painter.setPen(QPen(QColor("#aeb5b1"), 1.5))
            painter.setBrush(QColor("#dfe3e0"))
        elif self.isChecked():
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.setBrush(QColor("#347c9b"))
        else:
            painter.setPen(QPen(QColor("#aeb8b3"), 1.5))
            painter.setBrush(QColor("#ffffff"))
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


class PhotoCard(QFrame):
    status_changed = Signal()
    selection_changed = Signal()
    open_requested = Signal(object)
    trash_requested = Signal(object)

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
        self.setFixedWidth(242)
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self._clear_feedback)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = PreviewLabel("正在载入…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(220, 154)
        self.preview.clicked.connect(lambda: self.open_requested.emit(self.photo))
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_frame)

        self.select_box = SelectionCheckBox()
        self.select_box.setObjectName("photoSelect")
        self.select_box.setToolTip("选择照片以执行批量操作")
        self.select_box.setChecked(photo.selected)
        self.select_box.setParent(preview_frame)
        self.select_box.move(188, 8)
        self.select_box.stateChanged.connect(self._selection_changed)
        self.select_box.raise_()

        if recommended:
            badge = QLabel("推荐")
            badge.setObjectName("recommendBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(52, 24)
            badge.setParent(preview_frame)
            badge.move(8, 8)
            badge.raise_()

        name = QLabel(photo.display_name)
        name.setObjectName("photoName")
        name.setToolTip(str(photo.path))
        name.setWordWrap(True)
        name.setFixedHeight(36)
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name)

        details = QLabel(
            f"{photo.width} × {photo.height}  ·  {photo.megapixels:.1f} MP\n"
            f"清晰度 {photo.sharpness:.2f}  ·  {photo.captured_at:%H:%M:%S}"
        )
        details.setObjectName("photoDetails")
        layout.addWidget(details)

        actions = QHBoxLayout()
        self.trash_button = FeedbackToolButton()
        self.trash_button.setObjectName("trashButton")
        self.trash_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.trash_button.setToolTip("移到系统废纸篓/回收站")
        self.trash_button.clicked.connect(lambda: self.trash_requested.emit(self.photo))
        self.keep_button = FeedbackButton("保留")
        self.keep_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.keep_button.setCheckable(True)
        self.keep_button.setObjectName("keepButton")
        self.reject_button = FeedbackButton("排除")
        self.reject_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.reject_button.setCheckable(True)
        self.reject_button.setObjectName("rejectButton")
        self.keep_button.clicked.connect(lambda: self._set_status(ReviewStatus.KEPT))
        self.reject_button.clicked.connect(lambda: self._set_status(ReviewStatus.REJECTED))
        actions.addWidget(self.trash_button)
        actions.addWidget(self.keep_button)
        actions.addWidget(self.reject_button)
        layout.addLayout(actions)

        self.sync_status()
        self._load_thumbnail()

    def _load_thumbnail(self) -> None:
        image = _read_preview(self.photo.path, QSize(440, 308))
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

    def sync_status(self) -> None:
        self.keep_button.setChecked(self.photo.status == ReviewStatus.KEPT)
        self.reject_button.setChecked(self.photo.status == ReviewStatus.REJECTED)
        is_final = self.photo.status in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
        self.keep_button.setEnabled(not is_final)
        self.reject_button.setEnabled(not is_final)
        self.trash_button.setEnabled(
            self.photo.status != ReviewStatus.TRASHED and self.photo.path.is_file()
        )
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
        photos: list[PhotoRecord],
        start_index: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.photos = photos
        self.index = start_index
        self.setObjectName("photoViewer")
        self.setWindowTitle("照片预览")
        self.setModal(True)
        self.resize(1100, 760)
        self.setMinimumSize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.image_label = QLabel()
        self.image_label.setObjectName("viewerImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 400)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(self.image_label, 1)

        controls = QHBoxLayout()
        self.previous_button = FeedbackToolButton()
        self.previous_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.previous_button.setToolTip("上一张")
        self.previous_button.clicked.connect(self._previous)
        controls.addWidget(self.previous_button)

        self.next_button = FeedbackToolButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.next_button.setToolTip("下一张")
        self.next_button.clicked.connect(self._next)
        controls.addWidget(self.next_button)

        self.info_label = QLabel()
        self.info_label.setObjectName("viewerInfo")
        controls.addWidget(self.info_label, 1)
        self.trash_button = FeedbackToolButton()
        self.trash_button.setObjectName("trashButton")
        self.trash_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.trash_button.setToolTip("移到系统废纸篓/回收站")
        self.trash_button.clicked.connect(self._request_trash)
        controls.addWidget(self.trash_button)
        self.reject_button = FeedbackButton("排除")
        self.reject_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.reject_button.clicked.connect(lambda: self._set_status(ReviewStatus.REJECTED))
        controls.addWidget(self.reject_button)
        self.keep_button = FeedbackButton("保留")
        self.keep_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("拾影 · 照片筛选")
        self.resize(1280, 820)
        self.setMinimumSize(920, 640)
        self.setAcceptDrops(True)

        self.source_folder: Optional[Path] = None
        self.destination_folder: Optional[Path] = None
        self.groups: list[PhotoGroup] = []
        self.visible_groups: list[PhotoGroup] = []
        self.cards: list[PhotoCard] = []
        self._grid_columns = 0
        self.analysis_thread: Optional[QThread] = None
        self.analysis_worker: Optional[AnalysisWorker] = None

        self._build_ui()
        self.grid_resize_timer = QTimer(self)
        self.grid_resize_timer.setSingleShot(True)
        self.grid_resize_timer.setInterval(45)
        self.grid_resize_timer.timeout.connect(self._reflow_cards)
        self._build_shortcuts()
        self._show_empty_state()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 14, 22, 14)
        title_box = QVBoxLayout()
        title = QLabel("拾影")
        title.setObjectName("appTitle")
        self.source_label = QLabel("拖入照片文件夹，或点击“选择照片文件夹”")
        self.source_label.setObjectName("sourceLabel")
        self.source_label.setMaximumWidth(360)
        title_box.addWidget(title)
        title_box.addWidget(self.source_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        self.undo_button = FeedbackToolButton()
        self.undo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.undo_button.setToolTip("撤销上一次移动")
        self.undo_button.clicked.connect(self._undo_move)
        header_layout.addWidget(self.undo_button)

        self.destination_button = FeedbackButton("已筛选文件夹")
        self.destination_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        )
        self.destination_button.setToolTip("设置已筛选照片的目标文件夹")
        self.destination_button.clicked.connect(self._choose_destination)
        header_layout.addWidget(self.destination_button)
        self.move_button = FeedbackButton("移动已保留照片")
        self.move_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)
        )
        self.move_button.setObjectName("primaryButton")
        self.move_button.clicked.connect(self._move_kept)
        header_layout.addWidget(self.move_button)
        root_layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_content())
        splitter.setSizes([280, 1000])
        root_layout.addWidget(splitter, 1)

        self.setCentralWidget(root)
        status = QStatusBar()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(260)
        self.progress.hide()
        status.addPermanentWidget(self.progress)
        self.setStatusBar(status)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(250)
        sidebar.setMaximumWidth(340)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        folder_button = FeedbackButton("选择照片文件夹")
        folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        folder_button.clicked.connect(self._choose_source)
        layout.addWidget(folder_button)

        settings_title = QLabel("分组设置")
        settings_title.setObjectName("sectionTitle")
        layout.addWidget(settings_title)

        similarity_row = QHBoxLayout()
        similarity_row.addWidget(QLabel("相似度"))
        self.similarity_value = QLabel("84%")
        similarity_row.addStretch()
        similarity_row.addWidget(self.similarity_value)
        layout.addLayout(similarity_row)
        self.similarity_slider = QSlider(Qt.Orientation.Horizontal)
        self.similarity_slider.setRange(70, 95)
        self.similarity_slider.setValue(84)
        self.similarity_slider.valueChanged.connect(
            lambda value: self.similarity_value.setText(f"{value}%")
        )
        layout.addWidget(self.similarity_slider)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("连拍时间范围"))
        self.time_window = QSpinBox()
        self.time_window.setRange(5, 600)
        self.time_window.setValue(90)
        self.time_window.setSuffix(" 秒")
        time_row.addStretch()
        time_row.addWidget(self.time_window)
        layout.addLayout(time_row)

        self.analyze_button = FeedbackButton("开始分析")
        self.analyze_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.analyze_button.setObjectName("primaryButton")
        self.analyze_button.setEnabled(False)
        self.analyze_button.clicked.connect(self._start_analysis)
        layout.addWidget(self.analyze_button)

        filter_title = QLabel("照片组")
        filter_title.setObjectName("sectionTitle")
        layout.addWidget(filter_title)
        self.group_filter = QComboBox()
        self.group_filter.addItem("全部照片组", "all")
        self.group_filter.addItem("待审核", "pending")
        self.group_filter.addItem("已有保留", "kept")
        self.group_filter.addItem("相似组（2 张以上）", "similar")
        self.group_filter.currentIndexChanged.connect(self._apply_group_filter)
        layout.addWidget(self.group_filter)

        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self._show_group_at_row)
        layout.addWidget(self.group_list, 1)

        self.summary_label = QLabel("尚未分析照片")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        return sidebar

    def _build_content(self) -> QWidget:
        self.content_stack = QStackedWidget()

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel()
        icon.setPixmap(
            self.style()
            .standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
            .pixmap(72, 72)
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon)
        empty_title = QLabel("把照片文件夹拖到这里")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_hint = QLabel("照片只在本机分析；确认保留后才会移动原文件")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint)
        choose = FeedbackButton("选择照片文件夹")
        choose.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        choose.clicked.connect(self._choose_source)
        empty_layout.addWidget(choose, alignment=Qt.AlignmentFlag.AlignCenter)
        self.content_stack.addWidget(empty)

        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(24, 20, 24, 20)
        review_layout.setSpacing(14)
        toolbar = QHBoxLayout()
        group_text = QVBoxLayout()
        self.group_title = QLabel("照片组")
        self.group_title.setObjectName("groupTitle")
        self.group_meta = QLabel("")
        self.group_meta.setObjectName("groupMeta")
        group_text.addWidget(self.group_title)
        group_text.addWidget(self.group_meta)
        toolbar.addLayout(group_text)
        toolbar.addStretch()
        select_group = FeedbackButton("选择本组")
        select_group.clicked.connect(self._select_current_group)
        toolbar.addWidget(select_group)
        reject_all = FeedbackButton("全部排除")
        reject_all.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        reject_all.clicked.connect(lambda: self._set_current_group(ReviewStatus.REJECTED))
        toolbar.addWidget(reject_all)
        keep_all = FeedbackButton("全部保留")
        keep_all.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        keep_all.clicked.connect(lambda: self._set_current_group(ReviewStatus.KEPT))
        toolbar.addWidget(keep_all)
        recommend = FeedbackButton("采用推荐")
        recommend.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        recommend.setObjectName("primaryButton")
        recommend.clicked.connect(self._keep_recommended)
        toolbar.addWidget(recommend)
        review_layout.addLayout(toolbar)

        self.photo_scroll = QScrollArea()
        self.photo_scroll.setWidgetResizable(True)
        self.photo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.photo_grid_host = QWidget()
        self.photo_grid_host.setObjectName("photo_grid_host")
        self.photo_grid = QGridLayout(self.photo_grid_host)
        self.photo_grid.setContentsMargins(0, 0, 0, 0)
        self.photo_grid.setSpacing(14)
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
        clear_selection = FeedbackButton("清除选择")
        clear_selection.setObjectName("quietButton")
        clear_selection.clicked.connect(self._clear_selection)
        batch_layout.addWidget(clear_selection)
        batch_reject = FeedbackButton("标为排除")
        batch_reject.clicked.connect(
            lambda: self._set_selected_status(ReviewStatus.REJECTED)
        )
        batch_layout.addWidget(batch_reject)
        batch_keep = FeedbackButton("标为保留")
        batch_keep.clicked.connect(lambda: self._set_selected_status(ReviewStatus.KEPT))
        batch_layout.addWidget(batch_keep)
        batch_trash = FeedbackToolButton()
        batch_trash.setObjectName("trashButton")
        batch_trash.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        batch_trash.setToolTip("将所选照片移到系统回收站")
        batch_trash.clicked.connect(self._confirm_trash_selected)
        batch_layout.addWidget(batch_trash)
        batch_move = FeedbackButton("移动到…")
        batch_move.setObjectName("primaryButton")
        batch_move.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)
        )
        batch_move.clicked.connect(self._move_explicit_selection)
        batch_layout.addWidget(batch_move)
        review_layout.addWidget(self.batch_bar)
        self.batch_bar.hide()
        self.content_stack.addWidget(review)
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
        clear_action.triggered.connect(self._clear_selection)
        self.addAction(clear_action)

    def _show_empty_state(self) -> None:
        self.content_stack.setCurrentIndex(0)
        self.move_button.setText("移动已保留照片")
        self.move_button.setEnabled(False)
        self.undo_button.setEnabled(False)

    def _choose_source(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if selected:
            self._set_source(Path(selected))

    def _set_source(self, folder: Path) -> None:
        self.source_folder = folder
        self.source_label.setText(f"照片文件夹 · {folder.name}")
        self.source_label.setToolTip(str(folder))
        self.analyze_button.setEnabled(True)
        if self.destination_folder is None:
            self.destination_folder = folder / "已筛选"
            self.destination_button.setToolTip(f"目标文件夹：{self.destination_folder}")
        self.statusBar().showMessage("已选择照片文件夹，点击“开始分析”", 5000)

    def _choose_destination(self) -> None:
        start = str(self.destination_folder or self.source_folder or Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择已筛选照片保存位置",
            start,
        )
        if selected:
            self.destination_folder = Path(selected)
            self.destination_button.setToolTip(f"目标文件夹：{selected}")
            self.undo_button.setEnabled(True)
            self.statusBar().showMessage(f"已筛选照片将移动到：{selected}", 5000)

    def _start_analysis(self) -> None:
        if not self.source_folder:
            return
        paths = discover_images(self.source_folder)
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

        self.analyze_button.setEnabled(False)
        self.analyze_button.setText("正在分析")
        self.similarity_slider.setEnabled(False)
        self.time_window.setEnabled(False)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.show()
        self.statusBar().showMessage(f"准备分析 {len(paths)} 张照片…")

        thread = QThread(self)
        worker = AnalysisWorker(
            paths,
            self.similarity_slider.value() / 100.0,
            self.time_window.value(),
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
        thread.start()

    def _analysis_progress(self, current: int, total: int, filename: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.analyze_button.setText(f"分析中 {current}/{total}")
        self.statusBar().showMessage(f"正在分析 {current}/{total}：{filename}")

    def _analysis_finished(
        self,
        groups: list[PhotoGroup],
        failures: list[tuple[Path, str]],
    ) -> None:
        self.groups = groups
        self._apply_group_filter()
        photo_count = sum(len(group.photos) for group in groups)
        similar_count = sum(len(group.photos) > 1 for group in groups)
        self.statusBar().showMessage(
            f"分析完成：{photo_count} 张照片，{similar_count} 个相似组",
            8000,
        )
        if failures:
            QMessageBox.warning(
                self,
                "部分照片未能读取",
                f"有 {len(failures)} 个文件未能读取，其他照片已正常完成分析。",
            )

    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(self, "分析失败", message)
        self.statusBar().showMessage("分析失败", 5000)

    def _analysis_cancelled(self) -> None:
        self.statusBar().showMessage("分析已取消", 5000)

    def _analysis_thread_finished(self) -> None:
        self.progress.hide()
        self.analyze_button.setText("重新分析")
        self.analyze_button.setEnabled(self.source_folder is not None)
        self.similarity_slider.setEnabled(True)
        self.time_window.setEnabled(True)
        self.analysis_thread = None
        self.analysis_worker = None

    def _apply_group_filter(self) -> None:
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
            self.content_stack.setCurrentIndex(1)
            self.group_list.setCurrentRow(0)
        elif self.groups:
            self.content_stack.setCurrentIndex(1)
            self._clear_grid()
            self.group_title.setText("当前筛选条件下没有照片组")
            self.group_meta.setText("")
        else:
            self._show_empty_state()
        self._update_summary()

    def _group_label(self, group: PhotoGroup) -> str:
        marker = "✓" if group.reviewed else "○"
        return (
            f"{marker}  第 {group.id} 组  ·  {len(group.photos)} 张"
            f"  ·  保留 {group.kept_count}"
        )

    def _show_group_at_row(self, row: int) -> None:
        if row < 0 or row >= len(self.visible_groups):
            return
        group = self.visible_groups[row]
        self._clear_grid()
        self.group_title.setText(f"第 {group.id} 组")
        self.group_meta.setText(
            f"{len(group.photos)} 张照片  ·  {group.photos[0].captured_at:%Y-%m-%d %H:%M}"
        )
        recommended = group.recommended
        columns = max(1, self.photo_scroll.viewport().width() // 260)
        self._grid_columns = columns
        for index, photo in enumerate(group.photos):
            card = PhotoCard(photo, photo is recommended)
            card.status_changed.connect(self._review_changed)
            card.selection_changed.connect(self._selection_changed)
            card.open_requested.connect(self._open_viewer)
            card.trash_requested.connect(self._confirm_trash)
            self.cards.append(card)
            self.photo_grid.addWidget(card, index // columns, index % columns)
            card.animate_in(min(index, 8) * 28)

    def _reflow_cards(self) -> None:
        if not self.cards:
            return
        columns = max(1, self.photo_scroll.viewport().width() // 260)
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

    def _open_viewer(self, photo: PhotoRecord) -> None:
        group = self._current_group()
        if not group:
            return
        viewer = PhotoViewer(group.photos, group.photos.index(photo), self)
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

    def _review_changed(self) -> None:
        row = self.group_list.currentRow()
        group = self._current_group()
        if group and row >= 0:
            self.group_list.item(row).setText(self._group_label(group))
        self._update_summary()

    def _refresh_group_labels(self) -> None:
        for row, group in enumerate(self.visible_groups):
            item = self.group_list.item(row)
            if item:
                item.setText(self._group_label(group))

    def _confirm_trash(self, photo: PhotoRecord) -> None:
        answer = QMessageBox.warning(
            self,
            "确认移到回收站",
            f"确定要将这张照片移到系统废纸篓/回收站吗？\n\n{photo.path}\n\n"
            "这不是永久删除，可从系统废纸篓/回收站恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
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

    def _confirm_trash_selected(self) -> None:
        selected = self._selected_photos()
        if not selected:
            return
        answer = QMessageBox.warning(
            self,
            "确认批量移到回收站",
            f"确定要将选中的 {len(selected)} 张照片移到"
            "系统废纸篓/回收站吗？\n\n"
            "这不是永久删除，可从系统废纸篓/回收站恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
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
        answer = QMessageBox.question(
            self,
            "确认批量移动",
            f"将选中的 {len(selected)} 张照片移动到：\n{destination_path}\n\n"
            "移动后可通过顶部撤销按钮恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = move_photos(selected, destination_path)
        except OSError as exc:
            QMessageBox.critical(self, "批量移动未完成", str(exc))
            for card in self.cards:
                card.sync_status()
            self._selection_changed()
            return
        self.destination_folder = destination_path
        self.destination_button.setToolTip(f"目标文件夹：{destination_path}")
        self.statusBar().showMessage(f"已移动 {len(moved)} 张照片", 8000)
        for card in self.cards:
            card.sync_status()
        self._selection_changed()
        self._refresh_group_labels()
        self._update_summary()

    def _update_summary(self) -> None:
        photos = [photo for group in self.groups for photo in group.photos]
        kept = sum(photo.status == ReviewStatus.KEPT for photo in photos)
        reviewed = sum(photo.status != ReviewStatus.PENDING for photo in photos)
        similar = sum(len(group.photos) > 1 for group in self.groups)
        trashed = sum(photo.status == ReviewStatus.TRASHED for photo in photos)
        if photos:
            self.summary_label.setText(
                f"共 {len(photos)} 张 · 已审核 {reviewed} 张\n"
                f"保留 {kept} 张 · 回收站 {trashed} 张\n"
                f"相似组 {similar} 个"
            )
        else:
            self.summary_label.setText("尚未分析照片")
        self.move_button.setText(f"移动 {kept} 张照片" if kept else "移动已保留照片")
        self.move_button.setEnabled(kept > 0)
        self.undo_button.setEnabled(self.destination_folder is not None)

    def _move_kept(self) -> None:
        photos = [photo for group in self.groups for photo in group.photos]
        kept = [photo for photo in photos if photo.status == ReviewStatus.KEPT]
        if not kept:
            return
        if not self.destination_folder:
            self._choose_destination()
            if not self.destination_folder:
                return
        answer = QMessageBox.question(
            self,
            "确认移动照片",
            f"将 {len(kept)} 张照片移动到：\n{self.destination_folder}\n\n"
            "移动后可以使用左上角的撤销按钮恢复。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = move_selected(kept, self.destination_folder)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "移动未完成",
                f"文件移动过程中发生错误：\n{exc}",
            )
            self._update_summary()
            return
        self.statusBar().showMessage(f"已移动 {len(moved)} 张照片", 8000)
        self._refresh_group_labels()
        self._update_summary()
        self._show_group_at_row(self.group_list.currentRow())

    def _undo_move(self) -> None:
        if not self.destination_folder:
            return
        restored, errors = undo_last_move(self.destination_folder)
        if restored:
            by_destination = {Path(entry.destination): Path(entry.source) for entry in restored}
            for group in self.groups:
                for photo in group.photos:
                    if photo.path in by_destination:
                        photo.path = by_destination[photo.path]
                        photo.status = ReviewStatus.KEPT
            self.statusBar().showMessage(f"已恢复 {len(restored)} 张照片到原位置", 8000)
            self._refresh_group_labels()
            self._show_group_at_row(self.group_list.currentRow())
            self._update_summary()
        elif not errors:
            QMessageBox.information(
                self,
                "没有可撤销操作",
                "该文件夹中没有可撤销的移动记录。",
            )
        if errors:
            QMessageBox.warning(self, "部分文件未恢复", "\n".join(errors[:8]))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
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


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget {
            color: #202522;
            font-family: "SF Pro Text", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 13px;
        }
        QMainWindow, #appRoot, QStackedWidget, QScrollArea, #photo_grid_host {
            background: #f3f4f2;
        }
        #header {
            min-height: 62px;
            background: #ffffff;
            border-bottom: 1px solid #dfe3e0;
        }
        #appTitle {
            color: #15201c;
            font-size: 21px;
            font-weight: 700;
        }
        #sourceLabel, #photoDetails, #groupMeta, #emptyHint, #summaryLabel {
            color: #69736f;
        }
        #sidebar {
            background: #ecefec;
            border-right: 1px solid #d9dedb;
        }
        #sectionTitle {
            margin-top: 11px;
            color: #34413c;
            font-size: 12px;
            font-weight: 700;
        }
        #emptyTitle {
            margin-top: 12px;
            color: #1a211e;
            font-size: 23px;
            font-weight: 700;
        }
        #groupTitle {
            color: #1a211e;
            font-size: 19px;
            font-weight: 700;
        }
        QPushButton, QComboBox, QSpinBox, QToolButton {
            min-height: 34px;
            padding: 0 12px;
            color: #26302c;
            background: #ffffff;
            border: 1px solid #cbd2ce;
            border-radius: 6px;
        }
        QToolButton {
            min-width: 34px;
            padding: 0;
        }
        QPushButton:hover, QToolButton:hover {
            background: #f8faf8;
            border-color: #82918a;
        }
        QPushButton:pressed, QToolButton:pressed {
            background: #edf1ee;
        }
        QPushButton:focus, QToolButton:focus, QComboBox:focus, QSpinBox:focus {
            border: 1px solid #28785d;
        }
        QPushButton:disabled, QToolButton:disabled {
            color: #9ca5a1;
            background: #e8ebe9;
            border-color: #d9dddb;
        }
        #primaryButton {
            color: #ffffff;
            background: #176b52;
            border-color: #176b52;
            font-weight: 600;
        }
        #primaryButton:hover {
            background: #125b45;
            border-color: #125b45;
        }
        #primaryButton:pressed {
            background: #0f4d3a;
        }
        #primaryButton:disabled {
            color: #d5dbd8;
            background: #81938c;
            border-color: #81938c;
        }
        #trashButton:hover {
            color: #8f403f;
            background: #fff5f4;
            border-color: #d8a19e;
        }
        QComboBox, QSpinBox {
            selection-color: #ffffff;
            selection-background-color: #176b52;
        }
        QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
            width: 24px;
            border: 0;
        }
        QListWidget {
            padding: 3px;
            background: #f8f9f7;
            border: 1px solid #d7dcd9;
            border-radius: 6px;
            outline: none;
        }
        QListWidget::item {
            min-height: 38px;
            padding: 0 9px;
            border-radius: 4px;
        }
        QListWidget::item:hover {
            background: #edf1ee;
        }
        QListWidget::item:selected {
            color: #123f30;
            background: #d9ebe4;
        }
        #photoCard {
            background: #ffffff;
            border: 1px solid #dce1de;
            border-radius: 8px;
        }
        #photoCard:hover {
            border-color: #abb5b0;
            background: #fdfefd;
        }
        #photoCard[selected="true"] {
            border: 2px solid #347c9b;
            background: #f4f9fb;
        }
        #photoCard[reviewStatus="kept"] {
            background: #f4faf7;
            border: 2px solid #25805f;
        }
        #photoCard[reviewStatus="kept"][selected="true"] {
            border: 2px solid #347c9b;
        }
        #photoCard[reviewStatus="rejected"] {
            background: #ebeeec;
            border: 1px solid #c2c8c5;
        }
        #photoCard[reviewStatus="trashed"] {
            background: #e3e6e4;
            border: 1px dashed #aeb5b1;
        }
        #photoCard[feedback="true"] {
            border: 2px solid #c96a2b;
        }
        #previewFrame {
            background: #181d1b;
            border-radius: 4px;
        }
        #photoName {
            color: #222a26;
            font-weight: 600;
        }
        #recommendBadge {
            color: #ffffff;
            background: #b95f2b;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 700;
        }
        #keepButton:checked {
            color: #ffffff;
            background: #25805f;
            border-color: #25805f;
        }
        #rejectButton:checked {
            color: #ffffff;
            background: #646d69;
            border-color: #646d69;
        }
        #batchBar {
            min-height: 48px;
            max-height: 48px;
            background: #202724;
            border: 1px solid #343e3a;
            border-radius: 7px;
        }
        #batchCount {
            min-width: 88px;
            color: #ffffff;
            font-weight: 700;
        }
        #batchBar QPushButton, #batchBar QToolButton {
            color: #eef2ef;
            background: #303936;
            border-color: #4b5752;
        }
        #batchBar QPushButton:hover, #batchBar QToolButton:hover {
            background: #3a4540;
            border-color: #74827b;
        }
        #batchBar #primaryButton {
            color: #ffffff;
            background: #1f795b;
            border-color: #1f795b;
        }
        #batchBar #quietButton {
            color: #bdc7c2;
            background: transparent;
            border-color: transparent;
        }
        #batchBar #trashButton:hover {
            color: #ffd9d5;
            background: #653a37;
            border-color: #925652;
        }
        QSlider::groove:horizontal {
            height: 4px;
            background: #cfd6d2;
            border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #25805f;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 16px;
            height: 16px;
            margin: -6px 0;
            background: #ffffff;
            border: 2px solid #25805f;
            border-radius: 8px;
        }
        QProgressBar {
            height: 16px;
            color: #38433e;
            background: #e6eae7;
            border: 0;
            border-radius: 4px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: #25805f;
            border-radius: 4px;
        }
        QScrollBar:vertical {
            width: 10px;
            margin: 2px;
            background: transparent;
        }
        QScrollBar::handle:vertical {
            min-height: 28px;
            background: #c1c8c4;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover {
            background: #99a49f;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        QSplitter::handle {
            width: 1px;
            background: #d9dedb;
        }
        QStatusBar {
            color: #5f6964;
            background: #ffffff;
            border-top: 1px solid #dfe3e0;
        }
        QToolTip {
            padding: 6px 8px;
            color: #ffffff;
            background: #262d2a;
            border: 0;
        }
        QDialog#photoViewer {
            background: #171b19;
        }
        QDialog#photoViewer #viewerImage {
            color: #aeb7b2;
            background: #0d100f;
            border-radius: 4px;
        }
        QDialog#photoViewer #viewerInfo {
            color: #e5e9e6;
        }
        QDialog#photoViewer QPushButton, QDialog#photoViewer QToolButton {
            color: #eef1ef;
            background: #292f2c;
            border-color: #424a46;
        }
        QDialog#photoViewer QPushButton:hover, QDialog#photoViewer QToolButton:hover {
            background: #343b37;
            border-color: #68736d;
        }
        QDialog#photoViewer #primaryButton {
            color: #ffffff;
            background: #1f795b;
            border-color: #1f795b;
        }
        QDialog#photoViewer #trashButton:hover {
            color: #ffd9d5;
            background: #653a37;
            border-color: #925652;
        }
        """
    )
