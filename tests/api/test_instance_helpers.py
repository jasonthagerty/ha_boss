"""Tests for instance helper functions."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from ha_boss.api.utils.instance_helpers import get_instance_ids, is_aggregate_mode


class TestGetInstanceIds:
    """Tests for get_instance_ids function."""

    def test_get_instance_ids_all_returns_all_instances(self) -> None:
        """Test that 'all' returns all configured instances."""
        service = MagicMock()
        service.ha_clients = {
            "instance1": MagicMock(),
            "instance2": MagicMock(),
            "instance3": MagicMock(),
        }

        result = get_instance_ids(service, "all")

        assert result == ["instance1", "instance2", "instance3"]

    def test_get_instance_ids_specific_instance_returns_list(self) -> None:
        """Test that a specific instance ID returns a single-item list."""
        service = MagicMock()
        service.ha_clients = {
            "instance1": MagicMock(),
            "instance2": MagicMock(),
        }

        result = get_instance_ids(service, "instance1")

        assert result == ["instance1"]

    def test_get_instance_ids_invalid_instance_raises_404(self) -> None:
        """Test that an invalid instance ID raises HTTPException 404."""
        service = MagicMock()
        service.ha_clients = {
            "instance1": MagicMock(),
            "instance2": MagicMock(),
        }

        with pytest.raises(HTTPException) as exc_info:
            get_instance_ids(service, "nonexistent")

        assert exc_info.value.status_code == 404
        assert "nonexistent" in str(exc_info.value.detail)
        assert "instance1" in str(exc_info.value.detail)
        assert "instance2" in str(exc_info.value.detail)

    def test_get_instance_ids_empty_clients_returns_empty_for_all(self) -> None:
        """Test that 'all' with no configured instances returns empty list."""
        service = MagicMock()
        service.ha_clients = {}

        result = get_instance_ids(service, "all")

        assert result == []

    def test_get_instance_ids_preserves_order(self) -> None:
        """Test that instance order is preserved (based on dict key order)."""
        service = MagicMock()
        # Python 3.7+ preserves dict insertion order
        service.ha_clients = {
            "alpha": MagicMock(),
            "beta": MagicMock(),
            "gamma": MagicMock(),
        }

        result = get_instance_ids(service, "all")

        assert result == ["alpha", "beta", "gamma"]


class TestIsAggregateMode:
    """Tests for is_aggregate_mode function."""

    def test_is_aggregate_mode_returns_true_for_all(self) -> None:
        """Test that 'all' returns True."""
        assert is_aggregate_mode("all") is True

    def test_is_aggregate_mode_returns_false_for_specific_instance(self) -> None:
        """Test that a specific instance returns False."""
        assert is_aggregate_mode("default") is False
        assert is_aggregate_mode("instance1") is False
        assert is_aggregate_mode("my_home") is False

    def test_is_aggregate_mode_case_sensitive(self) -> None:
        """Test that the check is case-sensitive."""
        assert is_aggregate_mode("ALL") is False
        assert is_aggregate_mode("All") is False
        assert is_aggregate_mode("aLl") is False
