"""Tests for common/config.py — loading, validation, helpers."""
from __future__ import annotations

import pytest

from common.config import AppConfig, _to_list, load_config


class TestLoadConfig:
    def test_load_config_from_file(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "vip_senders:\n"
            "  - boss@test.com\n"
            "gmail_max_results: 50\n"
            "summarizer_batch_size: 10\n"
            "ollama_timeout_seconds: 60\n"
            "ollama_num_ctx: 4096\n"
            "prompt_body_max_chars: 3000\n"
        )
        config = load_config(str(config_file))
        assert config.vip_senders == ["boss@test.com"]
        assert config.gmail_max_results == 50

    def test_load_config_validation_rejects_zero(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("gmail_max_results: 0\n")
        with pytest.raises(ValueError, match="must be > 0"):
            load_config(str(config_file))


class TestToList:
    def test_to_list_coercion(self):
        assert _to_list(None, ["default"]) == ["default"]
        assert _to_list("single", []) == ["single"]
        assert _to_list(["a", "b"], []) == ["a", "b"]
        with pytest.raises(ValueError):
            _to_list(123, [])
