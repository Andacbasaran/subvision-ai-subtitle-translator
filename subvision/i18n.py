"""
SubVision AI — Lightweight Internationalization (TR / EN) module.
Provides instant dictionary-based translation for UI labels, tooltips, and status messages.
"""

from typing import Dict

SUPPORTED_LANGUAGES = ("tr", "en")
DEFAULT_LANGUAGE = "tr"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "tr": {
        "app_subtitle": "Gerçek Zamanlı Ekran Üstü & Ses Tabanlı Türkçe Altyazı Stüdyosu",
        "tab_home": "Ana Ekran",
        "tab_studio": "Stüdyo",
        "tab_appearance": "Görünüm",
        "tab_history": "Geçmiş",
        "tab_settings": "Ayarlar",
        "step1_title": "1. Adım — Altyazı Alanını Seç",
        "step1_btn": "Altyazı Alanını Seç (F7)",
        "step2_title": "2. Adım — Çeviriyi Başlat",
        "step2_start": "Anlık Çeviriyi Başlat (F8)",
        "step2_stop": "Çeviriyi Durdur (F8)",
        "sample_btn": "Örnek Sahne Dene (F9)",
        "copy_btn": "Kopyala",
        "clear_btn": "Temizle",
        "ui_language": "Arayüz Dili",
        "ui_language_desc": "Uygulama dilini değiştirir (Türkçe / English). Bazı metinler yeniden başlatmada tam güncellenir.",
        "translation_backend_title": "Çeviri Motoru & Bağlam Katmanı",
        "translation_backend_desc": "Varsayılan: %100 çevrimdışı CTranslate2 INT8. İsteğe bağlı olarak son diyalogları bağlam alan yerel Ollama veya API destekli yüksek kalite katmanı seçilebilir; hata/zaman aşımında otomatik yerele düşer.",
        "backend_local": "Yerel CTranslate2 INT8 (%100 Çevrimdışı — Varsayılan)",
        "backend_ollama": "Yerel Ollama LLM (Bağlam Farkındalıklı)",
        "backend_gemini": "Google Gemini API (Bağlam Farkındalıklı)",
        "backend_deepl": "DeepL API (Bağlam Destekli)",
        "backend_openai": "OpenAI-Uyumlu API (LM Studio / Groq / OpenAI)",
        "backend_endpoint": "API Adresi / Endpoint",
        "backend_model": "Model Adı",
        "backend_apikey": "API Anahtarı (yalnızca harici API için)",
        "backend_test_btn": "Bağlantıyı Test Et",
        "backend_test_ok": "Bağlantı başarılı",
        "backend_test_fail": "Bağlantı başarısız (yerel CT2 yedek aktif)",
        "input_source_title": "Giriş Kaynağı (OCR / Canlı Ses)",
        "input_source_desc": "Ekran OCR altyazısı veya altyazısız yayın/videolar için opsiyonel Whisper (faster-whisper) ses tanıma modu.",
        "source_ocr": "Ekran Altyazısı (OCR — Varsayılan)",
        "source_audio": "Canlı Sistem Sesi / Mikrofon (Whisper — Opsiyonel)",
        "audio_model_size": "Whisper Modeli",
        "audio_ready": "Ses motoru hazır (faster-whisper + ses yakalama bulundu)",
        "audio_missing": "Opsiyonel ses paketleri kurulu değil. Kurmak için: pip install faster-whisper sounddevice",
        "updates_title": "Güncelleme Denetleyici",
        "updates_auto": "Açılışta yeni sürümleri otomatik denetle (GitHub Releases)",
        "updates_check_btn": "Şimdi Denetle",
        "updates_checking": "Güncellemeler denetleniyor...",
        "updates_up_to_date": "Güncelsiniz (v{version})",
        "updates_available": "Yeni sürüm mevcut: v{latest} (mevcut: v{current})",
        "updates_download": "İndir",
        "updates_error": "Güncelleme kontrolü yapılamadı (çevrimdışı olabilir).",
        "target_app_label": "HEDEF UYGULAMA",
        "target_app_all": "Tüm Ekran (Pencere Kilidi Yok)",
        "target_app_refresh": "Yenile",
        "target_app_tooltip": "Belirli bir oyun veya uygulama seçildiğinde, Alt+Tab ile başka bir pencereye geçerseniz OCR otomatik duraklatılır ve altyazı gizlenir.",
        "target_app_waiting": "Beklemede ({target} odak dışı — Alt+Tab koruması aktif)",
        "target_app_waiting_pill": "●  Beklemede ({target})",
        "target_app_active": "{target} kilitli — yalnızca bu uygulama öndeyken yakalanır.",
        "target_app_saved_missing": "{target} (Kayıtlı — pencere açıldığında aktif olur)",
        "target_app_unsupported_os": "Tüm Ekran (Pencere kilidi yalnızca Windows'ta desteklenir)",
    },
    "en": {
        "app_subtitle": "Real-Time On-Screen & Live-Audio Turkish Subtitle Studio",
        "tab_home": "Home",
        "tab_studio": "Studio",
        "tab_appearance": "Appearance",
        "tab_history": "History",
        "tab_settings": "Settings",
        "step1_title": "Step 1 — Select Subtitle Region",
        "step1_btn": "Select Subtitle Area (F7)",
        "step2_title": "Step 2 — Start Translation",
        "step2_start": "Start Live Translation (F8)",
        "step2_stop": "Stop Translation (F8)",
        "sample_btn": "Try Sample Scene (F9)",
        "copy_btn": "Copy",
        "clear_btn": "Clear",
        "ui_language": "Interface Language",
        "ui_language_desc": "Switch application language (Türkçe / English). Some labels update fully on restart.",
        "translation_backend_title": "Translation Engine & Context Layer",
        "translation_backend_desc": "Default: 100% offline CTranslate2 INT8. Optionally enable context-aware local Ollama or API backends using recent dialogue; automatically falls back to local CT2 on timeout/error.",
        "backend_local": "Local CTranslate2 INT8 (100% Offline — Default)",
        "backend_ollama": "Local Ollama LLM (Context-Aware)",
        "backend_gemini": "Google Gemini API (Context-Aware)",
        "backend_deepl": "DeepL API (Context-Aware)",
        "backend_openai": "OpenAI-Compatible API (LM Studio / Groq / OpenAI)",
        "backend_endpoint": "API Endpoint URL",
        "backend_model": "Model Name",
        "backend_apikey": "API Key (external APIs only)",
        "backend_test_btn": "Test Connection",
        "backend_test_ok": "Connection successful",
        "backend_test_fail": "Connection failed (local CT2 fallback active)",
        "input_source_title": "Input Source (OCR / Live Audio)",
        "input_source_desc": "Screen subtitle OCR or optional Whisper (faster-whisper) live audio transcription for unsubtitled streams/videos.",
        "source_ocr": "Screen Subtitles (OCR — Default)",
        "source_audio": "Live System Audio / Mic (Whisper — Optional)",
        "audio_model_size": "Whisper Model",
        "audio_ready": "Audio engine ready (faster-whisper + audio capture detected)",
        "audio_missing": "Optional audio packages not installed. Run: pip install faster-whisper sounddevice",
        "updates_title": "Update Checker",
        "updates_auto": "Automatically check for updates on startup (GitHub Releases)",
        "updates_check_btn": "Check Now",
        "updates_checking": "Checking for updates...",
        "updates_up_to_date": "You are up to date (v{version})",
        "updates_available": "New version available: v{latest} (current: v{current})",
        "updates_download": "Download",
        "updates_error": "Could not check for updates (offline or rate-limited).",
        "target_app_label": "TARGET APP",
        "target_app_all": "All Windows (No Window Lock)",
        "target_app_refresh": "Refresh",
        "target_app_tooltip": "When locked to a specific game or app, Alt+Tabbing to another window automatically pauses OCR and hides the overlay.",
        "target_app_waiting": "Paused ({target} unfocused — Alt+Tab protection active)",
        "target_app_waiting_pill": "●  Paused ({target})",
        "target_app_active": "Locked to {target} — captures only while this app is in focus.",
        "target_app_saved_missing": "{target} (Saved — activates when window opens)",
        "target_app_unsupported_os": "All Windows (Window lock is supported on Windows only)",
    },
}


class LanguageManager:
    """Holds the active UI language and resolves localized strings with safe fallback."""

    def __init__(self, lang: str = DEFAULT_LANGUAGE):
        self._lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    @property
    def lang(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        if lang in SUPPORTED_LANGUAGES:
            self._lang = lang

    def t(self, key: str, **kwargs) -> str:
        table = TRANSLATIONS.get(self._lang, TRANSLATIONS[DEFAULT_LANGUAGE])
        text = table.get(key) or TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text


def tr(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Stateless helper to translate a UI key."""
    return LanguageManager(lang).t(key, **kwargs)
