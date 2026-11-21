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

from PyQt6.QtCore import QRect, QSize, QTimer, Qt
from PyQt6.QtGui import QAction, QFont, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
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
from subvision.ui_widgets import (
    FlatComboBox,
    FlatSwitch,
    TelemetryCard,
    create_app_icon,
    create_app_pixmap,
    make_flat_icon,
)
from subvision.updater import UpdateCheckerThread, UpdateInfo
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

        # Kompakt, ferah ve her ekrana kaydırmasız sığan modern pencere boyutu
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        min_w = min(740, max(660, avail.width() - 40))
        min_h = min(560, max(500, avail.height() - 40))
        init_w = min(860, max(min_w, avail.width() - 60))
        init_h = min(650, max(min_h, avail.height() - 60))
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

        self.roi: Dict[str, int] = self.settings.get("roi", self._default_roi())
        self._resume_after_roi = False
        self._restore_window_after_roi = False

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
        self._selected_color = self.settings.get("text_color", "#FACC15")
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
        dpr = screen.devicePixelRatio() if screen else 1.0
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
                background-color: #060A13;
                color: #F8FAFC;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', 'DejaVu Sans', -apple-system, sans-serif;
            }}
            QLabel {{
                background-color: transparent;
                color: #E2E8F0;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', 'DejaVu Sans', -apple-system, sans-serif;
            }}
            QFrame#brandHeader {{
                background-color: #0B1220;
                border: 1px solid #1E2D45;
                border-radius: 14px;
            }}
            QFrame#studioPanel {{
                background-color: #0C1322;
                border: 1px solid #1A263B;
                border-radius: 14px;
            }}
            QFrame#stepCard {{
                background-color: #090F1C;
                border: 1px solid #1C2940;
                border-radius: 12px;
            }}
            QPushButton {{
                background-color: #131D31;
                color: #F1F5F9;
                border: 1px solid #24344F;
                border-radius: 9px;
                padding: 8px 14px;
                font-size: 9.2pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #1A2742;
                border-color: #38BDF8;
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: #0F172A;
            }}
            QPushButton:disabled {{
                background-color: #0B101C;
                color: #475569;
                border-color: #162033;
            }}
            QComboBox {{
                background-color: #0F172A;
                border: 1px solid #24344F;
                border-radius: 8px;
                padding: 7px 12px;
                min-height: 22px;
                color: #F8FAFC;
                font-size: 9.2pt;
                font-weight: 500;
            }}
            QComboBox:hover {{
                border-color: #38BDF8;
                background-color: #131E36;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 26px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #0F172A;
                color: #F8FAFC;
                selection-background-color: #1E3A5F;
                selection-color: #FFFFFF;
                border: 1px solid #38BDF8;
                outline: none;
                padding: 4px;
            }}
            QSlider {{
                background-color: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 5px;
                background: #1A263B;
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: #38BDF8;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 2px solid #0284C7;
                width: 15px;
                height: 15px;
                margin: -6px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #FACC15;
                border-color: #38BDF8;
            }}
            QListWidget {{
                background-color: #080D18;
                border: 1px solid #1A263B;
                border-radius: 10px;
                color: #E2E8F0;
                font-size: 9pt;
                padding: 6px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 0px;
                border-bottom: 1px solid #131D30;
                border-radius: 8px;
                margin-bottom: 4px;
            }}
            QListWidget::item:hover {{
                background-color: #0E1729;
            }}
            QListWidget::item:selected {{
                background-color: #132038;
                color: #FFFFFF;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: #1E2D45;
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #38BDF8;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            """
        )

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        central = QWidget()
        central.setObjectName("centralWidget")
        scroll_area.setWidget(central)
        self.setCentralWidget(scroll_area)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(18, 16, 18, 14)

        # ═════════════════════════════════════════════════════════════════════
        # 1. YENİ LOGOLU MODERN BAŞLIK & SEKMELİ GEZİNTİ ÇUBUĞU
        # ═════════════════════════════════════════════════════════════════════
        header_frame = QFrame()
        header_frame.setObjectName("brandHeader")
        header_v = QVBoxLayout(header_frame)
        header_v.setContentsMargins(16, 13, 16, 13)
        header_v.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(14)

        # Yeni Logo (52x52 HiDPI)
        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(52))
        logo_lbl.setFixedSize(52, 52)
        logo_lbl.setStyleSheet("border: none; background: transparent;")
        top_bar.addWidget(logo_lbl)

        # Marka Başlığı ve Durum Satırı
        title_col = QVBoxLayout()
        title_col.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_lbl = QLabel("SubVision AI")
        title_lbl.setFont(QFont(ui_font, 15, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        title_row.addWidget(title_lbl)

        ver_pill = QLabel("v1.3")
        ver_pill.setStyleSheet(
            """
            color: #38BDF8;
            background-color: #0F223D;
            border: 1px solid #1E3A5F;
            border-radius: 5px;
            padding: 1px 7px;
            font-size: 7.8pt;
            font-weight: 700;
            """
        )
        title_row.addWidget(ver_pill)

        self.lbl_model_status = QLabel("●  Hazırlanıyor...")
        self.lbl_model_status.setStyleSheet(
            """
            color: #FACC15;
            background-color: #231F0D;
            border: 1px solid #4D4113;
            border-radius: 9px;
            padding: 2px 10px;
            font-size: 8.2pt;
            font-weight: 600;
            """
        )
        title_row.addWidget(self.lbl_model_status)
        title_row.addStretch(1)
        title_col.addLayout(title_row)

        sub_lbl = QLabel("Oyun, Dizi ve Videolar İçin Anlık Ekran Üstü Türkçe Altyazı")
        sub_lbl.setStyleSheet(
            "color: #94A3B8; font-size: 9pt; font-weight: 500; border: none; background: transparent;"
        )
        title_col.addWidget(sub_lbl)
        top_bar.addLayout(title_col, stretch=1)

        # Sağ: Sade 3 Sekmeli Kapsül Gezinti Menüsü
        nav_capsule = QFrame()
        nav_capsule.setStyleSheet(
            """
            QFrame {
                background-color: #060A13;
                border: 1px solid #1A263B;
                border-radius: 10px;
            }
            """
        )
        nav_row = QHBoxLayout(nav_capsule)
        nav_row.setContentsMargins(4, 4, 4, 4)
        nav_row.setSpacing(4)

        self.btn_tab_main = QPushButton("Ana Ekran")
        self.btn_tab_history = QPushButton("Geçmiş")
        self.btn_tab_settings = QPushButton("Ayarlar")
        for idx, b in enumerate((self.btn_tab_main, self.btn_tab_history, self.btn_tab_settings)):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda checked=False, i=idx: self._switch_tab(i))
            nav_row.addWidget(b)

        top_bar.addWidget(nav_capsule, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_v.addLayout(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 2px;
                background-color: #131D31;
            }
            QProgressBar::chunk {
                background-color: #38BDF8;
                border-radius: 2px;
            }
            """
        )
        header_v.addWidget(self.progress_bar)
        main_layout.addWidget(header_frame)

        # ═════════════════════════════════════════════════════════════════════
        # 2. SEKMELİ İÇERİK ALANI (QStackedWidget)
        # ═════════════════════════════════════════════════════════════════════
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, stretch=1)

        # ─────────────────────────────────────────────────────────────────────
        # SEKME 0: ANA EKRAN (ÇEVİRİ & GÖRÜNÜM) — %100 Sadeleştirilmiş Deneyim
        # ─────────────────────────────────────────────────────────────────────
        page_main = QWidget()
        page_main_lay = QVBoxLayout(page_main)
        page_main_lay.setContentsMargins(0, 0, 0, 0)
        page_main_lay.setSpacing(12)

        # A) 2 ADIMDA KULLANIM KARTI (Alan Seç -> Çeviriyi Başlat)
        steps_row = QHBoxLayout()
        steps_row.setSpacing(12)

        # ADIM 1 KARTI
        step1_card = QFrame()
        step1_card.setObjectName("stepCard")
        s1_lay = QVBoxLayout(step1_card)
        s1_lay.setContentsMargins(14, 12, 14, 12)
        s1_lay.setSpacing(7)

        s1_hdr = QHBoxLayout()
        lbl_s1_badge = QLabel("1. ADIM  ·  ALTYAZI YERİ")
        lbl_s1_badge.setStyleSheet(
            "color: #38BDF8; font-size: 7.8pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        s1_hdr.addWidget(lbl_s1_badge)

        self.lbl_roi_badge = QLabel(f"Seçili: {self.roi['width']}×{self.roi['height']} px")
        self.lbl_roi_badge.setStyleSheet(
            "color: #94A3B8; font-size: 7.8pt; font-weight: 600;"
        )
        s1_hdr.addWidget(self.lbl_roi_badge, alignment=Qt.AlignmentFlag.AlignRight)
        s1_lay.addLayout(s1_hdr)

        self.btn_select_roi = QPushButton("  Altyazı Alanını Seç   (F7)")
        self.btn_select_roi.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_roi.setIcon(make_flat_icon("target", "#38BDF8", 15))
        self.btn_select_roi.setIconSize(QSize(15, 15))
        self.btn_select_roi.setMinimumHeight(44)
        self.btn_select_roi.setStyleSheet(
            """
            QPushButton {
                background-color: #132038;
                border: 1px solid #25406B;
                border-radius: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #192B4B;
                border-color: #38BDF8;
                color: #FFFFFF;
            }
            """
        )
        self.btn_select_roi.clicked.connect(self.open_roi_selector)
        s1_lay.addWidget(self.btn_select_roi)

        lbl_s1_desc = QLabel("Ekranda İngilizce altyazının çıktığı bölgeyi fareyle kutu içine alın.")
        lbl_s1_desc.setStyleSheet("color: #64748B; font-size: 8.1pt; font-weight: 500;")
        s1_lay.addWidget(lbl_s1_desc)
        steps_row.addWidget(step1_card, stretch=1)

        # ADIM 2 KARTI
        step2_card = QFrame()
        step2_card.setObjectName("stepCard")
        s2_lay = QVBoxLayout(step2_card)
        s2_lay.setContentsMargins(14, 12, 14, 12)
        s2_lay.setSpacing(7)

        s2_hdr = QHBoxLayout()
        lbl_s2_badge = QLabel("2. ADIM  ·  CANLI ÇEVİRİ")
        lbl_s2_badge.setStyleSheet(
            "color: #FACC15; font-size: 7.8pt; font-weight: 700; letter-spacing: 0.7px;"
        )
        s2_hdr.addWidget(lbl_s2_badge)

        self.lbl_scene_tag = QLabel(f"Otomatik · {self.tuning.scan_fps} FPS")
        self.lbl_scene_tag.setStyleSheet(
            "color: #94A3B8; font-size: 7.8pt; font-weight: 600;"
        )
        s2_hdr.addWidget(self.lbl_scene_tag, alignment=Qt.AlignmentFlag.AlignRight)
        s2_lay.addLayout(s2_hdr)

        self.btn_toggle = QPushButton("  Anlık Çeviriyi Başlat   (F8)")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setIcon(make_flat_icon("play", "#FFFFFF", 14))
        self.btn_toggle.setIconSize(QSize(14, 14))
        self.btn_toggle.setMinimumHeight(44)
        self.btn_toggle.setEnabled(False)
        self._set_toggle_button_style(active=False)
        self.btn_toggle.clicked.connect(self.toggle_translation)
        s2_lay.addWidget(self.btn_toggle)

        self.lbl_toggle_desc = QLabel("Seçili alandaki altyazıları gerçek zamanlı okuyup Türkçeye çevirir.")
        self.lbl_toggle_desc.setStyleSheet("color: #64748B; font-size: 8.1pt; font-weight: 500;")
        s2_lay.addWidget(self.lbl_toggle_desc)
        steps_row.addWidget(step2_card, stretch=1)

        page_main_lay.addLayout(steps_row)

        # B) TEK BİRLEŞİK CANLI ALTYAZI & ÖNİZLEME EKRANI
        live_card = QFrame()
        live_card.setObjectName("studioPanel")
        live_lay = QVBoxLayout(live_card)
        live_lay.setContentsMargins(16, 13, 16, 14)
        live_lay.setSpacing(9)

        live_hdr = QHBoxLayout()
        live_hdr.setSpacing(8)
        lbl_live_title = QLabel("CANLI ALTYAZI & ÖNİZLEME")
        lbl_live_title.setStyleSheet(
            "color: #94A3B8; font-size: 8pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        live_hdr.addWidget(lbl_live_title)
        live_hdr.addStretch(1)

        self.btn_test = QPushButton(" Örnek Sahne Dene (F9)")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.setIcon(make_flat_icon("preview", "#38BDF8", 13))
        self.btn_test.setIconSize(QSize(13, 13))
        self.btn_test.setEnabled(False)
        self.btn_test.setStyleSheet(
            """
            QPushButton {
                background-color: #101A2E;
                color: #38BDF8;
                border: 1px solid #1E3A5F;
                padding: 4px 11px;
                font-size: 8.2pt;
                font-weight: 600;
                border-radius: 7px;
            }
            QPushButton:hover {
                background-color: #162642;
                border-color: #38BDF8;
                color: #FFFFFF;
            }
            QPushButton:disabled {
                color: #475569;
                border-color: #162033;
                background-color: #0B101C;
            }
            """
        )
        self.btn_test.clicked.connect(self.run_sample_test)
        live_hdr.addWidget(self.btn_test)

        btn_copy = QPushButton(" Kopyala")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setIcon(make_flat_icon("copy", "#94A3B8", 12))
        btn_copy.setIconSize(QSize(12, 12))
        btn_copy.setStyleSheet(
            """
            QPushButton {
                background-color: #101A2E;
                color: #CBD5E1;
                border: 1px solid #1E2D45;
                padding: 4px 10px;
                font-size: 8.2pt;
                font-weight: 600;
                border-radius: 7px;
            }
            QPushButton:hover {
                background-color: #1A2742;
                color: #FFFFFF;
                border-color: #38BDF8;
            }
            """
        )
        btn_copy.clicked.connect(self._copy_current_translation)
        live_hdr.addWidget(btn_copy)
        live_lay.addLayout(live_hdr)

        # Birleşik Sinematik Önizleme Kutusu
        self.preview_box = QFrame()
        self.preview_box.setMinimumHeight(106)
        prev_v = QVBoxLayout(self.preview_box)
        prev_v.setContentsMargins(18, 14, 18, 14)
        prev_v.setSpacing(6)

        self.lbl_en_preview = QLabel(
            "Altyazı bekleniyor... Test etmek için 'Örnek Sahne Dene (F9)' butonuna tıklayabilirsiniz."
        )
        self.lbl_en_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_en_preview.setWordWrap(True)
        prev_v.addWidget(self.lbl_en_preview)

        self.lbl_tr_preview = QLabel("Türkçe çeviri burada ve seçtiğiniz ekran bölgesinde anında görünür.")
        self.lbl_tr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_tr_preview.setWordWrap(True)
        prev_v.addWidget(self.lbl_tr_preview)

        # Geriye dönük uyumluluk referansları
        self.lbl_mini_en = self.lbl_en_preview
        self.lbl_mini_tr = self.lbl_tr_preview

        live_lay.addWidget(self.preview_box, stretch=1)
        page_main_lay.addWidget(live_card, stretch=1)

        # C) SADELEŞTİRİLMİŞ ALTYAZI GÖRÜNÜMÜ KARTI
        style_card = QFrame()
        style_card.setObjectName("studioPanel")
        style_lay = QVBoxLayout(style_card)
        style_lay.setContentsMargins(16, 13, 16, 13)
        style_lay.setSpacing(10)

        lbl_style_hdr = QLabel("ALTYAZI GÖRÜNÜMÜ")
        lbl_style_hdr.setStyleSheet(
            "color: #94A3B8; font-size: 8pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        style_lay.addWidget(lbl_style_hdr)

        # Üst Satır: Altyazı Rengi (Sol) & Ekrandaki Konumu (Sağ)
        style_top_grid = QGridLayout()
        style_top_grid.setHorizontalSpacing(18)
        style_top_grid.setVerticalSpacing(6)

        lbl_col_title = QLabel("Altyazı Rengi")
        lbl_col_title.setStyleSheet("color: #CBD5E1; font-size: 8.6pt; font-weight: 600;")
        style_top_grid.addWidget(lbl_col_title, 0, 0)

        lbl_pos_title = QLabel("Ekrandaki Konumu")
        lbl_pos_title.setStyleSheet("color: #CBD5E1; font-size: 8.6pt; font-weight: 600;")
        style_top_grid.addWidget(lbl_pos_title, 0, 1)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        self._color_buttons: Dict[str, QPushButton] = {}
        color_presets = [
            ("#FACC15", "Sarı"),
            ("#FFFFFF", "Beyaz"),
            ("#38BDF8", "Turkuaz"),
            ("#4ADE80", "Yeşil"),
        ]
        for hex_code, label_txt in color_presets:
            b = QPushButton(f" {label_txt}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(make_flat_icon("dot", hex_code, 10))
            b.setIconSize(QSize(10, 10))
            b.clicked.connect(lambda checked=False, c=hex_code: self._select_color_swatch(c))
            self._color_buttons[hex_code] = b
            swatch_row.addWidget(b)
        style_top_grid.addLayout(swatch_row, 1, 0)

        seg_frame = QFrame()
        seg_frame.setStyleSheet(
            "QFrame { background-color: #070B14; border: 1px solid #1C2940; border-radius: 9px; }"
        )
        pos_row = QHBoxLayout(seg_frame)
        pos_row.setContentsMargins(3, 3, 3, 3)
        pos_row.setSpacing(4)
        self.btn_mode_cover = QPushButton("Orijinalin Üstünü Kapat")
        self.btn_mode_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        if not self.hw_profile.capture_exclude_supported:
            self.btn_mode_cover.setToolTip(
                "Bu işletim sistemi sürümünde WDA_EXCLUDEFROMCAPTURE desteklenmediği için "
                "OCR döngüsünü önlemek adına 'Hemen Üstünde' konumu otomatik uygulanır."
            )
        self.btn_mode_above = QPushButton("Hemen Üstünde Göster")
        self.btn_mode_above.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_cover.clicked.connect(lambda: self._select_overlay_mode("cover"))
        self.btn_mode_above.clicked.connect(lambda: self._select_overlay_mode("above"))
        pos_row.addWidget(self.btn_mode_cover)
        pos_row.addWidget(self.btn_mode_above)
        style_top_grid.addWidget(seg_frame, 1, 1)

        style_top_grid.setColumnStretch(0, 1)
        style_top_grid.setColumnStretch(1, 1)
        style_lay.addLayout(style_top_grid)

        # Orta Satır: Yazı Boyutu & Arka Plan Koyuluğu (Yan Yana 2 Sütun)
        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(18)

        # Sol Slider: Yazı Boyutu
        font_col = QHBoxLayout()
        font_col.setSpacing(8)
        self.lbl_font_cap = QLabel("Yazı Boyutu")
        self.lbl_font_cap.setStyleSheet("color: #CBD5E1; font-size: 8.6pt; font-weight: 600;")
        font_col.addWidget(self.lbl_font_cap)

        self.slider_font = QSlider(Qt.Orientation.Horizontal)
        self.slider_font.setRange(14, 36)
        self.slider_font.setValue(self.settings.get("font_size", 22))
        self.slider_font.valueChanged.connect(self._on_appearance_changed)
        font_col.addWidget(self.slider_font, stretch=1)

        self.lbl_font_val = QLabel("22 pt")
        self.lbl_font_val.setMinimumWidth(42)
        self.lbl_font_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_font_val.setStyleSheet("color: #38BDF8; font-size: 8.6pt; font-weight: 700;")
        font_col.addWidget(self.lbl_font_val)
        sliders_row.addLayout(font_col, stretch=1)

        # Sağ Slider: Arka Plan Koyuluğu
        alpha_col = QHBoxLayout()
        alpha_col.setSpacing(8)
        lbl_alpha_cap = QLabel("Arka Plan Koyuluğu")
        lbl_alpha_cap.setStyleSheet("color: #CBD5E1; font-size: 8.6pt; font-weight: 600;")
        alpha_col.addWidget(lbl_alpha_cap)

        init_alpha = self.settings.get("bg_alpha", 225)
        self.slider_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(90, 250)
        self.slider_alpha.setValue(init_alpha)
        self.slider_alpha.valueChanged.connect(self._on_appearance_changed)
        alpha_col.addWidget(self.slider_alpha, stretch=1)

        self.lbl_alpha_val = QLabel(f"%{int(init_alpha / 255 * 100)}")
        self.lbl_alpha_val.setMinimumWidth(42)
        self.lbl_alpha_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_alpha_val.setStyleSheet("color: #38BDF8; font-size: 8.6pt; font-weight: 700;")
        alpha_col.addWidget(self.lbl_alpha_val)
        sliders_row.addLayout(alpha_col, stretch=1)

        style_lay.addLayout(sliders_row)

        # Alt Satır: 3 Pratik Görünüm Anahtarı
        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(20)

        self.chk_guide = FlatSwitch("Hizalama çerçevesini göster")
        self.chk_guide.setChecked(False)
        self.chk_guide.toggled.connect(self.overlay.set_guide_border)
        toggles_row.addWidget(self.chk_guide)

        self.chk_bilingual = FlatSwitch("Çift dilli görünüm (EN + TR)")
        self.chk_bilingual.setChecked(self.settings.get("show_bilingual", False))
        self.chk_bilingual.toggled.connect(self._on_appearance_changed)
        toggles_row.addWidget(self.chk_bilingual)

        self.chk_autofit = FlatSwitch("Yazıyı kutuya otomatik sığdır")
        self.chk_autofit.setChecked(self.settings.get("auto_fit_font", True))
        self.chk_autofit.toggled.connect(self._on_appearance_changed)
        toggles_row.addWidget(self.chk_autofit)

        toggles_row.addStretch(1)
        style_lay.addLayout(toggles_row)

        page_main_lay.addWidget(style_card)
        self.stack.addWidget(page_main)

        # ─────────────────────────────────────────────────────────────────────
        # SEKME 1: DİYALOG GEÇMİŞİ
        # ─────────────────────────────────────────────────────────────────────
        page_hist = QFrame()
        page_hist.setObjectName("studioPanel")
        hist_lay = QVBoxLayout(page_hist)
        hist_lay.setContentsMargins(16, 14, 16, 14)
        hist_lay.setSpacing(10)

        hist_hdr = QHBoxLayout()
        hist_hdr.setSpacing(8)
        lbl_hist = QLabel("ÇEVRİLEN DİYALOG GEÇMİŞİ")
        lbl_hist.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        hist_hdr.addWidget(lbl_hist)
        hist_hdr.addStretch(1)

        export_btn_css = (
            "QPushButton { background-color: #0F1D33; color: #38BDF8; border: 1px solid #1E3A5F; "
            "padding: 4px 10px; font-size: 8pt; font-weight: 600; border-radius: 7px; }"
            "QPushButton:hover { background-color: #162B4D; color: #FFFFFF; border-color: #38BDF8; }"
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

        btn_clear_hist = QPushButton("Geçmişi Temizle")
        btn_clear_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_hist.setStyleSheet(
            """
            QPushButton {
                background-color: #131D31;
                color: #94A3B8;
                border: 1px solid #1E2D45;
                padding: 4px 12px;
                font-size: 8.2pt;
                font-weight: 600;
                border-radius: 7px;
            }
            QPushButton:hover {
                color: #F87171;
                border-color: #EF4444;
                background-color: #1F1218;
            }
            """
        )
        btn_clear_hist.clicked.connect(self._clear_history)
        hist_hdr.addWidget(btn_clear_hist, alignment=Qt.AlignmentFlag.AlignRight)
        hist_lay.addLayout(hist_hdr)

        self.list_history = QListWidget()
        self.list_history.setWordWrap(True)
        self.list_history.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list_history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_history.itemClicked.connect(self._on_history_item_clicked)
        hist_lay.addWidget(self.list_history, stretch=1)

        self.stack.addWidget(page_hist)

        # ─────────────────────────────────────────────────────────────────────
        # SEKME 2: GELİŞMİŞ AYARLAR & SİSTEM (Kaydırılabilir)
        # ─────────────────────────────────────────────────────────────────────
        page_settings_scroll = QScrollArea()
        page_settings_scroll.setWidgetResizable(True)
        page_settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_settings_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        page_settings = QWidget()
        page_settings.setStyleSheet("background: transparent;")
        settings_lay = QVBoxLayout(page_settings)
        settings_lay.setContentsMargins(0, 0, 4, 0)
        settings_lay.setSpacing(12)

        # Motor & Algılama Ayarları Kartı
        engine_card = QFrame()
        engine_card.setObjectName("studioPanel")
        eng_lay = QVBoxLayout(engine_card)
        eng_lay.setContentsMargins(16, 14, 16, 14)
        eng_lay.setSpacing(10)

        lbl_eng_title = QLabel("ALGILAMA VE PERFORMANS AYARLARI")
        lbl_eng_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        eng_lay.addWidget(lbl_eng_title)

        eng_grid = QGridLayout()
        eng_grid.setHorizontalSpacing(16)
        eng_grid.setVerticalSpacing(6)

        lbl_ocr_prof = QLabel("Altyazı Okuma (OCR) Modu")
        lbl_ocr_prof.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 600;")
        eng_grid.addWidget(lbl_ocr_prof, 0, 0)

        lbl_perf_prof = QLabel("İşlemci Hız Profili")
        lbl_perf_prof.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 600;")
        eng_grid.addWidget(lbl_perf_prof, 0, 1)

        self.combo_ocr_mode = FlatComboBox()
        self.combo_ocr_mode.addItem("Kontürlü / Adaptif Maske — Oyun & Dizi (Önerilen)", "fast_mask")
        self.combo_ocr_mode.addItem("Akıllı Hibrit — Oyun, Dizi & Açık Zemin", "hybrid")
        self.combo_ocr_mode.addItem("Tam Kare Okuma — Genel Video & Yayın", "full_ocr")
        self.combo_ocr_mode.currentIndexChanged.connect(self._on_ocr_mode_changed)
        eng_grid.addWidget(self.combo_ocr_mode, 1, 0)

        self.combo_perf_profile = FlatComboBox()
        self.combo_perf_profile.addItem("Otomatik — Bilgisayara Göre En İyi (Önerilen)", PROFILE_AUTO)
        self.combo_perf_profile.addItem("Eko — Düşük İşlemci Kullanımı (15 FPS)", PROFILE_ECO)
        self.combo_perf_profile.addItem("Dengeli — Standart Akıcılık (24 FPS)", PROFILE_BALANCED)
        self.combo_perf_profile.addItem("Performans — Maksimum Akıcılık (30 FPS)", PROFILE_PERFORMANCE)
        self.combo_perf_profile.currentIndexChanged.connect(self._on_perf_profile_changed)
        eng_grid.addWidget(self.combo_perf_profile, 1, 1)

        eng_grid.setColumnStretch(0, 1)
        eng_grid.setColumnStretch(1, 1)
        eng_lay.addLayout(eng_grid)

        settings_lay.addWidget(engine_card)

        # Sistem & Performans Telemetrisi Kartı
        sys_card = QFrame()
        sys_card.setObjectName("studioPanel")
        sys_lay = QVBoxLayout(sys_card)
        sys_lay.setContentsMargins(16, 14, 16, 14)
        sys_lay.setSpacing(10)

        sys_hdr = QHBoxLayout()
        lbl_sys_title = QLabel("DONANIM VE CANLI HIZ ÖLÇÜMÜ")
        lbl_sys_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        sys_hdr.addWidget(lbl_sys_title)

        self.hw_badge = QLabel(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.hw_badge.setStyleSheet(
            "color: #38BDF8; background-color: #091526; border: 1px solid #1E3A5F; border-radius: 6px; padding: 3px 10px; font-size: 7.8pt; font-weight: 600;"
        )
        sys_hdr.addWidget(self.hw_badge, alignment=Qt.AlignmentFlag.AlignRight)
        sys_lay.addLayout(sys_hdr)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self.card_ocr = TelemetryCard(
            "OCR OKUMA",
            "FAST MASK",
            "— ms",
            f"Kare Kilidi · {self.tuning.ocr_intra_threads} Thread",
            "#38BDF8",
            18,
        )
        self.card_nmt = TelemetryCard(
            f"ÇEVİRİ ({self.translator.active_compute_type.upper()})",
            f"{self.translator.cpu_threads} THREAD",
            "— ms",
            "Opus-MT EN → TR",
            "#FACC15",
            40,
        )
        self.card_total = TelemetryCard(
            "TOPLAM SÜRE",
            "REAL-TIME",
            "— ms",
            "Hedef < 150 ms anlık yanıt",
            "#10B981",
            50,
        )
        self.card_stats = TelemetryCard(
            "OTURUM",
            f"{self.tuning.scan_fps} FPS",
            "0 Çeviri",
            f"ROI {self.roi['width']}×{self.roi['height']} px · Hit %0",
            "#A78BFA",
            10,
        )

        kpi_row.addWidget(self.card_ocr)
        kpi_row.addWidget(self.card_nmt)
        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_stats)
        sys_lay.addLayout(kpi_row)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(10)

        self.btn_benchmark = QPushButton("  Donanım Hız Testi Yap (Benchmark)")
        self.btn_benchmark.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_benchmark.setIcon(make_flat_icon("gauge", "#38BDF8", 14))
        self.btn_benchmark.setIconSize(QSize(14, 14))
        self.btn_benchmark.setMinimumHeight(38)
        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.clicked.connect(self.run_benchmark_suite)
        tools_row.addWidget(self.btn_benchmark)

        self.btn_manage = QPushButton("  İndirilen Bileşenler / Uygulamayı Kaldır")
        self.btn_manage.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manage.setIcon(make_flat_icon("manage", "#FACC15", 14))
        self.btn_manage.setIconSize(QSize(14, 14))
        self.btn_manage.setMinimumHeight(38)
        self.btn_manage.clicked.connect(self.open_component_manager)
        tools_row.addWidget(self.btn_manage)

        sys_lay.addLayout(tools_row)
        settings_lay.addWidget(sys_card)

        # ── BAĞLAM FARKINDALIKLI ÇEVİRİ KATMANI & CANLI SES (WHISPER) KARTI ──
        ai_card = QFrame()
        ai_card.setObjectName("studioPanel")
        ai_lay = QVBoxLayout(ai_card)
        ai_lay.setContentsMargins(16, 14, 16, 14)
        ai_lay.setSpacing(10)

        lbl_ai_title = QLabel(self.i18n.t("translation_backend_title").upper())
        lbl_ai_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        ai_lay.addWidget(lbl_ai_title)

        lbl_ai_desc = QLabel(self.i18n.t("translation_backend_desc"))
        lbl_ai_desc.setWordWrap(True)
        lbl_ai_desc.setStyleSheet("color: #64748B; font-size: 8.2pt;")
        ai_lay.addWidget(lbl_ai_desc)

        ai_grid = QGridLayout()
        ai_grid.setHorizontalSpacing(14)
        ai_grid.setVerticalSpacing(6)

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
        ai_grid.addWidget(self.combo_tr_backend, 0, 0, 1, 2)

        input_css = (
            "QLineEdit { background-color: #090E1A; border: 1px solid #1E2D47; "
            "border-radius: 7px; padding: 6px 10px; color: #E2E8F0; font-size: 8.5pt; }"
            "QLineEdit:focus { border: 1px solid #38BDF8; }"
        )
        self.edit_tr_endpoint = QLineEdit(self.settings.get("translation_endpoint", ""))
        self.edit_tr_endpoint.setPlaceholderText(self.i18n.t("backend_endpoint"))
        self.edit_tr_endpoint.setStyleSheet(input_css)
        self.edit_tr_endpoint.editingFinished.connect(self._on_translation_backend_changed)
        ai_grid.addWidget(self.edit_tr_endpoint, 1, 0)

        self.edit_tr_model = QLineEdit(self.settings.get("translation_model", ""))
        self.edit_tr_model.setPlaceholderText(self.i18n.t("backend_model"))
        self.edit_tr_model.setStyleSheet(input_css)
        self.edit_tr_model.editingFinished.connect(self._on_translation_backend_changed)
        ai_grid.addWidget(self.edit_tr_model, 1, 1)

        self.edit_tr_apikey = QLineEdit(self.settings.get("translation_api_key", ""))
        self.edit_tr_apikey.setPlaceholderText(self.i18n.t("backend_apikey"))
        self.edit_tr_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_tr_apikey.setStyleSheet(input_css)
        self.edit_tr_apikey.editingFinished.connect(self._on_translation_backend_changed)
        ai_grid.addWidget(self.edit_tr_apikey, 2, 0)

        self.btn_test_backend = QPushButton(self.i18n.t("backend_test_btn"))
        self.btn_test_backend.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_backend.setMinimumHeight(32)
        self.btn_test_backend.clicked.connect(self._on_test_translation_backend)
        ai_grid.addWidget(self.btn_test_backend, 2, 1)

        ai_lay.addLayout(ai_grid)

        # Giriş Kaynağı (Ekran OCR vs Opsiyonel Canlı Ses Whisper)
        sep_audio = QFrame()
        sep_audio.setFrameShape(QFrame.Shape.HLine)
        sep_audio.setStyleSheet("color: #1C283E;")
        ai_lay.addWidget(sep_audio)

        lbl_src_title = QLabel(self.i18n.t("input_source_title").upper())
        lbl_src_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        ai_lay.addWidget(lbl_src_title)

        src_row = QHBoxLayout()
        src_row.setSpacing(12)
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
            self.combo_whisper_model.addItem(f"Whisper {wm} (INT8 CPU)", wm)
        saved_wm = self.settings.get("whisper_model", "tiny.en")
        for i in range(self.combo_whisper_model.count()):
            if self.combo_whisper_model.itemData(i) == saved_wm:
                self.combo_whisper_model.setCurrentIndex(i)
                break
        self.combo_whisper_model.currentIndexChanged.connect(lambda _: self._save_settings())
        src_row.addWidget(self.combo_whisper_model, stretch=1)
        ai_lay.addLayout(src_row)

        audio_caps = detect_audio_capabilities()
        lbl_audio_status = QLabel(
            self.i18n.t("audio_ready") if audio_caps.is_ready else self.i18n.t("audio_missing")
        )
        lbl_audio_status.setWordWrap(True)
        lbl_audio_status.setStyleSheet(
            f"color: {'#34D399' if audio_caps.is_ready else '#94A3B8'}; font-size: 8pt;"
        )
        ai_lay.addWidget(lbl_audio_status)

        settings_lay.addWidget(ai_card)

        # ── ARAYÜZ DİLİ (TR/EN) & GÜNCELLEME DENETLEYİCİ KARTI ──
        meta_card = QFrame()
        meta_card.setObjectName("studioPanel")
        meta_lay = QVBoxLayout(meta_card)
        meta_lay.setContentsMargins(16, 14, 16, 14)
        meta_lay.setSpacing(10)

        meta_grid = QGridLayout()
        meta_grid.setHorizontalSpacing(14)
        meta_grid.setVerticalSpacing(8)

        lbl_lang = QLabel(self.i18n.t("ui_language"))
        lbl_lang.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 600;")
        meta_grid.addWidget(lbl_lang, 0, 0)

        self.combo_ui_lang = FlatComboBox()
        self.combo_ui_lang.addItem("Türkçe (TR)", "tr")
        self.combo_ui_lang.addItem("English (EN)", "en")
        for i in range(self.combo_ui_lang.count()):
            if self.combo_ui_lang.itemData(i) == self.i18n.lang:
                self.combo_ui_lang.setCurrentIndex(i)
                break
        self.combo_ui_lang.currentIndexChanged.connect(self._on_ui_language_changed)
        meta_grid.addWidget(self.combo_ui_lang, 0, 1)

        self.chk_auto_update = FlatSwitch(self.i18n.t("updates_auto"))
        self.chk_auto_update.setChecked(bool(self.settings.get("check_updates_on_startup", True)))
        self.chk_auto_update.toggled.connect(lambda _: self._save_settings())
        meta_grid.addWidget(self.chk_auto_update, 1, 0)

        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        self.btn_check_update = QPushButton(self.i18n.t("updates_check_btn"))
        self.btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_update.setMinimumHeight(32)
        self.btn_check_update.clicked.connect(lambda: self.check_for_updates_async(silent=False))
        upd_row.addWidget(self.btn_check_update)

        self.btn_open_release = QPushButton(self.i18n.t("updates_download"))
        self.btn_open_release.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_release.setMinimumHeight(32)
        self.btn_open_release.setVisible(False)
        self.btn_open_release.clicked.connect(self._open_latest_release_page)
        upd_row.addWidget(self.btn_open_release)
        meta_grid.addLayout(upd_row, 1, 1)

        self.lbl_update_status = QLabel(f"SubVision AI v{__version__}")
        self.lbl_update_status.setStyleSheet("color: #64748B; font-size: 8.2pt;")
        meta_grid.addWidget(self.lbl_update_status, 2, 0, 1, 2)

        meta_grid.setColumnStretch(0, 1)
        meta_grid.setColumnStretch(1, 1)
        meta_lay.addLayout(meta_grid)
        settings_lay.addWidget(meta_card)

        # ── OYUN / UYGULAMA PROFİLLERİ, ÖZEL SÖZLÜK & KISAYOLLAR KARTI ──
        prof_card = QFrame()
        prof_card.setObjectName("studioPanel")
        prof_lay = QVBoxLayout(prof_card)
        prof_lay.setContentsMargins(16, 14, 16, 14)
        prof_lay.setSpacing(10)

        lbl_prof_title = QLabel("PROFİLLER, ÖZEL SÖZLÜK & KISAYOLLAR")
        lbl_prof_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.8px;"
        )
        prof_lay.addWidget(lbl_prof_title)

        # Profil satırı
        prof_row = QHBoxLayout()
        prof_row.setSpacing(8)
        self.combo_profile = FlatComboBox()
        self._refresh_profile_combo()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selected)
        prof_row.addWidget(self.combo_profile, stretch=2)

        btn_save_prof = QPushButton("Profil Kaydet")
        btn_save_prof.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save_prof.setMinimumHeight(32)
        btn_save_prof.clicked.connect(self._on_save_profile_clicked)
        prof_row.addWidget(btn_save_prof)

        btn_del_prof = QPushButton("Sil")
        btn_del_prof.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del_prof.setMinimumHeight(32)
        btn_del_prof.clicked.connect(self._on_delete_profile_clicked)
        prof_row.addWidget(btn_del_prof)
        prof_lay.addLayout(prof_row)

        # Özel JSON Sözlük satırı
        glos_row = QHBoxLayout()
        glos_row.setSpacing(10)
        lbl_glos = QLabel("Özel Oyun/Dizi Sözlüğü (JSON)")
        lbl_glos.setStyleSheet("color: #CBD5E1; font-size: 8.6pt; font-weight: 600;")
        glos_row.addWidget(lbl_glos)

        self.combo_glossary_pack = FlatComboBox()
        self._refresh_glossary_combo()
        self.combo_glossary_pack.currentIndexChanged.connect(self._on_glossary_pack_changed)
        glos_row.addWidget(self.combo_glossary_pack, stretch=1)
        prof_lay.addLayout(glos_row)

        # Özelleştirilebilir Kısayollar (F1-F12)
        hk_grid = QGridLayout()
        hk_grid.setHorizontalSpacing(10)
        hk_grid.setVerticalSpacing(4)
        hk_labels = [("Alan Seç", "roi"), ("Başlat / Durdur", "toggle"), ("Örnek Sahne", "sample")]
        self._hk_combos: Dict[str, FlatComboBox] = {}
        for col_idx, (lbl_txt, hk_key) in enumerate(hk_labels):
            lbl_hk = QLabel(lbl_txt)
            lbl_hk.setStyleSheet("color: #94A3B8; font-size: 8pt; font-weight: 600;")
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
        prof_lay.addLayout(hk_grid)

        # Otomatik profil & Sistem tepsisi anahtarları
        extra_toggles = QHBoxLayout()
        extra_toggles.setSpacing(16)
        self.chk_auto_profile = FlatSwitch("Aktif oyuna/uygulamaya göre profil değiştir")
        self.chk_auto_profile.setChecked(bool(self.settings.get("auto_switch_profiles", False)))
        self.chk_auto_profile.toggled.connect(self._on_auto_profile_toggled)
        extra_toggles.addWidget(self.chk_auto_profile)

        self.chk_minimize_tray = FlatSwitch("Kapatınca sistem tepsisine küçült")
        self.chk_minimize_tray.setChecked(bool(self.settings.get("minimize_to_tray", False)))
        self.chk_minimize_tray.toggled.connect(lambda _: self._save_settings())
        extra_toggles.addWidget(self.chk_minimize_tray)
        extra_toggles.addStretch(1)
        prof_lay.addLayout(extra_toggles)

        settings_lay.addWidget(prof_card)

        self._sync_backend_inputs_visibility()

        settings_lay.addStretch(1)
        page_settings_scroll.setWidget(page_settings)
        self.stack.addWidget(page_settings_scroll)

        # ═════════════════════════════════════════════════════════════════════
        # 3. SADE KISAYOL ALT BİLGİ ÇUBUĞU
        # ═════════════════════════════════════════════════════════════════════
        footer = QLabel(
            "Kısayollar (Oyun ve video içindeyken çalışır):   F7 Altyazı Alanını Seç   ·   "
            "F8 Çeviriyi Başlat / Durdur   ·   F9 Örnek Altyazı Testi"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #64748B; font-size: 8.2pt; font-weight: 600; padding-top: 2px;")
        main_layout.addWidget(footer)

        self._switch_tab(0)

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        active_css = (
            "QPushButton { background-color: #162642; border: 1px solid #38BDF8; border-radius: 7px; "
            "color: #FFFFFF; padding: 5px 13px; font-size: 8.4pt; font-weight: 700; }"
        )
        idle_css = (
            "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 7px; "
            "color: #94A3B8; padding: 5px 13px; font-size: 8.4pt; font-weight: 600; }"
            "QPushButton:hover { color: #F8FAFC; background-color: #0F172A; }"
        )
        tabs = (self.btn_tab_main, self.btn_tab_history, self.btn_tab_settings)
        for i, btn in enumerate(tabs):
            btn.setStyleSheet(active_css if i == index else idle_css)

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
        if active:
            self.btn_toggle.setIcon(make_flat_icon("stop", "#FFFFFF", 13))
            self.btn_toggle.setText("  Canlı Çeviriyi Durdur   (F8)")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #DC2626;
                    border: 1px solid #F87171;
                    border-radius: 10px;
                    color: #FFFFFF;
                    font-size: 10pt;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #B91C1C;
                    border-color: #FCA5A5;
                }
                """
            )
        else:
            self.btn_toggle.setIcon(make_flat_icon("play", "#FFFFFF", 13))
            self.btn_toggle.setText("  Anlık Çeviriyi Başlat   (F8)")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #2563EB;
                    border: 1px solid #38BDF8;
                    border-radius: 10px;
                    color: #FFFFFF;
                    font-size: 10pt;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #1D4ED8;
                    border-color: #7DD3FC;
                }
                QPushButton:disabled {
                    background-color: #0F172A;
                    border-color: #1E293B;
                    color: #475569;
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
            "QPushButton { background-color: #162642; border: 1px solid #38BDF8; border-radius: 6px; "
            "color: #FFFFFF; padding: 6px 10px; font-size: 8.4pt; font-weight: 700; }"
        )
        idle_pos_css = (
            "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 6px; "
            "color: #94A3B8; padding: 6px 10px; font-size: 8.4pt; font-weight: 500; } "
            "QPushButton:hover { color: #F8FAFC; background-color: #0F172A; }"
        )
        self.btn_mode_cover.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "cover" else idle_pos_css
        )
        self.btn_mode_above.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "above" else idle_pos_css
        )

        for hex_code, btn in self._color_buttons.items():
            if hex_code == self._selected_color:
                btn.setStyleSheet(
                    "QPushButton { background-color: #162642; border: 1px solid #38BDF8; border-radius: 8px; "
                    "color: #FFFFFF; padding: 6px 8px; font-size: 8.5pt; font-weight: 700; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #090F1C; border: 1px solid #1C2940; border-radius: 8px; "
                    "color: #94A3B8; padding: 6px 8px; font-size: 8.5pt; font-weight: 500; } "
                    "QPushButton:hover { border-color: #38BDF8; color: #FFFFFF; background-color: #111C33; }"
                )

    def _apply_saved_appearance(self) -> None:
        self._selected_color = self.settings.get("text_color", "#FACC15")
        if self._selected_color not in self._color_buttons:
            self._selected_color = "#FACC15"

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
            self.lbl_model_status.setText(f"●  Canlı Çeviri Aktif ({self.tuning.scan_fps} FPS)")

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
        self.loader_thread = ModelLoaderThread(self.translator, self.ocr_engine)
        self.loader_thread.progress.connect(self._on_model_progress)
        self.loader_thread.finished_ok.connect(self._on_model_ready)
        self.loader_thread.failed.connect(self._on_model_failed)
        self.loader_thread.start()

    def _on_model_progress(self, msg: str, pct: int) -> None:
        self.lbl_model_status.setText(f"●  {msg}")
        self.progress_bar.setValue(pct)

    def _on_model_ready(self) -> None:
        ctype = self.translator.active_compute_type.upper()
        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.card_nmt.lbl_title.setText(f"ÇEVİRİ ({ctype})")
        self.lbl_model_status.setText("●  Çeviriye Hazır")
        self.lbl_model_status.setStyleSheet(
            """
            color: #34D399;
            background-color: #06281E;
            border: 1px solid #059669;
            border-radius: 9px;
            padding: 2px 10px;
            font-size: 8.2pt;
            font-weight: 700;
            """
        )
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.btn_toggle.setEnabled(True)
        self.btn_test.setEnabled(True)
        self.btn_benchmark.setEnabled(True)

    def _on_model_failed(self, err: str) -> None:
        self.lbl_model_status.setText(f"●  Hata: {err}")
        self.lbl_model_status.setStyleSheet(
            """
            color: #F87171;
            background-color: #2A0F14;
            border: 1px solid #DC2626;
            border-radius: 9px;
            padding: 2px 10px;
            font-size: 8.2pt;
            font-weight: 700;
            """
        )

    def open_roi_selector(self) -> None:
        was_running = self.worker is not None and self.worker.running
        self._resume_after_roi = was_running
        if was_running:
            self.toggle_translation()

        # Kullanıcı alanı seçerken ana pencere arkadaki videoyu/oyunu kapatmasın
        self._restore_window_after_roi = self.isVisible() and not self.isMinimized()
        if self._restore_window_after_roi:
            self.hide()

        self.roi_selector.show_selector()

    def _on_roi_cancelled(self) -> None:
        if self._restore_window_after_roi:
            self._restore_window_after_roi = False
            self.showNormal()
            self.raise_()
            self.activateWindow()
        if self._resume_after_roi and self.translator.is_ready:
            self._resume_after_roi = False
            self.toggle_translation()

    def _on_roi_selected(self, new_roi: Dict[str, int]) -> None:
        self.roi = new_roi
        self.overlay.align_to_roi(self.roi)
        self.lbl_roi_badge.setText(f"✓ Seçili: {self.roi['width']}×{self.roi['height']} px")
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

        self.lbl_font_cap.setText("Maks. Boyut" if auto_fit else "Yazı Boyutu")
        self.lbl_font_val.setText(f"{f_size} pt")
        self.lbl_alpha_val.setText(f"%{alpha_pct}")
        self._update_designer_button_styles()

        # Birleşik Canlı Önizleme Kutusunu Güncelle
        preview_font_pt = max(11, min(17, int(f_size * 0.58)))
        en_font_pt = max(9, int(preview_font_pt * 0.72))
        self.preview_box.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(7, 11, 20, {alpha});
                border: 1px solid #1E2D45;
                border-radius: 12px;
            }}
            """
        )
        self.lbl_en_preview.setStyleSheet(
            f"color: #94A3B8; font-size: {en_font_pt}pt; font-weight: 500; border: none; background: transparent;"
        )
        self.lbl_tr_preview.setStyleSheet(
            f"color: {self._selected_color}; font-size: {preview_font_pt}pt; font-weight: 700; border: none; background: transparent;"
        )

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
            self.btn_tab_main.setText(self.i18n.t("tab_home"))
            self.btn_tab_history.setText(self.i18n.t("tab_history"))
            self.btn_tab_settings.setText(self.i18n.t("tab_settings"))

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
                self.btn_open_release.setVisible(True)
        elif not silent and hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setText(
                self.i18n.t("updates_up_to_date", version=info.current_version)
            )
            self.lbl_update_status.setStyleSheet("color: #34D399; font-size: 8.2pt;")

    def _open_latest_release_page(self) -> None:
        if self._latest_release_url:
            webbrowser.open(self._latest_release_url)

    def _refresh_profile_combo(self) -> None:
        if not hasattr(self, "combo_profile"):
            return
        cur = self.combo_profile.currentText()
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
        proc, _ = QInputDialog.getText(
            self,
            "Otomatik Uygulama Eşleştirme (Opsiyonel)",
            "İsteğe bağlı .exe adı (örn. vlc.exe, Spider-Man2.exe — boş bırakılabilir):",
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
            self._hotkeys[hk_key] = str(cb.currentData() or self._hotkeys[hk_key])
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
        self.lbl_roi_badge.setText(f"Seçili: {self.roi['width']}×{self.roi['height']} px")
        self.card_stats.set_metric(
            f"{req} Çeviri",
            sub_text=f"ROI {self.roi['width']}×{self.roi['height']} px · Hit %{hit_pct}",
            badge_text=f"%{hit_pct} CACHE" if req > 0 else f"{self.tuning.scan_fps} FPS",
            bar_pct=max(12, hit_pct),
        )

    def toggle_translation(self) -> None:
        if not self.translator.is_ready:
            return

        is_ocr_active = bool(self.worker and self.worker.running)
        is_audio_active = bool(self.audio_worker and self.audio_worker.isRunning())

        if is_ocr_active or is_audio_active:
            if self.worker and self.worker.running:
                self.worker.stop()
                self.worker = None
            if self.audio_worker and self.audio_worker.isRunning():
                self.audio_worker.stop()
                self.audio_worker.wait(1500)
                self.audio_worker = None
            self._set_toggle_button_style(active=False)
            self.lbl_model_status.setText("●  Çeviriye Hazır")
            self.lbl_model_status.setStyleSheet(
                """
                color: #34D399;
                background-color: #06281E;
                border: 1px solid #059669;
                border-radius: 9px;
                padding: 2px 10px;
                font-size: 8.2pt;
                font-weight: 700;
                """
            )
            self.lbl_toggle_desc.setText("Canlı çeviri duraklatıldı. Tekrar başlatmak için F8 tuşuna basın.")
            self.lbl_scene_tag.setText(f"Hazır · {self.tuning.scan_fps} FPS")
            self.overlay.set_subtitle("")
        else:
            input_source = (
                self.combo_input_source.currentData()
                if hasattr(self, "combo_input_source")
                else "ocr"
            )
            self.overlay.align_to_roi(self.roi)
            self.overlay.set_subtitle("")

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
                self.audio_worker.error_occurred.connect(
                    lambda err: QMessageBox.warning(self, "Canlı Ses (Whisper)", err)
                )
                self.audio_worker.start()
                self.lbl_model_status.setText(f"●  Canlı Ses Aktif (Whisper {whisper_model})")
            else:
                self.lbl_scene_tag.setText(f"Canlı Yakalama · {self.tuning.scan_fps} FPS")
                self.worker = CaptureTranslateWorker(
                    ocr_engine=self.ocr_engine,
                    translator=self.translator,
                    roi=self.roi,
                    scan_interval_sec=self.tuning.scan_interval_sec,
                    idle_scan_interval_sec=self.tuning.idle_scan_interval_sec,
                )
                self.worker.subtitle_updated.connect(self._on_subtitle_updated)
                self.worker.subtitle_cleared.connect(self._on_subtitle_cleared)
                self.worker.status_tick.connect(
                    lambda msg: self.card_total.set_metric(self.card_total.lbl_val.text(), sub_text=msg)
                )
                self.worker.start()
                self.lbl_model_status.setText(f"●  Canlı Çeviri Aktif ({self.tuning.scan_fps} FPS)")

            self.lbl_model_status.setStyleSheet(
                """
                color: #38BDF8;
                background-color: #0A2239;
                border: 1px solid #0284C7;
                border-radius: 9px;
                padding: 2px 10px;
                font-size: 8.2pt;
                font-weight: 700;
                """
            )
            self.lbl_toggle_desc.setText("Ekrandaki altyazılar canlı olarak takip ediliyor ve Türkçeye çevriliyor.")
            self._set_toggle_button_style(active=True)

    def _on_subtitle_updated(
        self,
        en_text: str,
        tr_text: str,
        ocr_ms: float,
        tr_ms: float,
        is_cached: bool,
        orig_line_h: int = 0,
    ) -> None:
        self.overlay.set_subtitle(tr_text, en_text, orig_line_h_px=orig_line_h)
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
        lbl_meta.setStyleSheet("color: #38BDF8; font-size: 7.8pt; font-weight: 600;")
        lay.addWidget(lbl_meta)

        lbl_en = QLabel(en_text)
        lbl_en.setWordWrap(True)
        lbl_en.setStyleSheet("color: #94A3B8; font-size: 8.8pt; font-weight: 500;")
        lay.addWidget(lbl_en)

        lbl_tr = QLabel(tr_text)
        lbl_tr.setWordWrap(True)
        lbl_tr.setStyleSheet("color: #FACC15; font-size: 9.6pt; font-weight: 700;")
        lay.addWidget(lbl_tr)

        return card

    def _on_subtitle_cleared(self) -> None:
        self.overlay.set_subtitle("")

    def run_sample_test(self) -> None:
        if not self.translator.is_ready:
            return
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
        self.bench_worker = BenchmarkWorker(self.ocr_engine, self.translator, self.hw_profile)
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
                background-color: #060A13;
                color: #F8FAFC;
            }
            QFrame#mgrCard {
                background-color: #0C1322;
                border: 1px solid #1E2D45;
                border-radius: 12px;
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
            "QPushButton { background-color: #131D31; border: 1px solid #D97706; color: #FBBF24; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #1E293B; }"
        )

        btn_uninst = QPushButton("Tam Kaldırma Yardımcısını Aç")
        btn_uninst.setStyleSheet(
            "QPushButton { background-color: #DC2626; border: 1px solid #EF4444; color: #FFFFFF; padding: 8px 14px; }"
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
                if self.worker and self.worker.running:
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

        roi_key = self._hotkeys.get("roi", "F7")
        toggle_key = self._hotkeys.get("toggle", "F8")
        sample_key = self._hotkeys.get("sample", "F9")

        self._shortcuts = [
            QShortcut(QKeySequence(roi_key), self, activated=self.open_roi_selector),
            QShortcut(QKeySequence(toggle_key), self, activated=self.toggle_translation),
            QShortcut(QKeySequence(sample_key), self, activated=self.run_sample_test),
        ]

        if sys.platform == "win32":
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

    def _poll_global_hotkeys(self) -> None:
        if sys.platform != "win32":
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
        if self.update_thread and self.update_thread.isRunning():
            self.update_thread.wait(1000)
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.overlay.close()
        self.roi_selector.close()
        super().closeEvent(event)


def _install_crash_logger() -> None:
    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}]\n{tb_text}\n")
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None,
                    "SubVision AI — Beklenmeyen Hata",
                    f"Uygulama çalışırken beklenmeyen bir hata oluştu:\n\n{exc_value}\n\n"
                    f"Detaylı hata kaydı şuraya yazıldı:\n{CRASH_LOG_PATH}",
                )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

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
