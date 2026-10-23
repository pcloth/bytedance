# -*- coding: utf-8 -*-
"""ByteDance / Douyin mini-app server SDK."""
__version__ = "1.0.0"

from .base import ByteDanceError, Map
from .client import ByteDance

__all__ = ("ByteDance", "ByteDanceError", "Map", "__version__")
