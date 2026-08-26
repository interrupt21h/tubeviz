from pathlib import Path

from fastapi.testclient import TestClient

from tubeviz.gui import create_gui_app
from tubeviz.library import ClipLibrary
from tubeviz.settings import load_settings, save_settings, settings_path


def test_user_settings_persist_secrets_without_returning_them(monkeypatch, tmp_path: Path):
    path = tmp_path / "home" / "tubeviz.json"
    monkeypatch.setenv("TUBEVIZ_CONFIG", str(path))
    saved = save_settings({"vision_enabled": True, "openai_api_key": "sk-test", "hf_token": "hf-test"})
    assert saved.vision_enabled
    assert load_settings().effective_openai_key() == "sk-test"
    assert settings_path() == path
    assert "sk-test" not in str(saved.public_dict())
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_ai_description_migrates_and_is_available_to_scene_selection(tmp_path: Path):
    library = ClipLibrary(tmp_path / "library")
    library.initialize()
    clip_id = library.upsert_discovery(
        source="youtube", source_id="vision", source_url="https://example/vision",
        term="neon city", rank=1, metadata={"title": "Vision"},
    )
    normalized = library.normalized_dir / "vision.mp4"
    normalized.write_bytes(b"video")
    library.mark_normalized(clip_id, normalized, "sha")
    library.replace_scenes(clip_id, [(0, 3, None), (3, 7, None)])
    library.store_clip_ai_description(
        clip_id,
        {"summary": "rainy neon street", "scenes": [
            {"scene_index": 0, "description": "car in rain", "semantic_tags": ["night"], "drop_fit": .8},
            {"scene_index": 1, "description": "empty tunnel", "semantic_tags": ["tunnel"], "ambient_fit": .9},
        ]},
        provider="openai", model="test", prompt_version="v1", cache_key="cache",
    )
    candidates = library.scene_candidates()
    assert candidates[0].ai_description["description"] == "car in rain"
    assert candidates[0].ai_description["clip_context"]["summary"] == "rainy neon street"
    assert library.load_clip_ai_description(clip_id)["summary"] == "rainy neon street"
    assert library.list_clips()[0]["ai_enhanced"] is True
    assert library.list_clips()[0]["ai_metadata"]["summary"] == "rainy neon street"


def test_gui_exposes_structured_ai_metadata_in_cards_and_clip_viewer():
    root = Path(__file__).parents[1] / "src" / "tubeviz" / "static"
    html = (root / "gui.html").read_text()
    js = (root / "gui.js").read_text()
    assert 'id="clipAiMetadata"' in html
    assert "c.ai_metadata.summary" in js
    assert "Scene descriptions · click to seek" in js
    assert "Raw AI metadata" in js


def test_gui_ai_settings_are_centralized(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TUBEVIZ_CONFIG", str(tmp_path / "config.json"))
    client = TestClient(create_gui_app(default_library=tmp_path / "library", project_root=tmp_path))
    response = client.post("/api/gui/ai-settings", json={
        "ai_enabled": True, "vision_enabled": True, "openai_api_key": "secret",
        "openai_base_url": "https://api.openai.com/v1", "openai_vision_model": "vision-test",
        "vision_detail": "low", "vision_max_frames": 8, "vision_timeout_seconds": 60,
    })
    assert response.status_code == 200
    assert response.json()["openai_key_configured"] is True
    assert "secret" not in response.text
    assert client.get("/api/gui/ai-settings").json()["openai_vision_model"] == "vision-test"
