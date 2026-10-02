"""The check catalogue (docs/checks/catalogue.md)."""

from .base import Check, Context
from .catalogue import BY_TYPE, CATALOGUE

__all__ = ["BY_TYPE", "CATALOGUE", "Check", "Context"]
