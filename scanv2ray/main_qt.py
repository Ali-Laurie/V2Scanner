"""QApplication bootstrap for the PySide6 ScanV2Ray UI.

Loads fonts, applies the global stylesheet (after token substitution), builds
the main window and runs the event loop.  Mirrors the SNI-Spoofer main.py.
"""

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from .ui_qt import MainWindow, build_style


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('ScanV2Ray')

    # Base UI font — system sans (Segoe UI where present, else the platform default).
    app.setFont(QFont('Segoe UI', 10))

    # Apply the global stylesheet once, after token substitution.
    app.setStyleSheet(build_style())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
