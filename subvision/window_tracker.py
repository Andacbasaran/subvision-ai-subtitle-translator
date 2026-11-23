"""
SubVision AI — Target Application / Window Tracking & Foreground Gating.

Enumerates visible user windows and resolves the active foreground window using
pure 64-bit-safe Windows `ctypes` APIs (zero extra dependencies), with safe
no-op fallbacks on macOS and Linux.

Used to lock OCR capture to a specific game or application so Alt+Tabbing to a
browser/forum automatically pauses OCR and hides the overlay until the target
window regains focus.
"""

import os
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

# Multi-window apps (browsers, UWP host) where two different windows share one .exe.
# When a specific HWND is alive, we match by HWND so Alt+Tabbing from a video window
# to another browser window (e.g. a forum) pauses capture instead of OCR'ing the forum.
MULTI_WINDOW_HOSTS = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
        "vivaldi.exe",
        "arc.exe",
        "applicationframehost.exe",
    }
)

_IGNORED_TITLES = frozenset(
    {
        "program manager",
        "windows input experience",
        "default ime",
        "msctfime ui",
    }
)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str

    def display_label(self, max_title_len: int = 44) -> str:
        clean_title = " ".join((self.title or "").split())
        if len(clean_title) > max_title_len:
            clean_title = clean_title[: max_title_len - 1].rstrip() + "…"
        if clean_title and self.process_name:
            return f"{clean_title}  ({self.process_name})"
        return clean_title or self.process_name or f"HWND {self.hwnd}"


@dataclass(frozen=True)
class TargetWindowSpec:
    hwnd: int = 0
    process_name: str = ""
    title: str = ""

    @property
    def is_active(self) -> bool:
        return bool(self.hwnd or (self.process_name or "").strip() or (self.title or "").strip())

    def short_label(self) -> str:
        if self.process_name:
            return self.process_name
        clean_title = " ".join((self.title or "").split())
        if len(clean_title) > 28:
            clean_title = clean_title[:27].rstrip() + "…"
        return clean_title or "Hedef"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except Exception:
        _dwmapi = None

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL

    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL

    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL

    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int

    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int

    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND

    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long

    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE

    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    if _dwmapi is not None:
        _dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

    _GWL_EXSTYLE = -20
    _WS_EX_TOOLWINDOW = 0x00000080
    _WS_EX_APPWINDOW = 0x00040000
    _GA_ROOTOWNER = 3
    _DWMWA_CLOAKED = 14
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _query_process_name_by_pid(pid: int) -> str:
    if sys.platform != "win32" or not pid:
        return ""
    try:
        h_proc = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h_proc:
            return ""
        try:
            buf_size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            ok = _kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(buf_size))
            if ok and buf.value:
                return os.path.basename(buf.value).lower()
        finally:
            _kernel32.CloseHandle(h_proc)
    except Exception:
        return ""
    return ""


def _read_window_title(hwnd: int) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""
    try:
        length = int(_user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.strip()
    except Exception:
        return ""


def _is_window_cloaked(hwnd: int) -> bool:
    if sys.platform != "win32" or _dwmapi is None or not hwnd:
        return False
    try:
        cloaked = wintypes.DWORD(0)
        hr = _dwmapi.DwmGetWindowAttribute(
            hwnd,
            _DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return hr == 0 and bool(cloaked.value)
    except Exception:
        return False


def is_window_alive(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        return bool(_user32.IsWindow(hwnd))
    except Exception:
        return False


def get_root_owner_hwnd(hwnd: int) -> int:
    if sys.platform != "win32" or not hwnd:
        return 0
    try:
        root = _user32.GetAncestor(hwnd, _GA_ROOTOWNER)
        return int(root) if root else int(hwnd)
    except Exception:
        return int(hwnd)


def get_foreground_window_info() -> Optional[WindowInfo]:
    """Returns WindowInfo for the currently focused Windows window, or None."""
    if sys.platform != "win32":
        return None
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid_val = int(pid.value)
        proc = _query_process_name_by_pid(pid_val)
        title = _read_window_title(hwnd)
        return WindowInfo(hwnd=int(hwnd), pid=pid_val, process_name=proc, title=title)
    except Exception:
        return None


def list_visible_windows(exclude_own_pid: bool = True) -> List[WindowInfo]:
    """
    Enumerates visible top-level user windows in Z-order (most recently used first).
    Elevated/anti-cheat game windows are preserved even if OpenProcess returns 0
    (with process_name='') so HWND/title locking still works.
    """
    if sys.platform != "win32":
        return []

    own_pid = os.getpid() if exclude_own_pid else -1
    results: List[WindowInfo] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            ex_style = int(_user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
            if (ex_style & _WS_EX_TOOLWINDOW) and not (ex_style & _WS_EX_APPWINDOW):
                return True
            if _is_window_cloaked(hwnd):
                return True

            title = _read_window_title(hwnd)
            if not title or title.lower() in _IGNORED_TITLES:
                return True

            pid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_val = int(pid.value)
            if exclude_own_pid and pid_val == own_pid:
                return True

            proc = _query_process_name_by_pid(pid_val)
            results.append(
                WindowInfo(hwnd=int(hwnd), pid=pid_val, process_name=proc, title=title)
            )
        except Exception:
            pass
        return True

    try:
        cb = _WNDENUMPROC(_callback)
        _user32.EnumWindows(cb, 0)
    except Exception:
        return []
    return results


def is_target_foreground(
    target: Optional[TargetWindowSpec],
    fg: Optional[WindowInfo],
    own_pid: Optional[int] = None,
    window_alive_fn: Callable[[int], bool] = is_window_alive,
    root_owner_fn: Callable[[int], int] = get_root_owner_hwnd,
) -> bool:
    """
    Determines whether capture should run for the given target window lock.
    - Unlocked (`target is None` or `not target.is_active`): always True.
    - Target locked but foreground is unknown or belongs to SubVision itself: False.
    - Exact HWND or owned child dialog match: True.
    - Process name match: True for single-window apps/games; for multi-window
      browsers, falls back to process match only when saved HWND is no longer alive.
    - Title fallback: handles elevated/anti-cheat or UWP apps across restarts.
    """
    if target is None or not target.is_active:
        return True
    if fg is None:
        return False

    my_pid = os.getpid() if own_pid is None else own_pid
    if my_pid and fg.pid == my_pid:
        return False

    target_hwnd = int(target.hwnd or 0)
    target_proc = (target.process_name or "").strip().lower()
    target_title = (target.title or "").strip().lower()

    fg_hwnd = int(fg.hwnd or 0)
    fg_proc = (fg.process_name or "").strip().lower()
    fg_title = (fg.title or "").strip().lower()

    if target_hwnd and fg_hwnd:
        if fg_hwnd == target_hwnd:
            return True
        try:
            if root_owner_fn(fg_hwnd) == target_hwnd:
                return True
        except Exception:
            pass

    target_hwnd_alive = False
    if target_hwnd:
        try:
            target_hwnd_alive = bool(window_alive_fn(target_hwnd))
        except Exception:
            target_hwnd_alive = False

    if target_proc and fg_proc and fg_proc == target_proc:
        if target_proc not in MULTI_WINDOW_HOSTS:
            return True
        # For browsers, isolate by HWND while the chosen window is alive
        if not target_hwnd or not target_hwnd_alive:
            return True
        return False

    if (not target_proc or target_proc == "applicationframehost.exe") and target_title:
        if not target_hwnd or not target_hwnd_alive:
            if fg_title == target_title:
                return True

    return False
