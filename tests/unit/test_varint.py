import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from img2schem.util.varint import decode_varints, encode_varints


@pytest.mark.parametrize(
    ("value", "encoded"),
    [(0, b"\x00"), (127, b"\x7f"), (128, b"\x80\x01"), (300, b"\xac\x02"), (2**31 - 1, b"\xff\xff\xff\xff\x07")],
)
def test_known_encodings(value, encoded):
    assert encode_varints(np.array([value])) == encoded
    assert decode_varints(encoded, 1).tolist() == [value]


@given(st.lists(st.integers(min_value=0, max_value=2**31 - 1), max_size=300))
def test_roundtrip(values):
    arr = np.array(values, dtype=np.int64)
    assert decode_varints(encode_varints(arr), len(values)).tolist() == values


def test_truncated_and_trailing_data_rejected():
    with pytest.raises(ValueError, match="truncated"):
        decode_varints(b"\x80", 1)
    with pytest.raises(ValueError, match="trailing"):
        decode_varints(b"\x01\x02", 1)


def test_negative_rejected():
    with pytest.raises(ValueError):
        encode_varints(np.array([-1]))
