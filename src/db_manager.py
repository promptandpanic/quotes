"""
Manages the posted-quotes database stored as JSON in the GitHub repo.
Reads/writes via the GitHub Contents API so no git commands are needed.
"""
import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def _quote_hash(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode()).hexdigest()[:16]


class DBManager:
    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")  # owner/repo
        self.path = "data/posted_quotes.json"
        self._sha = None
        self._data = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load(self) -> dict:
        if self._data is not None:
            return self._data

        # Try GitHub API first (canonical source in CI)
        if self.token and self.repo:
            url = f"https://api.github.com/repos/{self.repo}/contents/{self.path}"
            resp = requests.get(
                url,
                headers={"Authorization": f"token {self.token}",
                         "Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            if resp.status_code == 200:
                body = resp.json()
                self._sha = body.get("sha")
                raw = base64.b64decode(body["content"]).decode()
                self._data = json.loads(raw)
                logger.info("DB loaded from GitHub API")
                return self._data

        # Fallback: read local file (useful for local dev)
        local = Path(self.path)
        if local.exists():
            self._data = json.loads(local.read_text())
            logger.info("DB loaded from local file")
            return self._data

        # Fresh start
        self._data = {"posted_hashes": [], "history": [], "last_updated": None}
        return self._data

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def active_hashes(self, window_days: int | None = None) -> set:
        """
        Hashes of quotes posted within the repeat window.
        Quotes outside the window are eligible for reuse.
        window_days=None means use REPEAT_WINDOW_DAYS from config.
        """
        from src.config import REPEAT_WINDOW_DAYS
        days = window_days if window_days is not None else REPEAT_WINDOW_DAYS
        data = self.load()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        hashes = set()
        for entry in data.get("history", []):
            try:
                posted_at = datetime.fromisoformat(entry["posted_at"])
                if posted_at >= cutoff:
                    hashes.add(entry["hash"])
            except Exception:
                pass
        return hashes

    def is_posted(self, text: str) -> bool:
        return _quote_hash(text) in self.active_hashes()

    def recent_topic_hints(self, days: int = 90, max_hints: int = 30) -> list[str]:
        """
        Return a list of short topic hints from the last `days` days.
        Each hint is the first 10 words of a posted quote — enough for
        the LLM to understand the topic without seeing the full text.
        Retained for one quarter (90 days) so the same themes aren't repeated.
        """
        data = self.load()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        hints = []
        for entry in data.get("history", []):
            try:
                posted_at = datetime.fromisoformat(entry["posted_at"])
                if posted_at < cutoff:
                    continue
            except Exception:
                continue
            text = entry.get("text", "")
            words = text.split()
            if words:
                hints.append(" ".join(words[:10]))
        # Most recent last, trimmed to max_hints
        return hints[-max_hints:]

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------
    def mark_posted(self, quote: dict, theme: str) -> None:
        data = self.load()
        qhash = _quote_hash(quote["text"])
        if qhash not in data["posted_hashes"]:
            data["posted_hashes"].append(qhash)
        data["history"].append({
            "hash": qhash,
            "text": quote["text"][:120],
            "author": quote.get("author", "Unknown"),
            "theme": theme,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        })
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        # Keep history under control (last 500 entries)
        data["history"] = data["history"][-500:]
        self._data = data

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    def save(self) -> bool:
        if self._data is None:
            return False

        content_bytes = json.dumps(self._data, indent=2, ensure_ascii=False).encode()
        encoded = base64.b64encode(content_bytes).decode()

        # Save locally for dev / as backup
        Path(self.path).write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False)
        )

        if not (self.token and self.repo):
            logger.warning("No GITHUB_TOKEN/GITHUB_REPOSITORY — saved locally only")
            return True

        url = f"https://api.github.com/repos/{self.repo}/contents/{self.path}"
        payload = {
            "message": "chore: update posted-quotes db [skip ci]",
            "content": encoded,
        }
        if self._sha:
            payload["sha"] = self._sha

        resp = requests.put(
            url,
            headers={"Authorization": f"token {self.token}",
                     "Accept": "application/vnd.github.v3+json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            logger.info("DB saved to GitHub")
            return True
        logger.error(f"DB save failed: {resp.status_code} {resp.text[:200]}")
        return False
