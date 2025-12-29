"""
MIRS Routes Package
"""

from .anesthesia import router as anesthesia_router, init_anesthesia_schema

__all__ = ['anesthesia_router', 'init_anesthesia_schema']
