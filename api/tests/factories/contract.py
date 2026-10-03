"""Late-bound access to P01 interfaces named in docs/build/phases/P01-test-contract.md.

Importing the symbol at call time (not at module import) means a missing implementation module makes
only the tests that need it fail, each with its own ModuleNotFoundError / AttributeError, instead of
one collection error hiding every test in the file.
"""

import importlib
from typing import Any


def load(module: str, name: str | None = None) -> Any:
    """Import `module`; return attribute `name` of it when given."""
    mod = importlib.import_module(module)
    return mod if name is None else getattr(mod, name)
