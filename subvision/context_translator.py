"""
SubVision AI — Optional Context-Aware High-Quality Translation Layer (EN -> TR).

Architecture:
- Default backend is always `"local_ct2"` (100% offline CTranslate2 INT8, ~68 ms).
- Optionally, users can enable a context-aware backend that passes the last N
  dialogue turns (EN -> TR) as conversational context for natural Turkish subtitles:
    * `"ollama"`            — Local Ollama server (e.g. qwen2.5:3b, gemma2:2b)
    * `"openai_compatible"` — OpenAI, Groq, LM Studio, OpenRouter, vLLM
    * `"gemini"`            — Google Gemini REST API
    * `"deepl"`             — DeepL Free/Pro REST API (native `context` field)
- Zero extra pip dependencies: uses Python stdlib `urllib.request` + `json`.
- Safe Automatic Fallback: any timeout, missing API key, or HTTP error transparently
  falls back to the local CTranslate2 INT8 engine so subtitles never stall.
"""

import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from subvision.glossary import extract_speaker_and_body
from subvision.translator import LocalEnTrTranslator

_STDLIB_URLOPEN = urllib.request.urlopen
_MAX_RESPONSE_BYTES = 1_048_576  # 1 MiB response cap
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_LANG_NAMES: Dict[str, str] = {
    "en": "English",
    "tr": "Turkish",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "pt": "Portuguese",
    "ru": "Russian",
    "it": "Italian",
    "ja": "Japanese",
}

_DEEPL_TARGET_MAP: Dict[str, str] = {
    "en": "EN-US",
    "pt": "PT-BR",
}

BACKEND_LOCAL_CT2 = "local_ct2"
BACKEND_OLLAMA = "ollama"
BACKEND_GEMINI = "gemini"
BACKEND_DEEPL = "deepl"
BACKEND_OPENAI_COMPAT = "openai_compatible"

VALID_BACKENDS = (
    BACKEND_LOCAL_CT2,
    BACKEND_OLLAMA,
    BACKEND_GEMINI,
    BACKEND_DEEPL,
    BACKEND_OPENAI_COMPAT,
)

DEFAULT_ENDPOINTS: Dict[str, str] = {
    BACKEND_LOCAL_CT2: "",
    BACKEND_OLLAMA: "http://localhost:11434/api/chat",
    BACKEND_GEMINI: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    BACKEND_DEEPL: "https://api-free.deepl.com/v2/translate",
    BACKEND_OPENAI_COMPAT: "https://api.openai.com/v1/chat/completions",
}

DEFAULT_MODELS: Dict[str, str] = {
    BACKEND_LOCAL_CT2: "opus-mt-tc-big-en-tr-int8",
    BACKEND_OLLAMA: "qwen2.5:3b",
    BACKEND_GEMINI: "gemini-2.0-flash-lite",
    BACKEND_DEEPL: "deepl-en-tr",
    BACKEND_OPENAI_COMPAT: "gpt-4o-mini",
}


def _build_system_prompt(source_lang: str = "en", target_lang: str = "tr") -> str:
    src_name = _LANG_NAMES.get((source_lang or "en").lower(), (source_lang or "en").upper())
    tgt_name = _LANG_NAMES.get((target_lang or "tr").lower(), (target_lang or "tr").upper())
    tone_note = (
        "Use the previous dialogue lines solely for pronoun, gender, tone (sen/siz), and context consistency. "
        if (target_lang or "").lower() == "tr"
        else "Use the previous dialogue lines solely for pronoun, gender, tone, and context consistency. "
    )
    return (
        f"You are an expert {src_name}-to-{tgt_name} subtitle translator for games, movies, and TV shows. "
        f"Translate ONLY the current {src_name} subtitle line into natural, idiomatic {tgt_name}. "
        f"{tone_note}"
        "Keep translations concise for on-screen readability. "
        f"Output ONLY the {tgt_name} translation with no explanations, quotes, or prefixes."
    )


_SYSTEM_PROMPT = _build_system_prompt("en", "tr")


def _scrub_secret(message: str, secret: str) -> str:
    text = str(message or "")
    key = (secret or "").strip()
    if key and key in text:
        text = text.replace(key, "[REDACTED]")
    return text


def _validate_endpoint_url(url: str) -> str:
    cleaned = (url or "").strip()
    parsed = urllib.parse.urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"Invalid endpoint URL: {cleaned!r}")
    if scheme == "https":
        return cleaned
    if scheme == "http" and host in _LOOPBACK_HOSTS:
        return cleaned
    raise ValueError(
        f"Insecure endpoint URL rejected (HTTPS required for non-localhost hosts): {cleaned!r}"
    )


def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


@dataclass
class ContextBackendConfig:
    backend: str = BACKEND_LOCAL_CT2
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    context_window: int = 3
    timeout_sec: float = 3.0

    def normalized(self) -> "ContextBackendConfig":
        b = self.backend if self.backend in VALID_BACKENDS else BACKEND_LOCAL_CT2
        ep = (self.endpoint or "").strip() or DEFAULT_ENDPOINTS.get(b, "")
        mdl = (self.model or "").strip() or DEFAULT_MODELS.get(b, "")
        ctx = max(0, min(8, int(self.context_window)))
        to = max(0.5, min(15.0, float(self.timeout_sec)))
        return ContextBackendConfig(
            backend=b,
            endpoint=ep,
            model=mdl,
            api_key=(self.api_key or "").strip(),
            context_window=ctx,
            timeout_sec=to,
        )


class ContextAwareTranslator:
    """
    Wraps `LocalEnTrTranslator` with an optional context-aware translation layer.
    Preserves the exact interface (`translate_with_metrics`, `try_fast_lookup`,
    `load`, `reconfigure_threads`, `clear_cache`) so existing workers need minimal changes.
    """

    def __init__(
        self,
        local_translator: LocalEnTrTranslator,
        config: Optional[ContextBackendConfig] = None,
        custom_glossary=None,
    ):
        self.local = local_translator
        self.config = (config or ContextBackendConfig()).normalized()
        self.custom_glossary = custom_glossary
        self._history_lock = threading.Lock()
        self._history: Deque[Tuple[str, str]] = deque(maxlen=max(1, self.config.context_window))
        self._ext_cache_lock = threading.Lock()
        self._ext_cache: "OrderedDict[Tuple[str, str, str, str], str]" = OrderedDict()
        self._ext_cache_max = 512
        self.last_provider_used: str = BACKEND_LOCAL_CT2
        self.last_error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return self.local.is_ready

    @is_ready.setter
    def is_ready(self, value: bool) -> None:
        self.local.is_ready = bool(value)

    @property
    def active_compute_type(self) -> str:
        return self.local.active_compute_type

    @property
    def cpu_threads(self) -> int:
        return self.local.cpu_threads

    @cpu_threads.setter
    def cpu_threads(self, value: int) -> None:
        self.local.cpu_threads = max(1, int(value))

    def set_cpu_threads(self, value: int) -> None:
        new_threads = max(1, int(value))
        if self.local.is_ready and self.local.cpu_threads != new_threads:
            self.local.reconfigure_threads(new_threads)
        else:
            self.local.cpu_threads = new_threads

    @property
    def model_dir(self) -> str:
        return self.local.model_dir

    @property
    def lang_pair(self) -> str:
        return str(getattr(self.local, "lang_pair", "en-tr") or "en-tr").lower()

    @property
    def source_lang(self) -> str:
        src = getattr(self.local, "source_lang", None)
        if src:
            return str(src).lower()
        pair = self.lang_pair
        return pair.split("-", 1)[0] if "-" in pair else "en"

    @property
    def target_lang(self) -> str:
        tgt = getattr(self.local, "target_lang", None)
        if tgt:
            return str(tgt).lower()
        pair = self.lang_pair
        return pair.split("-", 1)[1] if "-" in pair else "tr"

    @property
    def cache_size(self) -> int:
        with self._ext_cache_lock:
            ext_len = len(self._ext_cache)
        return self.local.cache_size + ext_len

    @property
    def total_requests(self) -> int:
        return self.local.total_requests

    @total_requests.setter
    def total_requests(self, value: int) -> None:
        self.local.total_requests = int(value)

    @property
    def cache_hits(self) -> int:
        return self.local.cache_hits

    @cache_hits.setter
    def cache_hits(self, value: int) -> None:
        self.local.cache_hits = int(value)

    def unload(self) -> None:
        """Releases underlying local CTranslate2/SentencePiece resources cleanly."""
        if hasattr(self.local, "unload"):
            self.local.unload()
        else:
            self.local.translator = None
            self.local.source_sp = None
            self.local.target_sp = None
            self.local.is_ready = False

    def _active_glossary_key(self) -> str:
        if self.custom_glossary is None:
            return "none"
        return str(getattr(self.custom_glossary, "active_pack_id", "none") or "none")

    def _ext_cache_get(self, key: Tuple[str, str, str, str]) -> Optional[str]:
        with self._ext_cache_lock:
            val = self._ext_cache.get(key)
            if val is not None:
                self._ext_cache.move_to_end(key)
            return val

    def _ext_cache_put(self, key: Tuple[str, str, str, str], value: str) -> None:
        with self._ext_cache_lock:
            self._ext_cache[key] = value
            self._ext_cache.move_to_end(key)
            while len(self._ext_cache) > self._ext_cache_max:
                self._ext_cache.popitem(last=False)

    def update_config(self, config: ContextBackendConfig) -> None:
        self.config = config.normalized()
        with self._history_lock:
            old = list(self._history)
            self._history = deque(
                old[-max(1, self.config.context_window) :],
                maxlen=max(1, self.config.context_window),
            )
        with self._ext_cache_lock:
            self._ext_cache.clear()

    def clear_context(self) -> None:
        with self._history_lock:
            self._history.clear()

    def clear_cache(self) -> None:
        self.local.clear_cache()
        with self._ext_cache_lock:
            self._ext_cache.clear()
        self.clear_context()

    def get_context_snapshot(self) -> List[Tuple[str, str]]:
        if self.config.context_window <= 0:
            return []
        with self._history_lock:
            return list(self._history)

    def _record_turn(self, en_text: str, tr_text: str) -> None:
        if not en_text or not tr_text or self.config.context_window <= 0:
            return
        with self._history_lock:
            if self._history and self._history[-1][0] == en_text:
                return
            self._history.append((en_text, tr_text))

    def load(self, progress_callback=None, cancel_check=None) -> None:
        try:
            self.local.load(progress_callback=progress_callback, cancel_check=cancel_check)
        except TypeError:
            self.local.load(progress_callback=progress_callback)

    def reconfigure_threads(self, cpu_threads: int) -> None:
        self.local.reconfigure_threads(cpu_threads)

    def try_fast_lookup(self, english_text: str) -> Optional[Tuple[str, float, bool]]:
        """
        Zero-wait cache/glossary lookup.
        Checks custom JSON glossary packs and context LRU cache first, then built-in cache/glossary.
        """
        t0 = time.perf_counter()
        if self.custom_glossary is not None:
            speaker, body = extract_speaker_and_body(english_text, source_lang=self.source_lang)
            custom_hit = self.custom_glossary.lookup_exact(body or english_text)
            if custom_hit:
                final_tr = f"{speaker}: {custom_hit}" if speaker else custom_hit
                self.last_provider_used = "custom_glossary"
                self._record_turn(english_text, final_tr)
                return final_tr, 0.01, True

        cache_key = (
            self.config.backend,
            self.lang_pair,
            self._active_glossary_key(),
            english_text.strip().lower(),
        )
        ext_hit = self._ext_cache_get(cache_key)
        if ext_hit is not None:
            self.last_provider_used = self.config.backend
            self._record_turn(english_text, ext_hit)
            return ext_hit, (time.perf_counter() - t0) * 1000.0, True

        if self.config.backend == BACKEND_LOCAL_CT2:
            res = self.local.try_fast_lookup(english_text)
            if res is not None:
                tr_text, elapsed_ms, from_cache = res
                self.last_provider_used = BACKEND_LOCAL_CT2
                self._record_turn(english_text, tr_text)
                return tr_text, elapsed_ms, from_cache
        return None

    def _get_system_prompt(self) -> str:
        return _build_system_prompt(self.source_lang, self.target_lang)

    def _build_user_prompt(self, body_text: str, speaker: Optional[str]) -> str:
        src_code = self.source_lang.upper()
        tgt_code = self.target_lang.upper()
        tgt_name = _LANG_NAMES.get(self.target_lang, tgt_code)
        ctx = self.get_context_snapshot()
        lines: List[str] = []
        if ctx:
            lines.append("Recent dialogue context:")
            for prev_src, prev_tgt in ctx:
                lines.append(f"- {src_code}: {prev_src} => {tgt_code}: {prev_tgt}")
            lines.append("")
        if speaker:
            lines.append(f"Current speaker: {speaker}")
        lines.append(f"Translate to {tgt_name}:\n{body_text}")
        return "\n".join(lines)

    def _http_post_json(
        self,
        url: str,
        payload: dict,
        headers: Optional[Dict[str, str]] = None,
    ) -> dict:
        validated_url = _validate_endpoint_url(url)
        body = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(validated_url, data=body, headers=req_headers, method="POST")
        if urllib.request.urlopen is not _STDLIB_URLOPEN:
            ctx_mgr = urllib.request.urlopen(req, timeout=self.config.timeout_sec)
        elif validated_url.lower().startswith("https://"):
            ctx_mgr = urllib.request.urlopen(
                req, timeout=self.config.timeout_sec, context=_build_ssl_context()
            )
        else:
            ctx_mgr = urllib.request.urlopen(req, timeout=self.config.timeout_sec)
        with ctx_mgr as resp:
            raw_bytes = resp.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw_bytes) > _MAX_RESPONSE_BYTES:
            raise ValueError("Context backend response exceeded 1 MiB safety limit")
        raw = raw_bytes.decode("utf-8", errors="replace")
        return json.loads(raw)

    def _call_ollama(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "stream": False,
            "options": {"temperature": 0.15, "num_predict": 120},
            "messages": [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
        }
        data = self._http_post_json(self.config.endpoint, payload)
        return str((data.get("message") or {}).get("content") or "").strip()

    def _call_openai_compat(self, prompt: str) -> str:
        headers: Dict[str, str] = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload = {
            "model": self.config.model,
            "temperature": 0.15,
            "max_tokens": 128,
            "messages": [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
        }
        data = self._http_post_json(self.config.endpoint, payload, headers=headers)
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "").strip()

    def _call_gemini(self, prompt: str) -> str:
        if not self.config.api_key:
            raise ValueError("Gemini API key is required")
        url = self.config.endpoint.format(model=self.config.model)
        payload = {
            "systemInstruction": {"parts": [{"text": self._get_system_prompt()}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.15, "maxOutputTokens": 128},
        }
        headers = {"x-goog-api-key": self.config.api_key}
        data = self._http_post_json(url, payload, headers=headers)
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(str(p.get("text") or "") for p in parts).strip()

    def _call_deepl(self, body_text: str) -> str:
        if not self.config.api_key:
            raise ValueError("DeepL API key is required")
        ctx = self.get_context_snapshot()
        ctx_text = " ".join(prev_en for prev_en, _ in ctx)
        src_lang = self.source_lang.upper()
        tgt_lang = _DEEPL_TARGET_MAP.get(self.target_lang, self.target_lang.upper())
        payload: Dict[str, object] = {
            "text": [body_text],
            "source_lang": src_lang,
            "target_lang": tgt_lang,
        }
        if ctx_text:
            payload["context"] = ctx_text
        headers = {"Authorization": f"DeepL-Auth-Key {self.config.api_key}"}
        data = self._http_post_json(self.config.endpoint, payload, headers=headers)
        translations = data.get("translations") or []
        if not translations:
            return ""
        return str(translations[0].get("text") or "").strip()

    @staticmethod
    def _clean_llm_output(text: str) -> str:
        cleaned = (text or "").strip()
        if len(cleaned) >= 2 and cleaned[0] in ('"', "'", "“") and cleaned[-1] in ('"', "'", "”"):
            cleaned = cleaned[1:-1].strip()
        # Keep only first non-empty line if an LLM accidentally adds a note
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        return lines[0] if lines else ""

    def _translate_via_context_backend(self, english_text: str) -> Tuple[str, float]:
        t0 = time.perf_counter()
        speaker, body = extract_speaker_and_body(english_text, source_lang=self.source_lang)
        target_body = body or english_text
        prompt = self._build_user_prompt(target_body, speaker)

        backend = self.config.backend
        if backend == BACKEND_OLLAMA:
            raw_tr = self._call_ollama(prompt)
        elif backend == BACKEND_OPENAI_COMPAT:
            raw_tr = self._call_openai_compat(prompt)
        elif backend == BACKEND_GEMINI:
            raw_tr = self._call_gemini(prompt)
        elif backend == BACKEND_DEEPL:
            raw_tr = self._call_deepl(target_body)
        else:
            raise ValueError(f"Unsupported backend: {backend}")

        cleaned = self._clean_llm_output(raw_tr)
        if not cleaned:
            raise RuntimeError("Empty response from context backend")
        final_tr = f"{speaker}: {cleaned}" if speaker else cleaned
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return final_tr, elapsed_ms

    def translate_with_metrics(self, english_text: str) -> Tuple[str, float, bool]:
        if not english_text or not english_text.strip():
            return "", 0.0, False

        # Check custom glossary & fast cache first
        fast = self.try_fast_lookup(english_text)
        if fast is not None:
            return fast

        cache_key = (
            self.config.backend,
            self.lang_pair,
            self._active_glossary_key(),
            english_text.strip().lower(),
        )

        protected_input = english_text
        placeholders: Dict[str, str] = {}
        if self.custom_glossary is not None:
            protected_input, placeholders = self.custom_glossary.protect_terms(english_text)

        if self.config.backend == BACKEND_LOCAL_CT2:
            tr_text, elapsed_ms, from_cache = self.local.translate_with_metrics(protected_input)
            if placeholders:
                tr_text = self.custom_glossary.restore_terms(tr_text, placeholders)
                if tr_text:
                    self._ext_cache_put(cache_key, tr_text)
            self.last_provider_used = BACKEND_LOCAL_CT2
            self.last_error = None
            self._record_turn(english_text, tr_text)
            return tr_text, elapsed_ms, from_cache

        try:
            tr_text, elapsed_ms = self._translate_via_context_backend(protected_input)
            if placeholders:
                tr_text = self.custom_glossary.restore_terms(tr_text, placeholders)
            if tr_text:
                self._ext_cache_put(cache_key, tr_text)
            self.last_provider_used = self.config.backend
            self.last_error = None
            self._record_turn(english_text, tr_text)
            return tr_text, elapsed_ms, False
        except Exception as exc:
            # Safe automatic fallback to 100% offline CTranslate2 INT8
            self.last_error = _scrub_secret(str(exc), self.config.api_key)
            tr_text, elapsed_ms, from_cache = self.local.translate_with_metrics(protected_input)
            if placeholders:
                tr_text = self.custom_glossary.restore_terms(tr_text, placeholders)
            self.last_provider_used = f"{BACKEND_LOCAL_CT2}_fallback"
            self._record_turn(english_text, tr_text)
            return tr_text, elapsed_ms, from_cache

    def test_connection(self) -> Tuple[bool, str]:
        """Tests the configured context backend with a short sample sentence."""
        if self.config.backend == BACKEND_LOCAL_CT2:
            return True, "Local CTranslate2 INT8 (Offline)"
        try:
            tr_text, ms = self._translate_via_context_backend("Stay with me, we are almost there.")
            return True, f"{tr_text} ({ms:.0f} ms)"
        except Exception as exc:
            return False, _scrub_secret(str(exc), self.config.api_key)
