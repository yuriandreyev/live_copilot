from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bootstrap.main import create_app

REQUIRED_SETTINGS = {
    "ASR_BACKEND": "fake",
    "POSTGRES_DB": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test-only",
    "RABBITMQ_DEFAULT_USER": "test",
    "RABBITMQ_DEFAULT_PASS": "test-only",
}


@pytest.fixture
def configured_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    for name, value in REQUIRED_SETTINGS.items():
        monkeypatch.setenv(name, value)


def test_healthz_is_available_without_running_services(
    configured_environment: None,
) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_serves_browser_capture_assets(configured_environment: None) -> None:
    with TestClient(create_app()) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert 'src="/app.js"' in index.text
        for path in ("/app.js", "/audio-worklet.js", "/style.css"):
            assert client.get(path).status_code == 200


def test_app_startup_reports_missing_model(
    configured_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASR_BACKEND", "faster-whisper")
    monkeypatch.setenv("ASR_MODEL_PATH", "missing-model")
    with pytest.raises(FileNotFoundError, match="ASR model directory does not exist"):
        with TestClient(create_app()):
            pass


@pytest.mark.parametrize("value", [None, ""])
def test_app_creation_fails_without_postgres_password(
    configured_environment: None, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("POSTGRES_PASSWORD")
    else:
        monkeypatch.setenv("POSTGRES_PASSWORD", value)

    with pytest.raises(ValidationError, match="postgres_password"):
        create_app()
