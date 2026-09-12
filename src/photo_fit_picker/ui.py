from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QImageReader,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
from .fileops import move_selected, undo_last_move
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


class PhotoCard(QFrame):
    status_changed = Signal()
    open_requested = Signal(object)

    def __init__(self, photo: PhotoRecord, recommended: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.photo = photo
        self.recommended = recommended
        self.setObjectName("photoCard")
        self.setProperty("reviewStatus", photo.status.value)
        self.setFixedWidth(242)

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
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name)

        details = QLabel(
            f"{photo.width} × {photo.height}  ·  {photo.megapixels:.1f} MP\n"
            f"清晰度 {photo.sharpness:.2f}  ·  {photo.captured_at:%H:%M:%S}"
        )
        details.setObjectName("photoDetails")
        layout.addWidget(details)

        actions = QHBoxLayout()
        self.keep_button = QPushButton("保留")
        self.keep_button.setCheckable(True)
        self.keep_button.setObjectName("keepButton")
        self.reject_button = QPushButton("排除")
        self.reject_button.setCheckable(True)
        self.reject_button.setObjectName("rejectButton")
        self.keep_button.clicked.connect(lambda: self._set_status(ReviewStatus.KEPT))
        self.reject_button.clicked.connect(lambda: self._set_status(ReviewStatus.REJECTED))
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
        self.status_changed.emit()

    def sync_status(self) -> None:
        self.keep_button.setChecked(self.photo.status == ReviewStatus.KEPT)
        self.reject_button.setChecked(self.photo.status == ReviewStatus.REJECTED)
        is_moved = self.photo.status == ReviewStatus.MOVED
        self.keep_button.setEnabled(not is_moved)
        self.reject_button.setEnabled(not is_moved)
        self.setProperty("reviewStatus", self.photo.status.value)
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

    def __init__(
        self,
        photos: list[PhotoRecord],
        start_index: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.photos = photos
        self.index = start_index
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
        layout.addWidget(self.image_label, 1)

        controls = QHBoxLayout()
        self.previous_button = QToolButton()
        self.previous_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.previous_button.setToolTip("上一张")
        self.previous_button.clicked.connect(self._previous)
        controls.addWidget(self.previous_button)

        self.next_button = QToolButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.next_button.setToolTip("下一张")
        self.next_button.clicked.connect(self._next)
        controls.addWidget(self.next_button)

        self.info_label = QLabel()
        self.info_label.setObjectName("viewerInfo")
        controls.addWidget(self.info_label, 1)
        self.reject_button = QPushButton("排除")
        self.reject_button.clicked.connect(lambda: self._set_status(ReviewStatus.REJECTED))
        controls.addWidget(self.reject_button)
        self.keep_button = QPushButton("保留")
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
        }[photo.status]
        self.info_label.setText(
            f"{self.index + 1} / {len(self.photos)}  ·  {photo.display_name}  ·  {state}"
        )
        self.previous_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.photos) - 1)
        movable = photo.status != ReviewStatus.MOVED
        self.keep_button.setEnabled(movable)
        self.reject_button.setEnabled(movable)

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
        if photo.status == ReviewStatus.MOVED:
            return
        photo.status = ReviewStatus.PENDING if photo.status == status else status
        self.status_changed.emit()
        self._load_current()


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
        self.analysis_thread: Optional[QThread] = None
        self.analysis_worker: Optional[AnalysisWorker] = None

        self._build_ui()
        self._build_shortcuts()
        self._show_empty_state()

    def _build_ui(self) -> None:
        root = QWidget()
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
        title_box.addWidget(title)
        title_box.addWidget(self.source_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        self.undo_button = QToolButton()
        self.undo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.undo_button.setToolTip("撤销上一次移动")
        self.undo_button.clicked.connect(self._undo_move)
        header_layout.addWidget(self.undo_button)

        destination_button = QPushButton("设置已筛选文件夹")
        destination_button.clicked.connect(self._choose_destination)
        header_layout.addWidget(destination_button)
        self.move_button = QPushButton("移动已保留照片")
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

        folder_button = QPushButton("选择照片文件夹")
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

        self.analyze_button = QPushButton("开始分析")
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
        choose = QPushButton("选择照片文件夹")
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
        reject_all = QPushButton("本组全部排除")
        reject_all.clicked.connect(lambda: self._set_current_group(ReviewStatus.REJECTED))
        toolbar.addWidget(reject_all)
        keep_all = QPushButton("本组全部保留")
        keep_all.clicked.connect(lambda: self._set_current_group(ReviewStatus.KEPT))
        toolbar.addWidget(keep_all)
        recommend = QPushButton("仅保留推荐")
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
        self.content_stack.addWidget(review)
        return self.content_stack

    def _build_shortcuts(self) -> None:
        open_action = QAction(self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._choose_source)
        self.addAction(open_action)

    def _show_empty_state(self) -> None:
        self.content_stack.setCurrentIndex(0)
        self.move_button.setEnabled(False)
        self.undo_button.setEnabled(False)

    def _choose_source(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if selected:
            self._set_source(Path(selected))

    def _set_source(self, folder: Path) -> None:
        self.source_folder = folder
        self.source_label.setText(str(folder))
        self.analyze_button.setEnabled(True)
        if self.destination_folder is None:
            self.destination_folder = folder / "已筛选"
        self.statusBar().showMessage("已选择照片文件夹，点击“开始分析”", 5000)

    def _choose_destination(self) -> None:
        start = str(self.destination_folder or self.source_folder or Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择已筛选照片保存位置", start)
        if selected:
            self.destination_folder = Path(selected)
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
            QMessageBox.information(self, "没有照片", "该文件夹中没有找到支持的照片。")
            return

        self.analyze_button.setEnabled(False)
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
        self.statusBar().showMessage(f"正在分析 {current}/{total}：{filename}")

    def _analysis_finished(self, groups: list[PhotoGroup], failures: list[tuple[Path, str]]) -> None:
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
            self._show_group_at_row(0)
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
        return f"{marker}  第 {group.id} 组  ·  {len(group.photos)} 张  ·  保留 {group.kept_count}"

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
        for index, photo in enumerate(group.photos):
            card = PhotoCard(photo, photo is recommended)
            card.status_changed.connect(self._review_changed)
            card.open_requested.connect(self._open_viewer)
            self.cards.append(card)
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
            photo.status = status
        for card in self.cards:
            card.sync_status()
        self._review_changed()

    def _open_viewer(self, photo: PhotoRecord) -> None:
        group = self._current_group()
        if not group:
            return
        viewer = PhotoViewer(group.photos, group.photos.index(photo), self)
        viewer.status_changed.connect(self._review_changed)
        viewer.exec()
        for card in self.cards:
            card.sync_status()

    def _keep_recommended(self) -> None:
        group = self._current_group()
        if not group or not group.recommended:
            return
        for photo in group.photos:
            photo.status = ReviewStatus.KEPT if photo is group.recommended else ReviewStatus.REJECTED
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

    def _update_summary(self) -> None:
        photos = [photo for group in self.groups for photo in group.photos]
        kept = sum(photo.status == ReviewStatus.KEPT for photo in photos)
        reviewed = sum(photo.status != ReviewStatus.PENDING for photo in photos)
        similar = sum(len(group.photos) > 1 for group in self.groups)
        if photos:
            self.summary_label.setText(
                f"共 {len(photos)} 张 · 已审核 {reviewed} 张\n"
                f"已保留 {kept} 张 · 相似组 {similar} 个"
            )
        else:
            self.summary_label.setText("尚未分析照片")
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
            QMessageBox.critical(self, "移动未完成", f"文件移动过程中发生错误：\n{exc}")
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
            QMessageBox.information(self, "没有可撤销操作", "该文件夹中没有可撤销的移动记录。")
        if errors:
            QMessageBox.warning(self, "部分文件未恢复", "\n".join(errors[:8]))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        local_paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
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


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget { color: #1f2933; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; font-size: 13px; }
        QMainWindow, QScrollArea, #photo_grid_host { background: #f4f6f7; }
        #header { background: #ffffff; border-bottom: 1px solid #d8dee2; }
        #appTitle { font-size: 22px; font-weight: 700; color: #15201c; }
        #sourceLabel, #photoDetails, #groupMeta, #emptyHint, #summaryLabel { color: #66727a; }
        #sidebar { background: #edf1f0; border-right: 1px solid #d5dcda; }
        #sectionTitle { margin-top: 12px; font-weight: 700; color: #33423d; }
        #emptyTitle { font-size: 24px; font-weight: 700; margin-top: 12px; }
        #groupTitle { font-size: 20px; font-weight: 700; }
        QPushButton, QComboBox, QSpinBox, QToolButton {
            min-height: 34px; padding: 0 12px; border: 1px solid #c7d0cd;
            border-radius: 6px; background: #ffffff;
        }
        QPushButton:hover, QToolButton:hover { border-color: #71837c; background: #f8faf9; }
        QPushButton:disabled { color: #9ca7a3; background: #edf0ef; }
        #primaryButton { color: #ffffff; background: #176b52; border-color: #176b52; font-weight: 600; }
        #primaryButton:hover { background: #125640; }
        QListWidget { border: 1px solid #d0d8d5; border-radius: 6px; background: #ffffff; outline: none; }
        QListWidget::item { min-height: 38px; padding: 0 8px; border-bottom: 1px solid #edf0ef; }
        QListWidget::item:selected { background: #d9ebe4; color: #163d30; }
        #photoCard { background: #ffffff; border: 1px solid #dce2e0; border-radius: 8px; }
        #photoCard[reviewStatus="kept"] { border: 2px solid #25805f; background: #f5fbf8; }
        #photoCard[reviewStatus="rejected"] { border: 1px solid #c6ccca; background: #eef1f0; }
        #previewFrame { background: #1d2422; border-radius: 4px; }
        #viewerImage { background: #121715; border-radius: 4px; }
        #photoName { font-weight: 600; }
        #recommendBadge { color: #ffffff; background: #b75824; border-radius: 4px; font-size: 12px; font-weight: 700; }
        #keepButton:checked { color: #ffffff; background: #25805f; border-color: #25805f; }
        #rejectButton:checked { color: #ffffff; background: #626d69; border-color: #626d69; }
        QProgressBar { border: 1px solid #cbd3d0; border-radius: 4px; text-align: center; background: #ffffff; }
        QProgressBar::chunk { background: #25805f; }
        """
    )
