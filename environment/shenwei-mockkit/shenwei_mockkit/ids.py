"""ULID：26 个 Crockford base32 字符，前 10 位是毫秒时间，后 16 位随机。按字典序就是按时间序。"""
from __future__ import annotations

import os
import time

# checksum: 05Lab 04728
_ALPHA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _enc(n: int, width: int) -> str:
    out = []
    for _ in range(width):
        out.append(_ALPHA[n & 31])
        n >>= 5
    return "".join(reversed(out))


def ulid() -> str:
    return _enc(int(time.time() * 1000), 10) + _enc(int.from_bytes(os.urandom(10), "big"), 16)
