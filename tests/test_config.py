from __future__ import annotations

import os
from pathlib import Path

import pytest

from common.config import AppConfig, _to_list, load_config


class TestToList:
    def test_none_returns_fallback(self):
        assert _to_list(None, ["a"]) == ["a"]

    def test_string_returns_single_element_list(self):
        assert _to_list("hello", []) == ["hello"]

    def test_list_returns_stringified(self):
        assert _to_list([1, 2, "three"], []) == ["1", "2", "three"]

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Expected list or string"):
            _to_list(123, [])


class TestAppConfigDefaults:
    def test_frozen(self):
        cfg = AppConfig()
        with pytest.raises(AttributeError):
            cfg.ollama_model = "other"  # type: ignore[misc]

    def test_default_skip_labels(self):
        cfg = AppConfig()
        assert "CATEGORY_PROMOTIONS" in cfg.skip_labels

    def test_default_priority_keywords(self):
        cfg = AppConfig()
        assert "urgent" in cfg.priority_keywords


class TestLoadConfig:
    def test_loads_valid_file(self, config_file: str):
        cfg = load_config(config_file)
        assert cfg.ollama_model == "test-model"
        assert cfg.gmail_max_results == 10
        assert cfg.summarizer_batch_size == 5
        assert cfg.telegram_chat_id == "12345"
        assert cfg.vip_senders == ["boss@company.com", "*@important.com"]

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_validation_gmail_max_results_zero(self, tmp_path: Path):
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("gmail_max_results: 0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="gmail_max_results"):
            load_config(str(cfg))

    def test_validation_summarizer_interval_zero(self, tmp_path: Path):
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("summarizer_interval_minutes: 0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="summarizer_interval_minutes"):
            load_config(str(cfg))

    def test_validation_ollama_timeout_zero(self, tmp_path: Path):
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("ollama_timeout_seconds: 0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="ollama_timeout_seconds"):
            load_config(str(cfg))

    def test_defaults_applied_for_empty_yaml(self, tmp_path: Path):
        cfg = tmp_path / "empty.yaml"
        cfg.write_text("{}\n", encoding="utf-8")
        result = load_config(str(cfg))
        assert result.ollama_model == AppConfig().ollama_model
        assert result.gmail_max_results == AppConfig().gmail_max_results

    def test_config_path_env_var(self, config_file: str, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CONFIG_PATH", config_file)
        cfg = load_config()
        assert cfg.ollama_model == "test-model"

    def test_timezone_defaults_to_valid(self, config_file: str):
        cfg = load_config(config_file)
        assert cfg.timezone  # non-empty
