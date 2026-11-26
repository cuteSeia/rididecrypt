import sys

from PySide6.QtWidgets import QApplication

from .window import MainWindow, font


def main() -> None:
    if len(sys.argv) > 1:
        from .core import main as cli
        raise SystemExit(cli())
    app = QApplication(sys.argv)
    app.setFont(font())
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
