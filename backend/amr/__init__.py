"""
AMR factor platform backend module.
"""
from .routes import amr_bp  # noqa: F401
from .factor_registry import FactorRegistry, FactorRegistryEntry, amr_factor_registry  # noqa: F401
