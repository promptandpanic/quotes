"""
Temporarily host a video as a GitHub Release asset so Instagram can download it.
The asset is publicly accessible on public repos.
After Instagram processes the reel, call cleanup() to delete the asset.
"""
import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

RELEASE_TAG = "media-pool"
RELEASE_NAME = "Temporary Media Pool"
RELEASE_BODY = "Auto-managed by the quotes bot. Assets are deleted after posting."


class GitHubUploader:
    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self._release_id: int | None = None
        self._asset_id: int | None = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def _get_or_create_release(self) -> int | None:
        if not (self.token and self.repo):
            return None
        base = f"https://api.github.com/repos/{self.repo}"

        # Try to get existing release
        resp = requests.get(
            f"{base}/releases/tags/{RELEASE_TAG}",
            headers=self._headers(), timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()["id"]

        # Create new release
        resp = requests.post(
            f"{base}/releases",
            headers=self._headers(),
            json={
                "tag_name": RELEASE_TAG,
                "name": RELEASE_NAME,
                "body": RELEASE_BODY,
                "draft": False,
                "prerelease": True,
            },
            timeout=15,
        )
        if resp.status_code == 201:
            return resp.json()["id"]
        logger.error(f"Could not create release: {resp.text[:200]}")
        return None

    def upload(self, data: bytes, filename: str | None = None) -> str | None:
        """Upload bytes and return the public download URL.
        filename: optional override — if None, auto-names as reel_{ts}.mp4.
        """
        release_id = self._get_or_create_release()
        if not release_id:
            return None
        self._release_id = release_id

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if filename:
            asset_name = filename
            content_type = "image/jpeg" if filename.endswith((".jpg", ".jpeg")) else "video/mp4"
        else:
            asset_name = f"reel_{ts}.mp4"
            content_type = "video/mp4"

        upload_url = (
            f"https://uploads.github.com/repos/{self.repo}"
            f"/releases/{release_id}/assets?name={asset_name}"
        )
        resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"token {self.token}",
                "Content-Type": content_type,
            },
            data=data,
            timeout=120,
        )
        if resp.status_code == 201:
            self._asset_id = resp.json()["id"]
            owner, repo_name = self.repo.split("/")
            url = f"https://github.com/{owner}/{repo_name}/releases/download/{RELEASE_TAG}/{asset_name}"
            # Instagram doesn't follow redirects — resolve to direct CDN URL
            try:
                head = requests.head(url, allow_redirects=True, timeout=15)
                if head.url and head.url != url:
                    url = head.url
            except Exception:
                pass
            logger.info(f"✓ Uploaded: {url}")
            return url
        logger.error(f"Asset upload failed: {resp.status_code} {resp.text[:200]}")
        return None

    def cleanup(self) -> None:
        """Delete the uploaded asset after Instagram has processed it."""
        if not (self.token and self.repo and self._asset_id):
            return
        url = f"https://api.github.com/repos/{self.repo}/releases/assets/{self._asset_id}"
        resp = requests.delete(url, headers=self._headers(), timeout=15)
        if resp.status_code == 204:
            logger.info("✓ Temporary video asset deleted")
        else:
            logger.warning(f"Asset cleanup failed: {resp.status_code}")
