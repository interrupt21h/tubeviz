# SPDX-License-Identifier: Apache-2.0
"""Persistent, user-scoped Tubeviz settings.

Secrets live in one mode-0600 JSON file rather than project files or shell
history. Environment variables remain supported when a saved value is empty.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def settings_path() -> Path:
    override = os.environ.get("TUBEVIZ_CONFIG")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tubeviz" / "config.json"


@dataclass(frozen=True)
class UserSettings:
    ai_enabled: bool = True
    vision_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.1"
    vision_detail: str = "low"
    vision_max_frames: int = 12
    vision_timeout_seconds: int = 180
    hf_token: str = ""

    def effective_openai_key(self) -> str:
        return (self.openai_api_key or os.environ.get("OPENAI_API_KEY", "")).strip()

    def effective_hf_token(self) -> str:
        return self.hf_token or os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGING_FACE_HUB_TOKEN", "")

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("openai_api_key")
        value.pop("hf_token")
        value.update(
            openai_key_configured=bool(self.effective_openai_key()),
            hf_token_configured=bool(self.effective_hf_token()),
            config_path=str(settings_path()),
        )
        return value


def load_settings() -> UserSettings:
    path = settings_path()
    if not path.is_file():
        return UserSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # v0.31/v0.32 stored the shared OpenAI model under the more narrow
        # ``openai_vision_model`` name. Migrate it transparently so existing
        # user configuration remains authoritative after the setting becomes
        # the common model for vision, acquisition planning, and AI directing.
        if "openai_model" not in raw and raw.get("openai_vision_model"):
            raw["openai_model"] = raw["openai_vision_model"]
        allowed = {field.name for field in fields(UserSettings)}
        return UserSettings(**{key: value for key, value in raw.items() if key in allowed})
    except (OSError, ValueError, TypeError):
        return UserSettings()


def is_openai_api_url(base_url: str | None) -> bool:
    """Return True only for the first-party OpenAI API host.

    This guard is intentionally strict so a saved OpenAI credential is never
    forwarded automatically to an arbitrary OpenAI-compatible endpoint.
    """
    if not base_url:
        return False
    try:
        return (urlsplit(base_url).hostname or "").lower() == "api.openai.com"
    except ValueError:
        return False


def resolve_llm_api_key(
    base_url: str | None,
    explicit: str | None = None,
    *,
    settings: UserSettings | None = None,
) -> str:
    """Resolve credentials for OpenAI-compatible LLM requests safely.

    Precedence is: explicit call-site key, TUBEVIZ_LLM_API_KEY, then the
    persistent/user OPENAI_API_KEY only when the destination is api.openai.com.
    That makes the AI Settings key available everywhere Tubeviz talks to OpenAI
    without leaking it to local or third-party compatible endpoints.
    """
    explicit_value = (explicit or "").strip()
    if explicit_value:
        return explicit_value
    llm_value = os.environ.get("TUBEVIZ_LLM_API_KEY", "").strip()
    if llm_value:
        return llm_value
    if is_openai_api_url(base_url):
        return (settings or load_settings()).effective_openai_key()
    return ""


def save_settings(changes: dict[str, Any], *, clear_openai: bool = False, clear_hf: bool = False) -> UserSettings:
    # Accept the legacy API/GUI field during upgrades, but persist only the new
    # shared model setting.
    changes = dict(changes)
    if "openai_model" not in changes and changes.get("openai_vision_model"):
        changes["openai_model"] = changes["openai_vision_model"]
    current = asdict(load_settings())
    allowed = set(current)
    for key, value in changes.items():
        if key not in allowed or value is None:
            continue
        # Blank secret fields mean "keep saved value", which makes the GUI safe
        # to reload without ever returning credentials to the browser.
        if key in {"openai_api_key", "hf_token"} and not str(value).strip():
            continue
        current[key] = value
    if clear_openai:
        current["openai_api_key"] = ""
    if clear_hf:
        current["hf_token"] = ""
    result = UserSettings(**current)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    return result
