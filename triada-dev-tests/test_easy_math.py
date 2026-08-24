import pytest
from easy_math import clamp


class TestClamp:
    def test_lower_bound(self):
        assert clamp(0, 5, 10) == 5

    def test_upper_bound(self):
        assert clamp(15, 5, 10) == 10

    def test_within_range(self):
        assert clamp(7, 5, 10) == 7

    def test_invalid_range_raises_error(self):
        with pytest.raises(ValueError, match="lower bound.*cannot be greater than upper bound"):
            clamp(7, 10, 5)
