"""Tests for fetcher/service.py — VIP matching and skip logic."""
from __future__ import annotations

from common.config import AppConfig
from fetcher.service import _sender_is_vip, _should_skip


class TestSenderIsVip:
    def test_sender_is_vip_wildcard(self):
        patterns = ["boss@company.com", "*@important-client.com"]
        assert _sender_is_vip("boss@company.com", patterns) is True
        assert _sender_is_vip("anyone@important-client.com", patterns) is True
        assert _sender_is_vip("stranger@other.com", patterns) is False
        # Case insensitive
        assert _sender_is_vip("BOSS@COMPANY.COM", patterns) is True


class TestShouldSkip:
    def test_should_skip_promo_label(self, sample_config):
        message = {
            "label_ids": ["CATEGORY_PROMOTIONS", "INBOX"],
            "headers": {},
        }
        assert _should_skip(message, sample_config) is True

    def test_should_skip_list_unsubscribe(self, sample_config):
        message = {
            "label_ids": ["INBOX"],
            "headers": {"list-unsubscribe": "<mailto:unsub@example.com>"},
        }
        assert _should_skip(message, sample_config) is True

        # No unsubscribe header, no skip labels → should NOT skip
        clean_message = {
            "label_ids": ["INBOX"],
            "headers": {},
        }
        assert _should_skip(clean_message, sample_config) is False
