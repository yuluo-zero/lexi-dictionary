# -*- coding: utf-8 -*-
"""Entry point for 划词词典."""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QLocale, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import config


def setup_logging():
    config.ensure_dirs()
    logging.basicConfig(
        filename=os.path.join(config.LOG_DIR, "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    if sys.stderr is not None:
        logging.getLogger().addHandler(logging.StreamHandler())


def excepthook(exc_type, exc, tb):
    logging.error("uncaught", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def main() -> int:
    setup_logging()
    sys.excepthook = excepthook
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lexi.Dict.1")
    except Exception:
        pass

    QApplication.setApplicationName("划词词典")
    QApplication.setOrganizationName("Lexi")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(app.font())

    icon_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "app", "assets", "app.ico"
    )
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(icon_path))

    # single instance -------------------------------------------------------
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    user = os.environ.get("USERNAME", "user")
    name = "LexiDict-" + hashlib.md5(user.encode("utf-8")).hexdigest()[:10]
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(250):
        probe.write(b"show")
        probe.waitForBytesWritten(250)
        probe.disconnectFromServer()
        return 0

    server = QLocalServer()
    QLocalServer.removeServer(name)
    if not server.listen(name):
        logging.warning("local server listen failed: %s", server.errorString())

    from app.application import Application

    application = Application(app, start_hidden="--autostart" in sys.argv)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), application.show_window()))

    if "--search" in sys.argv:
        try:
            query = sys.argv[sys.argv.index("--search") + 1]
            QTimer.singleShot(500, lambda: application.lookup_word(query))
        except (IndexError, ValueError):
            pass

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
