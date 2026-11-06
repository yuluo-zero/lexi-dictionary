# -*- coding: utf-8 -*-
"""Global selection watcher: low-level mouse hook + clipboard capture.

The hook thread only records mouse gestures. A worker thread waits for the
selection to settle, sends Ctrl+C, reads the copied text and puts the previous
clipboard content back (COM IDataObject when possible).
"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
CF_UNICODETEXT = 13
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
LowLevelMouseProc = HOOKPROC


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43

TERMINAL_EXES = {
    "windowsterminal.exe", "conhost.exe", "openconsole.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "mintty.exe", "alacritty.exe", "wezterm-gui.exe", "tabby.exe", "hyper.exe",
    "conemu64.exe", "conemu.exe",
}

SCREENSHOT_EXES = {
    "snippingtool.exe", "screensketch.exe", "screenclippinghost.exe", "snipaste.exe",
    "sharex.exe", "pixpin.exe", "greenshot.exe", "lightshot.exe",
}

user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.CopyImage.restype = wintypes.HANDLE
user32.CopyImage.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.GetDoubleClickTime.restype = wintypes.UINT
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
kernel32.GlobalFree.restype = ctypes.c_void_p
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

ole32.OleGetClipboard.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
ole32.OleSetClipboard.argtypes = [ctypes.c_void_p]
ole32.OleFlushClipboard.restype = ctypes.c_long


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _release_com(ptr):
    try:
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(ptr)
    except Exception:
        pass


def clipboard_text() -> str:
    for _ in range(8):
        if user32.OpenClipboard(None):
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                locked = kernel32.GlobalLock(handle)
                if not locked:
                    return ""
                try:
                    return ctypes.wstring_at(locked)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        time.sleep(0.012)
    return ""


CF_BITMAP, CF_METAFILEPICT, CF_DIB, CF_DIBV5 = 2, 3, 8, 17
CF_ENHMETAFILE, CF_HDROP = 14, 15
GMEM_MOVEABLE = 0x0002
_image_format_ids: list[int] = []


def _image_formats() -> list[int]:
    if not _image_format_ids:
        for name in ("PNG", "image/png"):
            fid = user32.RegisterClipboardFormatW(name)
            if fid:
                _image_format_ids.append(fid)
    return [CF_DIBV5, CF_DIB, *_image_format_ids]


def _global_bytes(handle) -> bytes:
    size = kernel32.GlobalSize(handle)
    if not size:
        return b""
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return b""
    try:
        return ctypes.string_at(ptr, size)
    finally:
        kernel32.GlobalUnlock(handle)


def _alloc_global(data: bytes):
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not handle:
        return None
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        return None
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle


def clipboard_formats():
    """List clipboard format ids, or None when the clipboard is busy."""
    formats = []
    if not user32.OpenClipboard(None):
        return None
    try:
        fmt = user32.EnumClipboardFormats(0)
        while fmt:
            formats.append(fmt)
            fmt = user32.EnumClipboardFormats(fmt)
    finally:
        user32.CloseClipboard()
    return formats


def _read_image_items() -> list[tuple[int, bytes]]:
    """Read image formats that can be handed back to the clipboard later."""
    items = []
    for fmt in _image_formats():
        handle = user32.GetClipboardData(fmt)
        if handle:
            data = _global_bytes(handle)
            if data:
                items.append((fmt, data))
    return items


def has_unrestorable_clipboard() -> bool:
    """True for content we cannot put back (files, metafiles, GDI-only bitmap)."""
    formats = clipboard_formats()
    if formats is None:
        return True
    if CF_HDROP in formats or CF_METAFILEPICT in formats or CF_ENHMETAFILE in formats:
        return True
    return False


def _set_clipboard(text: str, image_items: list[tuple[int, bytes]], bitmap=None) -> bool:
    if not user32.OpenClipboard(None):
        return False
    image_handles = []
    text_handle = None
    try:
        if text:
            text_handle = _alloc_global(text.encode("utf-16-le") + b"\x00\x00")
            if not text_handle:
                return False
        for fmt, data in image_items:
            handle = _alloc_global(data)
            if not handle:
                for _fmt, h in image_handles:
                    kernel32.GlobalFree(h)
                if text_handle:
                    kernel32.GlobalFree(text_handle)
                return False
            image_handles.append((fmt, handle))
        user32.EmptyClipboard()
        for fmt, handle in image_handles:
            user32.SetClipboardData(fmt, handle)
        if bitmap:
            if not user32.SetClipboardData(CF_BITMAP, bitmap):
                gdi32.DeleteObject(bitmap)
        if text_handle:
            user32.SetClipboardData(CF_UNICODETEXT, text_handle)
        return True
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    return _set_clipboard(text, [])


def send_ctrl_c():
    events = (INPUT * 4)()
    specs = [
        (VK_CONTROL, 0),
        (VK_C, 0),
        (VK_C, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]
    for i, (vk, flags) in enumerate(specs):
        events[i].type = INPUT_KEYBOARD
        events[i].ki.wVk = vk
        events[i].ki.wScan = 0
        events[i].ki.dwFlags = flags
        events[i].ki.time = 0
        events[i].ki.dwExtraInfo = 0
    user32.SendInput(4, events, ctypes.sizeof(INPUT))


class ClipboardSnapshot:
    """Remembers clipboard text, image bytes and bitmap so a lookup can restore them."""

    def __init__(self):
        self.text = ""
        self.items: list[tuple[int, bytes]] = []
        self.bitmap = None
        self.incomplete = False

    def save(self):
        self.text = ""
        self.items = []
        self.bitmap = None
        self.incomplete = False
        if not user32.OpenClipboard(None):
            self.incomplete = True
            return
        try:
            formats = []
            fmt = user32.EnumClipboardFormats(0)
            while fmt:
                formats.append(fmt)
                fmt = user32.EnumClipboardFormats(fmt)
            if CF_HDROP in formats or CF_METAFILEPICT in formats or CF_ENHMETAFILE in formats:
                self.incomplete = True
                return
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                ptr = kernel32.GlobalLock(handle)
                if ptr:
                    try:
                        self.text = ctypes.wstring_at(ptr)
                    finally:
                        kernel32.GlobalUnlock(handle)
            self.items = _read_image_items()
            hbmp = user32.GetClipboardData(CF_BITMAP)
            if hbmp:
                copy = user32.CopyImage(hbmp, 0, 0, 0, 0)
                if copy:
                    self.bitmap = copy
                else:
                    self.incomplete = True
        finally:
            user32.CloseClipboard()

    def restore(self):
        if not self.text and not self.items and not self.bitmap:
            return False
        return _set_clipboard(self.text, self.items, self.bitmap)

    def discard(self):
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None


class SelectionWatcher(QObject):
    selection = Signal(str, int, int, bool)
    clicked = Signal(int, int)
    plain_click = Signal()
    key_pressed = Signal()
    selection_blocked = Signal(str)

    def __init__(self, settings_getter, parent=None):
        super().__init__(parent)
        self.settings = settings_getter
        self.self_pid = os.getpid()
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._hook = None
        self._hook_thread_id = 0
        self._last_text = ""
        self._last_time = 0.0
        self._last_sel_at = 0.0
        self._double_until = 0.0
        self._last_down_time = 0.0
        self._last_down_pt = (0, 0)
        self._down_hwnd = 0
        self._enabled = True
        self.allow_hwnd = 0
        self.titlebar_h = 46
        self.sidebar_w = 214

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._enabled = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._hook_loop, name="lexi-hook", daemon=True)
        self._thread.start()
        self._worker = threading.Thread(target=self._worker_loop, name="lexi-select", daemon=True)
        self._worker.start()

    def stop(self):
        self._enabled = False
        self._stop.set()
        if self._hook_thread_id:
            user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
        self._hook_thread_id = 0

    def set_enabled(self, on: bool):
        self._enabled = on
        if on and not (self._thread and self._thread.is_alive()):
            self.start()

    def reset_dedupe(self):
        self._last_text = ""
        self._last_time = 0.0
        self._last_sel_at = 0.0

    # ------------------------------------------------------------------ hook
    def _emit_click(self, x: int, y: int):
        hwnd = user32.GetForegroundWindow()
        dpi = user32.GetDpiForWindow(hwnd) or 96
        scale = max(1.0, dpi / 96.0)
        self.clicked.emit(int(round(x / scale)), int(round(y / scale)))

    def _hook_loop(self):
        self._hook_thread_id = kernel32.GetCurrentThreadId()

        def callback(n_code, w_param, l_param):
            try:
                if n_code >= 0:
                    if w_param in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                        ms = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        self._emit_click(ms.pt.x, ms.pt.y)
                    if w_param == WM_LBUTTONDOWN:
                        ms = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        now = time.time()
                        is_double = (
                            now - self._last_down_time < user32.GetDoubleClickTime() / 1000.0
                            and abs(ms.pt.x - self._last_down_pt[0]) <= 10
                            and abs(ms.pt.y - self._last_down_pt[1]) <= 10
                        )
                        self._last_down_time = now
                        self._last_down_pt = (ms.pt.x, ms.pt.y)
                        self._down_hwnd = int(user32.GetForegroundWindow() or 0)
                        if is_double:
                            self._double_until = now + 0.6
                            log.info("double-click detected")
                        self._down = (ms.pt.x, ms.pt.y, now, is_double)
                    elif w_param == WM_LBUTTONDBLCLK:
                        ms = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        self._double_until = time.time() + 0.6
                        if hasattr(self, "_down"):
                            x, y, t, _ = self._down
                            self._down = (x, y, t, True)
                        # Double-click selects a word without a drag; queue it
                        # directly so the marker still appears if the final
                        # button-up event is swallowed by the target app.
                        log.info("double-click queued")
                        self._queue.put((ms.pt.x, ms.pt.y, 0, True))
                    elif w_param == WM_LBUTTONUP:
                        self._on_up()
            except Exception:
                pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = LowLevelMouseProc(callback)

        def key_callback(n_code, w_param, l_param):
            try:
                if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self.key_pressed.emit()
            except Exception:
                pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._key_proc = LowLevelMouseProc(key_callback)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self._key_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._key_proc, None, 0)
        log.info("mouse hook installed=%s keyboard hook=%s", bool(self._hook), bool(self._key_hook))
        if not self._hook:
            return
        msg = wintypes.MSG()
        while not self._stop.is_set():
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        if getattr(self, "_key_hook", None):
            user32.UnhookWindowsHookEx(self._key_hook)
        self._hook = None
        self._key_hook = None

    def _on_up(self):
        if not self._enabled or not hasattr(self, "_down"):
            return
        x0, y0, t0, double = self._down
        double = double or time.time() < self._double_until
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        moved = abs(pt.x - x0) + abs(pt.y - y0)
        duration = time.time() - t0
        if double or (moved > 6 and duration > 0.05):
            self._queue.put((pt.x, pt.y, moved, double))
        elif moved <= 6:
            self.plain_click.emit()

    # ------------------------------------------------------------------ worker
    def _worker_loop(self):
        try:
            ole32.OleInitialize(None)
        except Exception:
            pass
        while not self._stop.is_set():
            try:
                x, y, moved, double = self._queue.get(timeout=0.4)
            except queue.Empty:
                continue
            if not self._enabled:
                continue
            try:
                self._handle(x, y, moved, double)
            except Exception:
                pass

    def _handle(self, x, y, moved: int = 0, double: bool = False):
        if not self._enabled:
            return
        # A drag that starts in another app and is released over this app is
        # a text drop, not a selection.  The foreground window can still be
        # the source app at this point, so use WindowFromPoint to detect the
        # drop target.
        try:
            target = user32.WindowFromPoint(wintypes.POINT(x, y))
            tpid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(target, ctypes.byref(tpid))
            if (
                not double
                and tpid.value == self.self_pid
                and self._down_hwnd
                and int(self._down_hwnd) != int(self.allow_hwnd or 0)
            ):
                log.info("selection skipped: dropped into own window")
                return
        except Exception:
            pass
        hwnd = user32.GetForegroundWindow()
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not double and self._down_hwnd and int(hwnd or 0) != self._down_hwnd:
            log.info("selection skipped: cross-window drag")
            return
        if pid.value == self.self_pid:
            # Allow selections inside the dictionary's own content area (so
            # double-clicking a result word works), but never the title bar,
            # sidebar, bubble, marker or ball.
            if not self.allow_hwnd or int(hwnd or 0) != self.allow_hwnd:
                log.info("selection skipped: own auxiliary window")
                return
            if not double:
                # Allow selecting words/phrases inside the dictionary content
                # too; the marker is what makes the lookup explicit.
                pass
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            dpi = user32.GetDpiForWindow(hwnd) or 96
            scale = max(1.0, dpi / 96.0)
            if x < rect.left + self.sidebar_w * scale or y < rect.top + self.titlebar_h * scale:
                log.info("selection skipped: own chrome")
                return
        name = _process_name(pid.value)
        log.info("selection attempt fg=%s moved=%s double=%s", name or pid.value, moved, double)
        if name in TERMINAL_EXES and not self.settings().get("selection_in_terminals", False):
            log.info("selection skipped: terminal %s", name)
            return
        if name in SCREENSHOT_EXES:
            log.info("selection skipped: screenshot tool %s", name)
            return
        # Never overwrite an image / file clipboard: losing it would be worse
        # than skipping one lookup.
        if has_unrestorable_clipboard():
            self.selection_blocked.emit("剪贴板里有文件或对象，已暂停划词；复制一段文字后自动恢复")
            log.info("selection skipped: clipboard holds files/metafile, foreground=%s", name)
            return
        delay = int(self.settings().get("selection_delay_ms", 90) or 90)
        time.sleep(delay / 1000.0)
        # Screenshot tools copy the bitmap right after the drag ends; re-check
        # so we never steal a freshly taken screenshot.
        if has_unrestorable_clipboard():
            self.selection_blocked.emit("剪贴板里有文件或对象，已暂停划词；复制一段文字后自动恢复")
            log.info("selection skipped after delay: clipboard holds files/metafile")
            return
        seq0 = user32.GetClipboardSequenceNumber()
        snap = ClipboardSnapshot()
        restore = bool(self.settings().get("restore_clipboard", True))
        snap.save()
        if snap.incomplete:
            log.info("selection skipped: cannot snapshot clipboard safely")
            snap.discard()
            return
        def read_copy(seq):
            send_ctrl_c()
            end = time.time() + 0.6
            value = ""
            stable_count = 0
            while time.time() < end:
                if user32.GetClipboardSequenceNumber() != seq:
                    current = clipboard_text()
                    if current:
                        if current == value:
                            stable_count += 1
                            if stable_count >= 2:
                                break
                        else:
                            stable_count = 0
                            value = current
                time.sleep(0.015)
            if not value:
                value = clipboard_text()
            return value

        text = read_copy(seq0)
        if not text:
            # Some apps (and a fast double-click) need a second attempt.
            time.sleep(0.12)
            text = read_copy(user32.GetClipboardSequenceNumber())
        seq_after = user32.GetClipboardSequenceNumber()
        if restore and text:
            time.sleep(0.04)
            # Only put the old text back if our Ctrl+C really produced this text
            # and the user has not copied anything newer in the meantime.
            if seq_after == user32.GetClipboardSequenceNumber() and clipboard_text() == text:
                snap.restore()
        text = (text or "").strip("\x00\r\n\t ")
        text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
        text = text.strip()
        if not text or len(text) > 1200:
            return
        now = time.time()
        # A drag-and-drop finishes with Ctrl+C copying the drop target (chat
        # input), not the dragged selection. Such drops land in the input zone
        # at the bottom of the window and are usually shorter than the previous
        # selection, so do not raise the marker for them.
        if (
            not double and moved > 200
            and y > rect.top + (rect.bottom - rect.top) * 0.72
        ):
            log.info("selection skipped: drop into bottom input zone")
            self._last_text = ""
            self._last_sel_at = 0.0
            return
        self._last_sel_at = now
        self._last_text = text
        self._last_time = now
        # The hook reports physical pixels; Qt uses logical pixels. Convert with
        # the foreground window's DPI, otherwise the marker lands off-screen on
        # 150%/200% displays.
        dpi = user32.GetDpiForWindow(hwnd) or 96
        scale = max(1.0, dpi / 96.0)
        lx, ly = int(round(x / scale)), int(round(y / scale))
        log.info("selection captured len=%d at %d,%d (dpi=%d)", len(text), lx, ly, dpi)
        self.selection.emit(text, lx, ly, bool(double))
