from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .analysis import analyze_paths, group_similar_photos
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
    ) -> None:
        super().__init__()
        self.paths = paths
        self.options = options
        self._cancelled = False

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            records, failures = analyze_paths(
                self.paths,
                progress=self.progress.emit,
                cancelled=lambda: self._cancelled,
            )
            if self._cancelled:
                self.cancelled.emit()
                return
            self.progress.emit(len(self.paths), len(self.paths), "正在整理相似照片…")
            groups = group_similar_photos(
                records,
                self.options,
            )
            self.finished.emit(groups, failures)
        except Exception as exc:
            self.failed.emit(str(exc))
