"""Suno AI music generation client - full function surface.

Implements the complete Suno API function set (sunoapi.org-compatible):
generate, lyrics, extend, cover, upload-extend, upload-cover, add-vocals,
add-instrumental, stems separation, WAV conversion, timestamped lyrics,
concat, mashup, persona creation, style boost, task status, and quota.

Configure via environment:
  SUNO_API_KEY   - Bearer token (required to enable)
  SUNO_API_BASE  - defaults to https://api.sunoapi.org
"""

import os

import requests

DEFAULT_BASE = "https://api.sunoapi.org"

# Every enabled function, for capability reporting.
SUNO_FUNCTIONS = [
    "generate",
    "generate_lyrics",
    "extend",
    "cover",
    "upload_extend",
    "upload_cover",
    "add_vocals",
    "add_instrumental",
    "stems",
    "convert_wav",
    "timestamped_lyrics",
    "concat",
    "mashup",
    "persona",
    "boost_style",
    "status",
    "quota",
]


class SunoError(Exception):
    pass


class SunoClient:
    def __init__(self, api_key=None, base_url=None, timeout=60):
        self.api_key = api_key or os.getenv("SUNO_API_KEY", "")
        self.base_url = (base_url or os.getenv("SUNO_API_BASE", DEFAULT_BASE)).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise SunoError("SUNO_API_KEY is not configured.")

    @classmethod
    def from_env(cls):
        """Return a client when SUNO_API_KEY is set, else None."""
        if os.getenv("SUNO_API_KEY"):
            return cls()
        return None

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SunoError(f"Suno returned non-JSON ({response.status_code})") from exc
        code = payload.get("code", response.status_code)
        if response.status_code != 200 or code != 200:
            raise SunoError(f"Suno error {code}: {payload.get('msg') or payload.get('message') or 'request failed'}")
        return payload.get("data", payload)

    def _post(self, path, body):
        return self._request("POST", path, json=body)

    # --- Generation -------------------------------------------------------
    def generate_custom(self, prompt, style, title, instrumental=False, model="V4_5", callback_url=None):
        """Custom-mode generation: prompt = lyrics (or empty), style = genre tags."""
        body = {
            "customMode": True,
            "instrumental": bool(instrumental),
            "prompt": prompt,
            "style": style,
            "title": title,
            "model": model,
        }
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate", body)

    def generate_description(self, description, instrumental=False, model="V4_5"):
        """Simple mode: generate from a natural-language description."""
        return self._post("/api/v1/generate", {
            "customMode": False,
            "instrumental": bool(instrumental),
            "prompt": description,
            "model": model,
        })

    # --- Lyrics ------------------------------------------------------------
    def generate_lyrics(self, prompt, callback_url=None):
        body = {"prompt": prompt}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/lyrics", body)

    def get_lyrics_status(self, task_id):
        return self._request("GET", f"/api/v1/lyrics/record-info?taskId={task_id}")

    # --- Extend / Cover ----------------------------------------------------
    def extend(self, audio_id, prompt="", style="", title="", continue_at=0, model="V4_5", callback_url=None):
        body = {"audioId": audio_id, "defaultParamFlag": True, "prompt": prompt,
                "style": style, "title": title, "continueAt": continue_at, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/extend", body)

    def cover(self, audio_id, prompt="", style="", title="", model="V4_5", callback_url=None):
        body = {"audioId": audio_id, "defaultParamFlag": True, "prompt": prompt,
                "style": style, "title": title, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/cover", body)

    def upload_extend(self, upload_url, prompt="", style="", title="", continue_at=0, model="V4_5", callback_url=None):
        body = {"uploadUrl": upload_url, "defaultParamFlag": True, "prompt": prompt,
                "style": style, "title": title, "continueAt": continue_at, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/upload-extend", body)

    def upload_cover(self, upload_url, prompt="", style="", title="", model="V4_5", callback_url=None):
        body = {"uploadUrl": upload_url, "defaultParamFlag": True, "prompt": prompt,
                "style": style, "title": title, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/upload-cover", body)

    # --- Vocals / Instrumentals -------------------------------------------
    def add_vocals(self, upload_url, prompt, style, title, model="V4_5", callback_url=None):
        body = {"uploadUrl": upload_url, "prompt": prompt, "style": style, "title": title, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/add-vocals", body)

    def add_instrumental(self, upload_url, title, tags, model="V4_5", callback_url=None):
        body = {"uploadUrl": upload_url, "title": title, "tags": tags, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/add-instrumental", body)

    # --- Post-processing ---------------------------------------------------
    def separate_stems(self, task_id, audio_id, stem_type="vocal", callback_url=None):
        body = {"taskId": task_id, "audioId": audio_id, "type": stem_type}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/vocal-removal/generate", body)

    def get_stems_status(self, task_id):
        return self._request("GET", f"/api/v1/vocal-removal/record-info?taskId={task_id}")

    def convert_wav(self, task_id, audio_id, callback_url=None):
        body = {"taskId": task_id, "audioId": audio_id}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/wav/generate", body)

    def get_wav_status(self, task_id):
        return self._request("GET", f"/api/v1/wav/record-info?taskId={task_id}")

    def timestamped_lyrics(self, task_id, audio_id):
        return self._post("/api/v1/generate/timestamped-lyrics", {"taskId": task_id, "audioId": audio_id})

    # --- Composition helpers ----------------------------------------------
    def concat(self, task_id, clips):
        return self._post("/api/v1/generate/concat", {"taskId": task_id, "clips": clips})

    def mashup(self, task_ids, model="V4_5", callback_url=None):
        body = {"taskIdList": task_ids, "model": model}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/mashup", body)

    def create_persona(self, task_id, audio_id, name, description, callback_url=None):
        body = {"taskId": task_id, "audioId": audio_id, "name": name, "description": description}
        if callback_url:
            body["callBackUrl"] = callback_url
        return self._post("/api/v1/generate/persona", body)

    def boost_style(self, content):
        return self._post("/api/v1/style/generate", {"content": content})

    # --- Status / Quota ----------------------------------------------------
    def get_status(self, task_id):
        return self._request("GET", f"/api/v1/generate/record-info?taskId={task_id}")

    def get_quota(self):
        return self._request("GET", "/api/v1/generate/credit")
