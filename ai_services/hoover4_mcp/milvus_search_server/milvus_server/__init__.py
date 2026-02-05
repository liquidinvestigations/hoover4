"""Hoover4 MCP RAG Server Module.

This module provides a Model Context Protocol (MCP) server that exposes
the Hoover4 RAG functionality for use with MCP-compatible clients.
"""

from .server import milvus_server

__all__ = [
    "milvus_server",
]

__version__ = "0.1.0"
