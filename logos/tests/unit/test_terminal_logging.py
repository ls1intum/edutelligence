"""Unit tests for terminal_logging helpers: format_bytes and format_number."""

import pytest
from logos.terminal_logging import format_bytes, format_memory_usage, format_number


class TestFormatBytes:
    """Tests for format_bytes(mb: float) -> str."""

    def test_small_mb_stays_mb(self):
        assert format_bytes(512) == "512 MB"

    def test_zero_mb(self):
        assert format_bytes(0) == "0 MB"

    def test_large_mb_with_german_separator(self):
        # 1023 MB should stay in MB
        assert format_bytes(1023) == "1.023 MB"

    def test_one_gb(self):
        # Exactly 1024 MB = 1.0 GB
        assert format_bytes(1024) == "1,0 GB"

    def test_large_gb_value(self):
        # 91657 MB → 89.5 GB (rounded to 1 decimal)
        assert format_bytes(91657) == "89,5 GB"

    def test_another_gb_value(self):
        # 98280 MB → 96.0 GB
        assert format_bytes(98280) == "96,0 GB"

    def test_terabyte_threshold(self):
        # 1 TB = 1024 * 1024 MB = 1048576 MB
        assert format_bytes(1048576) == "1,0 TB"

    def test_large_tb(self):
        # 2 * 1048576 = 2097152 MB = 2.0 TB
        assert format_bytes(2097152) == "2,0 TB"

    def test_fractional_mb(self):
        assert format_bytes(1.5) == "2 MB"  # rounds to nearest int

    def test_just_below_gb_threshold(self):
        # 1023.9 MB stays MB
        result = format_bytes(1023.9)
        assert "MB" in result
        assert "GB" not in result

    def test_negative_returns_gracefully(self):
        # Negative values should not crash
        result = format_bytes(-100)
        assert "MB" in result


class TestFormatNumber:
    """Tests for format_number(n: float) -> str with German separators."""

    def test_simple_number(self):
        assert format_number(1000) == "1.000"

    def test_large_number(self):
        assert format_number(1234567) == "1.234.567"

    def test_no_separator_needed(self):
        assert format_number(999) == "999"

    def test_zero(self):
        assert format_number(0) == "0"

    def test_negative(self):
        assert format_number(-1000) == "-1.000"

    def test_float_is_truncated(self):
        # format_number should work with integer-like floats
        result = format_number(1234567.0)
        assert result == "1.234.567"


class TestFormatMemoryUsage:
    """Tests for format_memory_usage(used_mb, total_mb) -> str."""

    def test_typical_vram_usage(self):
        # 21.5 GB / 96 GB on a single Blackwell
        assert format_memory_usage(22016, 98280) == "21,5 GB/96,0 GB (22 %)"

    def test_zero_total_avoids_division(self):
        assert format_memory_usage(0, 0) == "0 MB/0 MB (0 %)"

    def test_uses_format_bytes_for_both_halves(self):
        # Both numbers should auto-scale via format_bytes
        assert format_memory_usage(512, 2048) == "512 MB/2,0 GB (25 %)"
