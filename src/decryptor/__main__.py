import sys


def main() -> None:
    cli_options = {"--device-id", "--user-idx", "-o", "--output", "--book", "--help", "-h"}
    if any(argument in cli_options for argument in sys.argv[1:]):
        from .core import main as cli
        raise SystemExit(cli())

    if sys.platform == "darwin":
        from .cocoa_window import run

        run()
        return

    from PySide6.QtWidgets import QApplication
    from .window import MainWindow, font

    app = QApplication(sys.argv)
    app.setFont(font())
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
