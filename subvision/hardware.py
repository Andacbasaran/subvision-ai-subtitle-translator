"""
SubVision AI — Evrensel Donanım, İşlemci (CPU/ISA) ve İşletim Sistemi Uyumluluk Modülü.

Farklı bilgisayarlarda ve farklı işlemcilerde (eski Intel/AMD, düşük çekirdekli laptoplar,
yeni nesil hibrit P+E çekirdekli işlemciler, Apple Silicon / ARM64, Windows/macOS/Linux)
uygulamanın çökmeden ve yüksek verimlilikle çalışması için donanımı otomatik algılar ve
optimum çalışma parametrelerini üretir.
"""

import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

_CACHED_WRITABLE_DATA_DIR: Optional[str] = None

# CTranslate2 için öncelik sırası (hız + bellek verimliliği -> maksimum uyumluluk)
CT2_COMPUTE_PRIORITY: Tuple[str, ...] = (
    "int8",
    "int8_float32",
    "int16",
    "float32",
    "default",
)

# Performans profili sabitleri
PROFILE_AUTO = "auto"
PROFILE_ECO = "eco"
PROFILE_BALANCED = "balanced"
PROFILE_PERFORMANCE = "performance"

VALID_PROFILES = (PROFILE_AUTO, PROFILE_ECO, PROFILE_BALANCED, PROFILE_PERFORMANCE)


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    os_version: str
    windows_build: int
    arch: str
    cpu_name: str
    logical_cores: int
    physical_cores: int
    isa_features: Tuple[str, ...] = field(default_factory=tuple)
    supported_ct2_types: Tuple[str, ...] = field(default_factory=tuple)
    capture_exclude_supported: bool = False
    recommended_tier: str = PROFILE_BALANCED

    @property
    def has_modern_simd(self) -> bool:
        feats = set(self.isa_features)
        return bool(
            feats.intersection(
                {"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"}
            )
        )

    @property
    def short_cpu_label(self) -> str:
        name = " ".join(self.cpu_name.split())
        if len(name) > 42:
            name = name[:39] + "..."
        return name or f"{self.arch.upper()} CPU"


@dataclass(frozen=True)
class RuntimeTuning:
    requested_profile: str
    effective_profile: str
    nmt_threads: int
    ocr_intra_threads: int
    ocr_inter_threads: int
    cv_threads: int
    scan_fps: int
    scan_interval_sec: float
    idle_scan_interval_sec: float
    max_capture_width: int
    det_limit_side_len: int
    warmup_buckets: Tuple[int, ...]
    warmup_double_line: bool
    default_ocr_mode: str
    compute_type_candidates: Tuple[str, ...]


def normalize_arch(raw_machine: Optional[str] = None) -> str:
    m = (raw_machine or platform.machine() or "").strip().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    if m in ("i386", "i686", "x86"):
        return "x86"
    return m or "unknown"


def get_windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def detect_cpu_name() -> str:
    # 1. Windows Registry (en hızlı ve en temiz yöntem, subprocess açmaz)
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if val and str(val).strip():
                    return " ".join(str(val).strip().split())
        except Exception:
            pass

    # 2. Linux /proc/cpuinfo
    if sys.platform.startswith("linux"):
        try:
            fallback_arm: Optional[str] = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    k = key.strip().lower()
                    v = " ".join(val.strip().split())
                    if not v:
                        continue
                    if k == "model name":
                        return v
                    if k in ("hardware", "model") and not v.isdigit() and fallback_arm is None:
                        fallback_arm = v
            if fallback_arm:
                return fallback_arm
        except Exception:
            pass

    # 3. macOS sysctl (Apple Silicon & Intel Mac)
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return " ".join(res.stdout.strip().split())
        except Exception:
            pass

    fallback = (platform.processor() or "").strip()
    if fallback:
        return " ".join(fallback.split())
    return f"{normalize_arch().upper()} Processor"


def detect_physical_cores(logical_cores: int) -> int:
    logical = max(1, int(logical_cores))

    # 1. Linux /proc/cpuinfo
    if sys.platform.startswith("linux"):
        try:
            pairs: Set[Tuple[str, str]] = set()
            phys_id = "0"
            core_id: Optional[str] = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        if core_id is not None:
                            pairs.add((phys_id, core_id))
                        phys_id = "0"
                        core_id = None
                        continue
                    if ":" in stripped:
                        k, v = [p.strip() for p in stripped.split(":", 1)]
                        if k == "physical id":
                            phys_id = v
                        elif k == "core id":
                            core_id = v
                if core_id is not None:
                    pairs.add((phys_id, core_id))
            if pairs:
                return max(1, min(logical, len(pairs)))
        except Exception:
            pass

    # 2. macOS sysctl
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return max(1, min(logical, int(res.stdout.strip())))
        except Exception:
            pass

    # 3. Windows Win32 API (GetLogicalProcessorInformationEx - RelationProcessorCore = 0)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            get_lpi_ex = kernel32.GetLogicalProcessorInformationEx
            get_lpi_ex.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
            get_lpi_ex.restype = wintypes.BOOL
            relation_processor_core = 0
            buf_len = wintypes.DWORD(0)
            get_lpi_ex(relation_processor_core, None, ctypes.byref(buf_len))
            if buf_len.value > 0:
                buf = ctypes.create_string_buffer(buf_len.value)
                ok = get_lpi_ex(relation_processor_core, buf, ctypes.byref(buf_len))
                if ok:
                    raw = buf.raw
                    offset = 0
                    cores = 0
                    while offset + 8 <= buf_len.value:
                        rel = int.from_bytes(raw[offset : offset + 4], "little")
                        size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
                        if size <= 0:
                            break
                        if rel == relation_processor_core:
                            cores += 1
                        offset += size
                    if cores > 0:
                        return max(1, min(logical, cores))
        except Exception:
            pass

    # Güvenli tahmin: 1-2 mantıksal çekirdek varsa muhtemelen 1-2 fiziksel, 4+ ise genelde SMT/HT
    if logical <= 2:
        return logical
    return max(2, logical // 2)


def detect_isa_features(arch: Optional[str] = None) -> Tuple[str, ...]:
    norm_arch = normalize_arch(arch)
    found: Set[str] = set()

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            is_feat = ctypes.windll.kernel32.IsProcessorFeaturePresent
            is_feat.argtypes = [wintypes.DWORD]
            is_feat.restype = wintypes.BOOL
            win_flags = (
                (10, "sse2"),
                (37, "sse4_1"),
                (38, "sse4_2"),
                (39, "avx"),
                (40, "avx2"),
                (41, "avx512f"),
                (19, "neon"),  # PF_ARM_NEON_INSTRUCTIONS_AVAILABLE
                (43, "dotprod"),
            )
            for code, name in win_flags:
                try:
                    if bool(is_feat(code)):
                        found.add(name)
                except Exception:
                    pass
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    lower = line.lower()
                    if lower.startswith(("flags", "features")) and ":" in lower:
                        tokens = set(lower.split(":", 1)[1].split())
                        flag_map = {
                            "sse2": "sse2",
                            "sse4_1": "sse4_1",
                            "sse4_2": "sse4_2",
                            "avx": "avx",
                            "avx2": "avx2",
                            "avx512f": "avx512f",
                            "avx512_vnni": "avx512_vnni",
                            "avx_vnni": "avx_vnni",
                            "asimd": "neon",
                            "neon": "neon",
                            "asimddp": "dotprod",
                        }
                        for src_flag, norm_name in flag_map.items():
                            if src_flag in tokens:
                                found.add(norm_name)
                        break
        except Exception:
            pass
    elif sys.platform == "darwin":
        if norm_arch == "arm64":
            found.update({"neon", "dotprod"})
        else:
            for sysctl_key, feat_name in (
                ("hw.optional.sse4_2", "sse4_2"),
                ("hw.optional.avx1_0", "avx"),
                ("hw.optional.avx2_0", "avx2"),
                ("hw.optional.avx512f", "avx512f"),
            ):
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", sysctl_key],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    if res.returncode == 0 and res.stdout.strip() == "1":
                        found.add(feat_name)
                except Exception:
                    pass

    return tuple(sorted(found))


def query_ct2_supported_compute_types() -> Tuple[str, ...]:
    try:
        import ctranslate2

        supported = ctranslate2.get_supported_compute_types("cpu")
        if supported:
            return tuple(sorted(str(x) for x in supported))
    except Exception:
        pass
    return ()


def select_compute_type_candidates(
    supported_types: Sequence[str],
    isa_features: Sequence[str] = (),
) -> Tuple[str, ...]:
    """
    İşlemcinin desteklediği CTranslate2 hesaplama tiplerini en hızlıdan en uyumluya sıralar.
    Eski/farklı işlemcilerde INT8 desteklenmiyorsa otomatik olarak INT8_FLOAT32 / INT16 / FLOAT32'ye düşer.
    """
    supported_set = {str(x).lower() for x in supported_types}
    ordered: List[str] = []

    if supported_set:
        for candidate in CT2_COMPUTE_PRIORITY:
            if candidate in supported_set or candidate == "default":
                if candidate not in ordered:
                    ordered.append(candidate)
        # CTranslate2'nin desteklediğini bildirdiği diğer tipleri de yedek olarak ekle
        for extra in sorted(supported_set):
            if extra not in ordered and extra != "auto":
                ordered.append(extra)
    else:
        # CTranslate2 henüz sorgulanamadıysa güvenli varsayılan sıra
        ordered = list(CT2_COMPUTE_PRIORITY)

    if "auto" not in ordered:
        ordered.append("auto")
    return tuple(ordered)


def classify_hardware_tier(
    logical_cores: int,
    physical_cores: int,
    isa_features: Sequence[str],
    arch: str,
) -> str:
    feats = set(isa_features)
    has_modern = bool(
        feats.intersection({"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"})
    )

    # Çok çekirdekli + modern SIMD işlemci
    if physical_cores >= 6 and logical_cores >= 8 and (has_modern or not feats):
        return PROFILE_PERFORMANCE

    # Eski / düşük çekirdekli veya AVX2/NEON olmayan işlemci
    if physical_cores <= 2 or logical_cores <= 2:
        return PROFILE_ECO
    if arch == "x86_64" and feats and not has_modern and physical_cores <= 4:
        return PROFILE_ECO

    return PROFILE_BALANCED


def detect_hardware_profile(query_ct2: bool = True) -> HardwareProfile:
    os_name = platform.system() or sys.platform
    os_version = platform.release() or ""
    win_build = get_windows_build()
    arch = normalize_arch()
    cpu_name = detect_cpu_name()
    logical = max(1, os.cpu_count() or 2)
    physical = detect_physical_cores(logical)
    isa = detect_isa_features(arch)
    ct2_types = query_ct2_supported_compute_types() if query_ct2 else ()

    # WDA_EXCLUDEFROMCAPTURE (0x11) Windows 10 2004 (Build 19041) ve Windows 11'de desteklenir
    capture_exclude_supported = sys.platform == "win32" and win_build >= 19041

    tier = classify_hardware_tier(logical, physical, isa, arch)

    return HardwareProfile(
        os_name=os_name,
        os_version=os_version,
        windows_build=win_build,
        arch=arch,
        cpu_name=cpu_name,
        logical_cores=logical,
        physical_cores=physical,
        isa_features=isa,
        supported_ct2_types=ct2_types,
        capture_exclude_supported=capture_exclude_supported,
        recommended_tier=tier,
    )


def compute_runtime_tuning(
    hw: HardwareProfile,
    requested_profile: str = PROFILE_AUTO,
) -> RuntimeTuning:
    req = requested_profile if requested_profile in VALID_PROFILES else PROFILE_AUTO
    eff = hw.recommended_tier if req == PROFILE_AUTO else req

    # En az 1 mantıksal iş parçacığını işletim sistemi + arayüz + oyun için boşta bırak
    safe_max_threads = max(1, hw.logical_cores - 1) if hw.logical_cores >= 2 else 1

    if eff == PROFILE_ECO:
        nmt_threads = max(1, min(2, hw.physical_cores, safe_max_threads))
        ocr_intra_threads = 1
        cv_threads = 1
        scan_fps = 15
        idle_fps = 10
        max_capture_width = 720
        det_limit_side_len = 384
        warmup_buckets: Tuple[int, ...] = (10, 16)
        warmup_double_line = False
        default_ocr_mode = "fast_mask"
    elif eff == PROFILE_PERFORMANCE:
        nmt_threads = max(1, min(6, hw.physical_cores, safe_max_threads))
        ocr_intra_threads = max(1, min(4, max(2, hw.physical_cores // 2), safe_max_threads))
        cv_threads = 2 if hw.logical_cores >= 4 else 1
        scan_fps = 30
        idle_fps = 20
        max_capture_width = 960
        det_limit_side_len = 480
        warmup_buckets = (10, 16, 22)
        warmup_double_line = True
        default_ocr_mode = "fast_mask"
    else:
        # PROFILE_BALANCED
        nmt_threads = max(1, min(4, hw.physical_cores, safe_max_threads))
        ocr_intra_threads = max(1, min(2, max(1, hw.physical_cores // 2), safe_max_threads))
        cv_threads = 2 if hw.logical_cores >= 4 else 1
        scan_fps = 24
        idle_fps = 14
        max_capture_width = 860
        det_limit_side_len = 480
        warmup_buckets = (10, 16, 22)
        warmup_double_line = False
        default_ocr_mode = "fast_mask"

    compute_candidates = select_compute_type_candidates(
        hw.supported_ct2_types, hw.isa_features
    )

    return RuntimeTuning(
        requested_profile=req,
        effective_profile=eff,
        nmt_threads=nmt_threads,
        ocr_intra_threads=ocr_intra_threads,
        ocr_inter_threads=1,
        cv_threads=cv_threads,
        scan_fps=scan_fps,
        scan_interval_sec=round(1.0 / scan_fps, 4),
        idle_scan_interval_sec=round(1.0 / idle_fps, 4),
        max_capture_width=max_capture_width,
        det_limit_side_len=det_limit_side_len,
        warmup_buckets=warmup_buckets,
        warmup_double_line=warmup_double_line,
        default_ocr_mode=default_ocr_mode,
        compute_type_candidates=compute_candidates,
    )


def apply_thread_env_defaults(tuning: RuntimeTuning) -> None:
    """
    OpenMP / BLAS / MKL kütüphanelerinin yüksek çekirdekli veya düşük çekirdekli
    işlemcilerde gereksiz thread patlaması yaratmasını önler.
    """
    t = str(max(1, tuning.nmt_threads))
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(var, t)


def get_app_base_dir() -> str:
    """
    Hem Python betiği olarak hem de derlenmiş (.exe) olarak çalışırken
    uygulamanın kök dizinini doğru şekilde döndürür.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".write_probe_{os.getpid()}")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def get_writable_data_dir(preferred_dir: Optional[str] = None) -> str:
    """
    Uygulama dizini yazılabilir ise taşınabilir (portable) modu korur;
    salt-okunur (örn. Program Files) veya macOS .app paketi içinden çalışıyorsa
    kullanıcı veri dizinine (gerekirse geçici dizine) yönlendirir.
    """
    global _CACHED_WRITABLE_DATA_DIR
    if preferred_dir is None and _CACHED_WRITABLE_DATA_DIR:
        return _CACHED_WRITABLE_DATA_DIR

    def _ensure_fallback(path: str) -> str:
        try:
            os.makedirs(path, exist_ok=True)
            if _is_dir_writable(path):
                return path
        except OSError:
            pass
        tmp_dir = os.path.join(tempfile.gettempdir(), "SubVisionAI")
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir

    if preferred_dir is None and sys.platform == "darwin" and getattr(sys, "frozen", False):
        resolved = _ensure_fallback(os.path.expanduser("~/Library/Application Support/SubVisionAI"))
        _CACHED_WRITABLE_DATA_DIR = resolved
        return resolved

    base = preferred_dir or get_app_base_dir()
    if _is_dir_writable(base):
        if preferred_dir is None:
            _CACHED_WRITABLE_DATA_DIR = base
        return base

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        fallback = os.path.join(root, "SubVisionAI")
    elif sys.platform == "darwin":
        fallback = os.path.expanduser("~/Library/Application Support/SubVisionAI")
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        fallback = os.path.join(xdg, "SubVisionAI")

    resolved = _ensure_fallback(fallback)
    if preferred_dir is None:
        _CACHED_WRITABLE_DATA_DIR = resolved
    return resolved


def get_ct2_safe_path(model_dir: str) -> str:
    """
    CTranslate2 C++ yükleyicisinin Windows üzerinde Türkçe / Unicode karakter içeren
    klasör yollarında (örn. 'Masaüstü', 'Kullanıcılar\\Ömer') hata vermesini engeller.
    """
    try:
        model_dir.encode("ascii")
        return model_dir
    except UnicodeEncodeError:
        pass

    # 1. Göreceli yol ASCII ise onu kullan
    try:
        rel = os.path.relpath(model_dir)
        rel.encode("ascii")
        return rel
    except Exception:
        pass

    # 2. Windows 8.3 kısa yol (Short Path Name) dene
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(1024)
            res = ctypes.windll.kernel32.GetShortPathNameW(model_dir, buf, len(buf))
            if 0 < res < len(buf):
                short_path = buf.value
                short_path.encode("ascii")
                return short_path
        except Exception:
            pass

    return model_dir


def get_ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Display"
    return "DejaVu Sans"


def format_hardware_summary(hw: HardwareProfile, tuning: RuntimeTuning) -> str:
    tier_labels: Dict[str, str] = {
        PROFILE_ECO: "Eko / Düşük CPU",
        PROFILE_BALANCED: "Dengeli",
        PROFILE_PERFORMANCE: "Yüksek Performans",
    }
    tier_tr = tier_labels.get(tuning.effective_profile, tuning.effective_profile)
    simd_str = ", ".join(f.upper() for f in hw.isa_features) if hw.isa_features else "Standart"
    return (
        f"{hw.short_cpu_label} ({hw.physical_cores}C/{hw.logical_cores}T, {hw.arch}) • "
        f"Profil: {tier_tr} • NMT: {tuning.nmt_threads}T • OCR: {tuning.ocr_intra_threads}T • "
        f"{tuning.scan_fps} FPS • ISA: {simd_str}"
    )
