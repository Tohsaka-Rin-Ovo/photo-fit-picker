import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, QSettings, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from photo_fit_picker.models import PhotoGroup, PhotoRecord, ReviewStatus
from photo_fit_picker.session import ReviewSessionStore
from photo_fit_picker.ui import (
    CARD_RENDER_BATCH_SIZE,
    MainWindow,
    PhotoCard,
    ZoomablePhotoArea,
    _clamped_thumbnail_size,
    _cached_preview,
    _filtered_photo_groups,
    _get_cached_preview,
    _normalized_sort_mode,
    _normalized_view_mode,
    _photo_grid_columns,
    _preview_cache,
    _preview_cache_lock,
    _preview_locks,
    _preview_pool,
    _sorted_group_photos,
)


def test_view_preferences_are_normalized() -> None:
    assert _normalized_view_mode("compact") == "compact"
    assert _normalized_view_mode("unexpected") == "large"
    assert _clamped_thumbnail_size("80") == 120
    assert _clamped_thumbnail_size(999) == 320
    assert _clamped_thumbnail_size("invalid") == 268
    assert _normalized_sort_mode("time") == "time"
    assert _normalized_sort_mode("unexpected") == "recommended"


def test_group_photos_can_be_sorted_by_recommendation_time_and_size() -> None:
    neutral = tuple([1 / 48] * 48)

    def photo(
        name: str,
        minute: int,
        size: int,
        sharpness: float,
        portrait: bool = False,
    ) -> PhotoRecord:
        return PhotoRecord(
            path=Path(name),
            width=1200,
            height=800,
            file_size=size,
            captured_at=datetime(2026, 1, 1, 12, minute),
            dhash=minute,
            color_signature=neutral,
            sharpness=sharpness,
            exposure=0.5,
            portrait_detected=portrait,
        )

    earliest_and_largest = photo("early.jpg", 1, 300, 0.04)
    portrait = photo("portrait.jpg", 2, 200, 0.08, True)
    recommended = photo("best.jpg", 3, 100, 0.2)
    group = PhotoGroup(1, [portrait, recommended, earliest_and_largest])

    assert _sorted_group_photos(group, "recommended") == [
        recommended,
        portrait,
        earliest_and_largest,
    ]
    assert _sorted_group_photos(group, "time") == [
        earliest_and_largest,
        portrait,
        recommended,
    ]
    assert _sorted_group_photos(group, "size") == [
        earliest_and_largest,
        portrait,
        recommended,
    ]
    assert group.photos == [portrait, recommended, earliest_and_largest]


def test_portrait_badge_does_not_overlap_compact_card_controls() -> None:
    app = QApplication.instance() or QApplication([])
    image_path = Path("demo-photos/01_lake_clear.jpg").resolve()
    photo = PhotoRecord(
        path=image_path,
        width=1200,
        height=800,
        file_size=image_path.stat().st_size,
        captured_at=datetime(2026, 1, 1),
        dhash=1,
        color_signature=tuple([1 / 48] * 48),
        sharpness=0.1,
        exposure=0.5,
        portrait_detected=True,
    )
    card = PhotoCard(photo, True, "compact", 120, True)
    portrait_badge = card.findChild(QLabel, "portraitBadge")
    recommended_badge = card.findChild(QLabel, "recommendBadge")

    assert portrait_badge is not None
    assert recommended_badge is not None
    assert not portrait_badge.geometry().intersects(card.select_box.geometry())
    assert not recommended_badge.geometry().intersects(card.select_box.geometry())
    assert not portrait_badge.geometry().intersects(recommended_badge.geometry())
    card.close()


def test_portrait_detection_setting_updates_analysis_options() -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("PortraitDetectionSetting")
    QSettings().clear()
    window = MainWindow()

    window.settings_view.portrait_detection_toggle.setChecked(True)
    window._set_sort_mode("size")

    assert QSettings().value("review/detect_portraits", type=bool) is True
    assert QSettings().value("view/sort_mode") == "size"
    assert window.analysis_options.detect_portraits is True
    window.close()
    QSettings().clear()


def test_kook_theme_is_available_and_persisted() -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("KookThemeSetting")
    QSettings().clear()
    window = MainWindow()
    combo = window.settings_view.theme_combo
    kook_index = combo.findData("kook")

    assert kook_index >= 0
    combo.setCurrentIndex(kook_index)
    app.processEvents()

    assert QSettings().value("appearance/theme") == "kook"
    assert "#7acc35" in app.styleSheet()
    window.close()
    QSettings().clear()


def test_grid_columns_follow_view_mode_and_available_width() -> None:
    assert _photo_grid_columns(900, "compact", 168) == 4
    assert _photo_grid_columns(900, "large", 268) == 3
    assert _photo_grid_columns(900, "list", 136) == 1
    assert _photo_grid_columns(40, "compact", 168) == 1


def test_preview_cache_coalesces_concurrent_reads(tmp_path: Path) -> None:
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"placeholder")
    target = QSize(120, 80)
    call_count = 0
    call_lock = threading.Lock()

    def fake_read(_path: Path, _target: QSize) -> QImage:
        nonlocal call_count
        time.sleep(0.02)
        with call_lock:
            call_count += 1
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        return image

    with _preview_cache_lock:
        _preview_cache.clear()
        _preview_locks.clear()

    with patch("photo_fit_picker.ui._read_preview", side_effect=fake_read):
        with ThreadPoolExecutor(max_workers=8) as executor:
            images = list(
                executor.map(lambda _: _cached_preview(image_path, target), range(8))
            )

    assert call_count == 1
    assert all(not image.isNull() for image in images)
    assert not _get_cached_preview(image_path, target).isNull()


def test_preview_pool_is_dedicated_to_photo_loading() -> None:
    pool = _preview_pool()

    assert pool is not QThreadPool.globalInstance()
    assert pool.maxThreadCount() == 3


def test_demo_photos_load_prebuilt_groups_without_analysis(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("DemoPhotos")
    QSettings().clear()
    for name in (
        "02_lake_bright.jpg",
        "01_lake_clear.jpg",
        "03_lake_soft.jpg",
        "04_street_clear.jpg",
        "05_street_step.jpg",
        "06_street_dark.jpg",
        "07_coast_clear.jpg",
        "08_coast_shift.jpg",
        "09_coast_soft.jpg",
        "10_forest.jpg",
        "11_abstract.jpg",
    ):
        pixmap = QPixmap(24, 16)
        pixmap.fill(QColor("white"))
        assert pixmap.save(str(tmp_path / name), "JPG")

    window = MainWindow()
    with (
        patch("photo_fit_picker.ui._prepare_demo_folder", return_value=tmp_path),
        patch.object(window, "_start_analysis", side_effect=AssertionError),
    ):
        window._load_demo_photos()

    assert len(window.groups) == 5
    assert sum(len(group.photos) for group in window.groups) == 11
    assert window.analysis_thread is None
    window.close()
    QSettings().clear()


def test_singleton_groups_can_be_excluded_from_every_review_filter() -> None:
    neutral = tuple([1 / 48] * 48)
    photos = [
        PhotoRecord(
            path=Path(f"{index}.jpg"),
            width=1200,
            height=800,
            file_size=100,
            captured_at=datetime(2026, 1, 1),
            dhash=index,
            color_signature=neutral,
            sharpness=0.1,
            exposure=0.5,
        )
        for index in range(3)
    ]
    singleton = PhotoGroup(1, [photos[0]])
    similar = PhotoGroup(2, photos[1:])

    assert _filtered_photo_groups([singleton, similar], "all", False) == [
        singleton,
        similar,
    ]
    assert _filtered_photo_groups([singleton, similar], "all", True) == [similar]
    assert _filtered_photo_groups([singleton, similar], "pending", True) == [
        similar
    ]

    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("SingletonFilter")
    QSettings().clear()
    window = MainWindow()
    window.groups = [singleton, similar]
    window.settings_view.hide_singletons_toggle.setChecked(True)

    assert QSettings().value("review/hide_singletons", type=bool) is True
    assert window.hide_singleton_groups is True
    assert window.visible_groups == [similar]
    assert window.progress_count.text() == "0 / 2"
    assert "略过 1" in window.summary_label.text()
    window.close()
    QSettings().clear()


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


def test_large_photo_group_is_rendered_in_responsive_batches() -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("CardBatching")
    image_path = Path("demo-photos/01_lake_clear.jpg").resolve()
    neutral = tuple([1 / 48] * 48)
    photos = [
        PhotoRecord(
            path=image_path,
            width=1200,
            height=800,
            file_size=image_path.stat().st_size,
            captured_at=datetime(2026, 1, 1),
            dhash=index,
            color_signature=neutral,
            sharpness=0.1,
            exposure=0.5,
        )
        for index in range(CARD_RENDER_BATCH_SIZE + 10)
    ]
    window = MainWindow()
    window.groups = [PhotoGroup(1, photos)]
    window.visible_groups = window.groups
    window.group_list.addItem("01")

    window.group_list.setCurrentRow(0)

    assert len(window.cards) == CARD_RENDER_BATCH_SIZE
    assert not window.card_loading_progress.isHidden()
    for _ in range(100):
        if len(window.cards) == len(photos):
            break
        QTest.qWait(20)
    assert len(window.cards) == len(photos)
    assert not window.card_loading_progress.isVisible()
    window.close()


def test_new_review_round_resets_decisions_and_persisted_session(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("NewReviewRound")
    QSettings().clear()
    neutral = tuple([1 / 48] * 48)
    statuses = [
        ReviewStatus.KEPT,
        ReviewStatus.REJECTED,
        ReviewStatus.MOVED,
        ReviewStatus.TRASHED,
    ]
    photos = []
    for index, status in enumerate(statuses):
        path = tmp_path / f"photo-{index}.jpg"
        pixmap = QPixmap(8, 8)
        pixmap.fill(QColor("white"))
        assert pixmap.save(str(path), "JPG")
        photos.append(
            PhotoRecord(
                path=path,
                width=8,
                height=8,
                file_size=path.stat().st_size,
                captured_at=datetime(2026, 1, 1),
                dhash=index,
                color_signature=neutral,
                sharpness=0.1,
                exposure=0.5,
                status=status,
                selected=True,
            )
        )

    window = MainWindow()
    window.source_folder = tmp_path
    window.session_store = ReviewSessionStore(tmp_path / "sessions")
    window.groups = [PhotoGroup(1, photos)]
    window.group_filter.setCurrentIndex(window.group_filter.findData("all"))
    window._save_session_now()
    window.root_stack.setCurrentWidget(window.settings_view)

    with patch(
        "photo_fit_picker.ui.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        window._confirm_new_round()

    assert [photo.status for photo in photos] == [
        ReviewStatus.PENDING,
        ReviewStatus.PENDING,
        ReviewStatus.MOVED,
        ReviewStatus.TRASHED,
    ]
    assert all(not photo.selected for photo in photos)
    assert window.group_filter.currentData() == "pending"
    assert window.root_stack.currentWidget() is window.workspace
    assert not window.new_round_button.isEnabled()
    assert not window.settings_view.new_round_button.isEnabled()

    restored = [
        PhotoRecord(
            path=photo.path,
            width=photo.width,
            height=photo.height,
            file_size=photo.file_size,
            captured_at=photo.captured_at,
            dhash=photo.dhash,
            color_signature=photo.color_signature,
            sharpness=photo.sharpness,
            exposure=photo.exposure,
        )
        for photo in photos
    ]
    assert window.session_store.restore(tmp_path, restored) == 0
    assert all(photo.status == ReviewStatus.PENDING for photo in restored)
    window.close()
    QSettings().clear()


def test_cancelling_new_review_round_keeps_current_state() -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("PhotoFitPickerTests")
    app.setApplicationName("CancelNewReviewRound")
    neutral = tuple([1 / 48] * 48)
    photo = PhotoRecord(
        path=Path("unchanged.jpg"),
        width=1200,
        height=800,
        file_size=100,
        captured_at=datetime(2026, 1, 1),
        dhash=1,
        color_signature=neutral,
        sharpness=0.1,
        exposure=0.5,
        status=ReviewStatus.KEPT,
        selected=True,
    )
    window = MainWindow()
    window.groups = [PhotoGroup(1, [photo])]

    with patch(
        "photo_fit_picker.ui.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Cancel,
    ):
        window._confirm_new_round()

    assert photo.status == ReviewStatus.KEPT
    assert photo.selected
    window.close()
