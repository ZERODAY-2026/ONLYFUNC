"""Local conversation snapshots. Never an analytics engine or answer source."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from uuid import UUID, uuid4

from .models import Answer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title(question: str) -> str:
    return " ".join(question.split())[:72] or "Untitled conversation"


class ChatStore:
    """One JSON file per chat under gitignored data/; atomic writes on Windows."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, chat_id: str) -> Path:
        if UUID(chat_id).hex != chat_id:
            raise ValueError("Invalid conversation ID")
        return self.root / f"{chat_id}.json"

    def _read(self, chat_id: str) -> dict:
        return json.loads(self._path(chat_id).read_text(encoding="utf-8"))

    def _write(self, chat: dict) -> None:
        payload = json.dumps(chat, ensure_ascii=False, default=str)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, suffix=".tmp", delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
            os.replace(temp_path, self._path(chat["id"]))
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def create(self, first_question: str) -> str:
        with self._lock:
            chat_id = uuid4().hex
            stamp = _now()
            self._write({"id": chat_id, "title": _title(first_question), "created_at": stamp,
                         "updated_at": stamp, "answers": []})
            return chat_id

    def append(self, chat_id: str, answer: Answer) -> None:
        with self._lock:
            chat = self._read(chat_id)
            chat["answers"].append(asdict(answer))
            chat["updated_at"] = _now()
            self._write(chat)

    def load(self, chat_id: str) -> tuple[dict, list[Answer]]:
        with self._lock:
            chat = self._read(chat_id)
        return chat, [Answer(**saved) for saved in chat["answers"]]

    def list_chats(self, search: str = "") -> list[dict]:
        with self._lock:
            chats = []
            for path in self.root.glob("*.json"):
                chat = json.loads(path.read_text(encoding="utf-8"))
                if search.casefold() in chat["title"].casefold():
                    chats.append({key: chat[key] for key in ("id", "title", "created_at", "updated_at")})
        return sorted(chats, key=lambda chat: chat["updated_at"], reverse=True)

    def rename(self, chat_id: str, title: str) -> None:
        with self._lock:
            chat = self._read(chat_id)
            chat["title"] = _title(title)
            chat["updated_at"] = _now()
            self._write(chat)
