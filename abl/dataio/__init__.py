"""Loaders for public datasets (OPS.md C.1). Every loader calls common.paths.assert_not_holdout."""
from .catalog import CATALOG, available_locally  # noqa: F401
from .loaders import load_pig_cleveland, load_wheat_bglr  # noqa: F401
