from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from .analysis import analyze_paths, group_similar_photos
from .feature_cache import FeatureCache
from .models import AnalysisOptions


class AnalysisWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        paths: list[Path],
        options: AnalysisOptions,
        cache_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.options = options
        self.cache_path = cache_path
        self._cancelled = False

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            grouping_passes = 3 if self.options.detect_exact_duplicates else 1
            total_work = max(1, len(self.paths) * (1 + grouping_passes))
            records, failures = analyze_paths(
                self.paths,
                progress=lambda current, _total, filename: self.progress.emit(
                    current,
                    total_work,
                    f"读取特征 · {filename}",
                ),
                cancelled=lambda: self._cancelled,
                cache=FeatureCache(self.cache_path) if self.cache_path else None,
            )
            if self._cancelled:
                self.cancelled.emit()
                return
            self.progress.emit(len(self.paths), total_work, "正在整理相似照片…")
            groups = group_similar_photos(
                records,
                self.options,
                progress=lambda current, _total: self.progress.emit(
                    len(self.paths) + current,
                    total_work,
                    "正在整理相似照片…",
                ),
                cancelled=lambda: self._cancelled,
            )
            if self._cancelled:
                self.cancelled.emit()
                return
            self.progress.emit(total_work, total_work, "分析完成")
            self.finished.emit(groups, failures)
        except Exception as exc:
            self.failed.emit(str(exc))
