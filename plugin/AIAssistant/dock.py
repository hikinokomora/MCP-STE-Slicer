# -*- coding: utf-8 -*-
"""Chat window docked to the STE Slicer main window (Windows only).

The SPA is opened in Microsoft Edge in app mode (--app: no tabs, no address bar).
The Edge window is then:
  * placed over the right part of the slicer viewport (like a floating panel);
  * made an *owned* window of the slicer (GWLP_HWNDPARENT): it always stays above the
    slicer, minimizes and restores together with it, but does not cover other apps;
  * moved together with the slicer when the slicer window is moved or resized.
If Edge is not found (or we are not on Windows) the caller falls back to the default browser.
Python 3.5 compatible, standard library + PyQt5 only.
"""
import os
import subprocess
import sys

from UM.Logger import Logger

WINDOW_TITLE = "slicer assistant"  # must match <title> in web/index.html

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _SetWindowLongPtr = _user32.SetWindowLongPtrW
        _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        _SetWindowLongPtr.restype = ctypes.c_ssize_t
    else:
        _SetWindowLongPtr = _user32.SetWindowLongW
        _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        _SetWindowLongPtr.restype = ctypes.c_long

GWLP_HWNDPARENT = -8
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

# Panel placement relative to the slicer window (physical pixels at 100% scale; scaled by DPI below)
PANEL_WIDTH = 520
PANEL_MARGIN_RIGHT = 28
PANEL_MARGIN_TOP = 96       # below the slicer top bar
PANEL_MARGIN_BOTTOM = 70    # above the slicer bottom bar
PANEL_MIN_HEIGHT = 520


def find_edge():
    """Path to msedge.exe or None."""
    if sys.platform != "win32":
        return None
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _rect(hwnd):
    r = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def _find_chat_hwnd():
    """Top-level Edge (Chromium) window whose title is our page title."""
    found = []

    def callback(hwnd, _lparam):
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0 or not _user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        if WINDOW_TITLE not in buf.value.lower():
            return True
        cls = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, cls, 64)
        if cls.value.startswith("Chrome_WidgetWin"):
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return found[0] if found else None


class DockedChatWindow:
    """Opens the chat as an Edge app window and keeps it attached to the slicer window."""

    def __init__(self, app, profile_dir):
        self._app = app
        self._profile_dir = profile_dir
        self._edge = find_edge()
        self._chat = None          # HWND of the Edge window
        self._slicer = None        # HWND of the slicer main window
        self._last_slicer_rect = None
        self._placed = False
        self._timer = None
        self._wait_ticks = 0

    def available(self):
        return self._edge is not None

    # ------------------------------------------------------------------ public
    def open(self, url):
        """Show the docked chat. Returns False if the caller should fall back to a normal browser."""
        if not self.available():
            return False
        try:
            self._slicer = self._slicer_hwnd()
            existing = self._chat if self._chat and _user32.IsWindow(self._chat) else _find_chat_hwnd()
            if existing:
                self._chat = existing
                _user32.ShowWindow(existing, SW_RESTORE)
                _user32.SetForegroundWindow(existing)
                self._ensure_timer()
                return True
            self._launch(url)
            self._chat = None
            self._placed = False
            self._wait_ticks = 0
            self._ensure_timer()
            return True
        except Exception:
            Logger.logException("w", "AIAssistant: could not open docked chat window")
            return False

    def is_open(self):
        hwnd = self._chat if self._chat and _user32.IsWindow(self._chat) else _find_chat_hwnd()
        if hwnd:
            self._chat = hwnd
        return bool(hwnd)

    # ------------------------------------------------------------------ internals
    def _slicer_hwnd(self):
        window = self._app.getMainWindow()
        return int(window.winId()) if window is not None else None

    def _scale(self):
        try:
            window = self._app.getMainWindow()
            return float(window.devicePixelRatio()) if window is not None else 1.0
        except Exception:
            return 1.0

    def _target_rect(self, slicer_rect):
        left, top, right, bottom = slicer_rect
        s = self._scale()
        width = int(PANEL_WIDTH * s)
        height = max(int(PANEL_MIN_HEIGHT * s), (bottom - top) - int((PANEL_MARGIN_TOP + PANEL_MARGIN_BOTTOM) * s))
        x = right - width - int(PANEL_MARGIN_RIGHT * s)
        y = top + int(PANEL_MARGIN_TOP * s)
        return x, y, width, height

    def _launch(self, url):
        os.makedirs(self._profile_dir, exist_ok=True)
        args = [self._edge, "--app=" + url, "--user-data-dir=" + self._profile_dir,
                "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
        rect = _rect(self._slicer) if self._slicer else None
        if rect:
            x, y, w, h = self._target_rect(rect)
            s = self._scale() or 1.0  # Chromium takes DIPs here
            args += ["--window-position=%d,%d" % (int(x / s), int(y / s)),
                     "--window-size=%d,%d" % (int(w / s), int(h / s))]
        flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        subprocess.Popen(args, close_fds=True, creationflags=flags)
        Logger.log("i", "AIAssistant: opened chat in Edge app mode")

    def _ensure_timer(self):
        if self._timer is not None:
            if not self._timer.isActive():
                self._timer.start()
            return
        from PyQt5.QtCore import QTimer
        self._timer = QTimer()
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        """Runs on the Qt main thread: find the Edge window, attach it, follow the slicer."""
        try:
            if not self._slicer or not _user32.IsWindow(self._slicer):
                self._slicer = self._slicer_hwnd()
                if not self._slicer:
                    return
            if not self._chat or not _user32.IsWindow(self._chat):
                if self._chat:  # the user closed the chat window
                    self._chat = None
                    self._timer.stop()
                    return
                self._chat = _find_chat_hwnd()
                if not self._chat:
                    self._wait_ticks += 1
                    if self._wait_ticks > 120:  # ~30 s: Edge did not show up, stop looking
                        self._timer.stop()
                    return
                # owned window: stays above the slicer, minimizes with it
                _SetWindowLongPtr(self._chat, GWLP_HWNDPARENT, self._slicer)
                self._placed = False

            if _user32.IsIconic(self._slicer):
                return
            slicer_rect = _rect(self._slicer)
            if slicer_rect is None:
                return
            if not self._placed:
                x, y, w, h = self._target_rect(slicer_rect)
                _user32.SetWindowPos(self._chat, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
                self._placed = True
            elif self._last_slicer_rect and slicer_rect != self._last_slicer_rect:
                # keep the user's own position/size of the panel, just follow the slicer's right edge
                old = self._last_slicer_rect
                chat_rect = _rect(self._chat)
                if chat_rect:
                    dx = slicer_rect[2] - old[2]
                    dy = slicer_rect[1] - old[1]
                    _user32.SetWindowPos(self._chat, None, chat_rect[0] + dx, chat_rect[1] + dy, 0, 0,
                                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            self._last_slicer_rect = slicer_rect
        except Exception:
            Logger.logException("w", "AIAssistant: dock tick failed")
            if self._timer is not None:
                self._timer.stop()
