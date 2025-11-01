"""Basic tests to verify the test infrastructure is working."""

import pytest
from ha_boss import __version__


def test_version() -> None:
    """Test that version is defined."""
    assert __version__ == "0.1.0"


def test_basic_math() -> None:
    """Basic sanity test."""
    assert 1 + 1 == 2


@pytest.mark.asyncio
async def test_async_support() -> None:
    """Test that async tests work."""
    async def async_func() -> str:
        return "async works"

    result = await async_func()
    assert result == "async works"
