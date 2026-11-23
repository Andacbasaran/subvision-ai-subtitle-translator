"""
SubVision AI Studio — Oyunlar, Diziler, Filmler ve Yayınlar İçin Evrensel Lokal (EN -> TR) Anlık Altyazı Çevirici
Mimari: Uyarlanabilir CTranslate2 (INT8/FP32) + RapidOCR (ONNX CPU) + Opsiyonel Bağlam/Ses Katmanı + Şeffaf Overlay
"""

import ctypes
import json
import os
import sys
import time
import traceback
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QRect, QSize, QThread, QTimer, Qt
from PyQt6.QtGui import QAction, QFont, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from hardware import (
    HardwareProfile,
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    RuntimeTuning,
    apply_thread_env_defaults,
    compute_runtime_tuning,
    detect_hardware_profile,
    format_hardware_summary,
    get_app_base_dir,
    get_ui_font_family,
    get_writable_data_dir,
)
from ocr_engine import SubtitleOCREngine
from overlay_ui import ROISelectorOverlay, SubtitleOverlayWindow
from subvision import __version__
from subvision.audio_whisper import AudioCaptureTranslateWorker, detect_audio_capabilities
from subvision.context_translator import (
    BACKEND_DEEPL,
    BACKEND_GEMINI,
    BACKEND_LOCAL_CT2,
    BACKEND_OLLAMA,
    BACKEND_OPENAI_COMPAT,
    ContextAwareTranslator,
    ContextBackendConfig,
    DEFAULT_ENDPOINTS,
    DEFAULT_MODELS,
)
from subvision.custom_glossary import CustomGlossaryManager
from subvision.exporters import (
    HistoryEntry,
    export_history_to_anki_csv,
    export_history_to_srt,
)
from subvision.i18n import LanguageManager
from subvision.profiles import ProfileManager, get_foreground_process_name
from subvision.window_tracker import (
    TargetWindowSpec,
    WindowInfo,
    list_visible_windows,
)
from subvision.ui_widgets import (
    ColorDotSwatch,
    FlatComboBox,
    FlatSwitch,
    SidebarNavButton,
    TelemetryCard,
    create_app_icon,
    create_app_pixmap,
    make_flat_icon,
)
from subvision.updater import (
    UpdateCheckerThread,
    UpdateDownloadThread,
    UpdateInfo,
    apply_downloaded_update,
)
from subvision.workers import (
    BenchmarkWorker,
    CaptureTranslateWorker,
    LatestTextSlot,
    ModelLoaderThread,
)
from translator import LocalEnTrTranslator

APP_TITLE = f"SubVision AI v{__version__} — Real-Time Subtitle Studio (EN -> TR)"
DATA_DIR = get_writable_data_dir()
CONFIG_PATH = os.path.join(DATA_DIR, "user_settings.json")
CRASH_LOG_PATH = os.path.join(DATA_DIR, "crash.log")

# Windows Global Hotkey Sabitleri (Admin yetkisi gerektirmez)
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_FUNCTION_KEYS: Dict[str, int] = {f"F{i}": 0x6F + i for i in range(1, 13)}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(create_app_icon())

        # Studio 2.0 geniş ekran sol kenar çubuklu modern pencere boyutu
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        min_w = min(820, max(720, avail.width() - 40))
        min_h = min(560, max(500, avail.height() - 40))
        init_w = min(960, max(min_w, avail.width() - 60))
        init_h = min(636, max(min_h, avail.height() - 60))
        self.setMinimumSize(min_w, min_h)
        self.resize(init_w, init_h)

        self.settings = self._load_settings()
        self.i18n = LanguageManager(self.settings.get("ui_language", "tr"))
        self.profile_manager = ProfileManager(self.settings.get("profiles"))
        self.custom_glossary = CustomGlossaryManager()
        self.custom_glossary.set_active_pack(str(self.settings.get("glossary_pack", "none")))
        self._hotkeys: Dict[str, str] = {
            "roi": str((self.settings.get("hotkeys") or {}).get("roi", "F7")),
            "toggle": str((self.settings.get("hotkeys") or {}).get("toggle", "F8")),
            "sample": str((self.settings.get("hotkeys") or {}).get("sample", "F9")),
        }
        self._history_entries: List[HistoryEntry] = []
        self._session_start_ts: float = time.monotonic()
        self._force_quit: bool = False
        self._last_auto_proc: str = ""
        self.tray_icon: Optional[QSystemTrayIcon] = None

        self.roi: Dict[str, int] = self._validate_roi(self.settings.get("roi"))
        self._resume_after_roi = False
        self._restore_window_after_roi = False
        self._restore_overlay_after_roi = False
        self._retired_workers: List[QThread] = []

        saved_target_proc = str(self.settings.get("target_app_process", "") or "").strip().lower()
        saved_target_title = str(self.settings.get("target_app_title", "") or "").strip()
        self._target_window: Optional[TargetWindowSpec] = (
            TargetWindowSpec(hwnd=0, process_name=saved_target_proc, title=saved_target_title)
            if (saved_target_proc or saved_target_title)
            else None
        )

        # Evrensel Donanım & İşlemci (CPU / ISA) Algılama + Uyarlanabilir Çalışma Profili
        self.hw_profile: HardwareProfile = detect_hardware_profile(query_ct2=True)
        saved_perf_profile = self.settings.get("performance_profile", PROFILE_AUTO)
        self.tuning: RuntimeTuning = compute_runtime_tuning(self.hw_profile, saved_perf_profile)
        apply_thread_env_defaults(self.tuning)

        self._local_translator = LocalEnTrTranslator(
            cpu_threads=self.tuning.nmt_threads,
            compute_type_candidates=self.tuning.compute_type_candidates,
        )
        self.translator = ContextAwareTranslator(
            local_translator=self._local_translator,
            config=self._build_context_config_from_settings(),
            custom_glossary=self.custom_glossary,
        )

        saved_ocr_mode = self.settings.get("ocr_mode", self.tuning.default_ocr_mode)
        self.ocr_engine = SubtitleOCREngine(
            use_color_mask=(saved_ocr_mode != "full_ocr"),
            ocr_mode=saved_ocr_mode,
            tuning=self.tuning,
            lazy_init=True,
        )
        self.worker: Optional[CaptureTranslateWorker] = None
        self.audio_worker: Optional[AudioCaptureTranslateWorker] = None
        self.bench_worker: Optional[BenchmarkWorker] = None
        self.update_thread: Optional[UpdateCheckerThread] = None
        self._latest_release_url: str = ""

        self.overlay = SubtitleOverlayWindow()
        self.roi_selector = ROISelectorOverlay(
            on_selected=self._on_roi_selected,
            on_cancelled=self._on_roi_cancelled,
        )

        default_overlay_mode = "cover" if self.hw_profile.capture_exclude_supported else "above"
        self._selected_color = self.settings.get("text_color", "#F59E0B")
        self._selected_overlay_mode = self.settings.get("overlay_mode", default_overlay_mode)

        # Oyun, Dizi, Film ve Belgesellerden Gerçekçi Test Diyalogları
        self._sample_idx = 0
        self._samples: List[Tuple[str, str]] = [
            (
                "Dizi / Drama",
                "Detective: Everything we found in that room points to a much bigger conspiracy.",
            ),
            (
                "Oyun / RPG",
                "Arthur: Stay close to me, the woods ahead are crawling with bounty hunters.",
            ),
            (
                "Bilim Kurgu",
                "Commander: If we cross the event horizon, there's no turning back for any of us.",
            ),
            (
                "Belgesel",
                "For centuries, this ancient civilization remained completely hidden beneath the jungle.",
            ),
            (
                "Aksiyon",
                "Hold on tight! I'm gonna take the shortcut through the old tunnel!",
            ),
            (
                "Gerilim",
                "We need to talk before they realize what really happened last night.",
            ),
        ]

        self._build_ui()
        self._apply_saved_appearance()
        self.overlay.show()
        self.overlay.align_to_roi(self.roi)

        self._register_global_hotkeys()
        self._setup_system_tray()
        self._auto_profile_timer = QTimer(self)
        self._auto_profile_timer.setInterval(2000)
        self._auto_profile_timer.timeout.connect(self._check_foreground_profile)
        if self.settings.get("auto_switch_profiles", False):
            self._auto_profile_timer.start()

        self._start_model_loading()
        if self.settings.get("check_updates_on_startup", True):
            QTimer.singleShot(2500, lambda: self.check_for_updates_async(silent=True))

    def _build_context_config_from_settings(self) -> ContextBackendConfig:
        return ContextBackendConfig(
            backend=str(self.settings.get("translation_backend", BACKEND_LOCAL_CT2)),
            endpoint=str(self.settings.get("translation_endpoint", "")),
            model=str(self.settings.get("translation_model", "")),
            api_key=str(self.settings.get("translation_api_key", "")),
            context_window=int(self.settings.get("context_window", 3)),
            timeout_sec=float(self.settings.get("context_timeout_sec", 3.0)),
        )

    def _default_roi(self) -> Dict[str, int]:
        screen = QGuiApplication.primaryScreen()
        dpr = 1.0 if sys.platform == "darwin" else (screen.devicePixelRatio() if screen else 1.0)
        sg = screen.geometry() if screen else None
        sw = sg.width() if sg else 1920
        sh = sg.height() if sg else 1080

        w = int(sw * 0.56)
        h = 105
        x = (sw - w) // 2
        y = sh - h - 65
        return {
            "left": int(x * dpr),
            "top": int(y * dpr),
            "width": int(w * dpr),
            "height": int(h * dpr),
            "qt_left": x,
            "qt_top": y,
            "qt_width": w,
            "qt_height": h,
        }

    def _validate_roi(self, raw_roi: object) -> Dict[str, int]:
        if not isinstance(raw_roi, dict):
            return self._default_roi()
        try:
            left = int(round(raw_roi["left"]))
            top = int(round(raw_roi["top"]))
            width = max(40, int(round(raw_roi["width"])))
            height = max(18, int(round(raw_roi["height"])))
            qt_left = int(round(raw_roi.get("qt_left", left)))
            qt_top = int(round(raw_roi.get("qt_top", top)))
            qt_width = max(40, int(round(raw_roi.get("qt_width", width))))
            qt_height = max(18, int(round(raw_roi.get("qt_height", height))))
            if sys.platform == "darwin":
                # macOS'ta MSS mantıksal nokta koordinatlarını kullanır;
                # eski 2x Retina ölçekli kayıtları otomatik onar.
                left, top, width, height = qt_left, qt_top, qt_width, qt_height
            return {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "qt_left": qt_left,
                "qt_top": qt_top,
                "qt_width": qt_width,
                "qt_height": qt_height,
            }
        except Exception:
            return self._default_roi()

    def _load_settings(self) -> dict:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_settings(self) -> None:
        data = {
            "roi": self.roi,
            "font_size": self.slider_font.value(),
            "bg_alpha": self.slider_alpha.value(),
            "text_color": self._selected_color,
            "overlay_mode": self._selected_overlay_mode,
            "ocr_mode": self.combo_ocr_mode.currentData(),
            "performance_profile": self.combo_perf_profile.currentData(),
            "show_bilingual": self.chk_bilingual.isChecked(),
            "auto_fit_font": self.chk_autofit.isChecked(),
            "ui_language": self.combo_ui_lang.currentData() if hasattr(self, "combo_ui_lang") else self.i18n.lang,
            "translation_backend": self.combo_tr_backend.currentData() if hasattr(self, "combo_tr_backend") else BACKEND_LOCAL_CT2,
            "translation_endpoint": self.edit_tr_endpoint.text().strip() if hasattr(self, "edit_tr_endpoint") else "",
            "translation_model": self.edit_tr_model.text().strip() if hasattr(self, "edit_tr_model") else "",
            "translation_api_key": self.edit_tr_apikey.text().strip() if hasattr(self, "edit_tr_apikey") else "",
            "input_source": self.combo_input_source.currentData() if hasattr(self, "combo_input_source") else "ocr",
            "whisper_model": self.combo_whisper_model.currentData() if hasattr(self, "combo_whisper_model") else "tiny.en",
            "check_updates_on_startup": self.chk_auto_update.isChecked() if hasattr(self, "chk_auto_update") else True,
            "glossary_pack": self.combo_glossary_pack.currentData() if hasattr(self, "combo_glossary_pack") else self.custom_glossary.active_pack_id,
            "profiles": self.profile_manager.to_dict(),
            "auto_switch_profiles": self.chk_auto_profile.isChecked() if hasattr(self, "chk_auto_profile") else False,
            "hotkeys": dict(self._hotkeys),
            "minimize_to_tray": self.chk_minimize_tray.isChecked() if hasattr(self, "chk_minimize_tray") else False,
            "target_app_process": self._target_window.process_name if self._target_window else "",
            "target_app_title": self._target_window.title if self._target_window else "",
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _format_hw_badge_text(self) -> str:
        ctype = self.translator.active_compute_type.upper()
        return (
            f"{self.hw_profile.short_cpu_label}  ·  "
            f"{self.hw_profile.physical_cores}C/{self.hw_profile.logical_cores}T  ·  "
            f"{ctype} ({self.translator.cpu_threads}T)  ·  "
            f"{self.tuning.scan_fps} FPS  ·  0 MB VRAM"
        )

    def _build_ui(self) -> None:
        ui_font = get_ui_font_family()
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#centralWidget, QScrollArea {{
                background-color: #0A0A0C;
                color: #FAFAFA;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
            }}
            QLabel {{
                background-color: transparent;
                color: #E4E4E7;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
            }}
            QFrame#sidebarRail {{
                background-color: #111113;
                border: none;
                border-right: 1px solid #222227;
            }}
            QFrame#studioPanel {{
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 10px;
            }}
            QFrame#stagePanel {{
                background-color: #111114;
                border: 1px solid #24242A;
                border-radius: 11px;
            }}
            QFrame#stepCard {{
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 10px;
            }}
            QPushButton {{
                background-color: #1B1B21;
                color: #E4E4E7;
                border: 1px solid #2B2B34;
                border-radius: 7px;
                padding: 7px 13px;
                font-size: 8.8pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #23232B;
                border-color: #3F3F4A;
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: #16161B;
            }}
            QPushButton:disabled {{
                background-color: #121216;
                color: #52525B;
                border-color: #1E1E24;
            }}
            QComboBox {{
                background-color: #141417;
                border: 1px solid #26262E;
                border-radius: 8px;
                padding: 6px 26px 6px 11px;
                min-height: 22px;
                color: #FAFAFA;
                font-size: 8.8pt;
                font-weight: 500;
            }}
            QComboBox:hover {{
                border-color: #3F3F4A;
                background-color: #1A1A20;
            }}
            QComboBox:disabled {{
                color: #52525B;
                background-color: #121215;
                border-color: #1E1E24;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #16161A;
                color: #F4F4F5;
                selection-background-color: #272730;
                selection-color: #FFFFFF;
                border: 1px solid #32323C;
                outline: none;
                padding: 4px;
            }}
            QSlider {{
                background-color: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 3px;
                background: #27272E;
                border-radius: 1px;
            }}
            QSlider::sub-page:horizontal {{
                background: #FAFAFA;
                border-radius: 1px;
            }}
            QSlider::handle:horizontal {{
                background: #FAFAFA;
                border: 1px solid #09090B;
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #F59E0B;
                border-color: #09090B;
            }}
            QListWidget {{
                background-color: #101013;
                border: 1px solid #222228;
                border-radius: 8px;
                color: #E4E4E7;
                font-size: 9pt;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 0px;
                border-bottom: 1px solid #1E1E24;
                border-radius: 6px;
                margin-bottom: 2px;
            }}
            QListWidget::item:hover {{
                background-color: #17171C;
            }}
            QListWidget::item:selected {{
                background-color: #1F1F26;
                color: #FFFFFF;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: #2A2A32;
                border-radius: 2px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #52525E;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            """
        )

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ═════════════════════════════════════════════════════════════════════
        # 1. SOL NAVİGASYON RAYI (218 px — Studio 2.0 Sidebar)
        # ═════════════════════════════════════════════════════════════════════
        sidebar = QFrame()
        sidebar.setObjectName("sidebarRail")
        sidebar.setFixedWidth(218)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(14, 18, 14, 14)
        sb_lay.setSpacing(18)

        # Marka Başlığı (Konsept A · Cinema Frame)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 2, 0)
        brand_row.setSpacing(10)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(30))
        logo_lbl.setFixedSize(30, 30)
        logo_lbl.setStyleSheet("border: none; background: transparent;")
        brand_row.addWidget(logo_lbl)

        brand_txt_col = QVBoxLayout()
        brand_txt_col.setSpacing(0)
        brand_top = QHBoxLayout()
        brand_top.setSpacing(6)

        title_lbl = QLabel("SubVision")
        title_lbl.setFont(QFont(ui_font, 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FAFAFA; letter-spacing: -0.2px;")
        brand_top.addWidget(title_lbl)

        ver_lbl = QLabel(f"v{__version__}")
        ver_lbl.setStyleSheet("color: #71717A; font-size: 7.5pt; font-weight: 600;")
        brand_top.addWidget(ver_lbl)
        brand_top.addStretch(1)
        brand_txt_col.addLayout(brand_top)

        sub_lbl = QLabel("Subtitle Studio")
        sub_lbl.setStyleSheet("color: #71717A; font-size: 7.6pt; font-weight: 500;")
        brand_txt_col.addWidget(sub_lbl)

        brand_row.addLayout(brand_txt_col, stretch=1)
        sb_lay.addLayout(brand_row)

        # Navigasyon Öğeleri (Stüdyo / Görünüm / Geçmiş / Ayarlar)
        nav_col = QVBoxLayout()
        nav_col.setSpacing(4)

        self.btn_tab_main = SidebarNavButton(self.i18n.t("tab_studio"))
        self.btn_tab_appearance = SidebarNavButton(self.i18n.t("tab_appearance"))
        self.btn_tab_history = SidebarNavButton(self.i18n.t("tab_history"))
        self.btn_tab_settings = SidebarNavButton(self.i18n.t("tab_settings"))

        for idx, b in enumerate(
            (
                self.btn_tab_main,
                self.btn_tab_appearance,
                self.btn_tab_history,
                self.btn_tab_settings,
            )
        ):
            b.clicked.connect(lambda checked=False, i=idx: self._switch_tab(i))
            nav_col.addWidget(b)

        sb_lay.addLayout(nav_col)
        sb_lay.addStretch(1)

        # Alt Sabit Yardımcı Bölge: Motor Durum Kartı + Kısayol Tuşları
        status_card = QFrame()
        status_card.setStyleSheet(
            """
            QFrame {
                background-color: #151519;
                border: 1px solid #24242A;
                border-radius: 8px;
            }
            """
        )
        sc_lay = QVBoxLayout(status_card)
        sc_lay.setContentsMargins(11, 10, 11, 10)
        sc_lay.setSpacing(6)

        st_top = QHBoxLayout()
        st_top.setSpacing(7)
        self._status_dot = QFrame()
        self._status_dot.setFixedSize(7, 7)
        self._status_dot.setStyleSheet("background-color: #F59E0B; border-radius: 3px; border: none;")
        st_top.addWidget(self._status_dot)

        self.lbl_model_status = QLabel("Hazırlanıyor...")
        self.lbl_model_status.setStyleSheet(
            "color: #FAFAFA; font-size: 8.4pt; font-weight: 600; border: none; background: transparent;"
        )
        st_top.addWidget(self.lbl_model_status, stretch=1)
        sc_lay.addLayout(st_top)

        self.lbl_engine_meta = QLabel(
            f"{self.translator.active_compute_type.upper()} · {self.tuning.scan_fps} FPS · 0 MB VRAM"
        )
        self.lbl_engine_meta.setStyleSheet(
            "color: #71717A; font-size: 7.2pt; font-weight: 600; border: none; background: transparent;"
        )
        sc_lay.addWidget(self.lbl_engine_meta)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 1px;
                background-color: #24242A;
            }
            QProgressBar::chunk {
                background-color: #FAFAFA;
                border-radius: 1px;
            }
            """
        )
        sc_lay.addWidget(self.progress_bar)
        sb_lay.addWidget(status_card)

        # Kısayol Tuş Rozetleri (F7 · F8 · F9)
        hk_footer = QHBoxLayout()
        hk_footer.setContentsMargins(0, 0, 0, 0)
        hk_footer.setSpacing(4)
        self._hk_cap_labels: Dict[str, QLabel] = {}
        for hk_id, hk_name in (("roi", "Alan"), ("toggle", "Başlat"), ("sample", "Test")):
            pair = QHBoxLayout()
            pair.setSpacing(3)
            cap = QLabel(self._hotkeys.get(hk_id, "F7"))
            cap.setStyleSheet(
                "color: #D4D4D8; background-color: #1B1B21; border: 1px solid #2B2B34; "
                "border-radius: 4px; padding: 1px 4px; font-size: 7pt; font-weight: 700;"
            )
            self._hk_cap_labels[hk_id] = cap
            pair.addWidget(cap)
            nm = QLabel(hk_name)
            nm.setStyleSheet("color: #71717A; font-size: 7.2pt; font-weight: 500;")
            pair.addWidget(nm)
            hk_footer.addLayout(pair)
            if hk_id != "sample":
                hk_footer.addStretch(1)
        sb_lay.addLayout(hk_footer)

        root_layout.addWidget(sidebar)

        # ═════════════════════════════════════════════════════════════════════
        # 2. SAĞ ANA ÇALIŞMA TUVALİ (QStackedWidget)
        # ═════════════════════════════════════════════════════════════════════
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background-color: #0A0A0C; border: none; }")
        root_layout.addWidget(self.stack, stretch=1)

        # ─────────────────────────────────────────────────────────────────────
        # SAYFA 0: STÜDYO (Tek Satır Komut Çubuğu + Canlı Sahne + Hızlı Kontroller)
        # ─────────────────────────────────────────────────────────────────────
        page_main = QWidget()
        page_main.setObjectName("studioPage")
        page_main.setStyleSheet("QWidget#studioPage { background-color: #0A0A0C; }")
        page_main_lay = QVBoxLayout(page_main)
        page_main_lay.setContentsMargins(22, 18, 22, 18)
        page_main_lay.setSpacing(14)

        # A) TEK SATIR KOMUT ÇUBUĞU (Hedef Uygulama + Alan Seç + Başlat CTA)
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(9)

        # Hedef Uygulama Seçici Çerçevesi
        target_wrap = QFrame()
        target_wrap.setToolTip(self.i18n.t("target_app_tooltip"))
        target_wrap.setStyleSheet(
            """
            QFrame {
                background-color: #141417;
                border: 1px solid #26262E;
                border-radius: 8px;
            }
            """
        )
        tw_lay = QHBoxLayout(target_wrap)
        tw_lay.setContentsMargins(10, 3, 5, 3)
        tw_lay.setSpacing(7)

        self._target_dot = QFrame()
        self._target_dot.setFixedSize(7, 7)
        self._target_dot.setStyleSheet("background-color: #52525B; border-radius: 3px; border: none;")
        tw_lay.addWidget(self._target_dot)

        self.combo_target_app = FlatComboBox(on_before_popup=self._refresh_target_windows)
        self.combo_target_app.setMinimumHeight(30)
        self.combo_target_app.setStyleSheet(
            """
            QComboBox {
                background-color: transparent;
                border: none;
                padding: 4px 24px 4px 2px;
                color: #FAFAFA;
                font-size: 8.8pt;
                font-weight: 600;
            }
            QComboBox:disabled {
                color: #71717A;
                background-color: transparent;
            }
            """
        )
        self.combo_target_app.setToolTip(self.i18n.t("target_app_tooltip"))
        self.combo_target_app.currentIndexChanged.connect(self._on_target_app_changed)
        tw_lay.addWidget(self.combo_target_app, stretch=1)

        self.btn_refresh_windows = QPushButton("")
        self.btn_refresh_windows.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_windows.setIcon(make_flat_icon("refresh", "#A1A1AA", 12))
        self.btn_refresh_windows.setIconSize(QSize(12, 12))
        self.btn_refresh_windows.setFixedSize(28, 28)
        self.btn_refresh_windows.setToolTip(self.i18n.t("target_app_refresh"))
        self.btn_refresh_windows.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #202027;
                border-color: #32323D;
            }
            """
        )
        self.btn_refresh_windows.clicked.connect(self._refresh_target_windows)
        tw_lay.addWidget(self.btn_refresh_windows)

        cmd_row.addWidget(target_wrap, stretch=1)

        # Alan Seç Butonu (Kompakt ROI Boyutu Dahil)
        self.btn_select_roi = QPushButton(f"  Alan Seç   {self.roi['width']}×{self.roi['height']}")
        self.btn_select_roi.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_roi.setIcon(make_flat_icon("target", "#D4D4D8", 13))
        self.btn_select_roi.setIconSize(QSize(13, 13))
        self.btn_select_roi.setMinimumHeight(38)
        self.btn_select_roi.setToolTip("Altyazı bölgesini seçin (F7)")
        self.btn_select_roi.setStyleSheet(
            """
            QPushButton {
                background-color: #141417;
                border: 1px solid #26262E;
                border-radius: 8px;
                color: #E4E4E7;
                padding: 0 13px;
                font-size: 8.8pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1D1D23;
                border-color: #3F3F4A;
                color: #FFFFFF;
            }
            """
        )
        self.btn_select_roi.clicked.connect(self.open_roi_selector)
        cmd_row.addWidget(self.btn_select_roi)

        # Ana Yüksek Kontrastlı Düz Beyaz Başlat CTA (F8)
        self.btn_toggle = QPushButton("  Başlat   F8")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setIcon(make_flat_icon("play", "#09090B", 12))
        self.btn_toggle.setIconSize(QSize(12, 12))
        self.btn_toggle.setMinimumHeight(38)
        self.btn_toggle.setMinimumWidth(124)
        self.btn_toggle.setEnabled(False)
        self._set_toggle_button_style(active=False)
        self.btn_toggle.clicked.connect(self.toggle_translation)
        cmd_row.addWidget(self.btn_toggle)

        page_main_lay.addLayout(cmd_row)

        # Geriye dönük uyumluluk gizli/senkron referansları
        self.lbl_roi_badge = QLabel(f"{self.roi['width']} × {self.roi['height']} px")
        self.lbl_scene_tag = QLabel(f"Otomatik · {self.tuning.scan_fps} FPS")
        self.lbl_target_hint = QLabel("")

        # B) CANLI SİNEMA ÖNİZLEME SAHNESİ (Sıkı Hizalamalı Altyazı Pill'i ile)
        live_card = QFrame()
        live_card.setObjectName("stagePanel")
        live_lay = QVBoxLayout(live_card)
        live_lay.setContentsMargins(16, 14, 16, 16)
        live_lay.setSpacing(12)

        live_hdr = QHBoxLayout()
        live_hdr.setSpacing(8)
        lbl_live_title = QLabel("CANLI ÖNİZLEME")
        lbl_live_title.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        live_hdr.addWidget(lbl_live_title)

        self.lbl_toggle_desc = QLabel("Sıkı Hizalama · Alt+Tab Korumalı")
        self.lbl_toggle_desc.setStyleSheet(
            "color: #A1A1AA; background-color: #1B1B20; border: none; border-radius: 4px; "
            "padding: 2px 8px; font-size: 7.5pt; font-weight: 500;"
        )
        live_hdr.addWidget(self.lbl_toggle_desc)
        live_hdr.addStretch(1)

        ghost_btn_css = (
            "QPushButton { background-color: #19191E; color: #D4D4D8; border: 1px solid #2A2A32; "
            "padding: 4px 10px; font-size: 8pt; font-weight: 600; border-radius: 6px; }"
            "QPushButton:hover { background-color: #23232A; border-color: #3F3F4A; color: #FFFFFF; }"
            "QPushButton:disabled { color: #52525B; border-color: #1E1E24; background-color: #121215; }"
        )

        self.btn_test = QPushButton(" Örnek (F9)")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.setIcon(make_flat_icon("preview", "#D4D4D8", 12))
        self.btn_test.setIconSize(QSize(12, 12))
        self.btn_test.setEnabled(False)
        self.btn_test.setStyleSheet(ghost_btn_css)
        self.btn_test.clicked.connect(self.run_sample_test)
        live_hdr.addWidget(self.btn_test)

        btn_copy = QPushButton(" Kopyala")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setIcon(make_flat_icon("copy", "#A1A1AA", 12))
        btn_copy.setIconSize(QSize(12, 12))
        btn_copy.setStyleSheet(ghost_btn_css)
        btn_copy.clicked.connect(self._copy_current_translation)
        live_hdr.addWidget(btn_copy)
        live_lay.addLayout(live_hdr)

        # İç Sinematik Sahne (Koyu Mat Zemin + Ortalanmış Sıkı Altyazı Pill'i)
        self.preview_box = QFrame()
        self.preview_box.setMinimumHeight(180)
        self.preview_box.setStyleSheet(
            """
            QFrame {
                background-color: #09090B;
                border: 1px solid #1E1E24;
                border-radius: 8px;
            }
            """
        )
        prev_v = QVBoxLayout(self.preview_box)
        prev_v.setContentsMargins(22, 22, 22, 22)
        prev_v.setSpacing(12)
        prev_v.addStretch(1)

        self.lbl_en_preview = QLabel(
            "Altyazı bekleniyor — test etmek için Örnek (F9) butonunu kullanabilirsiniz."
        )
        self.lbl_en_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_en_preview.setWordWrap(True)
        prev_v.addWidget(self.lbl_en_preview)

        pill_row = QHBoxLayout()
        pill_row.addStretch(1)
        self.tight_preview_pill = QFrame()
        pill_lay = QHBoxLayout(self.tight_preview_pill)
        pill_lay.setContentsMargins(16, 8, 16, 8)
        self.lbl_tr_preview = QLabel(
            "Türkçe çeviri orijinal altyazı boyutunda burada görünür."
        )
        self.lbl_tr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_tr_preview.setWordWrap(True)
        pill_lay.addWidget(self.lbl_tr_preview)
        pill_row.addWidget(self.tight_preview_pill)
        pill_row.addStretch(1)
        prev_v.addLayout(pill_row)
        prev_v.addStretch(1)

        self.lbl_mini_en = self.lbl_en_preview
        self.lbl_mini_tr = self.lbl_tr_preview

        live_lay.addWidget(self.preview_box, stretch=1)
        page_main_lay.addWidget(live_card, stretch=1)

        # C) HIZLI GÖRÜNÜM KONTROL ŞERİDİ (Figma Frame 02 ile birebir)
        style_card = QFrame()
        style_card.setObjectName("studioPanel")
        style_lay = QVBoxLayout(style_card)
        style_lay.setContentsMargins(16, 13, 16, 13)
        style_lay.setSpacing(12)

        # Satır 1: Dairesel Renk Noktaları (Sol) & Yerleşim Segmenti (Sağ)
        ctrl_r1 = QHBoxLayout()
        ctrl_r1.setSpacing(10)

        lbl_col_title = QLabel("Renk")
        lbl_col_title.setStyleSheet("color: #A1A1AA; font-size: 8.4pt; font-weight: 600;")
        ctrl_r1.addWidget(lbl_col_title)

        self._color_buttons: Dict[str, ColorDotSwatch] = {}
        color_presets = [
            ("#F59E0B", "Sinema Amber"),
            ("#FAFAFA", "Saf Beyaz"),
            ("#38BDF8", "Buz Turkuaz"),
            ("#34D399", "Nane Yeşili"),
        ]
        for hex_code, label_txt in color_presets:
            dot_btn = ColorDotSwatch(hex_code, tooltip=label_txt)
            dot_btn.clicked.connect(lambda checked=False, c=hex_code: self._select_color_swatch(c))
            self._color_buttons[hex_code] = dot_btn
            ctrl_r1.addWidget(dot_btn)

        ctrl_r1.addStretch(1)

        seg_frame = QFrame()
        seg_frame.setStyleSheet(
            "QFrame { background-color: #0E0E11; border: 1px solid #24242A; border-radius: 7px; }"
        )
        pos_row = QHBoxLayout(seg_frame)
        pos_row.setContentsMargins(3, 3, 3, 3)
        pos_row.setSpacing(2)
        self.btn_mode_cover = QPushButton("Üstünü Kapat")
        self.btn_mode_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        if not self.hw_profile.capture_exclude_supported:
            self.btn_mode_cover.setToolTip(
                "Bu işletim sistemi sürümünde WDA_EXCLUDEFROMCAPTURE desteklenmediği için "
                "OCR döngüsünü önlemek adına 'Üstünde' konumu otomatik uygulanır."
            )
        self.btn_mode_above = QPushButton("Üstünde")
        self.btn_mode_above.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_cover.clicked.connect(lambda: self._select_overlay_mode("cover"))
        self.btn_mode_above.clicked.connect(lambda: self._select_overlay_mode("above"))
        pos_row.addWidget(self.btn_mode_cover)
        pos_row.addWidget(self.btn_mode_above)
        ctrl_r1.addWidget(seg_frame)
        style_lay.addLayout(ctrl_r1)

        # Satır 2: İki Saç Teli Slider + Kompakt Anahtarlar
        ctrl_r2 = QHBoxLayout()
        ctrl_r2.setSpacing(14)

        self.lbl_font_cap = QLabel("Boyut")
        self.lbl_font_cap.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 500;")
        ctrl_r2.addWidget(self.lbl_font_cap)

        self.slider_font = QSlider(Qt.Orientation.Horizontal)
        self.slider_font.setRange(14, 36)
        self.slider_font.setMinimumWidth(86)
        init_font_size = max(14, min(36, int(round(self.settings.get("font_size", 22)))))
        self.slider_font.setValue(init_font_size)
        self.slider_font.valueChanged.connect(self._on_appearance_changed)
        ctrl_r2.addWidget(self.slider_font, stretch=1)

        self.lbl_font_val = QLabel(f"{init_font_size} pt")
        self.lbl_font_val.setMinimumWidth(36)
        self.lbl_font_val.setStyleSheet("color: #FAFAFA; font-size: 8.3pt; font-weight: 700;")
        ctrl_r2.addWidget(self.lbl_font_val)

        lbl_alpha_cap = QLabel("Opaklık")
        lbl_alpha_cap.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 500;")
        ctrl_r2.addWidget(lbl_alpha_cap)

        init_alpha = max(90, min(250, int(round(self.settings.get("bg_alpha", 225)))))
        self.slider_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(90, 250)
        self.slider_alpha.setMinimumWidth(86)
        self.slider_alpha.setValue(init_alpha)
        self.slider_alpha.valueChanged.connect(self._on_appearance_changed)
        ctrl_r2.addWidget(self.slider_alpha, stretch=1)

        self.lbl_alpha_val = QLabel(f"%{int(init_alpha / 255 * 100)}")
        self.lbl_alpha_val.setMinimumWidth(34)
        self.lbl_alpha_val.setStyleSheet("color: #FAFAFA; font-size: 8.3pt; font-weight: 700;")
        ctrl_r2.addWidget(self.lbl_alpha_val)

        self.chk_bilingual = FlatSwitch("EN + TR")
        self.chk_bilingual.setChecked(bool(self.settings.get("show_bilingual", False)))
        self.chk_bilingual.toggled.connect(self._on_appearance_changed)
        ctrl_r2.addWidget(self.chk_bilingual)

        self.chk_autofit = FlatSwitch("Otomatik Sığdır")
        self.chk_autofit.setChecked(bool(self.settings.get("auto_fit_font", True)))
        self.chk_autofit.toggled.connect(self._on_appearance_changed)
        ctrl_r2.addWidget(self.chk_autofit)

        style_lay.addLayout(ctrl_r2)
        page_main_lay.addWidget(style_card)

        self._refresh_target_windows()
        self.stack.addWidget(page_main)

        # ─────────────────────────────────────────────────────────────────────
        # SAYFA 1: GÖRÜNÜM STÜDYOSU (Dinamik Sıkı Hizalama & Ön Ayarlar)
        # ─────────────────────────────────────────────────────────────────────
        page_appear = QWidget()
        page_appear.setObjectName("appearPage")
        page_appear.setStyleSheet("QWidget#appearPage { background-color: #0A0A0C; }")
        app_lay = QVBoxLayout(page_appear)
        app_lay.setContentsMargins(22, 18, 22, 18)
        app_lay.setSpacing(14)

        app_hdr = QHBoxLayout()
        lbl_app_h = QLabel("Görünüm & Dinamik Hizalama")
        lbl_app_h.setStyleSheet("color: #FAFAFA; font-size: 13pt; font-weight: 700;")
        app_hdr.addWidget(lbl_app_h)
        app_hdr.addStretch(1)

        self.chk_guide = FlatSwitch("Hizalama çerçevesini göster")
        self.chk_guide.setChecked(False)
        self.chk_guide.toggled.connect(self.overlay.set_guide_border)
        app_hdr.addWidget(self.chk_guide)
        app_lay.addLayout(app_hdr)

        # Dinamik Sıkı Hizalama Canlı Karşılaştırma Kartı (Figma Frame 04 uyarlaması)
        sim_card = QFrame()
        sim_card.setObjectName("studioPanel")
        sim_lay = QVBoxLayout(sim_card)
        sim_lay.setContentsMargins(16, 14, 16, 16)
        sim_lay.setSpacing(12)

        sim_lbl = QLabel("ORİJİNAL ALTYAZI ÜZERİNE SIKI HİZALAMA ÖNİZLEMESİ")
        sim_lbl.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        sim_lay.addWidget(sim_lbl)

        sim_row = QHBoxLayout()
        sim_row.setSpacing(12)

        def _make_sim_box(title_txt: str, sample_txt: str, caption_txt: str):
            box = QFrame()
            box.setStyleSheet(
                "QFrame { background-color: #0E0E11; border: 1px solid #222228; border-radius: 8px; }"
            )
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 10, 12, 12)
            bl.setSpacing(10)
            t = QLabel(title_txt)
            t.setStyleSheet("color: #A1A1AA; font-size: 8.2pt; font-weight: 600; border: none;")
            bl.addWidget(t)

            roi_sim = QFrame()
            roi_sim.setMinimumHeight(74)
            roi_sim.setStyleSheet(
                "QFrame { background-color: #09090B; border: 1px dashed #3A3424; border-radius: 6px; }"
            )
            rl = QHBoxLayout(roi_sim)
            rl.setContentsMargins(10, 10, 10, 10)
            rl.addStretch(1)
            pill = QLabel(sample_txt)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rl.addWidget(pill)
            rl.addStretch(1)
            bl.addWidget(roi_sim)

            c = QLabel(caption_txt)
            c.setWordWrap(True)
            c.setStyleSheet("color: #71717A; font-size: 7.8pt; border: none;")
            bl.addWidget(c)
            return box, pill

        sim_short_box, self._sim_short_pill = _make_sim_box(
            "1. Kısa Replik · Sıfır Ekstra Alan",
            "Bekle!",
            "Orijinal 'Wait!' kelimesi algılandığında yalnızca kelimenin kendi genişliği boyanır; geri kalan alan şeffaf kalır.",
        )
        sim_long_box, self._sim_long_pill = _make_sim_box(
            "2. Uzun Çeviri · Kontrollü Genişleme",
            "Bir saniye bekle, sakın hareket etme!",
            "Türkçe çeviri orijinal cümleden uzadığında orijinali %100 örterek yalnızca gerektiği kadar genişler.",
        )
        sim_row.addWidget(sim_short_box, stretch=1)
        sim_row.addWidget(sim_long_box, stretch=1)
        sim_lay.addLayout(sim_row)
        app_lay.addWidget(sim_card)

        # Hızlı Sinema Ön Ayarları Kartı
        preset_card = QFrame()
        preset_card.setObjectName("studioPanel")
        pr_lay = QVBoxLayout(preset_card)
        pr_lay.setContentsMargins(16, 14, 16, 14)
        pr_lay.setSpacing(10)
        lbl_pr = QLabel("HIZLI GÖRÜNÜM ÖN AYARLARI")
        lbl_pr.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        pr_lay.addWidget(lbl_pr)

        pr_row = QHBoxLayout()
        pr_row.setSpacing(10)
        presets = [
            ("Sinema Amber", "#F59E0B", 22, 225, False, True),
            ("Minimal Beyaz", "#FAFAFA", 21, 200, False, True),
            ("Yüksek Kontrast", "#38BDF8", 24, 245, False, True),
            ("Çift Dilli (EN+TR)", "#F59E0B", 20, 235, True, True),
        ]
        for pname, pcol, psize, palpha, pbi, pauto in presets:
            pb = QPushButton(f" {pname}")
            pb.setCursor(Qt.CursorShape.PointingHandCursor)
            pb.setIcon(make_flat_icon("dot", pcol, 9))
            pb.setIconSize(QSize(9, 9))
            pb.setMinimumHeight(36)
            pb.clicked.connect(
                lambda checked=False, c=pcol, s=psize, a=palpha, bi=pbi, au=pauto: self._apply_style_preset(
                    c, s, a, bi, au
                )
            )
            pr_row.addWidget(pb, stretch=1)
        pr_lay.addLayout(pr_row)
        app_lay.addWidget(preset_card)
        app_lay.addStretch(1)

        self.stack.addWidget(page_appear)

        # ─────────────────────────────────────────────────────────────────────
        # SAYFA 2: DİYALOG GEÇMİŞİ
        # ─────────────────────────────────────────────────────────────────────
        page_hist_wrap = QWidget()
        page_hist_wrap.setObjectName("historyPage")
        page_hist_wrap.setStyleSheet("QWidget#historyPage { background-color: #0A0A0C; }")
        hw_lay = QVBoxLayout(page_hist_wrap)
        hw_lay.setContentsMargins(22, 18, 22, 18)
        hw_lay.setSpacing(12)

        hist_hdr = QHBoxLayout()
        hist_hdr.setSpacing(8)
        lbl_hist = QLabel("Diyalog Geçmişi")
        lbl_hist.setStyleSheet("color: #FAFAFA; font-size: 13pt; font-weight: 700;")
        hist_hdr.addWidget(lbl_hist)
        hist_hdr.addStretch(1)

        export_btn_css = (
            "QPushButton { background-color: #19191E; color: #D4D4D8; border: 1px solid #2A2A32; "
            "padding: 5px 11px; font-size: 8pt; font-weight: 600; border-radius: 6px; }"
            "QPushButton:hover { background-color: #23232A; color: #FFFFFF; border-color: #3F3F4A; }"
        )
        btn_export_srt = QPushButton("SRT Dışa Aktar")
        btn_export_srt.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export_srt.setStyleSheet(export_btn_css)
        btn_export_srt.clicked.connect(self._export_history_srt)
        hist_hdr.addWidget(btn_export_srt)

        btn_export_anki = QPushButton("Anki CSV")
        btn_export_anki.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export_anki.setStyleSheet(export_btn_css)
        btn_export_anki.clicked.connect(self._export_history_anki)
        hist_hdr.addWidget(btn_export_anki)

        btn_clear_hist = QPushButton("Temizle")
        btn_clear_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_hist.setStyleSheet(
            """
            QPushButton {
                background-color: #19191E;
                color: #A1A1AA;
                border: 1px solid #2A2A32;
                padding: 5px 11px;
                font-size: 8pt;
                font-weight: 600;
                border-radius: 6px;
            }
            QPushButton:hover {
                color: #F87171;
                border-color: #7F1D1D;
                background-color: #1F1215;
            }
            """
        )
        btn_clear_hist.clicked.connect(self._clear_history)
        hist_hdr.addWidget(btn_clear_hist)
        hw_lay.addLayout(hist_hdr)

        self.list_history = QListWidget()
        self.list_history.setWordWrap(True)
        self.list_history.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list_history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_history.itemClicked.connect(self._on_history_item_clicked)
        hw_lay.addWidget(self.list_history, stretch=1)

        self.stack.addWidget(page_hist_wrap)

        # ─────────────────────────────────────────────────────────────────────
        # SAYFA 3: AYARLAR & TELEMETRİ (Figma Frame 03 ile birebir)
        # ─────────────────────────────────────────────────────────────────────
        page_settings_scroll = QScrollArea()
        page_settings_scroll.setWidgetResizable(True)
        page_settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_settings_scroll.setStyleSheet("QScrollArea { background: #0A0A0C; border: none; }")
        page_settings = QWidget()
        page_settings.setObjectName("settingsPage")
        page_settings.setStyleSheet("QWidget#settingsPage { background-color: #0A0A0C; }")
        settings_lay = QVBoxLayout(page_settings)
        settings_lay.setContentsMargins(22, 18, 20, 18)
        settings_lay.setSpacing(14)

        # Başlık + Donanım Özeti Rozeti
        set_hdr = QHBoxLayout()
        lbl_set_title = QLabel("Ayarlar & Telemetri")
        lbl_set_title.setStyleSheet("color: #FAFAFA; font-size: 13pt; font-weight: 700;")
        set_hdr.addWidget(lbl_set_title)
        set_hdr.addStretch(1)

        self.hw_badge = QLabel(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.hw_badge.setStyleSheet(
            "color: #A1A1AA; background-color: #141417; border: 1px solid #24242A; "
            "border-radius: 6px; padding: 4px 10px; font-size: 7.5pt; font-weight: 600;"
        )
        set_hdr.addWidget(self.hw_badge)
        settings_lay.addLayout(set_hdr)

        # 4 Telemetri Kartı
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self.card_ocr = TelemetryCard(
            "OCR OKUMA",
            "FAST MASK",
            "— ms",
            f"Kare Kilidi · {self.tuning.ocr_intra_threads}T",
            "#FAFAFA",
            18,
        )
        self.card_nmt = TelemetryCard(
            f"ÇEVİRİ ({self.translator.active_compute_type.upper()})",
            f"{self.translator.cpu_threads}T",
            "— ms",
            "Opus-MT EN → TR",
            "#F59E0B",
            40,
        )
        self.card_total = TelemetryCard(
            "TOPLAM",
            "REAL-TIME",
            "— ms",
            "Hedef < 150 ms",
            "#22C55E",
            50,
        )
        self.card_stats = TelemetryCard(
            "OTURUM",
            f"{self.tuning.scan_fps} FPS",
            "0 Çeviri",
            f"ROI {self.roi['width']}×{self.roi['height']} · %0",
            "#A1A1AA",
            10,
        )

        kpi_row.addWidget(self.card_ocr)
        kpi_row.addWidget(self.card_nmt)
        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_stats)
        settings_lay.addLayout(kpi_row)

        def _make_setting_row(label_text: str, widget: QWidget) -> QHBoxLayout:
            r = QHBoxLayout()
            r.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #D4D4D8; font-size: 8.6pt; font-weight: 500;")
            r.addWidget(lbl, stretch=1)
            widget.setMinimumWidth(360)
            r.addWidget(widget, stretch=2)
            return r

        # Kart 1: Algılama & Çeviri Motoru (Yatay Satırlı Düz Düzen)
        engine_card = QFrame()
        engine_card.setObjectName("studioPanel")
        eng_lay = QVBoxLayout(engine_card)
        eng_lay.setContentsMargins(16, 14, 16, 14)
        eng_lay.setSpacing(10)

        lbl_eng_title = QLabel("ALGILAMA & ÇEVİRİ MOTORU")
        lbl_eng_title.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        eng_lay.addWidget(lbl_eng_title)

        self.combo_ocr_mode = FlatComboBox()
        self.combo_ocr_mode.addItem("Kontürlü / Adaptif Maske — Oyun & Dizi (Önerilen)", "fast_mask")
        self.combo_ocr_mode.addItem("Akıllı Hibrit — Oyun, Dizi & Açık Zemin", "hybrid")
        self.combo_ocr_mode.addItem("Tam Kare Okuma — Genel Video & Yayın", "full_ocr")
        self.combo_ocr_mode.currentIndexChanged.connect(self._on_ocr_mode_changed)
        eng_lay.addLayout(_make_setting_row("Altyazı Okuma (OCR) Modu", self.combo_ocr_mode))

        self.combo_perf_profile = FlatComboBox()
        self.combo_perf_profile.addItem("Otomatik — Bilgisayara Göre En İyi (Önerilen)", PROFILE_AUTO)
        self.combo_perf_profile.addItem("Eko — Düşük İşlemci Kullanımı (15 FPS)", PROFILE_ECO)
        self.combo_perf_profile.addItem("Dengeli — Standart Akıcılık (24 FPS)", PROFILE_BALANCED)
        self.combo_perf_profile.addItem("Performans — Maksimum Akıcılık (30 FPS)", PROFILE_PERFORMANCE)
        self.combo_perf_profile.currentIndexChanged.connect(self._on_perf_profile_changed)
        eng_lay.addLayout(_make_setting_row("İşlemci Hız Profili", self.combo_perf_profile))

        self.combo_tr_backend = FlatComboBox()
        self.combo_tr_backend.addItem(self.i18n.t("backend_local"), BACKEND_LOCAL_CT2)
        self.combo_tr_backend.addItem(self.i18n.t("backend_ollama"), BACKEND_OLLAMA)
        self.combo_tr_backend.addItem(self.i18n.t("backend_gemini"), BACKEND_GEMINI)
        self.combo_tr_backend.addItem(self.i18n.t("backend_deepl"), BACKEND_DEEPL)
        self.combo_tr_backend.addItem(self.i18n.t("backend_openai"), BACKEND_OPENAI_COMPAT)
        saved_backend = self.settings.get("translation_backend", BACKEND_LOCAL_CT2)
        for i in range(self.combo_tr_backend.count()):
            if self.combo_tr_backend.itemData(i) == saved_backend:
                self.combo_tr_backend.setCurrentIndex(i)
                break
        self.combo_tr_backend.currentIndexChanged.connect(self._on_translation_backend_changed)
        eng_lay.addLayout(_make_setting_row("Çeviri Katmanı", self.combo_tr_backend))

        # Harici / Ollama Bağlam Alanları (Yalnızca yerel dışı seçilince açılır)
        ai_grid = QGridLayout()
        ai_grid.setHorizontalSpacing(10)
        ai_grid.setVerticalSpacing(6)
        input_css = (
            "QLineEdit { background-color: #101013; border: 1px solid #2A2A32; "
            "border-radius: 7px; padding: 6px 10px; color: #F4F4F5; font-size: 8.4pt; }"
            "QLineEdit:focus { border: 1px solid #52525E; }"
        )
        self.edit_tr_endpoint = QLineEdit(self.settings.get("translation_endpoint", ""))
        self.edit_tr_endpoint.setPlaceholderText(self.i18n.t("backend_endpoint"))
        self.edit_tr_endpoint.setStyleSheet(input_css)
        self.edit_tr_endpoint.editingFinished.connect(self._on_translation_backend_changed)
        ai_grid.addWidget(self.edit_tr_endpoint, 0, 0)

        self.edit_tr_model = QLineEdit(self.settings.get("translation_model", ""))
        self.edit_tr_model.setPlaceholderText(self.i18n.t("backend_model"))
        self.edit_tr_model.setStyleSheet(input_css)
        self.edit_tr_model.editingFinished.connect(self._on_translation_backend_changed)
        ai_grid.addWidget(self.edit_tr_model, 0, 1)

        self.edit_tr_apikey = QLineEdit(self.settings.get("translation_api_key", ""))
        self.edit_tr_apikey.setPlaceholderText(self.i18n.t("backend_apikey"))
        self.edit_tr_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_tr_apikey.setStyleSheet(input_css)
        self.edit_tr_apikey.editingFinished.connect(self._on_translation_backend_changed)
        ai_grid.addWidget(self.edit_tr_apikey, 1, 0)

        self.btn_test_backend = QPushButton(self.i18n.t("backend_test_btn"))
        self.btn_test_backend.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_backend.setMinimumHeight(30)
        self.btn_test_backend.clicked.connect(self._on_test_translation_backend)
        ai_grid.addWidget(self.btn_test_backend, 1, 1)
        eng_lay.addLayout(ai_grid)

        # Giriş Kaynağı (OCR vs Whisper Ses)
        src_wrap = QWidget()
        src_row = QHBoxLayout(src_wrap)
        src_row.setContentsMargins(0, 0, 0, 0)
        src_row.setSpacing(8)
        self.combo_input_source = FlatComboBox()
        self.combo_input_source.addItem(self.i18n.t("source_ocr"), "ocr")
        self.combo_input_source.addItem(self.i18n.t("source_audio"), "audio")
        saved_src = self.settings.get("input_source", "ocr")
        for i in range(self.combo_input_source.count()):
            if self.combo_input_source.itemData(i) == saved_src:
                self.combo_input_source.setCurrentIndex(i)
                break
        self.combo_input_source.currentIndexChanged.connect(lambda _: self._save_settings())
        src_row.addWidget(self.combo_input_source, stretch=2)

        self.combo_whisper_model = FlatComboBox()
        for wm in ("tiny.en", "base.en", "small.en"):
            self.combo_whisper_model.addItem(f"Whisper {wm}", wm)
        saved_wm = self.settings.get("whisper_model", "tiny.en")
        for i in range(self.combo_whisper_model.count()):
            if self.combo_whisper_model.itemData(i) == saved_wm:
                self.combo_whisper_model.setCurrentIndex(i)
                break
        self.combo_whisper_model.currentIndexChanged.connect(lambda _: self._save_settings())
        src_row.addWidget(self.combo_whisper_model, stretch=1)
        eng_lay.addLayout(_make_setting_row("Giriş Kaynağı", src_wrap))

        audio_caps = detect_audio_capabilities()
        lbl_audio_status = QLabel(
            self.i18n.t("audio_ready") if audio_caps.is_ready else self.i18n.t("audio_missing")
        )
        lbl_audio_status.setWordWrap(True)
        lbl_audio_status.setStyleSheet(
            f"color: {'#22C55E' if audio_caps.is_ready else '#71717A'}; font-size: 7.8pt;"
        )
        eng_lay.addWidget(lbl_audio_status)

        settings_lay.addWidget(engine_card)

        # Kart 2: Profiller, Sözlük, Kısayollar & Araçlar
        prof_card = QFrame()
        prof_card.setObjectName("studioPanel")
        prof_lay = QVBoxLayout(prof_card)
        prof_lay.setContentsMargins(16, 14, 16, 14)
        prof_lay.setSpacing(10)

        lbl_prof_title = QLabel("PROFİLLER, SÖZLÜK & ARAÇLAR")
        lbl_prof_title.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        prof_lay.addWidget(lbl_prof_title)

        prof_wrap = QWidget()
        prof_row = QHBoxLayout(prof_wrap)
        prof_row.setContentsMargins(0, 0, 0, 0)
        prof_row.setSpacing(6)
        self.combo_profile = FlatComboBox()
        self._refresh_profile_combo()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selected)
        prof_row.addWidget(self.combo_profile, stretch=1)

        btn_save_prof = QPushButton("Kaydet")
        btn_save_prof.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save_prof.setMinimumHeight(30)
        btn_save_prof.clicked.connect(self._on_save_profile_clicked)
        prof_row.addWidget(btn_save_prof)

        btn_del_prof = QPushButton("Sil")
        btn_del_prof.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del_prof.setMinimumHeight(30)
        btn_del_prof.clicked.connect(self._on_delete_profile_clicked)
        prof_row.addWidget(btn_del_prof)
        prof_lay.addLayout(_make_setting_row("Aktif Oyun Profili", prof_wrap))

        self.combo_glossary_pack = FlatComboBox()
        self._refresh_glossary_combo()
        self.combo_glossary_pack.currentIndexChanged.connect(self._on_glossary_pack_changed)
        prof_lay.addLayout(_make_setting_row("Özel Terim Sözlüğü (JSON)", self.combo_glossary_pack))

        tools_row = QHBoxLayout()
        tools_row.setSpacing(10)

        self.btn_benchmark = QPushButton("  Donanım Hız Testi (Benchmark)")
        self.btn_benchmark.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_benchmark.setIcon(make_flat_icon("gauge", "#D4D4D8", 13))
        self.btn_benchmark.setIconSize(QSize(13, 13))
        self.btn_benchmark.setMinimumHeight(35)
        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.clicked.connect(self.run_benchmark_suite)
        tools_row.addWidget(self.btn_benchmark, stretch=1)

        self.btn_manage = QPushButton("  Bileşenler && Kaldırma Yöneticisi")
        self.btn_manage.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manage.setIcon(make_flat_icon("manage", "#D4D4D8", 13))
        self.btn_manage.setIconSize(QSize(13, 13))
        self.btn_manage.setMinimumHeight(35)
        self.btn_manage.clicked.connect(self.open_component_manager)
        tools_row.addWidget(self.btn_manage, stretch=1)
        prof_lay.addLayout(tools_row)

        settings_lay.addWidget(prof_card)

        # Kart 3: Kısayollar, Dil & Güncellemeler
        meta_card = QFrame()
        meta_card.setObjectName("studioPanel")
        meta_lay = QVBoxLayout(meta_card)
        meta_lay.setContentsMargins(16, 14, 16, 14)
        meta_lay.setSpacing(10)

        lbl_meta_title = QLabel("KISAYOLLAR, DİL & SİSTEM")
        lbl_meta_title.setStyleSheet(
            "color: #71717A; font-size: 7.4pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        meta_lay.addWidget(lbl_meta_title)

        hk_grid = QGridLayout()
        hk_grid.setHorizontalSpacing(10)
        hk_grid.setVerticalSpacing(4)
        hk_labels = [("Alan Seç", "roi"), ("Başlat / Durdur", "toggle"), ("Örnek Sahne", "sample")]
        self._hk_combos: Dict[str, FlatComboBox] = {}
        for col_idx, (lbl_txt, hk_key) in enumerate(hk_labels):
            lbl_hk = QLabel(lbl_txt)
            lbl_hk.setStyleSheet("color: #71717A; font-size: 7.8pt; font-weight: 600;")
            hk_grid.addWidget(lbl_hk, 0, col_idx)
            cb = FlatComboBox()
            for fn_key in VK_FUNCTION_KEYS:
                cb.addItem(fn_key, fn_key)
            cur_val = self._hotkeys.get(hk_key, "F7")
            idx_val = cb.findData(cur_val)
            if idx_val >= 0:
                cb.setCurrentIndex(idx_val)
            cb.currentIndexChanged.connect(self._on_hotkeys_changed)
            self._hk_combos[hk_key] = cb
            hk_grid.addWidget(cb, 1, col_idx)
        meta_lay.addLayout(hk_grid)

        self.combo_ui_lang = FlatComboBox()
        self.combo_ui_lang.addItem("Türkçe (TR)", "tr")
        self.combo_ui_lang.addItem("English (EN)", "en")
        for i in range(self.combo_ui_lang.count()):
            if self.combo_ui_lang.itemData(i) == self.i18n.lang:
                self.combo_ui_lang.setCurrentIndex(i)
                break
        self.combo_ui_lang.currentIndexChanged.connect(self._on_ui_language_changed)
        meta_lay.addLayout(_make_setting_row(self.i18n.t("ui_language"), self.combo_ui_lang))

        extra_toggles = QHBoxLayout()
        extra_toggles.setSpacing(16)
        self.chk_auto_profile = FlatSwitch("Aktif uygulamaya göre profil değiştir")
        self.chk_auto_profile.setChecked(bool(self.settings.get("auto_switch_profiles", False)))
        self.chk_auto_profile.toggled.connect(self._on_auto_profile_toggled)
        extra_toggles.addWidget(self.chk_auto_profile)

        self.chk_minimize_tray = FlatSwitch("Sistem tepsisine küçült")
        self.chk_minimize_tray.setChecked(bool(self.settings.get("minimize_to_tray", False)))
        self.chk_minimize_tray.toggled.connect(lambda _: self._save_settings())
        extra_toggles.addWidget(self.chk_minimize_tray)

        self.chk_auto_update = FlatSwitch("Otomatik güncelleme")
        self.chk_auto_update.setChecked(bool(self.settings.get("check_updates_on_startup", True)))
        self.chk_auto_update.toggled.connect(lambda _: self._save_settings())
        extra_toggles.addWidget(self.chk_auto_update)
        extra_toggles.addStretch(1)
        meta_lay.addLayout(extra_toggles)

        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        self.lbl_update_status = QLabel(f"SubVision v{__version__}")
        self.lbl_update_status.setStyleSheet("color: #71717A; font-size: 8pt;")
        upd_row.addWidget(self.lbl_update_status, stretch=1)

        self.btn_check_update = QPushButton(self.i18n.t("updates_check_btn"))
        self.btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_update.setMinimumHeight(28)
        self.btn_check_update.clicked.connect(lambda: self.check_for_updates_async(silent=False))
        upd_row.addWidget(self.btn_check_update)

        self.btn_open_release = QPushButton(self.i18n.t("updates_download"))
        self.btn_open_release.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_release.setMinimumHeight(28)
        self.btn_open_release.setVisible(False)
        self.btn_open_release.clicked.connect(self._start_auto_update)
        upd_row.addWidget(self.btn_open_release)
        meta_lay.addLayout(upd_row)

        settings_lay.addWidget(meta_card)

        self._sync_backend_inputs_visibility()
        settings_lay.addStretch(1)
        page_settings_scroll.setWidget(page_settings)
        self.stack.addWidget(page_settings_scroll)

        self._switch_tab(0)

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        tabs = (
            self.btn_tab_main,
            self.btn_tab_appearance,
            self.btn_tab_history,
            self.btn_tab_settings,
        )
        for i, btn in enumerate(tabs):
            btn.set_active(i == index)

    def _set_engine_status(
        self,
        text: str,
        dot_hex: str,
        studio_badge: str = "",
        studio_badge_kind: str = "muted",
    ) -> None:
        self.lbl_model_status.setText(text)
        if hasattr(self, "_status_dot"):
            self._status_dot.setStyleSheet(
                f"background-color: {dot_hex}; border-radius: 3px; border: none;"
            )
        if hasattr(self, "btn_tab_main"):
            self.btn_tab_main.set_badge(studio_badge, kind=studio_badge_kind)
        if hasattr(self, "lbl_engine_meta"):
            ctype = self.translator.active_compute_type.upper()
            self.lbl_engine_meta.setText(f"{ctype} · {self.tuning.scan_fps} FPS · 0 MB VRAM")

    def _apply_style_preset(
        self, color_hex: str, font_pt: int, bg_alpha: int, bilingual: bool, autofit: bool
    ) -> None:
        self._selected_color = color_hex
        self.slider_font.blockSignals(True)
        self.slider_alpha.blockSignals(True)
        self.chk_bilingual.blockSignals(True)
        self.chk_autofit.blockSignals(True)
        self.slider_font.setValue(int(font_pt))
        self.slider_alpha.setValue(int(bg_alpha))
        self.chk_bilingual.setChecked(bool(bilingual))
        self.chk_autofit.setChecked(bool(autofit))
        self.slider_font.blockSignals(False)
        self.slider_alpha.blockSignals(False)
        self.chk_bilingual.blockSignals(False)
        self.chk_autofit.blockSignals(False)
        self._on_appearance_changed()

    def _clear_history(self) -> None:
        self.list_history.clear()
        self._history_entries.clear()
        self._session_start_ts = time.monotonic()
        self.btn_tab_history.setText("Geçmiş")

    def _export_history_srt(self) -> None:
        if not self._history_entries:
            QMessageBox.information(self, "SRT Dışa Aktar", "Dışa aktarılacak çeviri geçmişi henüz yok.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "SRT Altyazı Olarak Kaydet", "subvision_subtitles.srt", "SubRip (*.srt)"
        )
        if not path:
            return
        count = export_history_to_srt(
            self._history_entries,
            path,
            bilingual=self.chk_bilingual.isChecked(),
        )
        QMessageBox.information(self, "SRT Dışa Aktar", f"{count} altyazı satırı kaydedildi:\n{path}")

    def _export_history_anki(self) -> None:
        if not self._history_entries:
            QMessageBox.information(self, "Anki CSV", "Dışa aktarılacak çeviri geçmişi henüz yok.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Anki Flashcard CSV Olarak Kaydet", "subvision_anki.csv", "CSV (*.csv)"
        )
        if not path:
            return
        count = export_history_to_anki_csv(self._history_entries, path)
        QMessageBox.information(self, "Anki CSV", f"{count} kart kaydedildi:\n{path}")

    def _set_toggle_button_style(self, active: bool) -> None:
        hk = self._hotkeys.get("toggle", "F8")
        if active:
            self.btn_toggle.setIcon(make_flat_icon("stop", "#FFFFFF", 11))
            self.btn_toggle.setText(f"  Durdur   {hk}")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #E11D48;
                    border: 1px solid #E11D48;
                    border-radius: 8px;
                    color: #FFFFFF;
                    padding: 0 16px;
                    font-size: 9pt;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #BE123C;
                    border-color: #BE123C;
                }
                """
            )
        else:
            self.btn_toggle.setIcon(make_flat_icon("play", "#09090B", 11))
            self.btn_toggle.setText(f"  Başlat   {hk}")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #FAFAFA;
                    border: 1px solid #FAFAFA;
                    border-radius: 8px;
                    color: #09090B;
                    padding: 0 16px;
                    font-size: 9pt;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #E4E4E7;
                    border-color: #E4E4E7;
                    color: #09090B;
                }
                QPushButton:pressed {
                    background-color: #D4D4D8;
                }
                QPushButton:disabled {
                    background-color: #1A1A20;
                    border-color: #24242A;
                    color: #52525B;
                }
                """
            )

    def _select_color_swatch(self, hex_code: str) -> None:
        self._selected_color = hex_code
        self._on_appearance_changed()

    def _select_overlay_mode(self, mode: str) -> None:
        self._selected_overlay_mode = mode
        self._on_appearance_changed()

    def _update_designer_button_styles(self) -> None:
        active_pos_css = (
            "QPushButton { background-color: #25252C; border: 1px solid #35353F; border-radius: 5px; "
            "color: #FAFAFA; padding: 5px 11px; font-size: 8.1pt; font-weight: 600; }"
        )
        idle_pos_css = (
            "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 5px; "
            "color: #71717A; padding: 5px 11px; font-size: 8.1pt; font-weight: 500; } "
            "QPushButton:hover { color: #E4E4E7; background-color: #1B1B21; }"
        )
        self.btn_mode_cover.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "cover" else idle_pos_css
        )
        self.btn_mode_above.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "above" else idle_pos_css
        )

        for hex_code, btn in self._color_buttons.items():
            btn.set_selected(hex_code == self._selected_color)

    def _apply_saved_appearance(self) -> None:
        legacy_color_map = {
            "#FACC15": "#F59E0B",
            "#FFFFFF": "#FAFAFA",
            "#4ADE80": "#34D399",
        }
        raw_color = str(self.settings.get("text_color", "#F59E0B")).upper()
        self._selected_color = legacy_color_map.get(raw_color, raw_color)
        if self._selected_color not in self._color_buttons:
            self._selected_color = "#F59E0B"

        default_overlay = "cover" if self.hw_profile.capture_exclude_supported else "above"
        self._selected_overlay_mode = self.settings.get("overlay_mode", default_overlay)

        saved_perf = self.settings.get("performance_profile", PROFILE_AUTO)
        self.combo_perf_profile.blockSignals(True)
        idx_p = self.combo_perf_profile.findData(saved_perf)
        if idx_p >= 0:
            self.combo_perf_profile.setCurrentIndex(idx_p)
        self.combo_perf_profile.blockSignals(False)

        saved_ocr = self.settings.get("ocr_mode", self.tuning.default_ocr_mode)
        self.combo_ocr_mode.blockSignals(True)
        idx_o = self.combo_ocr_mode.findData(saved_ocr)
        if idx_o >= 0:
            self.combo_ocr_mode.setCurrentIndex(idx_o)
        self.combo_ocr_mode.blockSignals(False)
        self._sync_ocr_badge(saved_ocr)

        self._on_appearance_changed()

    def _sync_ocr_badge(self, mode: str) -> None:
        badge_map = {
            "hybrid": "HYBRID",
            "fast_mask": "FAST MASK",
            "full_ocr": "FULL OCR",
        }
        self.card_ocr.set_metric(
            self.card_ocr.lbl_val.text(),
            badge_text=badge_map.get(mode, "HYBRID"),
        )

    def _on_perf_profile_changed(self) -> None:
        selected_profile = self.combo_perf_profile.currentData() or PROFILE_AUTO
        self.tuning = compute_runtime_tuning(self.hw_profile, selected_profile)
        self.ocr_engine.apply_tuning(self.tuning)

        if self.translator.is_ready and self.translator.cpu_threads != self.tuning.nmt_threads:
            try:
                self.translator.reconfigure_threads(self.tuning.nmt_threads)
            except Exception:
                pass
        else:
            self.translator.cpu_threads = self.tuning.nmt_threads

        if self.worker and self.worker.running:
            self.worker.update_timing(
                self.tuning.scan_interval_sec, self.tuning.idle_scan_interval_sec
            )
            self._set_engine_status(
                f"Canlı Aktif ({self.tuning.scan_fps} FPS)",
                "#22C55E",
                studio_badge="CANLI",
                studio_badge_kind="live",
            )
        else:
            ctype = self.translator.active_compute_type.upper()
            if hasattr(self, "lbl_engine_meta"):
                self.lbl_engine_meta.setText(f"{ctype} · {self.tuning.scan_fps} FPS · 0 MB VRAM")

        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.lbl_scene_tag.setText(f"Canlı Yakalama · {self.tuning.scan_fps} FPS")
        self.card_ocr.set_metric(
            self.card_ocr.lbl_val.text(),
            sub_text=f"Kare Kilidi · {self.tuning.ocr_intra_threads} Thread",
        )
        ctype = self.translator.active_compute_type.upper()
        self.card_nmt.lbl_title.setText(f"ÇEVİRİ ({ctype})")
        self.card_nmt.set_metric(
            self.card_nmt.lbl_val.text(),
            badge_text=f"{self.translator.cpu_threads} THREAD",
        )
        self._update_session_kpi()
        self._save_settings()

    def _start_model_loading(self) -> None:
        self.loader_thread = ModelLoaderThread(self.translator, self.ocr_engine, parent=self)
        self.loader_thread.progress.connect(self._on_model_progress)
        self.loader_thread.finished_ok.connect(self._on_model_ready)
        self.loader_thread.failed.connect(self._on_model_failed)
        self.loader_thread.start()

    def _on_model_progress(self, msg: str, pct: int) -> None:
        self._set_engine_status(msg, "#F59E0B")
        self.progress_bar.setValue(pct)

    def _on_model_ready(self) -> None:
        ctype = self.translator.active_compute_type.upper()
        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.card_nmt.lbl_title.setText(f"ÇEVİRİ ({ctype})")
        self._set_engine_status("Motor Hazır", "#22C55E")
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.btn_toggle.setEnabled(True)
        self.btn_test.setEnabled(True)
        self.btn_benchmark.setEnabled(True)

    def _on_model_failed(self, err: str) -> None:
        self._set_engine_status(f"Hata: {err}", "#EF4444")

    def open_roi_selector(self) -> None:
        if self.roi_selector.isVisible():
            return
        if QApplication.activeModalWidget() is not None:
            return

        is_ocr_active = bool(self.worker is not None and self.worker.running)
        is_audio_active = bool(self.audio_worker is not None and self.audio_worker.isRunning())
        was_running = is_ocr_active or is_audio_active
        self._resume_after_roi = was_running
        if was_running:
            self.toggle_translation()

        # Alan seçerken overlay ve ana pencere arkadaki oyunu/videoyu kapatmasın
        self._restore_overlay_after_roi = self.overlay.isVisible()
        if self._restore_overlay_after_roi:
            self.overlay.hide()

        self._restore_window_after_roi = self.isVisible() and not self.isMinimized()
        if self._restore_window_after_roi:
            self.hide()

        self.roi_selector.show_selector()

    def _on_roi_cancelled(self) -> None:
        if self._restore_overlay_after_roi:
            self._restore_overlay_after_roi = False
            self.overlay.show()
        if self._restore_window_after_roi:
            self._restore_window_after_roi = False
            self.showNormal()
            self.raise_()
            self.activateWindow()
        if self._resume_after_roi and self.translator.is_ready:
            self._resume_after_roi = False
            self.toggle_translation()

    def _on_roi_selected(self, new_roi: Dict[str, int]) -> None:
        self.roi = self._validate_roi(new_roi)
        if self._restore_overlay_after_roi:
            self._restore_overlay_after_roi = False
            self.overlay.show()
        self.overlay.align_to_roi(self.roi)
        self.lbl_roi_badge.setText(f"{self.roi['width']} × {self.roi['height']} px")
        self.btn_select_roi.setText(f"  Alan Seç   {self.roi['width']}×{self.roi['height']}")
        self._update_session_kpi()
        self._save_settings()

        if self._restore_window_after_roi:
            self._restore_window_after_roi = False
            self.showNormal()
            self.raise_()
            self.activateWindow()

        if self._resume_after_roi and self.translator.is_ready:
            self._resume_after_roi = False
            self.toggle_translation()
        else:
            self.overlay.set_subtitle(
                "Altyazı alanı seçildi. Çeviriyi başlatmak için F8 tuşuna basın."
            )

    def _on_appearance_changed(self) -> None:
        f_size = self.slider_font.value()
        alpha = self.slider_alpha.value()
        alpha_pct = int(alpha / 255 * 100)
        bilingual = self.chk_bilingual.isChecked()
        auto_fit = self.chk_autofit.isChecked()

        self.lbl_font_cap.setText("Boyut" if auto_fit else "Sabit")
        self.lbl_font_val.setText(f"{f_size} pt")
        self.lbl_alpha_val.setText(f"%{alpha_pct}")
        self._update_designer_button_styles()

        # Sinematik Önizleme Sahnesi & Sıkı Altyazı Pill'ini Güncelle
        preview_font_pt = max(11, min(16, int(f_size * 0.56)))
        en_font_pt = max(9, int(preview_font_pt * 0.76))
        if hasattr(self, "tight_preview_pill"):
            self.tight_preview_pill.setStyleSheet(
                f"""
                QFrame {{
                    background-color: rgba(20, 20, 24, {alpha});
                    border: 1px solid #2C2C34;
                    border-radius: 7px;
                }}
                """
            )
        self.lbl_en_preview.setStyleSheet(
            f"color: #71717A; font-size: {en_font_pt}pt; font-weight: 500; border: none; background: transparent;"
        )
        self.lbl_tr_preview.setStyleSheet(
            f"color: {self._selected_color}; font-size: {preview_font_pt}pt; font-weight: 700; border: none; background: transparent;"
        )

        # Görünüm Sekmesindeki Sıkı Hizalama Simülasyon Pill'lerini Canlı Güncelle
        sim_pill_css = (
            f"QLabel {{ color: {self._selected_color}; background-color: rgba(14, 14, 18, {alpha}); "
            f"border: 1px solid rgba(255, 255, 255, 30); border-radius: 6px; "
            f"padding: 6px 14px; font-size: {max(10, preview_font_pt - 1)}pt; font-weight: 700; }}"
        )
        if hasattr(self, "_sim_short_pill"):
            self._sim_short_pill.setStyleSheet(sim_pill_css)
        if hasattr(self, "_sim_long_pill"):
            self._sim_long_pill.setStyleSheet(sim_pill_css)

        self.overlay.update_appearance(
            font_size=f_size,
            text_color=self._selected_color,
            bg_alpha=alpha,
            overlay_mode=self._selected_overlay_mode,
            show_bilingual=bilingual,
            auto_fit_font=auto_fit,
        )
        self.overlay.align_to_roi(self.roi)
        self._save_settings()

    def _on_ocr_mode_changed(self) -> None:
        mode = self.combo_ocr_mode.currentData()
        self.ocr_engine.set_mode(mode)
        self._sync_ocr_badge(mode)
        self._save_settings()

    def _sync_backend_inputs_visibility(self) -> None:
        backend = self.combo_tr_backend.currentData() if hasattr(self, "combo_tr_backend") else BACKEND_LOCAL_CT2
        is_local = backend == BACKEND_LOCAL_CT2
        needs_key = backend in (BACKEND_GEMINI, BACKEND_DEEPL, BACKEND_OPENAI_COMPAT)
        self.edit_tr_endpoint.setVisible(not is_local)
        self.edit_tr_model.setVisible(not is_local and backend != BACKEND_DEEPL)
        self.edit_tr_apikey.setVisible(needs_key)
        self.btn_test_backend.setVisible(not is_local)
        if not is_local:
            if not self.edit_tr_endpoint.text().strip():
                self.edit_tr_endpoint.setPlaceholderText(DEFAULT_ENDPOINTS.get(backend, ""))
            if not self.edit_tr_model.text().strip():
                self.edit_tr_model.setPlaceholderText(DEFAULT_MODELS.get(backend, ""))

    def _on_translation_backend_changed(self) -> None:
        self._sync_backend_inputs_visibility()
        cfg = ContextBackendConfig(
            backend=str(self.combo_tr_backend.currentData() or BACKEND_LOCAL_CT2),
            endpoint=self.edit_tr_endpoint.text().strip(),
            model=self.edit_tr_model.text().strip(),
            api_key=self.edit_tr_apikey.text().strip(),
        )
        self.translator.update_config(cfg)
        self._save_settings()

    def _on_test_translation_backend(self) -> None:
        self._on_translation_backend_changed()
        ok, detail = self.translator.test_connection()
        if ok:
            QMessageBox.information(
                self,
                self.i18n.t("backend_test_ok"),
                f"{self.i18n.t('backend_test_ok')}:\n{detail}",
            )
        else:
            QMessageBox.warning(
                self,
                self.i18n.t("backend_test_fail"),
                f"{self.i18n.t('backend_test_fail')}:\n{detail}",
            )

    def _on_ui_language_changed(self) -> None:
        lang = str(self.combo_ui_lang.currentData() or "tr")
        self.i18n.set_language(lang)
        self._save_settings()
        if hasattr(self, "btn_tab_main"):
            self.btn_tab_main.set_nav_text(self.i18n.t("tab_studio"))
            self.btn_tab_appearance.set_nav_text(self.i18n.t("tab_appearance"))
            self.btn_tab_history.set_nav_text(self.i18n.t("tab_history"))
            self.btn_tab_settings.set_nav_text(self.i18n.t("tab_settings"))
        if hasattr(self, "combo_target_app"):
            self.btn_refresh_windows.setToolTip(self.i18n.t("target_app_refresh"))
            self.combo_target_app.setToolTip(self.i18n.t("target_app_tooltip"))
            self._refresh_target_windows()

    def _refresh_target_windows(self) -> None:
        if not hasattr(self, "combo_target_app"):
            return

        current_spec = self._target_window
        self.combo_target_app.blockSignals(True)
        self.combo_target_app.clear()

        if sys.platform != "win32":
            self.combo_target_app.addItem(self.i18n.t("target_app_unsupported_os"), None)
            self.combo_target_app.setEnabled(False)
            if hasattr(self, "btn_refresh_windows"):
                self.btn_refresh_windows.setEnabled(False)
            self.combo_target_app.blockSignals(False)
            self._update_target_hint_label()
            return

        self.combo_target_app.addItem(self.i18n.t("target_app_all"), None)
        windows = list_visible_windows(exclude_own_pid=True)

        selected_idx = 0
        for win in windows:
            spec = TargetWindowSpec(
                hwnd=win.hwnd,
                process_name=win.process_name,
                title=win.title,
            )
            self.combo_target_app.addItem(win.display_label(), spec)
            item_idx = self.combo_target_app.count() - 1
            if current_spec and current_spec.is_active and selected_idx == 0:
                if current_spec.hwnd and win.hwnd == current_spec.hwnd:
                    selected_idx = item_idx
                elif current_spec.process_name and win.process_name == current_spec.process_name:
                    selected_idx = item_idx
                elif not current_spec.process_name and current_spec.title and win.title.lower() == current_spec.title.lower():
                    selected_idx = item_idx

        # Kayıtlı hedef uygulama henüz açılmadıysa seçili olarak koru
        if current_spec and current_spec.is_active and selected_idx == 0:
            missing_spec = TargetWindowSpec(
                hwnd=0,
                process_name=current_spec.process_name,
                title=current_spec.title,
            )
            missing_lbl = self.i18n.t(
                "target_app_saved_missing", target=missing_spec.short_label()
            )
            self.combo_target_app.addItem(missing_lbl, missing_spec)
            selected_idx = self.combo_target_app.count() - 1

        self.combo_target_app.setCurrentIndex(selected_idx)
        chosen = self.combo_target_app.currentData()
        self._target_window = chosen if isinstance(chosen, TargetWindowSpec) and chosen.is_active else None
        self.combo_target_app.blockSignals(False)

        if self.worker and self.worker.running:
            self.worker.set_target_filter(self._target_window)
        self._update_target_hint_label()

    def _update_target_hint_label(self, is_waiting: bool = False) -> None:
        if not self._target_window or not self._target_window.is_active:
            if hasattr(self, "_target_dot"):
                self._target_dot.setStyleSheet("background-color: #52525B; border-radius: 3px; border: none;")
            if hasattr(self, "lbl_target_hint"):
                self.lbl_target_hint.setText("")
            return
        label = self._target_window.short_label()
        if is_waiting:
            if hasattr(self, "_target_dot"):
                self._target_dot.setStyleSheet("background-color: #F59E0B; border-radius: 3px; border: none;")
            if hasattr(self, "lbl_target_hint"):
                self.lbl_target_hint.setText("Alt+Tab Beklemede")
        else:
            if hasattr(self, "_target_dot"):
                self._target_dot.setStyleSheet("background-color: #22C55E; border-radius: 3px; border: none;")
            if hasattr(self, "lbl_target_hint"):
                self.lbl_target_hint.setText(f"Kilitli: {label}")

    def _on_target_app_changed(self) -> None:
        if not hasattr(self, "combo_target_app"):
            return
        data = self.combo_target_app.currentData()
        self._target_window = data if isinstance(data, TargetWindowSpec) and data.is_active else None
        self._update_target_hint_label(is_waiting=False)
        if self.worker and self.worker.running:
            self.worker.set_target_filter(self._target_window)
            if self._target_window is None and not self.overlay.isVisible():
                self.overlay.show()
        self._save_settings()

    def _on_target_focus_changed(self, is_focused: bool) -> None:
        is_ocr_active = bool(self.worker and self.worker.running)
        if not is_ocr_active:
            return
        target_lbl = self._target_window.short_label() if self._target_window else "Hedef"
        if not is_focused:
            self.overlay.set_subtitle("")
            self.overlay.hide()
            self._update_target_hint_label(is_waiting=True)
            self._set_engine_status(
                f"Beklemede ({target_lbl})",
                "#F59E0B",
                studio_badge="BEKLE",
                studio_badge_kind="waiting",
            )
            self.lbl_toggle_desc.setText(
                self.i18n.t("target_app_waiting", target=target_lbl)
            )
        else:
            if not self.roi_selector.isVisible():
                self.overlay.show()
            self._update_target_hint_label(is_waiting=False)
            self._set_engine_status(
                f"Canlı Aktif ({self.tuning.scan_fps} FPS)",
                "#22C55E",
                studio_badge="CANLI",
                studio_badge_kind="live",
            )
            if self._target_window and self._target_window.is_active:
                self.lbl_toggle_desc.setText(
                    self.i18n.t("target_app_active", target=target_lbl)
                )
            else:
                self.lbl_toggle_desc.setText("Sıkı Hizalama · Canlı Yakalama Aktif")

    def check_for_updates_async(self, silent: bool = False) -> None:
        if UpdateCheckerThread is None:
            return
        if self.update_thread and self.update_thread.isRunning():
            return
        if not silent and hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setText(self.i18n.t("updates_checking"))
        self.update_thread = UpdateCheckerThread(current_version=__version__, parent=self)
        self.update_thread.update_checked.connect(
            lambda info: self._on_update_checked(info, silent=silent)
        )
        self.update_thread.start()

    def _on_update_checked(self, info: UpdateInfo, silent: bool = False) -> None:
        if info.error:
            if not silent and hasattr(self, "lbl_update_status"):
                self.lbl_update_status.setText(self.i18n.t("updates_error"))
            return
        if info.is_update_available:
            self._latest_update_info = info
            self._latest_release_url = info.release_url
            msg = self.i18n.t(
                "updates_available",
                latest=info.latest_version,
                current=info.current_version,
            )
            if hasattr(self, "lbl_update_status"):
                self.lbl_update_status.setText(msg)
                self.lbl_update_status.setStyleSheet("color: #FACC15; font-size: 8.2pt; font-weight: 700;")
            if hasattr(self, "btn_open_release"):
                if info.has_direct_installer:
                    self.btn_open_release.setText(f"Şimdi Güncelle (v{info.latest_version})")
                else:
                    self.btn_open_release.setText(self.i18n.t("updates_download"))
                self.btn_open_release.setVisible(True)

            # Aynı oturumda kullanıcıya yalnızca bir kez otomatik güncelleme önerisi göster
            already_prompted = getattr(self, "_update_prompted_version", None) == info.latest_version
            if (not already_prompted) or (not silent):
                self._update_prompted_version = info.latest_version
                self._prompt_install_update(info)
        elif not silent and hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setText(
                self.i18n.t("updates_up_to_date", version=info.current_version)
            )
            self.lbl_update_status.setStyleSheet("color: #34D399; font-size: 8.2pt;")

    def _prompt_install_update(self, info: UpdateInfo) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("SubVision AI — Yeni Sürüm Mevcut")
        box.setIcon(QMessageBox.Icon.Information)
        size_mb = f" ({info.asset_size / (1024 * 1024):.1f} MB)" if info.asset_size > 0 else ""
        notes_preview = (info.release_notes or "").strip()
        if len(notes_preview) > 360:
            notes_preview = notes_preview[:360].rstrip() + "..."
        body = (
            f"Yeni SubVision AI v{info.latest_version} sürümü hazır (mevcut: v{info.current_version}).\n\n"
            f"Uygulama GitHub Releases üzerinden yeni paketi indirip otomatik olarak güncelleyebilir{size_mb}."
        )
        if notes_preview:
            body += f"\n\nSürüm Notları:\n{notes_preview}"
        box.setText(body)

        btn_install = None
        if info.has_direct_installer and UpdateDownloadThread is not None:
            btn_install = box.addButton("Şimdi Güncelle", QMessageBox.ButtonRole.AcceptRole)
        btn_web = box.addButton("GitHub'da Aç", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Daha Sonra", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if btn_install is not None and clicked == btn_install:
            self._start_auto_update()
        elif clicked == btn_web:
            self._open_latest_release_page()

    def _start_auto_update(self) -> None:
        info: Optional[UpdateInfo] = getattr(self, "_latest_update_info", None)
        if not info or not info.has_direct_installer or UpdateDownloadThread is None:
            self._open_latest_release_page()
            return

        dl_thread: Optional[UpdateDownloadThread] = getattr(self, "_update_download_thread", None)
        if dl_thread and dl_thread.isRunning():
            return

        updates_dir = os.path.join(DATA_DIR, "updates")
        progress = QProgressDialog(
            f"SubVision AI v{info.latest_version} indiriliyor...",
            "İptal",
            0,
            100,
            self,
        )
        progress.setWindowTitle("SubVision AI — Otomatik Güncelleme")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(420)
        progress.setValue(0)
        self._update_progress_dlg = progress

        thread = UpdateDownloadThread(info=info, dest_dir=updates_dir, parent=self)
        self._update_download_thread = thread

        def _on_progress(downloaded: int, total: int) -> None:
            if not progress.isVisible():
                return
            if total > 0:
                pct = max(0, min(100, int(downloaded * 100 / total)))
                progress.setMaximum(100)
                progress.setValue(pct)
                progress.setLabelText(
                    f"SubVision AI v{info.latest_version} indiriliyor...\n"
                    f"{downloaded / (1024 * 1024):.1f} MB / {total / (1024 * 1024):.1f} MB (%{pct})"
                )
            else:
                progress.setMaximum(0)
                progress.setLabelText(
                    f"SubVision AI v{info.latest_version} indiriliyor... "
                    f"({downloaded / (1024 * 1024):.1f} MB)"
                )

        def _on_status(msg: str) -> None:
            if progress.isVisible():
                progress.setLabelText(msg)

        def _on_finished(installer_path: str, error_msg: str) -> None:
            progress.close()
            self._update_progress_dlg = None
            if error_msg:
                if "iptal" in error_msg.lower():
                    return
                res = QMessageBox.warning(
                    self,
                    "Güncelleme Hatası",
                    f"Otomatik güncelleme indirilemedi:\n{error_msg}\n\n"
                    "GitHub sürüm sayfasını tarayıcıda açmak ister misiniz?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if res == QMessageBox.StandardButton.Yes:
                    self._open_latest_release_page()
                return

            try:
                should_exit, status_msg = apply_downloaded_update(installer_path)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Güncelleme Başlatılamadı",
                    f"Kurulum başlatılırken hata oluştu:\n{exc}",
                )
                return

            if should_exit:
                if self.worker and self.worker.isRunning():
                    self.stop_translation()
                self._force_quit = True
                QTimer.singleShot(150, QApplication.quit)
            else:
                QMessageBox.information(self, "SubVision AI Güncelleme", status_msg)

        progress.canceled.connect(thread.cancel)
        thread.progress_changed.connect(_on_progress)
        thread.status_changed.connect(_on_status)
        thread.download_finished.connect(_on_finished)
        thread.start()

    def _open_latest_release_page(self) -> None:
        if self._latest_release_url:
            webbrowser.open(self._latest_release_url)

    def _refresh_profile_combo(self) -> None:
        if not hasattr(self, "combo_profile"):
            return
        cur = self.combo_profile.currentData()
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        for name in self.profile_manager.list_names():
            cfg = self.profile_manager.get_profile(name) or {}
            proc = cfg.get("process_name")
            label = f"{name} ({proc})" if proc else name
            self.combo_profile.addItem(label, name)
        idx = self.combo_profile.findData(cur)
        if idx >= 0:
            self.combo_profile.setCurrentIndex(idx)
        self.combo_profile.blockSignals(False)

    def _refresh_glossary_combo(self) -> None:
        if not hasattr(self, "combo_glossary_pack"):
            return
        self.combo_glossary_pack.blockSignals(True)
        self.combo_glossary_pack.clear()
        self.combo_glossary_pack.addItem("Kapalı (Yalnızca Dahili Sözlük)", "none")
        if self.custom_glossary.packs:
            self.combo_glossary_pack.addItem(
                f"Tüm Özel Paketler ({len(self.custom_glossary.packs)} paket)", "all"
            )
            for pid, pack in self.custom_glossary.packs.items():
                self.combo_glossary_pack.addItem(pack.name, pid)
        idx = self.combo_glossary_pack.findData(self.custom_glossary.active_pack_id)
        if idx >= 0:
            self.combo_glossary_pack.setCurrentIndex(idx)
        self.combo_glossary_pack.blockSignals(False)

    def _on_glossary_pack_changed(self) -> None:
        pid = str(self.combo_glossary_pack.currentData() or "none")
        self.custom_glossary.set_active_pack(pid)
        self.translator.clear_cache()
        self._save_settings()

    def _on_save_profile_clicked(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Profil Kaydet",
            "Profil adı (örn. Spider-Man 2, Netflix, VLC):",
            text=str(self.combo_profile.currentData() or "Oyun Profili"),
        )
        if not ok or not name.strip():
            return
        default_proc = self._target_window.process_name if self._target_window else ""
        proc, _ = QInputDialog.getText(
            self,
            "Otomatik Uygulama Eşleştirme (Opsiyonel)",
            "İsteğe bağlı .exe adı (örn. vlc.exe, Spider-Man2.exe — boş bırakılabilir):",
            text=default_proc,
        )
        self.profile_manager.save_profile(
            name=name.strip(),
            roi=self.roi,
            ocr_mode=str(self.combo_ocr_mode.currentData() or "fast_mask"),
            overlay_mode=self._selected_overlay_mode,
            text_color=self._selected_color,
            glossary_pack=str(self.combo_glossary_pack.currentData() or "none"),
            process_name=proc.strip(),
        )
        self._refresh_profile_combo()
        idx = self.combo_profile.findData(name.strip())
        if idx >= 0:
            self.combo_profile.setCurrentIndex(idx)
        self._save_settings()

    def _on_delete_profile_clicked(self) -> None:
        name = str(self.combo_profile.currentData() or "")
        if self.profile_manager.delete_profile(name):
            self._refresh_profile_combo()
            self._save_settings()

    def _apply_profile_by_name(self, name: str) -> None:
        cfg = self.profile_manager.get_profile(name)
        if not cfg:
            return
        if isinstance(cfg.get("roi"), dict):
            self.roi = dict(cfg["roi"])
            self.overlay.align_to_roi(self.roi)
            if self.worker and self.worker.running:
                self.worker.roi = self.roi
        if cfg.get("ocr_mode"):
            idx = self.combo_ocr_mode.findData(cfg["ocr_mode"])
            if idx >= 0:
                self.combo_ocr_mode.setCurrentIndex(idx)
        if cfg.get("overlay_mode"):
            self._selected_overlay_mode = cfg["overlay_mode"]
        if cfg.get("text_color"):
            self._selected_color = cfg["text_color"]
        if cfg.get("glossary_pack"):
            gidx = self.combo_glossary_pack.findData(cfg["glossary_pack"])
            if gidx >= 0:
                self.combo_glossary_pack.setCurrentIndex(gidx)
        self._update_designer_button_styles()
        self._on_appearance_changed()

    def _on_profile_selected(self) -> None:
        name = str(self.combo_profile.currentData() or "")
        if name:
            self._apply_profile_by_name(name)

    def _on_auto_profile_toggled(self, checked: bool) -> None:
        if checked:
            self._auto_profile_timer.start()
        else:
            self._auto_profile_timer.stop()
        self._save_settings()

    def _check_foreground_profile(self) -> None:
        proc = get_foreground_process_name()
        if not proc or proc == self._last_auto_proc:
            return
        self._last_auto_proc = proc
        matched = self.profile_manager.match_process(proc)
        if matched and matched != str(self.combo_profile.currentData() or ""):
            idx = self.combo_profile.findData(matched)
            if idx >= 0:
                self.combo_profile.setCurrentIndex(idx)

    def _on_hotkeys_changed(self) -> None:
        for hk_key, cb in self._hk_combos.items():
            val = str(cb.currentData() or self._hotkeys[hk_key])
            self._hotkeys[hk_key] = val
            if hasattr(self, "_hk_cap_labels") and hk_key in self._hk_cap_labels:
                self._hk_cap_labels[hk_key].setText(val)
        is_active = bool((self.worker and self.worker.running) or (self.audio_worker and self.audio_worker.isRunning()))
        self._set_toggle_button_style(active=is_active)
        self._register_global_hotkeys()
        self._save_settings()

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(create_app_icon(), self)
        self.tray_icon.setToolTip(f"SubVision AI v{__version__}")
        menu = QMenu(self)

        act_show = QAction("Stüdyoyu Göster", self)
        act_show.triggered.connect(self._restore_from_tray)
        menu.addAction(act_show)

        act_toggle = QAction("Çeviriyi Başlat / Durdur", self)
        act_toggle.triggered.connect(self.toggle_translation)
        menu.addAction(act_toggle)

        act_roi = QAction("Altyazı Alanını Seç", self)
        act_roi.triggered.connect(self.open_roi_selector)
        menu.addAction(act_roi)

        menu.addSeparator()

        act_quit = QAction("Çıkış", self)
        act_quit.triggered.connect(self._quit_from_tray)
        menu.addAction(act_quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray_icon.show()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()

    def _copy_current_translation(self) -> None:
        tr = self.lbl_tr_preview.text().strip()
        if tr and not tr.startswith("Türkçe çeviri burada"):
            QGuiApplication.clipboard().setText(tr)

    def _on_history_item_clicked(self, item: QListWidgetItem) -> None:
        tr_text = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(tr_text, str) and tr_text.strip():
            QGuiApplication.clipboard().setText(tr_text.strip())

    def _update_session_kpi(self) -> None:
        req = self.translator.total_requests
        hits = self.translator.cache_hits
        hit_pct = int((hits / req) * 100) if req > 0 else 0
        self.lbl_roi_badge.setText(f"{self.roi['width']} × {self.roi['height']} px")
        if hasattr(self, "btn_select_roi"):
            self.btn_select_roi.setText(f"  Alan Seç   {self.roi['width']}×{self.roi['height']}")
        self.card_stats.set_metric(
            f"{req} Çeviri",
            sub_text=f"ROI {self.roi['width']}×{self.roi['height']} · %{hit_pct}",
            badge_text=f"%{hit_pct} CACHE" if req > 0 else f"{self.tuning.scan_fps} FPS",
            bar_pct=max(12, hit_pct),
        )

    def _retire_worker(self, thread_obj: Optional[QThread]) -> None:
        """Hâlâ sonlanmakta olan QThread'in GC ile yok edilip çökmesini önler."""
        if thread_obj is None:
            return
        if thread_obj.isRunning():
            self._retired_workers.append(thread_obj)
            thread_obj.finished.connect(
                lambda t=thread_obj: self._retired_workers.remove(t)
                if t in self._retired_workers
                else None
            )

    def _reset_ui_to_stopped_state(self, desc_text: Optional[str] = None) -> None:
        self._set_toggle_button_style(active=False)
        self._update_target_hint_label(is_waiting=False)
        self._set_engine_status("Motor Hazır", "#22C55E", studio_badge="", studio_badge_kind="muted")
        self.lbl_toggle_desc.setText(desc_text or "Sıkı Hizalama · Alt+Tab Korumalı")
        self.lbl_scene_tag.setText(f"Hazır · {self.tuning.scan_fps} FPS")
        self.overlay.set_subtitle("")
        if not self.roi_selector.isVisible():
            self.overlay.show()

    def _on_audio_worker_error(self, err: str) -> None:
        if self.audio_worker is not None:
            self.audio_worker.stop()
            self._retire_worker(self.audio_worker)
            self.audio_worker = None
        self._reset_ui_to_stopped_state(f"Canlı ses başlatılamadı: {err}")
        QMessageBox.warning(self, "Canlı Ses (Whisper)", err)

    def toggle_translation(self) -> None:
        if not self.translator.is_ready:
            return

        is_ocr_active = bool(self.worker and self.worker.running)
        is_audio_active = bool(self.audio_worker and self.audio_worker.isRunning())

        if is_ocr_active or is_audio_active:
            if self.worker is not None:
                w_ref = self.worker
                self.worker = None
                w_ref.stop()
                self._retire_worker(w_ref)
            if self.audio_worker is not None:
                a_ref = self.audio_worker
                self.audio_worker = None
                a_ref.stop()
                a_ref.wait(1500)
                self._retire_worker(a_ref)
            self._reset_ui_to_stopped_state()
        else:
            input_source = (
                self.combo_input_source.currentData()
                if hasattr(self, "combo_input_source")
                else "ocr"
            )
            self.overlay.align_to_roi(self.roi)
            self.overlay.set_subtitle("")
            if not self.roi_selector.isVisible():
                self.overlay.show()

            if input_source == "audio" and AudioCaptureTranslateWorker is not None:
                whisper_model = (
                    str(self.combo_whisper_model.currentData() or "tiny.en")
                    if hasattr(self, "combo_whisper_model")
                    else "tiny.en"
                )
                self.lbl_scene_tag.setText(f"Canlı Ses · Whisper {whisper_model}")
                self.audio_worker = AudioCaptureTranslateWorker(
                    translator=self.translator,
                    model_size=whisper_model,
                    cpu_threads=self.tuning.nmt_threads,
                    parent=self,
                )
                self.audio_worker.subtitle_updated.connect(self._on_subtitle_updated)
                self.audio_worker.subtitle_cleared.connect(self._on_subtitle_cleared)
                self.audio_worker.status_message.connect(
                    lambda msg: self.lbl_toggle_desc.setText(msg)
                )
                self.audio_worker.error_occurred.connect(self._on_audio_worker_error)
                self.audio_worker.start()
                self._set_engine_status(
                    f"Canlı Ses ({whisper_model})",
                    "#22C55E",
                    studio_badge="CANLI",
                    studio_badge_kind="live",
                )
            else:
                self.lbl_scene_tag.setText(f"Canlı Yakalama · {self.tuning.scan_fps} FPS")
                self.worker = CaptureTranslateWorker(
                    ocr_engine=self.ocr_engine,
                    translator=self.translator,
                    roi=self.roi,
                    scan_interval_sec=self.tuning.scan_interval_sec,
                    idle_scan_interval_sec=self.tuning.idle_scan_interval_sec,
                    target_filter=self._target_window,
                    parent=self,
                )
                self.worker.subtitle_updated.connect(self._on_subtitle_updated)
                self.worker.subtitle_cleared.connect(self._on_subtitle_cleared)
                self.worker.target_focus_changed.connect(self._on_target_focus_changed)
                self.worker.status_tick.connect(
                    lambda msg: self.card_total.set_metric(self.card_total.lbl_val.text(), sub_text=msg)
                )
                self.worker.start()
                self._set_engine_status(
                    f"Canlı Aktif ({self.tuning.scan_fps} FPS)",
                    "#22C55E",
                    studio_badge="CANLI",
                    studio_badge_kind="live",
                )

            if self._target_window and self._target_window.is_active and input_source != "audio":
                self.lbl_toggle_desc.setText(
                    self.i18n.t("target_app_active", target=self._target_window.short_label())
                )
            else:
                self.lbl_toggle_desc.setText("Sıkı Hizalama · Canlı Yakalama Aktif")
            self._set_toggle_button_style(active=True)

    def _on_subtitle_updated(
        self,
        en_text: str,
        tr_text: str,
        ocr_ms: float,
        tr_ms: float,
        is_cached: bool,
        orig_line_h: int = 0,
        layout: Optional[dict] = None,
    ) -> None:
        self.overlay.set_subtitle(
            tr_text,
            en_text,
            orig_line_h_px=orig_line_h,
            layout=layout if isinstance(layout, dict) else None,
        )
        self.lbl_en_preview.setText(en_text)
        self.lbl_tr_preview.setText(tr_text)

        total_ms = ocr_ms + tr_ms
        ocr_pct = int(min(100, (ocr_ms / 80.0) * 100)) if ocr_ms > 0 else 8
        nmt_pct = 5 if is_cached else int(min(100, (tr_ms / 140.0) * 100))
        tot_pct = int(min(100, (total_ms / 150.0) * 100))
        ctype = self.translator.active_compute_type.upper()

        self.card_ocr.set_metric(
            f"{ocr_ms:.1f} ms",
            sub_text="RapidOCR ONNX · Kare Kilidi",
            bar_pct=ocr_pct,
        )
        self.card_nmt.set_metric(
            f"{tr_ms:.3f} ms" if is_cached else f"{tr_ms:.1f} ms",
            sub_text="Önbellek / Sözlük"
            if is_cached
            else f"CTranslate2 {ctype} · {self.translator.cpu_threads} Thread",
            badge_text="CACHE" if is_cached else ctype,
            bar_pct=nmt_pct,
        )
        self.card_total.set_metric(
            f"{total_ms:.1f} ms",
            sub_text="Anlık algı eşiği altı (<150 ms)"
            if total_ms < 150
            else "Gerçek zamanlı yanıt",
            badge_text="INSTANT" if is_cached else "REAL-TIME",
            bar_pct=tot_pct,
        )
        self._update_session_kpi()

        stamp = datetime.now().strftime("%H:%M:%S")
        self._history_entries.append(
            HistoryEntry(
                timestamp=stamp,
                en_text=en_text,
                tr_text=tr_text,
                elapsed_sec=max(0.0, time.monotonic() - self._session_start_ts),
            )
        )
        tag = "ÖNBELLEK" if is_cached else ctype
        card = self._create_history_card(stamp, total_ms, tag, en_text, tr_text)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, tr_text)
        vp_w = self.list_history.viewport().width()
        avail_w = (vp_w - 16) if vp_w > 400 else max(520, self.width() - 84)
        card.resize(avail_w, 64)
        card_lay = card.layout()
        if card_lay is not None:
            card_lay.activate()
        hint_h = card.sizeHint().height()
        if card_lay is not None and card_lay.hasHeightForWidth():
            hint_h = max(hint_h, card_lay.totalHeightForWidth(avail_w))
        item.setSizeHint(QSize(avail_w, max(62, hint_h + 4)))
        self.list_history.insertItem(0, item)
        self.list_history.setItemWidget(item, card)
        if self.list_history.count() > 25:
            self.list_history.takeItem(self.list_history.count() - 1)
        self.btn_tab_history.setText(f"Geçmiş ({self.list_history.count()})")

    @staticmethod
    def _create_history_card(
        stamp: str, total_ms: float, tag: str, en_text: str, tr_text: str
    ) -> QWidget:
        card = QWidget()
        card.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)

        lbl_meta = QLabel(f"{stamp}  ·  {total_ms:.1f} ms  ·  {tag}")
        lbl_meta.setStyleSheet("color: #71717A; font-size: 7.7pt; font-weight: 600;")
        lay.addWidget(lbl_meta)

        lbl_en = QLabel(en_text)
        lbl_en.setWordWrap(True)
        lbl_en.setStyleSheet("color: #A1A1AA; font-size: 8.7pt; font-weight: 500;")
        lay.addWidget(lbl_en)

        lbl_tr = QLabel(tr_text)
        lbl_tr.setWordWrap(True)
        lbl_tr.setStyleSheet("color: #FAFAFA; font-size: 9.5pt; font-weight: 700;")
        lay.addWidget(lbl_tr)

        return card

    def _on_subtitle_cleared(self) -> None:
        self.overlay.set_subtitle("")

    def run_sample_test(self) -> None:
        if not self.translator.is_ready:
            return
        if not self.roi_selector.isVisible() and not self.overlay.isVisible():
            self.overlay.show()
        category, sample_en = self._samples[self._sample_idx % len(self._samples)]
        self._sample_idx += 1
        self.lbl_scene_tag.setText(f"Örnek Sahne · {category}")
        tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(sample_en)
        self._on_subtitle_updated(sample_en, tr_text, 19.8, tr_ms, is_cached)

    def run_benchmark_suite(self) -> None:
        if not self.translator.is_ready:
            return
        if self.bench_worker and self.bench_worker.isRunning():
            return

        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setText("  Ölçülüyor...")
        self.bench_worker = BenchmarkWorker(
            self.ocr_engine, self.translator, self.hw_profile, parent=self
        )
        self.bench_worker.finished_report.connect(self._on_benchmark_finished)
        self.bench_worker.start()

    def _on_benchmark_finished(self, rep: dict) -> None:
        self.btn_benchmark.setEnabled(True)
        self.btn_benchmark.setText("  Donanım Hız Testi Yap (Benchmark)")

        self.card_ocr.set_metric(
            f"{rep['avg_ocr_ms']:.1f} ms",
            sub_text=f"Kare Kilidi: {rep['pixel_lock_ms']:.2f} ms",
            bar_pct=int(min(100, (rep["avg_ocr_ms"] / 80.0) * 100)),
        )
        self.card_nmt.set_metric(
            f"{rep['avg_nmt_ms']:.1f} ms",
            sub_text=f"Cache Hit: {rep['cache_ms']:.4f} ms",
            bar_pct=int(min(100, (rep["avg_nmt_ms"] / 140.0) * 100)),
        )
        self.card_total.set_metric(
            f"{rep['total_cold_ms']:.1f} ms",
            sub_text=f"Önbellekli Toplam: {rep['total_cached_ms']:.1f} ms",
            bar_pct=int(min(100, (rep["total_cold_ms"] / 150.0) * 100)),
        )

        msg = (
            f"SubVision AI — Donanım Performans Raporu\n"
            f"─────────────────────────────────────────────────\n"
            f"İşlemci:  {rep['cpu_name']} ({rep['cores']})\n"
            f"Profil / Mod:  {self.tuning.effective_profile.upper()} · CTranslate2 {rep['compute_type']}\n\n"
            f"1. Sabit Kare Kilidi (Frame Diff Lock):  {rep['pixel_lock_ms']:.3f} ms\n"
            f"2. Hızlı Satır Okuma (RapidOCR):  {rep['avg_ocr_ms']:.1f} ms\n"
            f"3. Yapay Zeka Çeviri ({rep['threads']} Thread):  {rep['avg_nmt_ms']:.1f} ms\n"
            f"4. Önbellek / Sözlük Yanıtı:  {rep['cache_ms']:.4f} ms\n\n"
            f"Toplam Gecikme (Yeni Altyazı):  {rep['total_cold_ms']:.1f} ms\n"
            f"Toplam Gecikme (Önbellekli):  {rep['total_cached_ms']:.1f} ms\n"
            f"Ekran Kartı (VRAM) Yükü:  0 MB (%100 CPU)"
        )
        QMessageBox.information(self, "Donanım Performans Raporu", msg)

    @staticmethod
    def _calc_dir_size_mb(path: str) -> float:
        if not path or not os.path.exists(path):
            return 0.0
        total = 0
        try:
            for root_d, _, files in os.walk(path):
                for fname in files:
                    try:
                        total += os.path.getsize(os.path.join(root_d, fname))
                    except Exception:
                        pass
        except Exception:
            pass
        return total / (1024.0 * 1024.0)

    def open_component_manager(self) -> None:
        """
        Uygulama ile birlikte indirilen bileşenleri (227 MB yapay zeka modeli,
        kullanıcı ayarları, önbellek ve çalışma ortamı) opsiyonel olarak sıfırlama
        veya dijital imzalı Kaldırma Yardımcısını (SubVisionAI-Uninstaller.exe) başlatma penceresi.
        """
        app_dir = get_app_base_dir()
        model_mb = self._calc_dir_size_mb(self.translator.model_dir)
        runtime_mb = self._calc_dir_size_mb(os.path.join(app_dir, "runtime"))

        dlg = QDialog(self)
        dlg.setWindowTitle("SubVision AI — Bileşen ve Kaldırma Yöneticisi")
        dlg.setWindowIcon(create_app_icon())
        dlg.setMinimumWidth(540)
        dlg.setStyleSheet(
            """
            QDialog {
                background-color: #0C0C0E;
                color: #FAFAFA;
            }
            QFrame#mgrCard {
                background-color: #141417;
                border: 1px solid #242429;
                border-radius: 10px;
            }
            """
        )

        v_main = QVBoxLayout(dlg)
        v_main.setContentsMargins(18, 16, 18, 16)
        v_main.setSpacing(12)

        card = QFrame()
        card.setObjectName("mgrCard")
        v_card = QVBoxLayout(card)
        v_card.setContentsMargins(16, 14, 16, 14)
        v_card.setSpacing(10)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(12)
        dlg_logo = QLabel()
        dlg_logo.setPixmap(create_app_pixmap(38))
        dlg_logo.setFixedSize(38, 38)
        hdr_row.addWidget(dlg_logo)

        lbl_h = QLabel("İndirilen Bileşenler ve Kaldırma Seçenekleri")
        lbl_h.setStyleSheet("color: #FFFFFF; font-size: 11.5pt; font-weight: 700;")
        hdr_row.addWidget(lbl_h, stretch=1)
        v_card.addLayout(hdr_row)

        lbl_desc = QLabel(
            "Program ile birlikte yüklenen bileşenleri aşağıdan opsiyonel olarak seçip "
            "temizleyebilir veya tam kaldırma sihirbazını başlatabilirsiniz:"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 8.8pt;")
        v_card.addWidget(lbl_desc)

        chk_cache = QCheckBox(
            f"1. Çeviri Önbelleği ve Geçmişi Temizle ({self.translator.cache_size} cümle)"
        )
        chk_cache.setChecked(True)
        v_card.addWidget(chk_cache)

        chk_settings = QCheckBox(
            "2. Kişisel Kullanıcı Ayarları ve Alan Kalibrasyonunu Sıfırla (user_settings.json)"
        )
        chk_settings.setChecked(False)
        v_card.addWidget(chk_settings)

        chk_model = QCheckBox(
            f"3. İndirilen Yapay Zeka Çeviri Modelini Sil (models/opus-en-tr-ct2 — {model_mb:.1f} MB)"
        )
        chk_model.setChecked(False)
        chk_model.setStyleSheet("color: #FACC15; font-weight: 600;")
        v_card.addWidget(chk_model)

        lbl_runtime_info = QLabel(
            f"• Taşınabilir Çalışma Ortamı (runtime/): {runtime_mb:.1f} MB  |  Konum: {app_dir}"
        )
        lbl_runtime_info.setWordWrap(True)
        lbl_runtime_info.setStyleSheet("color: #64748B; font-size: 8.2pt; padding-top: 4px;")
        v_card.addWidget(lbl_runtime_info)

        v_main.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_clean = QPushButton("Seçili Bileşenleri Temizle")
        btn_clean.setStyleSheet(
            "QPushButton { background-color: #1C1C21; border: 1px solid #3F3F4A; color: #F59E0B; border-radius: 7px; padding: 7px 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #25252C; border-color: #F59E0B; }"
        )

        btn_uninst = QPushButton("Tam Kaldırma Yardımcısını Aç")
        btn_uninst.setStyleSheet(
            "QPushButton { background-color: #DC2626; border: 1px solid #DC2626; color: #FFFFFF; border-radius: 7px; padding: 7px 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #B91C1C; }"
        )

        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(dlg.reject)

        def _on_clean_clicked() -> None:
            if not (chk_cache.isChecked() or chk_settings.isChecked() or chk_model.isChecked()):
                QMessageBox.information(dlg, "SubVision AI", "Lütfen temizlemek için en az bir bileşen seçin.")
                return

            cleaned_items: List[str] = []
            if chk_cache.isChecked():
                self.translator.clear_cache()
                self._clear_history()
                self._update_session_kpi()
                cleaned_items.append("Çeviri önbelleği ve diyalog geçmişi")

            if chk_settings.isChecked():
                for p in (CONFIG_PATH, CRASH_LOG_PATH, os.path.join(app_dir, "benchmark_results.json")):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                cleaned_items.append("Kullanıcı ayarları (user_settings.json)")

            if chk_model.isChecked():
                if (self.worker and self.worker.running) or (
                    self.audio_worker and self.audio_worker.isRunning()
                ):
                    self.toggle_translation()
                self.translator.translator = None
                self.translator.source_sp = None
                self.translator.target_sp = None
                self.translator.is_ready = False
                import shutil

                shutil.rmtree(self.translator.model_dir, ignore_errors=True)
                self.btn_toggle.setEnabled(False)
                self.lbl_model_status.setText("●  Model Silindi")
                cleaned_items.append("İndirilen yapay zeka çeviri modeli (~227 MB)")

            QMessageBox.information(
                dlg,
                "SubVision AI — Temizlendi",
                "Seçili bileşenler başarıyla temizlendi:\n• " + "\n• ".join(cleaned_items),
            )
            dlg.accept()

        def _on_uninstaller_clicked() -> None:
            uninst_candidates = [
                os.path.join(app_dir, "SubVisionAI-Uninstaller.exe"),
                os.path.join(app_dir, "SubVisionAI.exe"),
                os.path.join(app_dir, "unins000.exe"),
            ]
            target_exe = next((p for p in uninst_candidates if os.path.exists(p)), None)
            if not target_exe:
                QMessageBox.information(
                    dlg,
                    "SubVision AI",
                    "SubVisionAI-Uninstaller.exe bulunamadı.\nDerlemek için: python build_exe.py",
                )
                return

            ans = QMessageBox.question(
                dlg,
                "Tam Kaldırma Yardımcısı",
                "Kaldırma Yardımcısının (SubVisionAI-Uninstaller.exe) çalışma ortamı dosyalarını "
                "serbestçe silebilmesi için mevcut uygulama penceresi kapatılacak.\n\n"
                "Kaldırma Yardımcısını şimdi başlatmak istiyor musunuz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                import subprocess

                args = [target_exe]
                if not target_exe.lower().endswith("unins000.exe"):
                    args.append("--uninstall")
                subprocess.Popen(args, cwd=app_dir)
                dlg.accept()
                self.close()

        btn_clean.clicked.connect(_on_clean_clicked)
        btn_uninst.clicked.connect(_on_uninstaller_clicked)

        btn_row.addWidget(btn_clean)
        btn_row.addWidget(btn_uninst)
        btn_row.addWidget(btn_close)
        v_main.addLayout(btn_row)

        dlg.exec()

    def _register_global_hotkeys(self) -> None:
        for sc in getattr(self, "_shortcuts", []):
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []

        roi_key = self._hotkeys.get("roi", "F7")
        toggle_key = self._hotkeys.get("toggle", "F8")
        sample_key = self._hotkeys.get("sample", "F9")

        if sys.platform == "win32":
            # Windows'ta GetAsyncKeyState hem odaklı hem arka planda çalıştığı için
            # QShortcut ile çift tetiklenme (F7/F8 double-fire) oluşmaması adına yalnızca Win32 polling kullanılır.
            self._vk_bindings = (
                (VK_FUNCTION_KEYS.get(roi_key, VK_F7), self.open_roi_selector),
                (VK_FUNCTION_KEYS.get(toggle_key, VK_F8), self.toggle_translation),
                (VK_FUNCTION_KEYS.get(sample_key, VK_F9), self.run_sample_test),
            )
            self._key_states = {vk: False for vk, _ in self._vk_bindings}
            if not hasattr(self, "_hotkey_timer"):
                self._hotkey_timer = QTimer(self)
                self._hotkey_timer.setInterval(45)
                self._hotkey_timer.timeout.connect(self._poll_global_hotkeys)
                self._hotkey_timer.start()
        else:
            self._shortcuts = [
                QShortcut(QKeySequence(roi_key), self, activated=self.open_roi_selector),
                QShortcut(QKeySequence(toggle_key), self, activated=self.toggle_translation),
                QShortcut(QKeySequence(sample_key), self, activated=self.run_sample_test),
            ]

    def _poll_global_hotkeys(self) -> None:
        if sys.platform != "win32":
            return
        if QApplication.activeModalWidget() is not None:
            return
        try:
            for vk, callback in getattr(self, "_vk_bindings", ()):
                is_down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                if is_down and not self._key_states.get(vk, False):
                    self._key_states[vk] = True
                    callback()
                elif not is_down:
                    self._key_states[vk] = False
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        if (
            not self._force_quit
            and self.tray_icon is not None
            and hasattr(self, "chk_minimize_tray")
            and self.chk_minimize_tray.isChecked()
        ):
            event.ignore()
            self.hide()
            return

        if hasattr(self, "_hotkey_timer"):
            self._hotkey_timer.stop()
        if hasattr(self, "_auto_profile_timer"):
            self._auto_profile_timer.stop()
        if hasattr(self, "loader_thread") and self.loader_thread.isRunning():
            self.loader_thread.wait(2000)
        if self.bench_worker and self.bench_worker.isRunning():
            self.bench_worker.wait(2000)
        if self.worker and self.worker.running:
            self.worker.stop()
        if self.audio_worker and self.audio_worker.isRunning():
            self.audio_worker.stop()
            self.audio_worker.wait(1500)
        for retired in list(self._retired_workers):
            if retired.isRunning():
                retired.wait(1200)
        self._retired_workers.clear()
        if self.update_thread and self.update_thread.isRunning():
            self.update_thread.wait(1000)
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.overlay.close()
        self.roi_selector.close()
        super().closeEvent(event)


def _install_crash_logger() -> None:
    _handling = {"active": False}

    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        if _handling["active"]:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _handling["active"] = True
        try:
            tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            try:
                with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().isoformat()}]\n{tb_text}\n")
            except Exception:
                pass
            try:
                app = QApplication.instance()
                if app is not None and QThread.currentThread() == app.thread():
                    QMessageBox.critical(
                        None,
                        "SubVision AI — Beklenmeyen Hata",
                        f"Uygulama çalışırken beklenmeyen bir hata oluştu:\n\n{exc_value}\n\n"
                        f"Detaylı hata kaydı şuraya yazıldı:\n{CRASH_LOG_PATH}",
                    )
            except Exception:
                pass
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        finally:
            _handling["active"] = False

    sys.excepthook = _handle_exception


def _acquire_single_instance() -> Tuple[bool, object]:
    """
    Windows'ta Win32 Mutex, Linux/macOS'ta QLocalServer ile tek örnek (single-instance) kilidi sağlar.
    """
    if sys.platform == "win32":
        try:
            mutex_name = "SubVisionAI_TR_Subtitle_SingleInstance_Mutex_v2"
            mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
            if ctypes.windll.kernel32.GetLastError() == 183:
                hwnd = ctypes.windll.user32.FindWindowW(None, APP_TITLE)
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                return False, None
            return True, ("win32", mutex)
        except Exception:
            return True, None

    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket

        server_name = "SubVisionAI_SingleInstance_IPC_v2"
        probe = QLocalSocket()
        probe.connectToServer(server_name)
        if probe.waitForConnected(150):
            probe.disconnectFromServer()
            return False, None

        QLocalServer.removeServer(server_name)
        server = QLocalServer()
        if server.listen(server_name):
            return True, ("qt_ipc", server)
    except Exception:
        pass
    return True, None


def _release_single_instance(handle: object) -> None:
    if not handle or not isinstance(handle, tuple):
        return
    kind, obj = handle
    try:
        if kind == "win32" and obj:
            ctypes.windll.kernel32.CloseHandle(obj)
        elif kind == "qt_ipc" and obj:
            obj.close()
    except Exception:
        pass


def main():
    _install_crash_logger()

    app = QApplication(sys.argv)
    acquired, lock_handle = _acquire_single_instance()
    if not acquired:
        sys.exit(0)

    window = MainWindow()
    window.show()
    ret = app.exec()
    _release_single_instance(lock_handle)
    sys.exit(ret)


if __name__ == "__main__":
    main()
