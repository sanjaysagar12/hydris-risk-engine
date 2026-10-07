import math

import pytest

from hydris_risk.data.nodata import clean, is_nodata


@pytest.mark.parametrize("value,label", [
    (float("nan"), None), (None, None), (-9999, None), (-9999.0, "No Data"), (9999, None), (9000, None),
    (12345, None), (1.0, "No Data"), (1.0, "No data"), (1.0, "  no DATA "), ("abc", None),
])
def test_missing(value, label):
    assert is_nodata(value, label)


@pytest.mark.parametrize("value,label", [
    (0, None), (0.0, "Low (<10%)"), (-2.63896, None),  # gtd raw can be negative
    (-1, None),  # category -1 is a real category
    (1.0, "Arid and Low Water Use"),  # arid placeholder raw 1.0 with cat -1 is valid data
    (8999.9, None), (0.209484, "Medium - High (20-40%)"),
])
def test_valid(value, label):
    assert not is_nodata(value, label)


def test_clean():
    assert clean(-9999) is None and clean(0.0) == 0.0 and not math.isnan(clean(1.5))
