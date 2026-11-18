"""
SubVision AI — İngilizce -> Türkçe (EN -> TR) CTranslate2 INT8 Lokal Çeviri Motoru.
Model: Helsinki-NLP/opus-mt-tc-big-en-tr (CTranslate2 INT8 Quantized - ~227 MB)
Sıfır GPU/VRAM kullanımı ile CPU üzerinde ultra düşük gecikmeyle çeviri yapar.

Kararlılık ve Performans Özellikleri:
1. Eksik veya yarıda kalmış model indirmelerini dosya boyutu doğrulaması ile otomatik tespit eder ve tamamlar.
2. Çok cümleli altyazılarda önbellekte olmayan tüm cümleleri tek bir paralel CTranslate2 batch çağrısında çevirir.
3. Thread-Safe (iş parçacığı güvenli) 4096 cümlelik RAM önbelleği (LRU Cache) içerir.
"""

import os
import re
import shutil
import sys
import threading
import time
import urllib.request
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

import ctranslate2
import sentencepiece as spm

from glossary import (
    extract_speaker_and_body,
    lookup_exact_phrase,
    normalize_slang_for_nmt,
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


def get_app_base_dir() -> str:
    """
    Hem Python betiği olarak hem de derlenmiş (.exe) olarak çalışırken
    uygulamanın kök dizinini doğru şekilde döndürür.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


class LocalEnTrTranslator:
    """
    CTranslate2 + SentencePiece tabanlı ultra hızlı ve kararlı EN -> TR çeviri motoru.
    """

    def __init__(self, model_dir: Optional[str] = None, cpu_threads: int = 4):
        base_dir = get_app_base_dir()
        self.model_dir = model_dir or os.path.join(base_dir, "models", "opus-en-tr-ct2")
        self.cpu_threads = cpu_threads
        self.translator: Optional[ctranslate2.Translator] = None
        self.source_sp: Optional[spm.SentencePieceProcessor] = None
        self.target_sp: Optional[spm.SentencePieceProcessor] = None
        self.is_ready = False

        self._lock = threading.Lock()
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_max_size = 4096
        self.total_requests = 0
        self.cache_hits = 0

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self.total_requests = 0
            self.cache_hits = 0

    def is_model_downloaded(self) -> bool:
        for fname, min_bytes in MODEL_FILES_MIN_SIZE.items():
            fpath = os.path.join(self.model_dir, fname)
            if not os.path.exists(fpath) or os.path.getsize(fpath) < min_bytes:
                return False
        return True

    def download_model(self, progress_callback: Optional[Callable[[str, int], None]] = None) -> None:
        """
        Model dosyaları lokalde yoksa veya yarım kalmışsa HuggingFace üzerinden (~227 MB)
        otomatik yeniden deneme (retry) desteğiyle indirir.
        """
        os.makedirs(self.model_dir, exist_ok=True)
        for fname, min_bytes in MODEL_FILES_MIN_SIZE.items():
            dest_path = os.path.join(self.model_dir, fname)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) >= min_bytes:
                continue

            url = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{fname}"
            tmp_path = dest_path + ".part"

            last_err: Optional[Exception] = None
            for attempt in range(1, 4):
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
                    last_err = exc
                    time.sleep(1.5 * attempt)

            if last_err is not None:
                raise RuntimeError(f"Model indirilemedi ({fname}): {last_err}")

    def _init_engines(self) -> None:
        source_spm_path = os.path.join(self.model_dir, "source.spm")
        target_spm_path = os.path.join(self.model_dir, "target.spm")

        with open(source_spm_path, "rb") as f_src:
            self.source_sp = spm.SentencePieceProcessor(model_proto=f_src.read())
        with open(target_spm_path, "rb") as f_tgt:
            self.target_sp = spm.SentencePieceProcessor(model_proto=f_tgt.read())

        try:
            ct2_model_path = os.path.relpath(self.model_dir)
        except ValueError:
            ct2_model_path = self.model_dir

        self.translator = ctranslate2.Translator(
            ct2_model_path,
            device="cpu",
            compute_type="int8",
            intra_threads=self.cpu_threads,
            inter_threads=1,
        )

    def load(self, progress_callback: Optional[Callable[[str, int], None]] = None) -> None:
        """
        Modeli indirir (gerekirse), bozuk dosya varsa onarır ve CTranslate2 INT8 motorunu RAM'e yükler.
        """
        if not self.is_model_downloaded():
            self.download_model(progress_callback=progress_callback)

        if progress_callback:
            progress_callback("EN -> TR INT8 Model RAM'e yükleniyor...", 95)

        try:
            self._init_engines()
        except Exception:
            if progress_callback:
                progress_callback("Model dosyası onarılıyor ve yeniden indiriliyor...", 0)
            shutil.rmtree(self.model_dir, ignore_errors=True)
            self.download_model(progress_callback=progress_callback)
            self._init_engines()

        # Isınma (Warm-up) çevirisi (İstatistikleri sıfırla)
        self.translate_with_metrics("Welcome back, everything is ready.")
        self.total_requests = 0
        self.cache_hits = 0
        self.is_ready = True

        if progress_callback:
            progress_callback("Model hazır! (EN ➔ TR | CTranslate2 INT8 CPU)", 100)

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

    def translate_with_metrics(self, english_text: str) -> Tuple[str, float, bool]:
        """
        İngilizce altyazıyı en düşük gecikmeyle Türkçeye çevirir.
        Çok cümleli altyazılarda önbellekte olmayan tüm cümleleri tek bir paralel batch'te çevirir.
        Dönüş: (turkce_metin, gecen_sure_ms, cache_hit_mi)
        """
        t0 = time.perf_counter()

        speaker, body = extract_speaker_and_body(english_text)
        if not body:
            return "", 0.0, False

        sentences: List[str] = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()
        ]
        if not sentences:
            sentences = [body]

        with self._lock:
            self.total_requests += 1
            results_map: Dict[int, str] = {}
            uncached_indices: List[int] = []
            uncached_token_batches: List[List[str]] = []

            for idx, sent in enumerate(sentences):
                # 1. Hazır kalıp sözlüğü kontrolü (0.01 ms)
                exact = lookup_exact_phrase(sent)
                if exact is not None:
                    results_map[idx] = exact
                    continue

                # 2. RAM LRU Cache kontrolü (0.01 ms)
                cached_val = self._cache_get(sent.lower())
                if cached_val is not None:
                    results_map[idx] = cached_val
                    continue

                if not self.translator or not self.source_sp or not self.target_sp:
                    results_map[idx] = sent
                    continue

                normalized = normalize_slang_for_nmt(sent)
                tokens = self.source_sp.encode(normalized, out_type=str) + ["</s>"]
                uncached_indices.append(idx)
                uncached_token_batches.append(tokens)

            # 3. Önbellekte olmayan tüm cümleleri TEK BİR CTranslate2 Batch çağrısında paralel çevir
            if uncached_token_batches and self.translator and self.target_sp:
                batch_out = self.translator.translate_batch(
                    uncached_token_batches,
                    beam_size=1,
                    max_decoding_length=80,
                    replace_unknowns=True,
                )
                for idx, res in zip(uncached_indices, batch_out):
                    out_tokens = res.hypotheses[0]
                    if out_tokens and out_tokens[-1] == "</s>":
                        out_tokens = out_tokens[:-1]
                    tr_sent = self.target_sp.decode(out_tokens).strip()
                    results_map[idx] = tr_sent
                    self._cache_put(sentences[idx].lower(), tr_sent)

            tr_parts = [results_map[i] for i in range(len(sentences))]
            all_cached = len(uncached_indices) == 0
            if all_cached:
                self.cache_hits += 1

        tr_body = " ".join(tr_parts)
        final_tr = f"{speaker}: {tr_body}" if speaker else tr_body
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return final_tr, elapsed_ms, all_cached
