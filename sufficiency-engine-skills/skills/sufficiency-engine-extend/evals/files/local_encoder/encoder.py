"""A blocking local sentence encoder: the starting point of eval 3."""

from __future__ import annotations

import math
import time


class LocalEncoder:
    """Stand-in for an on-premises model; `encode` blocks the calling thread."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        time.sleep(0.05)
        vectors: list[list[float]] = []
        for text in texts:
            if not text.strip():
                vectors.append([])
            elif "?" not in text:
                vectors.append([math.nan, 0.0, 1.0])
            else:
                vectors.append([float(len(text)), float(text.count(" ")), 1.0])
        return vectors


if __name__ == "__main__":
    print(LocalEncoder().encode(["Which region?", "", "no question mark"]))
