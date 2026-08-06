"""DuckDuckGo MCP Server package."""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"
__description__ = "MCP server exposing DuckDuckGo search functionality"

from .server import ddg_server

__all__ = ["ddg_server"]
