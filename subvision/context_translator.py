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
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from subvision.glossary import extract_speaker_and_body
from subvision.translator import LocalEnTrTranslator

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

_SYSTEM_PROMPT = (
    "You are an expert English-to-Turkish subtitle translator for games, movies, and TV shows. "
    "Translate ONLY the current English subtitle line into natural, idiomatic Turkish. "
    "Use the previous dialogue lines solely for pronoun, gender, tone (sen/siz), and context consistency. "
    "Keep translations concise for on-screen readability. "
    "Output ONLY the Turkish translation with no explanations, quotes, or prefixes."
)


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
        self.last_provider_used: str = BACKEND_LOCAL_CT2
        self.last_error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return self.local.is_ready

    @property
    def active_compute_type(self) -> str:
        return self.local.active_compute_type

    @property
    def cpu_threads(self) -> int:
        return self.local.cpu_threads

    @property
    def model_dir(self) -> str:
        return self.local.model_dir

    @property
    def cache_size(self) -> int:
        return self.local.cache_size

    @property
    def total_requests(self) -> int:
        return self.local.total_requests

    @property
    def cache_hits(self) -> int:
        return self.local.cache_hits

    def update_config(self, config: ContextBackendConfig) -> None:
        self.config = config.normalized()
        with self._history_lock:
            old = list(self._history)
            self._history = deque(
                old[-max(1, self.config.context_window) :],
                maxlen=max(1, self.config.context_window),
            )

    def clear_context(self) -> None:
        with self._history_lock:
            self._history.clear()

    def clear_cache(self) -> None:
        self.local.clear_cache()
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

    def load(self, progress_callback=None) -> None:
        self.local.load(progress_callback=progress_callback)

    def reconfigure_threads(self, cpu_threads: int) -> None:
        self.local.reconfigure_threads(cpu_threads)

    def try_fast_lookup(self, english_text: str) -> Optional[Tuple[str, float, bool]]:
        """
        Zero-wait cache/glossary lookup.
        Checks custom JSON glossary packs first, then built-in cache/glossary.
        """
        if self.custom_glossary is not None:
            speaker, body = extract_speaker_and_body(english_text)
            custom_hit = self.custom_glossary.lookup_exact(body or english_text)
            if custom_hit:
                final_tr = f"{speaker}: {custom_hit}" if speaker else custom_hit
                self.last_provider_used = "custom_glossary"
                self._record_turn(english_text, final_tr)
                return final_tr, 0.01, True

        res = self.local.try_fast_lookup(english_text)
        if res is not None:
            tr_text, elapsed_ms, from_cache = res
            self.last_provider_used = BACKEND_LOCAL_CT2
            self._record_turn(english_text, tr_text)
            return tr_text, elapsed_ms, from_cache
        return None

    def _build_user_prompt(self, body_text: str, speaker: Optional[str]) -> str:
        ctx = self.get_context_snapshot()
        lines: List[str] = []
        if ctx:
            lines.append("Recent dialogue context:")
            for prev_en, prev_tr in ctx:
                lines.append(f"- EN: {prev_en} => TR: {prev_tr}")
            lines.append("")
        if speaker:
            lines.append(f"Current speaker: {speaker}")
        lines.append(f"Translate to Turkish:\n{body_text}")
        return "\n".join(lines)

    def _http_post_json(
        self,
        url: str,
        payload: dict,
        headers: Optional[Dict[str, str]] = None,
    ) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    def _call_ollama(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "stream": False,
            "options": {"temperature": 0.15, "num_predict": 120},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
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
                {"role": "system", "content": _SYSTEM_PROMPT},
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
        base_url = self.config.endpoint.format(model=self.config.model)
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}key={self.config.api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.15, "maxOutputTokens": 128},
        }
        data = self._http_post_json(url, payload)
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
        payload: Dict[str, object] = {
            "text": [body_text],
            "source_lang": "EN",
            "target_lang": "TR",
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
        speaker, body = extract_speaker_and_body(english_text)
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

        protected_input = english_text
        placeholders: Dict[str, str] = {}
        if self.custom_glossary is not None:
            protected_input, placeholders = self.custom_glossary.protect_terms(english_text)

        if self.config.backend == BACKEND_LOCAL_CT2:
            tr_text, elapsed_ms, from_cache = self.local.translate_with_metrics(protected_input)
            if placeholders:
                tr_text = self.custom_glossary.restore_terms(tr_text, placeholders)
            self.last_provider_used = BACKEND_LOCAL_CT2
            self.last_error = None
            self._record_turn(english_text, tr_text)
            return tr_text, elapsed_ms, from_cache

        try:
            tr_text, elapsed_ms = self._translate_via_context_backend(protected_input)
            if placeholders:
                tr_text = self.custom_glossary.restore_terms(tr_text, placeholders)
            self.last_provider_used = self.config.backend
            self.last_error = None
            self._record_turn(english_text, tr_text)
            return tr_text, elapsed_ms, False
        except Exception as exc:
            # Safe automatic fallback to 100% offline CTranslate2 INT8
            self.last_error = str(exc)
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
            return False, str(exc)
