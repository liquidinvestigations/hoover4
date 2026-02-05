"""Hoover4 RAG Package."""

__version__ = "0.2.0"

# Import main classes for easy access
from .text_content_iterator import TextContentIterator, TextContentEntry

__all__ = [
    "TextContentIterator",
    "TextContentEntry",
]
