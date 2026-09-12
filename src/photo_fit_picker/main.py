from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui import MainWindow, apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("拾影")
    app.setOrganizationName("PhotoFitPicker")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
