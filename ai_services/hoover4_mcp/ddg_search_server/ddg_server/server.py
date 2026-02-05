"""FastMCP DuckDuckGo Search Server.

A modern MCP server using FastMCP for DuckDuckGo search functionality.
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from ddgs import DDGS
from starlette.requests import Request
from starlette.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default search configuration from environment variables
DEFAULT_REGION = os.getenv("DDG_DEFAULT_REGION", "wt-wt")  # Worldwide
DEFAULT_MAX_RESULTS = int(os.getenv("DDG_DEFAULT_MAX_RESULTS", "10"))
DEFAULT_SAFESEARCH = os.getenv("DDG_DEFAULT_SAFESEARCH", "off")  # No safe search
DEFAULT_TIMELIMIT = os.getenv("DDG_DEFAULT_TIMELIMIT")  # None by default
MAX_ALLOWED_RESULTS = int(os.getenv("DDG_MAX_ALLOWED_RESULTS", "50"))  # Maximum results limit
DEFAULT_TIMEOUT = int(os.getenv("DDG_DEFAULT_TIMEOUT", "30"))  # Default timeout for requests


# Structured data models for search results
class SearchMetadata(BaseModel):
    """Metadata for search operations."""
    
    region: str = Field(description="Search region used")
    safesearch: str = Field(description="Safe search setting")
    timelimit: Optional[str] = Field(default=None, description="Time limit for search")


class SearchResult(BaseModel):
    """Individual search result."""
    
    title: str = Field(description="Title of the search result")
    url: str = Field(description="URL of the search result")
    snippet: str = Field(description="Text snippet from the result")
    date: Optional[str] = Field(default=None, description="Date of the result if available")


class NewsResult(BaseModel):
    """Individual news search result."""
    
    title: str = Field(description="Title of the news article")
    url: str = Field(description="URL of the news article")
    snippet: str = Field(description="Text snippet from the article")
    date: Optional[str] = Field(default=None, description="Publication date")
    source: Optional[str] = Field(default=None, description="News source")


class TextSearchResponse(BaseModel):
    """Response structure for text search."""
    
    success: bool = Field(description="Whether the search was successful")
    query: str = Field(description="The search query that was executed")
    results: List[SearchResult] = Field(description="List of search results")
    result_count: int = Field(description="Number of results returned")
    metadata: SearchMetadata = Field(description="Search metadata")
    error: Optional[str] = Field(default=None, description="Error message if search failed")


class NewsSearchResponse(BaseModel):
    """Response structure for news search."""
    
    success: bool = Field(description="Whether the search was successful")
    query: str = Field(description="The search query that was executed")
    results: List[NewsResult] = Field(description="List of news results")
    result_count: int = Field(description="Number of results returned")
    metadata: SearchMetadata = Field(description="Search metadata")
    error: Optional[str] = Field(default=None, description="Error message if search failed")

# Create FastMCP instance
ddg_server = FastMCP(
    name=os.getenv("SERVER_NAME", "ddgs"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", "Web search and news search capabilities using DuckDuckGo."),
    host = os.getenv("HOST", "0.0.0.0"),
    port = int(os.getenv("PORT", "8080")),
)


# Health check endpoint for monitoring
@ddg_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Basic health check endpoint."""
    return JSONResponse({"status": "ok", "service": "ddg-search"})


# Helper function to validate search parameters
def validate_search_params(query: str, max_results: int = DEFAULT_MAX_RESULTS, region: str = DEFAULT_REGION, 
                          safesearch: str = DEFAULT_SAFESEARCH, timelimit: Optional[str] = None):
    """Validate search parameters and return error message if invalid."""
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    
    if max_results <= 0 or max_results > MAX_ALLOWED_RESULTS:
        return f"Error: max_results must be between 1 and {MAX_ALLOWED_RESULTS}"
    
    if safesearch not in ["strict", "moderate", "off"]:
        return "Error: safesearch must be 'strict', 'moderate', or 'off'"
    
    if timelimit and timelimit not in ["d", "w", "m", "y"]:
        return "Error: timelimit must be 'd', 'w', 'm', or 'y'"
    
    return None


# Configuration from environment
@asynccontextmanager
async def get_ddgs_client():
    """Get configured DDGS client with proxy settings."""
    proxy = None
    if os.getenv("PROXY_URL"):
        proxy = os.getenv("PROXY_URL")
    
    timeout = DEFAULT_TIMEOUT
    
    ddgs = DDGS(proxy=proxy, timeout=timeout)
    try:
        yield ddgs
    finally:
        # DDGS doesn't need explicit cleanup
        pass


@ddg_server.tool(
    name="ddg_text_search",
    description="""Search the web using DuckDuckGo. Returns titles, URLs, and snippets for web pages.

Args:
    query: str
        The search query
    timelimit: str (optional)
        Time limit for search, timelimit must be 'd', 'w', 'm', or 'y'
""",
    structured_output=True,
)
async def ddg_text_search(query: str, max_results: int = DEFAULT_MAX_RESULTS, region: str = DEFAULT_REGION, 
                         safesearch: str = DEFAULT_SAFESEARCH, timelimit: str = DEFAULT_TIMELIMIT) -> TextSearchResponse:
    """Search the web using DuckDuckGo.
    
    Args:
        query: The search query
        timelimit: Time limit for search, timelimit must be 'd', 'w', 'm', or 'y'
    """
    
    # Create metadata object
    metadata = SearchMetadata(
        region=region,
        safesearch=safesearch,
        timelimit=timelimit
    )
    
    # Validate parameters
    error = validate_search_params(query, max_results, region, safesearch, timelimit)
    if error:
        return TextSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            metadata=metadata,
            error=error
        )
    
    try:
        logger.info(f"Performing text search for: {query}")
        
        async with get_ddgs_client() as ddgs:
            # Perform search
            results = list(ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=max_results
            ))
        
        # Format results
        search_results = []
        for result in results:
            search_results.append(SearchResult(
                title=result.get("title", ""),
                url=result.get("href", ""),
                snippet=result.get("body", ""),
                date=result.get("date")
            ))
        
        return TextSearchResponse(
            success=True,
            query=query,
            results=search_results,
            result_count=len(search_results),
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Text search failed: {e}")
        return TextSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            metadata=metadata,
            error=str(e)
        )


@ddg_server.tool(
    name="ddg_news_search",
    description="""Search for news using DuckDuckGo. Returns recent news articles with titles, sources, dates, and URLs.

Args:
    query: str
        The news search query
    timelimit: str (optional)
        Time limit for search, timelimit must be 'd', 'w', 'm', or 'y'
""",
    structured_output=True,
)
async def ddg_news_search(query: str, max_results: int = DEFAULT_MAX_RESULTS, region: str = DEFAULT_REGION, 
                         safesearch: str = DEFAULT_SAFESEARCH, timelimit: str = DEFAULT_TIMELIMIT) -> NewsSearchResponse:
    """Search for news using DuckDuckGo.
    
    Args:
        query: The news search query
        timelimit: Time limit for search, timelimit must be 'd', 'w', 'm', or 'y'
    """
    
    # Create metadata object
    metadata = SearchMetadata(
        region=region,
        safesearch=safesearch,
        timelimit=timelimit
    )
    
    # Validate parameters
    error = validate_search_params(query, max_results, region, safesearch, timelimit)
    if error:
        return NewsSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            metadata=metadata,
            error=error
        )
    
    try:
        logger.info(f"Performing news search for: {query}")
        
        async with get_ddgs_client() as ddgs:
            # Perform news search
            results = list(ddgs.news(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=max_results
            ))
        
        # Format results
        news_results = []
        for result in results:
            news_results.append(NewsResult(
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("body", ""),
                date=result.get("date"),
                source=result.get("source")
            ))
        
        return NewsSearchResponse(
            success=True,
            query=query,
            results=news_results,
            result_count=len(news_results),
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"News search failed: {e}")
        return NewsSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            metadata=metadata,
            error=str(e)
        )


def main():
    """Main function to start the DuckDuckGo Search MCP Server."""
    logger.info("Starting DuckDuckGo Search MCP Server...")
    ddg_server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
