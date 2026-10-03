"""Test package. The runtime requires an explicit QL_ENV (P01 contract, item 7), so the suite sets it before any
test module imports application settings. `local` is what the suite has always assumed (docs, demo seed)."""

import os

os.environ.setdefault("QL_ENV", "local")
