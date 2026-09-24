"""Deterministic core: GRM, GBLUP (frozen champion), plan simulator. No LLM anywhere in here."""
from .champion import ChampionConfig, freeze_champion  # noqa: F401
from .evaluate import Evaluator, FitStats  # noqa: F401
