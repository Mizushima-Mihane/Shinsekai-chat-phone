"""Legacy Qt/PySide6 phone UI — retained but dormant.

The React phone (../frontend/dist/index.html + ../webface.py + ../phone_core.py)
is the active implementation. Modules in this package are only imported when a
Qt GUI host is present (see ``_qt_ui_active()`` in ``plugin.py``); the Tauri /
React desktop path never touches them. See README.md in this directory.
"""
