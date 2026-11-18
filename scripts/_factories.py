"""Load only explicitly selected, trusted application callables."""

import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path


def load_callable(spec: str, path: Path) -> Callable[..., object]:
    module, separator, name = spec.partition(":")
    if not separator or not module or not name:
        raise ValueError("use MODULE:CALLABLE")
    sys.path.insert(0, str(path.resolve()))
    target = getattr(import_module(module), name)
    if not callable(target):
        raise TypeError("the selected attribute is not callable")
    return target
