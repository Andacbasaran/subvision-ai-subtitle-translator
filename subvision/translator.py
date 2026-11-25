"""
SubVision AI — Çok Dilli CTranslate2 INT8 Lokal Çeviri Motoru (Varsayılan: EN -> TR).
Model: Helsinki-NLP/opus-mt-tc-big-en-tr (CTranslate2 INT8 Quantized - ~227 MB)
Sıfır GPU/VRAM kullanımı ile CPU üzerinde (veya Apple Silicon'da opsiyonel MPS ile)
ultra düşük gecikmeyle çeviri yapar.

Kararlılık ve Performans Özellikleri:
1. Eksik veya yarıda kalmış model indirmelerini dosya boyutu doğrulaması ile otomatik tespit eder ve tamamlar.
2. Çok cümleli altyazılarda önbellekte olmayan tüm cümleleri tek bir paralel CTranslate2 batch çağrısında çevirir.
3. Çift kilitli (`_cache_lock` / `_engine_lock`) 4096 cümlelik RAM önbelleği (LRU Cache) sayesinde
   yakalama iş parçacığı CTranslate2 çıkarımı sırasında asla bloklanmaz.
"""

import errno
import gc
import os
import platform
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import ctranslate2
import sentencepiece as spm

from subvision.glossary import (
    extract_speaker_and_body,
    lookup_exact_phrase,
    normalize_slang_for_nmt,
)
from subvision.hardware import (
    compute_runtime_tuning,
    detect_hardware_profile,
    get_ct2_safe_path,
    query_ct2_supported_compute_types,
    select_compute_type_candidates,
)
from subvision.language_packs import (
    DEFAULT_LANG_PAIR,
    LanguagePackManager,
    has_valid_ct2_vocabulary,
)

MODEL_REPO = "VoragoStudios/gct-opus-mt-tc-big-en-tr-ct2"

# Dosya bütünlüğü kontrolü için minimum beklenen boyutlar (Byte)
MODEL_FILES_MIN_SIZE: Dict[str, int] = {
    "config.json": 200,
    "shared_vocabulary.json": 500_000,
    "source.spm": 400_000,
    "target.spm": 400_000,
    "model.bin": 210_000_000,  # ~227 MB
}

VALID_DEVICES = ("cpu", "mps", "auto")


def detect_mps_available() -> bool:
    """
    Apple Silicon (macOS ARM64) üzerinde CTranslate2 MPS hızlandırmasının
    güvenle kullanılabilir olup olmadığını kontrol eder.
    """
    if sys.platform != "darwin":
        return False
    if (platform.machine() or "").strip().lower() not in ("arm64", "aarch64"):
        return False
    try:
        mps_count_fn = getattr(ctranslate2, "get_mps_device_count", None)
        if callable(mps_count_fn) and int(mps_count_fn()) <= 0:
            return False
        supported = ctranslate2.get_supported_compute_types("mps")
        return bool(supported)
    except Exception:
        return False


def _is_model_corruption_error(exc: Exception) -> bool:
    """
    Returns True only when an initialization error points to missing, truncated,
    or corrupted model/tokenizer files on disk — NOT OOM, runtime/device failures,
    or user cancellation.
    """
    if isinstance(exc, MemoryError):
        return False
    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) == errno.ENOMEM:
            return False
        if isinstance(exc, (FileNotFoundError, EOFError)):
            return True
    if isinstance(exc, EOFError):
        return True

    msg = str(exc or "").lower()
    non_corrupt_markers = (
        "out of memory",
        "oom",
        "bad_alloc",
        "cannot allocate",
        "memory",
        "iptal",
        "cancel",
        "hiçbir cpu hesaplama tipiyle",
        "unsupported compute",
        "compute type",
        "cuda",
        "mps",
        "metal",
        "permission denied",
    )
    if any(tok in msg for tok in non_corrupt_markers):
        return False

    corrupt_markers = (
        "corrupt",
        "truncated",
        "not found",
        "no such file",
        "cannot open",
        "unable to open",
        "failed to open",
        "invalid model",
        "invalid format",
        "invalid protobuf",
        "parse",
        "sentencepiece",
        "vocabulary",
        "model.bin",
        "config.json",
        "unexpected eof",
        "bad magic",
        "json",
    )
    return any(tok in msg for tok in corrupt_markers)


class LocalEnTrTranslator:
    """
    CTranslate2 + SentencePiece tabanlı, tüm işlemci mimarilerine (AVX2/AVX-512/SSE/ARM64)
    ve isteğe bağlı Apple Silicon MPS hızlandırmasına otomatik uyum sağlayan ultra hızlı
    ve kararlı çeviri motoru.
    """

    def __init__(
        self,
        model_dir: Optional[str] = None,
        cpu_threads: Optional[int] = None,
        compute_type_candidates: Optional[Sequence[str]] = None,
        lang_pair: str = DEFAULT_LANG_PAIR,
        device: str = "cpu",
    ):
        self.lang_pair: str = (lang_pair or DEFAULT_LANG_PAIR).strip().lower()
        requested = (device or "cpu").strip().lower()
        self.requested_device: str = requested if requested in VALID_DEVICES else "cpu"
        self.active_device: str = "cpu"

        pack_manager = LanguagePackManager()
        self.language_pack = pack_manager.get_pack(self.lang_pair)
        if self.language_pack is not None:
            self.source_lang: str = self.language_pack.source_lang
            self.target_lang: str = self.language_pack.target_lang
        elif "-" in self.lang_pair:
            src, tgt = self.lang_pair.split("-", 1)
            self.source_lang = src or "en"
            self.target_lang = tgt or "tr"
        else:
            self.source_lang = "en"
            self.target_lang = "tr"

        self.model_dir = model_dir or pack_manager.get_pack_dir(self.lang_pair)
        self.model_repo: str = (
            self.language_pack.hf_repo if self.language_pack is not None else MODEL_REPO
        )
        self.model_files_min_size: Dict[str, int] = (
            dict(self.language_pack.min_files)
            if (self.language_pack is not None and self.language_pack.min_files)
            else dict(MODEL_FILES_MIN_SIZE)
        )

        if cpu_threads is None:
            hw = detect_hardware_profile(query_ct2=False)
            tuning = compute_runtime_tuning(hw)
            self.cpu_threads = tuning.nmt_threads
        else:
            self.cpu_threads = max(1, int(cpu_threads))

        self.compute_type_candidates: Tuple[str, ...] = (
            tuple(compute_type_candidates)
            if compute_type_candidates
            else select_compute_type_candidates(query_ct2_supported_compute_types())
        )
        self.active_compute_type: str = (
            self.compute_type_candidates[0] if self.compute_type_candidates else "default"
        )

        self.translator: Optional[ctranslate2.Translator] = None
        self.source_sp: Optional[spm.SentencePieceProcessor] = None
        self.target_sp: Optional[spm.SentencePieceProcessor] = None
        self.is_ready = False

        # Strict lock ordering: never acquire `_engine_lock` while holding `_cache_lock`.
        self._cache_lock = threading.Lock()
        self._engine_lock = threading.Lock()
        # Backwards-compatible alias for cache-level locking (e.g. BenchmarkWorker)
        self._lock = self._cache_lock

        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_max_size = 4096
        self.total_requests = 0
        self.cache_hits = 0

    @property
    def cache_size(self) -> int:
        with self._cache_lock:
            return len(self._cache)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()
            self.total_requests = 0
            self.cache_hits = 0

    def unload(self) -> None:
        """
        Safely unloads CTranslate2 and SentencePiece engines, releasing native
        file handles (such as `model.bin` on Windows) and resetting `is_ready`.
        """
        with self._engine_lock:
            self.translator = None
            self.source_sp = None
            self.target_sp = None
            self.is_ready = False
            gc.collect()

    def is_model_downloaded(self) -> bool:
        for fname, min_bytes in self.model_files_min_size.items():
            if fname == "shared_vocabulary.json":
                if not has_valid_ct2_vocabulary(self.model_dir, shared_min_bytes=min_bytes):
                    return False
                continue
            fpath = os.path.join(self.model_dir, fname)
            if not os.path.exists(fpath) or os.path.getsize(fpath) < min_bytes:
                return False
        return True

    def _download_single_file(
        self,
        fname: str,
        min_bytes: int,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        dest_path = os.path.join(self.model_dir, fname)
        if os.path.exists(dest_path) and os.path.getsize(dest_path) >= min_bytes:
            return

        url = f"https://huggingface.co/{self.model_repo}/resolve/main/{fname}"
        tmp_path = dest_path + ".part"

        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            if cancel_check and cancel_check():
                raise RuntimeError("Model indirmesi iptal edildi.")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

                if progress_callback:
                    retry_note = f" (Deneme {attempt}/3)" if attempt > 1 else ""
                    progress_callback(f"İndiriliyor: {fname}{retry_note}...", 0)

                req = urllib.request.Request(
                    url, headers={"User-Agent": "SubVision-AI-Subtitle-Engine/2.0"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp, open(
                    tmp_path, "wb"
                ) as out_file:
                    total_size = int(resp.headers.get("Content-Length", 0) or 0)
                    downloaded = 0
                    last_pct = -1
                    chunk_size = 256 * 1024

                    while True:
                        if cancel_check and cancel_check():
                            raise RuntimeError("Model indirmesi iptal edildi.")
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            pct = min(100, int((downloaded / total_size) * 100))
                            if pct != last_pct:
                                last_pct = pct
                                mb_done = downloaded / (1024 * 1024)
                                mb_total = total_size / (1024 * 1024)
                                progress_callback(
                                    f"İndiriliyor: {fname} ({mb_done:.1f} / {mb_total:.1f} MB)",
                                    pct,
                                )

                if os.path.getsize(tmp_path) < min_bytes:
                    raise IOError(f"{fname} eksik indirildi.")

                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.replace(tmp_path, dest_path)
                last_err = None
                break
            except Exception as exc:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                if cancel_check and cancel_check():
                    raise RuntimeError("Model indirmesi iptal edildi.") from exc
                last_err = exc
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                    break
                # Cooperative sleep so cancel takes effect quickly
                sleep_total = 1.5 * attempt
                slept = 0.0
                while slept < sleep_total:
                    if cancel_check and cancel_check():
                        raise RuntimeError("Model indirmesi iptal edildi.") from exc
                    step = min(0.15, sleep_total - slept)
                    time.sleep(step)
                    slept += step

        if last_err is not None:
            raise last_err

    def download_model(
        self,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Model dosyaları lokalde yoksa veya yarım kalmışsa HuggingFace üzerinden
        otomatik yeniden deneme (retry) desteğiyle indirir.
        """
        os.makedirs(self.model_dir, exist_ok=True)
        for fname, min_bytes in self.model_files_min_size.items():
            if cancel_check and cancel_check():
                raise RuntimeError("Model indirmesi iptal edildi.")
            if fname == "shared_vocabulary.json":
                if has_valid_ct2_vocabulary(self.model_dir, shared_min_bytes=min_bytes):
                    continue
                try:
                    self._download_single_file(
                        fname,
                        min_bytes,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                    )
                    continue
                except urllib.error.HTTPError as http_exc:
                    if http_exc.code != 404:
                        raise RuntimeError(f"Model indirilemedi ({fname}): {http_exc}") from http_exc
                    # Split-vocabulary models provide source_vocabulary.json + target_vocabulary.json
                    split_min = max(1, min(50_000, min_bytes // 2))
                    for split_name in ("source_vocabulary.json", "target_vocabulary.json"):
                        try:
                            self._download_single_file(
                                split_name,
                                split_min,
                                progress_callback=progress_callback,
                                cancel_check=cancel_check,
                            )
                        except Exception as split_exc:
                            raise RuntimeError(
                                f"Model indirilemedi ({split_name}): {split_exc}"
                            ) from split_exc
                    continue
                except Exception as exc:
                    raise RuntimeError(f"Model indirilemedi ({fname}): {exc}") from exc

            try:
                self._download_single_file(
                    fname,
                    min_bytes,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            except Exception as exc:
                if "iptal" in str(exc).lower():
                    raise
                raise RuntimeError(f"Model indirilemedi ({fname}): {exc}") from exc

    def _create_ct2_translator(self, ct2_model_path: str) -> Tuple[ctranslate2.Translator, str]:
        """
        İsteğe bağlı olarak Apple Silicon MPS (float16 -> float32 -> default) hızlandırmasını dener;
        desteklenmezse veya herhangi bir hata oluşursa işlemcinin desteklediği en hızlı
        CPU hesaplama tipine (int8 -> int8_float32 -> int16 -> float32 -> default) güvenle düşer.
        """
        errors: List[str] = []
        probe_tokens = (
            self.source_sp.encode("Hello.", out_type=str) + ["</s>"]
            if self.source_sp is not None
            else None
        )

        # Apple Silicon MPS hızlandırması (yalnızca kullanıcı "mps" veya "auto" istediğinde)
        if self.requested_device in ("mps", "auto") and detect_mps_available():
            try:
                raw_mps_types = ctranslate2.get_supported_compute_types("mps") or ()
                mps_supported = {str(x).lower() for x in raw_mps_types}
            except Exception:
                mps_supported = set()

            mps_candidates: List[str] = []
            for mps_ctype in ("float16", "float32", "default"):
                if not mps_supported or mps_ctype == "default" or mps_ctype in mps_supported:
                    mps_candidates.append(mps_ctype)
            if not mps_candidates:
                mps_candidates = ["float16", "float32", "default"]

            for mps_ctype in mps_candidates:
                try:
                    tr = ctranslate2.Translator(
                        ct2_model_path,
                        device="mps",
                        compute_type=mps_ctype,
                        intra_threads=self.cpu_threads,
                        inter_threads=1,
                    )
                    if probe_tokens:
                        tr.translate_batch(
                            [probe_tokens],
                            beam_size=1,
                            max_decoding_length=16,
                        )
                    self.active_device = "mps"
                    return tr, mps_ctype
                except Exception as exc:
                    errors.append(f"mps/{mps_ctype}: {exc}")

        candidates = list(self.compute_type_candidates)
        for fallback in ("int8", "int8_float32", "int16", "float32", "default", "auto"):
            if fallback not in candidates:
                candidates.append(fallback)

        for ctype in candidates:
            try:
                tr = ctranslate2.Translator(
                    ct2_model_path,
                    device="cpu",
                    compute_type=ctype,
                    intra_threads=self.cpu_threads,
                    inter_threads=1,
                )
                if probe_tokens:
                    tr.translate_batch(
                        [probe_tokens],
                        beam_size=1,
                        max_decoding_length=16,
                    )
                self.active_device = "cpu"
                return tr, ctype
            except Exception as exc:
                errors.append(f"{ctype}: {exc}")

        raise RuntimeError(
            "CTranslate2 hiçbir CPU hesaplama tipiyle başlatılamadı ("
            + " | ".join(errors[-3:])
            + ")"
        )

    def _init_engines(self) -> None:
        source_spm_path = os.path.join(self.model_dir, "source.spm")
        target_spm_path = os.path.join(self.model_dir, "target.spm")

        with open(source_spm_path, "rb") as f_src:
            self.source_sp = spm.SentencePieceProcessor(model_proto=f_src.read())
        with open(target_spm_path, "rb") as f_tgt:
            self.target_sp = spm.SentencePieceProcessor(model_proto=f_tgt.read())

        ct2_model_path = get_ct2_safe_path(self.model_dir)
        self.translator, self.active_compute_type = self._create_ct2_translator(ct2_model_path)

    def reconfigure_threads(self, cpu_threads: int) -> None:
        """
        Kullanıcı performans profilini değiştirdiğinde çeviri motorunu yeni thread sayısıyla günceller.
        Yeni motoru oluşturmadan önce eski CTranslate2 örneğini serbest bırakarak bellek artışını önler.
        """
        new_threads = max(1, int(cpu_threads))
        with self._engine_lock:
            if new_threads == self.cpu_threads and self.translator is not None:
                return
            self.cpu_threads = new_threads
            if self.is_ready and self.is_model_downloaded():
                self.translator = None
                gc.collect()
                ct2_model_path = get_ct2_safe_path(self.model_dir)
                try:
                    self.translator, self.active_compute_type = self._create_ct2_translator(
                        ct2_model_path
                    )
                except Exception:
                    self.is_ready = False
                    raise

    def load(
        self,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Modeli indirir (gerekirse), bozuk dosya varsa onarır ve işlemciye en uygun
        CTranslate2 hesaplama tipiyle (INT8 / INT8_FLOAT32 / FLOAT32) RAM'e yükler.
        """
        if cancel_check and cancel_check():
            raise RuntimeError("Model yüklemesi iptal edildi.")

        if not self.is_model_downloaded():
            self.download_model(progress_callback=progress_callback, cancel_check=cancel_check)

        if cancel_check and cancel_check():
            raise RuntimeError("Model yüklemesi iptal edildi.")

        pair_label = f"{self.source_lang.upper()} ➔ {self.target_lang.upper()}"
        if progress_callback:
            progress_callback(f"{pair_label} Model işlemcinize uygun modda RAM'e yükleniyor...", 92)

        with self._engine_lock:
            try:
                self._init_engines()
            except Exception as first_err:
                should_repair = (not self.is_model_downloaded()) or _is_model_corruption_error(
                    first_err
                )
                if not should_repair or (cancel_check and cancel_check()):
                    raise RuntimeError(
                        f"Çeviri motoru başlatılamadı: {first_err}"
                    ) from first_err

                # Yalnızca gerçek dosya eksikliği veya bozulmasında onarım/yeniden indirme yap
                if progress_callback:
                    progress_callback("Model dosyası doğrulanıyor ve onarılıyor...", 5)
                self.translator = None
                self.source_sp = None
                self.target_sp = None
                gc.collect()
                shutil.rmtree(self.model_dir, ignore_errors=True)
                self.download_model(progress_callback=progress_callback, cancel_check=cancel_check)
                try:
                    self._init_engines()
                except Exception as second_err:
                    raise RuntimeError(
                        f"Çeviri motoru başlatılamadı: {second_err} (İlk hata: {first_err})"
                    ) from second_err

        # Isınma (Warm-up) çevirisi (İstatistikleri sıfırla)
        self.translate_with_metrics("Welcome back, everything is ready.")
        with self._cache_lock:
            self.total_requests = 0
            self.cache_hits = 0
        self.is_ready = True

        if progress_callback:
            progress_callback(
                f"Model hazır! ({pair_label} | CTranslate2 {self.active_compute_type.upper()} • {self.cpu_threads} Thread)",
                100,
            )

    def _cache_get(self, key: str) -> Optional[str]:
        val = self._cache.get(key)
        if val is not None:
            self._cache.move_to_end(key)
        return val

    def _cache_put(self, key: str, val: str) -> None:
        self._cache[key] = val
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_max_size:
            self._cache.popitem(last=False)

    @staticmethod
    def compute_dynamic_max_length(token_batches: List[List[str]]) -> int:
        """
        Kaynak cümle uzunluğuna göre dinamik çıkış token sınırı hesaplar.
        Kısa cümlelerde veya gürültülü OCR çıktılarında modelin 80 token tekrar
        döngüsüne girip 500-800 ms kilitlenmesini engeller.
        """
        if not token_batches:
            return 32
        max_src = max(len(t) for t in token_batches)
        return min(88, max(20, int(max_src * 1.75) + 10))

    def try_fast_lookup(self, english_text: str) -> Optional[Tuple[str, float, bool]]:
        """
        Yalnızca sözlük ve RAM LRU Cache üzerinden 0.01 ms'de anlık sonuç arar.
        Sadece `_cache_lock` kullandığı için CTranslate2 çıkarımı sırasında asla beklemez.
        """
        t0 = time.perf_counter()
        speaker, body = extract_speaker_and_body(english_text, source_lang=self.source_lang)
        if not body:
            return None

        sentences: List[str] = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()
        ]
        if not sentences:
            sentences = [body]

        use_exact = self.lang_pair == "en-tr"
        with self._cache_lock:
            tr_parts: List[str] = []
            for sent in sentences:
                if use_exact:
                    exact = lookup_exact_phrase(sent)
                    if exact is not None:
                        tr_parts.append(exact)
                        continue
                cached_val = self._cache_get(sent.lower())
                if cached_val is not None:
                    tr_parts.append(cached_val)
                    continue
                return None

            self.total_requests += 1
            self.cache_hits += 1

        tr_body = " ".join(tr_parts)
        final_tr = f"{speaker}: {tr_body}" if speaker else tr_body
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return final_tr, elapsed_ms, True

    def translate_with_metrics(self, english_text: str) -> Tuple[str, float, bool]:
        """
        Altyazıyı en düşük gecikmeyle hedef dile çevirir.
        Çok cümleli altyazılarda önbellekte olmayan tüm cümleleri tek bir paralel batch'te çevirir.
        Dönüş: (ceviri_metin, gecen_sure_ms, cache_hit_mi)
        """
        t0 = time.perf_counter()

        speaker, body = extract_speaker_and_body(english_text, source_lang=self.source_lang)
        if not body:
            return "", 0.0, False

        sentences: List[str] = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()
        ]
        if not sentences:
            sentences = [body]

        use_exact = self.lang_pair == "en-tr"
        use_slang = self.source_lang == "en"

        results_map: Dict[int, str] = {}
        missing_indices: List[int] = []

        # Faz 1: Mikro-saniyelik önbellek/sözlük taraması (yalnızca _cache_lock)
        with self._cache_lock:
            self.total_requests += 1
            for idx, sent in enumerate(sentences):
                if use_exact:
                    exact = lookup_exact_phrase(sent)
                    if exact is not None:
                        results_map[idx] = exact
                        continue

                cached_val = self._cache_get(sent.lower())
                if cached_val is not None:
                    results_map[idx] = cached_val
                    continue

                missing_indices.append(idx)

            if not missing_indices:
                self.cache_hits += 1

        # Faz 2: Önbellekte olmayan cümleler için CTranslate2 çıkarımı (_engine_lock)
        all_cached = len(missing_indices) == 0
        if missing_indices:
            newly_translated: List[Tuple[str, str]] = []
            with self._engine_lock:
                if not self.translator or not self.source_sp or not self.target_sp:
                    for idx in missing_indices:
                        results_map[idx] = sentences[idx]
                else:
                    uncached_indices: List[int] = []
                    uncached_token_batches: List[List[str]] = []
                    for idx in missing_indices:
                        sent = sentences[idx]
                        normalized = normalize_slang_for_nmt(sent) if use_slang else sent
                        tokens = self.source_sp.encode(normalized, out_type=str) + ["</s>"]
                        uncached_indices.append(idx)
                        uncached_token_batches.append(tokens)

                    max_dec_len = self.compute_dynamic_max_length(uncached_token_batches)
                    batch_out = self.translator.translate_batch(
                        uncached_token_batches,
                        beam_size=1,
                        max_decoding_length=max_dec_len,
                        repetition_penalty=1.15,
                        no_repeat_ngram_size=3,
                        replace_unknowns=True,
                    )
                    for idx, res in zip(uncached_indices, batch_out):
                        out_tokens = res.hypotheses[0]
                        if out_tokens and out_tokens[-1] == "</s>":
                            out_tokens = out_tokens[:-1]
                        tr_sent = self.target_sp.decode(out_tokens).strip()
                        results_map[idx] = tr_sent
                        newly_translated.append((sentences[idx].lower(), tr_sent))

            if newly_translated:
                with self._cache_lock:
                    for cache_key, tr_sent in newly_translated:
                        self._cache_put(cache_key, tr_sent)

        tr_parts = [results_map[i] for i in range(len(sentences))]
        tr_body = " ".join(tr_parts)
        final_tr = f"{speaker}: {tr_body}" if speaker else tr_body
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return final_tr, elapsed_ms, all_cached


# Multi-language backwards-compatible alias
LocalSubtitleTranslator = LocalEnTrTranslator
