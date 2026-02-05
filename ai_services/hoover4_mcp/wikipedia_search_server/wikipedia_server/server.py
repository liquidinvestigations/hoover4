"""FastMCP Wikipedia Search Server.

A modern MCP server using FastMCP for Hoover4 Wikipedia search functionality.
This server provides Wikipedia search and summary capabilities without generation,
allowing the using agent to handle the generation part.
"""

import asyncio
import logging
import os
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    import wikipedia
    WIKIPEDIA_AVAILABLE = True
except ImportError:
    wikipedia = None
    WIKIPEDIA_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default configuration from environment variables
DEFAULT_MAX_RESULTS = int(os.getenv("WIKIPEDIA_MAX_RESULTS", "10"))
MAX_ALLOWED_RESULTS = int(os.getenv("WIKIPEDIA_MAX_ALLOWED_RESULTS", "50"))
DEFAULT_SUMMARY_SENTENCES = int(os.getenv("WIKIPEDIA_SUMMARY_SENTENCES", "3"))
MAX_SUMMARY_SENTENCES = int(os.getenv("WIKIPEDIA_MAX_SUMMARY_SENTENCES", "10"))
DEFAULT_LANGUAGE = os.getenv("WIKIPEDIA_LANGUAGE", "en")


# Structured data models for Wikipedia operations
class WikipediaSearchResult(BaseModel):
    """Individual Wikipedia search result."""
    
    title: str = Field(description="Wikipedia article title")
    url: str = Field(description="Direct URL to Wikipedia article")


class WikipediaSearchResponse(BaseModel):
    """Response structure for Wikipedia search query."""
    
    success: bool = Field(description="Whether the search was successful")
    query: str = Field(description="The original search query")
    results: List[WikipediaSearchResult] = Field(description="List of search results")
    result_count: int = Field(description="Number of results returned")
    language: str = Field(description="Wikipedia language code used")
    error: Optional[str] = Field(default=None, description="Error message if search failed")


class WikipediaSummaryResponse(BaseModel):
    """Response structure for Wikipedia summary query."""
    
    success: bool = Field(description="Whether the summary retrieval was successful")
    query: str = Field(description="The original query")
    title: str = Field(description="Actual Wikipedia article title")
    summary: str = Field(description="Article summary text")
    url: str = Field(description="Direct URL to Wikipedia article")
    language: str = Field(description="Wikipedia language code used")
    sentences: int = Field(description="Number of sentences in summary")
    error: Optional[str] = Field(default=None, description="Error message if summary failed")


# Create FastMCP instance
wikipedia_server = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_wikipedia_search"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", "Wikipedia article and summary search."),
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8083")),
)


# Health check endpoint for monitoring
@wikipedia_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Basic health check endpoint."""
    return JSONResponse({"status": "ok", "service": "hoover4-wikipedia-search"})


# Helper functions to validate parameters
def validate_search_params(query: str):
    """Validate search parameters and return error message if invalid."""
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    
    return None


def validate_summary_params(query: str):
    """Validate summary parameters and return error message if invalid."""
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    
    return None


@wikipedia_server.tool(
    name="wikipedia_search",
    description="""Search Wikipedia for articles related to a query. Returns a list of relevant article titles with URLs.

Args:
    query: str
        The search query to find relevant Wikipedia articles
""",
    structured_output=True,
)
async def wikipedia_search(
    query: str
) -> WikipediaSearchResponse:
    """Search Wikipedia for articles related to a query.
    
    Args:
        query: The search query to find relevant Wikipedia articles
    """
    # Get configuration from environment variables
    max_results = DEFAULT_MAX_RESULTS
    language = DEFAULT_LANGUAGE
    
    # Validate parameters
    error = validate_search_params(query)
    if error:
        return WikipediaSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            language=language,
            error=error
        )
    
    if not WIKIPEDIA_AVAILABLE:
        return WikipediaSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            language=language,
            error="Wikipedia library not available. Install with: pip install wikipedia"
        )
    
    try:
        logger.info(f"Searching Wikipedia for: {query}")
        
        # Set language
        wikipedia.set_lang(language)
        
        # Run search in executor to avoid blocking
        loop = asyncio.get_event_loop()
        
        def perform_search():
            return wikipedia.search(query, results=max_results)
        
        search_results = await loop.run_in_executor(None, perform_search)
        
        # Format results
        formatted_results = []
        for title in search_results:
            formatted_results.append(WikipediaSearchResult(
                title=title,
                url=f"https://{language}.wikipedia.org/wiki/{title.replace(' ', '_')}"
            ))
        
        return WikipediaSearchResponse(
            success=True,
            query=query,
            results=formatted_results,
            result_count=len(formatted_results),
            language=language
        )
        
    except Exception as e:
        logger.error(f"Wikipedia search failed: {e}")
        return WikipediaSearchResponse(
            success=False,
            query=query,
            results=[],
            result_count=0,
            language=language,
            error=str(e)
        )


@wikipedia_server.tool(
    name="wikipedia_summary",
    description="""Get a summary of a Wikipedia article. Retrieves a concise summary.

Args:
    query: str
        Page title or search query for the Wikipedia article
""",
    structured_output=True,
)
async def wikipedia_summary(
    query: str
) -> WikipediaSummaryResponse:
    """Get a summary of a Wikipedia article.
    
    Args:
        query: Page title or search query for the Wikipedia article
    """
    # Get configuration from environment variables
    sentences = DEFAULT_SUMMARY_SENTENCES
    language = DEFAULT_LANGUAGE
    
    # Validate parameters
    error = validate_summary_params(query)
    if error:
        return WikipediaSummaryResponse(
            success=False,
            query=query,
            title="",
            summary="",
            url="",
            language=language,
            sentences=sentences,
            error=error
        )
    
    if not WIKIPEDIA_AVAILABLE:
        return WikipediaSummaryResponse(
            success=False,
            query=query,
            title="",
            summary="",
            url="",
            language=language,
            sentences=sentences,
            error="Wikipedia library not available. Install with: pip install wikipedia"
        )
    
    try:
        logger.info(f"Getting Wikipedia summary for: {query}")
        
        # Set language
        wikipedia.set_lang(language)
        
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        
        def get_summary():
            try:
                # Try direct summary first
                summary = wikipedia.summary(query, sentences=sentences)
                page = wikipedia.page(query)
                return summary, page.title, page.url
            except wikipedia.DisambiguationError as e:
                # If disambiguation, try the first option
                if e.options:
                    summary = wikipedia.summary(e.options[0], sentences=sentences)
                    page = wikipedia.page(e.options[0])
                    return summary, page.title, page.url
                raise
            except wikipedia.PageError:
                # Try searching first
                search_results = wikipedia.search(query, results=1)
                if search_results:
                    summary = wikipedia.summary(search_results[0], sentences=sentences)
                    page = wikipedia.page(search_results[0])
                    return summary, page.title, page.url
                raise
        
        summary, title, url = await loop.run_in_executor(None, get_summary)
        
        return WikipediaSummaryResponse(
            success=True,
            query=query,
            title=title,
            summary=summary,
            url=url,
            language=language,
            sentences=sentences
        )
        
    except Exception as e:
        logger.error(f"Wikipedia summary failed for {query}: {e}")
        return WikipediaSummaryResponse(
            success=False,
            query=query,
            title="",
            summary="",
            url="",
            language=language,
            sentences=sentences,
            error=str(e)
        )


def main():
    """Main function to start the Hoover4 Wikipedia Search MCP Server."""
    if not WIKIPEDIA_AVAILABLE:
        logger.warning("Wikipedia library not available. Install with: pip install wikipedia")
    
    logger.info("Starting Hoover4 Wikipedia Search MCP Server...")
    wikipedia_server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
