"""
SubVision AI — Session Dialogue History Exporters (.srt & Anki .csv).
Enables exporting translated game/movie subtitles to standard SRT format or
Anki-compatible bilingual flashcards for language learners.
"""

import csv
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: str
    en_text: str
    tr_text: str
    elapsed_sec: float


def _format_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000.0)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export_history_to_srt(
    entries: Sequence[HistoryEntry],
    output_path: str,
    bilingual: bool = False,
    default_duration_sec: float = 3.2,
) -> int:
    """
    Writes dialogue history entries to a standard UTF-8 `.srt` subtitle file.
    Returns the number of exported subtitle blocks.
    """
    ordered = list(entries)
    lines = []
    for idx, item in enumerate(ordered, start=1):
        start_s = max(0.0, float(item.elapsed_sec))
        if idx < len(ordered):
            next_start = max(start_s + 0.5, float(ordered[idx].elapsed_sec))
            end_s = min(start_s + default_duration_sec, next_start - 0.05)
        else:
            end_s = start_s + default_duration_sec
        end_s = max(start_s + 0.4, end_s)

        lines.append(str(idx))
        lines.append(f"{_format_srt_time(start_s)} --> {_format_srt_time(end_s)}")
        if bilingual and item.en_text:
            lines.append(item.en_text.strip())
        lines.append(item.tr_text.strip())
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return len(ordered)


def export_history_to_anki_csv(
    entries: Sequence[HistoryEntry],
    output_path: str,
) -> int:
    """
    Writes bilingual dialogue history to a UTF-8-BOM semicolon CSV (`English;Turkish;Time`)
    ready for direct import into Anki or Excel.
    """
    ordered = list(entries)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["English", "Turkish", "Timestamp"])
        for item in ordered:
            writer.writerow([item.en_text.strip(), item.tr_text.strip(), item.timestamp])
    return len(ordered)
