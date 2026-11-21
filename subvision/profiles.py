"""
SubVision AI — Per-App / Game Profiles & Multi-ROI Manager.

Allows saving multiple named profiles (each with its own ROI, OCR mode,
overlay mode, color, glossary pack, and optional `.exe` process binding)
and automatically detects the foreground Windows process via pure `ctypes`
(zero extra dependencies).
"""

import ctypes
import os
import sys
from typing import Dict, List, Optional


def get_foreground_process_name() -> Optional[str]:
    """
    Returns the lowercase executable name (e.g. 'vlc.exe', 'chrome.exe', 'rdr2.exe')
    of the currently focused Windows application, or None on unsupported OS / error.
    """
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_proc:
            return None
        try:
            buf_size = ctypes.c_ulong(1024)
            buf = ctypes.create_unicode_buffer(1024)
            ok = kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(buf_size))
            if ok and buf.value:
                return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h_proc)
    except Exception:
        return None
    return None


class ProfileManager:
    """Manages named per-game/per-app ROI & appearance profiles inside user settings."""

    DEFAULT_PROFILE_NAME = "Varsayılan"

    def __init__(self, profiles_dict: Optional[Dict[str, dict]] = None):
        self.profiles: Dict[str, dict] = {}
        if isinstance(profiles_dict, dict):
            for name, cfg in profiles_dict.items():
                if isinstance(name, str) and name.strip() and isinstance(cfg, dict):
                    self.profiles[name.strip()] = dict(cfg)

    def list_names(self) -> List[str]:
        names = list(self.profiles.keys())
        if self.DEFAULT_PROFILE_NAME not in names:
            names.insert(0, self.DEFAULT_PROFILE_NAME)
        return names

    def save_profile(
        self,
        name: str,
        roi: Dict[str, int],
        ocr_mode: str,
        overlay_mode: str,
        text_color: str,
        glossary_pack: str = "none",
        process_name: str = "",
    ) -> None:
        clean_name = (name or "").strip() or self.DEFAULT_PROFILE_NAME
        self.profiles[clean_name] = {
            "roi": dict(roi),
            "ocr_mode": ocr_mode,
            "overlay_mode": overlay_mode,
            "text_color": text_color,
            "glossary_pack": glossary_pack,
            "process_name": (process_name or "").strip().lower(),
        }

    def get_profile(self, name: str) -> Optional[dict]:
        return self.profiles.get(name)

    def delete_profile(self, name: str) -> bool:
        if name == self.DEFAULT_PROFILE_NAME:
            return False
        return self.profiles.pop(name, None) is not None

    def match_process(self, process_name: Optional[str]) -> Optional[str]:
        """Returns the first profile name bound to the given executable name."""
        if not process_name:
            return None
        target = process_name.strip().lower()
        if not target:
            return None
        for prof_name, cfg in self.profiles.items():
            bound = str(cfg.get("process_name") or "").strip().lower()
            if bound and bound == target:
                return prof_name
        return None

    def to_dict(self) -> Dict[str, dict]:
        return {k: dict(v) for k, v in self.profiles.items()}
