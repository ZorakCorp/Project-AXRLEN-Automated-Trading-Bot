import json
import os
import tempfile
from typing import Any, Dict, Optional


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd: Optional[int] = None
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_state_", suffix=".json", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        fd = None
        os.replace(tmp_path, path)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass


def load_json(path: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not os.path.exists(path):
        return default or {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    _atomic_write_json(path, data)


def append_jsonl(path: str, event: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False))
        f.write("\n")
