"""
SubVision AI — Community Glossary Hub.

Discovers community-contributed JSON glossary packs from GitHub, validates their
schema and size safely, and installs them atomically into the writable local
glossaries directory. Uses only Python stdlib with strict timeouts and graceful
offline fallback.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Union

from subvision.hardware import get_app_base_dir, get_writable_data_dir

GITHUB_GLOSSARIES_API = (
    "https://api.github.com/repos/Andacbasaran/subvision-ai-subtitle-translator/contents/glossaries"
)
MAX_GLOSSARY_BYTES = 512 * 1024  # 512 KB safety cap

_SAFE_FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\.json$")
_USER_AGENT = "SubVisionAI"


@dataclass(frozen=True)
class RemoteGlossaryItem:
    pack_id: str
    filename: str
    download_url: str
    size_bytes: int
    sha: str
    is_local: bool


def safe_pack_filename(filename: str) -> str:
    """
    Validates a glossary pack filename and rejects path traversal or invalid characters.
    Requires lowercase alphanumeric stem matching `^[a-z0-9][a-z0-9_-]{0,63}\\.json$`.
    """
    if not isinstance(filename, str):
        raise ValueError("Glossary filename must be a string.")
    cleaned = filename.strip()
    if (
        not cleaned
        or "/" in cleaned
        or "\\" in cleaned
        or ".." in cleaned
        or "\x00" in cleaned
        or os.path.basename(cleaned) != cleaned
    ):
        raise ValueError(f"Unsafe glossary filename: {filename!r}")
    if not _SAFE_FILENAME_RE.match(cleaned):
        raise ValueError(f"Invalid glossary filename: {filename!r}")
    return cleaned


def validate_glossary_payload(raw_bytes: bytes) -> dict:
    """
    Validates raw JSON bytes for a glossary pack.

    Enforces:
      - Non-empty bytes within `MAX_GLOSSARY_BYTES`
      - Valid UTF-8 JSON object
      - Non-empty string `name`
      - Optional `description` is a string
      - Optional `exact_phrases` is a dict[str, str]
      - Optional `do_not_translate` is a list[str]
      - Optional `term_replacements` is a dict[str, str]

    Raises `ValueError` on any violation.
    """
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise ValueError("Glossary payload must be bytes.")
    if len(raw_bytes) == 0:
        raise ValueError("Glossary payload is empty.")
    if len(raw_bytes) > MAX_GLOSSARY_BYTES:
        raise ValueError(
            f"Glossary payload exceeds maximum allowed size ({MAX_GLOSSARY_BYTES} bytes)."
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Glossary payload is not valid UTF-8.") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Glossary payload is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Glossary payload must be a JSON object.")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Glossary 'name' must be a non-empty string.")

    if "description" in data and data["description"] is not None:
        if not isinstance(data["description"], str):
            raise ValueError("Glossary 'description' must be a string.")

    if "exact_phrases" in data and data["exact_phrases"] is not None:
        exact = data["exact_phrases"]
        if not isinstance(exact, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in exact.items()
        ):
            raise ValueError("Glossary 'exact_phrases' must be a mapping of string to string.")

    if "do_not_translate" in data and data["do_not_translate"] is not None:
        dnt = data["do_not_translate"]
        if not isinstance(dnt, list) or not all(isinstance(item, str) for item in dnt):
            raise ValueError("Glossary 'do_not_translate' must be a list of strings.")

    if "term_replacements" in data and data["term_replacements"] is not None:
        repl = data["term_replacements"]
        if not isinstance(repl, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in repl.items()
        ):
            raise ValueError("Glossary 'term_replacements' must be a mapping of string to string.")

    return data


class CommunityGlossaryHub:
    """Fetches and installs community glossary packs from GitHub with offline fallback."""

    def __init__(
        self,
        local_dir: Optional[str] = None,
        bundled_dir: Optional[str] = None,
        api_url: str = GITHUB_GLOSSARIES_API,
    ):
        self.local_dir = os.path.abspath(
            local_dir if local_dir is not None else os.path.join(get_writable_data_dir(), "glossaries")
        )
        self.bundled_dir = os.path.abspath(
            bundled_dir if bundled_dir is not None else os.path.join(get_app_base_dir(), "glossaries")
        )
        self.api_url = api_url

    def _collect_local_files(self) -> Dict[str, str]:
        """Returns mapping of safe filename -> absolute path across bundled and local dirs."""
        found: Dict[str, str] = {}
        for folder in (self.bundled_dir, self.local_dir):
            if not folder or not os.path.isdir(folder):
                continue
            try:
                entries = sorted(os.listdir(folder))
            except OSError:
                continue
            for fname in entries:
                try:
                    safe_name = safe_pack_filename(fname)
                except ValueError:
                    continue
                full_path = os.path.join(folder, safe_name)
                if os.path.isfile(full_path):
                    found[safe_name] = full_path
        return found

    def _local_filenames(self) -> Set[str]:
        return set(self._collect_local_files().keys())

    def _list_local_catalog(self) -> List[RemoteGlossaryItem]:
        items: List[RemoteGlossaryItem] = []
        for safe_name, full_path in sorted(self._collect_local_files().items()):
            try:
                size_bytes = os.path.getsize(full_path)
            except OSError:
                size_bytes = 0
            items.append(
                RemoteGlossaryItem(
                    pack_id=safe_name[:-5],
                    filename=safe_name,
                    download_url="",
                    size_bytes=size_bytes,
                    sha="",
                    is_local=True,
                )
            )
        return items

    def fetch_catalog(self, timeout: float = 6.0) -> List[RemoteGlossaryItem]:
        """
        Queries GitHub API for available glossary packs, marking packs already
        present in `local_dir` or `bundled_dir` with `is_local=True`.
        Falls back cleanly to local/bundled listing if offline or rate-limited.
        """
        local_files = self._local_filenames()
        req = urllib.request.Request(
            self.api_url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(MAX_GLOSSARY_BYTES * 2)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, list):
                return self._list_local_catalog()
        except Exception:
            return self._list_local_catalog()

        items: List[RemoteGlossaryItem] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type")
            if entry_type is not None and entry_type != "file":
                continue
            raw_name = entry.get("name", "")
            try:
                safe_name = safe_pack_filename(str(raw_name))
            except ValueError:
                continue
            download_url = str(entry.get("download_url") or "")
            try:
                size_bytes = int(entry.get("size") or 0)
            except (TypeError, ValueError):
                size_bytes = 0
            sha = str(entry.get("sha") or "")
            items.append(
                RemoteGlossaryItem(
                    pack_id=safe_name[:-5],
                    filename=safe_name,
                    download_url=download_url,
                    size_bytes=size_bytes,
                    sha=sha,
                    is_local=safe_name in local_files,
                )
            )

        items.sort(key=lambda item: item.pack_id)
        return items

    def install_pack(
        self,
        item_or_url: Union[RemoteGlossaryItem, str],
        filename: Optional[str] = None,
        timeout: float = 8.0,
    ) -> str:
        """
        Downloads a glossary pack JSON, validates it with `validate_glossary_payload`,
        and writes it atomically into `self.local_dir`. Returns the installed file path.
        """
        if isinstance(item_or_url, RemoteGlossaryItem):
            url = item_or_url.download_url.strip()
            target_name = safe_pack_filename(filename if filename is not None else item_or_url.filename)
        elif isinstance(item_or_url, str):
            url = item_or_url.strip()
            if filename is not None:
                target_name = safe_pack_filename(filename)
            else:
                parsed_path = urllib.parse.urlparse(url).path
                derived = os.path.basename(parsed_path)
                target_name = safe_pack_filename(derived)
        else:
            raise ValueError("item_or_url must be a RemoteGlossaryItem or URL string.")

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError(f"Invalid glossary download URL (HTTPS required): {url!r}")

        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read(MAX_GLOSSARY_BYTES + 1)

        validate_glossary_payload(raw_bytes)

        os.makedirs(self.local_dir, exist_ok=True)
        target_path = os.path.join(self.local_dir, target_name)
        tmp_path = f"{target_path}.tmp"

        try:
            with open(tmp_path, "wb") as f:
                f.write(raw_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

        return target_path
