"""FastMCP Milvus Search Server.

A modern MCP server using FastMCP for Hoover4 Milvus search functionality.
This server provides document search capabilities without generation,
allowing the using agent to handle the generation part.
"""

import asyncio
import logging
import os
from typing import Dict, Any, Optional, List
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default configuration from environment variables
DEFAULT_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "10"))
DEFAULT_SEARCH_MODE = os.getenv("SEARCH_MODE", "hybrid")
MAX_ALLOWED_RESULTS = int(os.getenv("SEARCH_MAX_ALLOWED_RESULTS", "100"))
DEFAULT_INITIAL_RETRIEVAL_K = int(os.getenv("SEARCH_INITIAL_K", "120"))

# Global Milvus retriever instance
milvus_retriever = None


# Structured data models for search operations
class SearchMetadata(BaseModel):
    """Metadata for search operations."""
    
    search_mode: str = Field(description="Search mode used (hybrid, semantic)")
    retrieval_count: int = Field(description="Number of documents retrieved")
    reranked: bool = Field(description="Whether results were reranked")


class SearchResult(BaseModel):
    """Individual search result document."""
    
    id: str = Field(description="Document ID")
    content: str = Field(description="Document content")
    score: Optional[float] = Field(default=None, description="Relevance score")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Document metadata")


class SearchResponse(BaseModel):
    """Response structure for search query."""
    
    success: bool = Field(description="Whether the search was successful")
    query: str = Field(description="The original search query")
    results: List[SearchResult] = Field(description="List of search results")
    metadata: SearchMetadata = Field(description="Search metadata")
    error: Optional[str] = Field(default=None, description="Error message if search failed")


# Create FastMCP instance
milvus_server = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_milvus_search"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", "Advanced document search over internal data not available to the public."),
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8082")),
)


# Health check endpoint for monitoring
@milvus_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Basic health check endpoint."""
    return JSONResponse({"status": "ok", "service": "hoover4-milvus-search"})


# Helper function to validate search parameters
def validate_search_params(query: str, max_results: int = DEFAULT_MAX_RESULTS):
    """Validate search parameters and return error message if invalid."""
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    
    if max_results <= 0 or max_results > MAX_ALLOWED_RESULTS:
        return f"Error: max_results must be between 1 and {MAX_ALLOWED_RESULTS}"
    
    return None


# Configuration from environment
@asynccontextmanager
async def get_milvus_retriever():
    """Get configured Milvus retriever with proper resource management."""
    global milvus_retriever
    
    if milvus_retriever is None:
        try:
            from hoover4_ai_clients import (
                Hoover4MilvusVectorStore,
                Hoover4EmbeddingsClient,
                Hoover4NERClient,
                Hoover4RerankClient
            )
            
            # Initialize AI service clients
            embeddings_client = Hoover4EmbeddingsClient(
                base_url=os.getenv("EMBEDDING_SERVER_URL", "http://localhost:8000/v1"),
                task_description="Given a search query, return the most relevant documents."
            )
            
            ner_client = Hoover4NERClient(
                base_url=os.getenv("NER_SERVER_URL", "http://localhost:8000/v1")
            )
            
            reranker_client = Hoover4RerankClient(
                base_url=os.getenv("RERANKER_SERVER_URL", "http://localhost:8000/v1")
            )
            
            # Configuration from environment
            vector_store = Hoover4MilvusVectorStore(
                collection_name=os.getenv("MILVUS_COLLECTION_NAME", "rag_chunks"),
                host=os.getenv("MILVUS_HOST", "localhost"),
                port=int(os.getenv("MILVUS_PORT", "19530")),
                embedding_dim=int(os.getenv("EMBEDDING_DIM", "1024")),
                embedding=embeddings_client,
                search_mode=os.getenv("SEARCH_MODE", DEFAULT_SEARCH_MODE),
                ner_client=ner_client,
                use_ner_for_entities=True,
                include_entities_sparse=True,
                rrf_k=int(os.getenv("SEARCH_RRF_K", "60")),
            )
            
            # Create retriever with reranker
            milvus_retriever = vector_store.as_retriever(
                search_type=os.getenv("SEARCH_MODE", DEFAULT_SEARCH_MODE),
                search_kwargs={
                    "k": int(os.getenv("SEARCH_INITIAL_K", str(DEFAULT_INITIAL_RETRIEVAL_K))),
                    "mode": os.getenv("SEARCH_MODE", DEFAULT_SEARCH_MODE),
                    "include_entities_sparse": True,
                },
                reranker_client=reranker_client
            )
            
            logger.info("Initialized Milvus retriever successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Milvus retriever: {e}")
            raise
    
    try:
        yield milvus_retriever
    finally:
        # Retriever doesn't need explicit cleanup for now
        pass


@milvus_server.tool(
    name="milvus_search",
    description="""Search for documents in the Milvus vector database. Returns relevant documents with scores and metadata.

Args:
    query: str
        The search query to find relevant documents
""",
    structured_output=True,
)
async def milvus_search(
    query: str
) -> SearchResponse:
    """Search for documents using Milvus vector database.
    
    Args:
        query: The search query to find relevant documents
    """
    # Create metadata object with defaults
    metadata = SearchMetadata(
        search_mode=DEFAULT_SEARCH_MODE,
        retrieval_count=0,
        reranked=False
    )
    
    # Validate parameters
    error = validate_search_params(query, DEFAULT_MAX_RESULTS)
    if error:
        return SearchResponse(
            success=False,
            query=query,
            results=[],
            metadata=metadata,
            error=error
        )
    
    try:
        logger.info(f"Processing Milvus search query: {query}")
        
        async with get_milvus_retriever() as retriever:
            # Use environment variable configuration
            search_kwargs = {
                "k": DEFAULT_MAX_RESULTS,
            }
            
            # Execute search
            documents = retriever._get_relevant_documents(
                query, 
                **search_kwargs
            )
        
        # Format results
        search_results = []
        for doc in documents:
            # Extract score from metadata if available
            doc_score = None
            doc_metadata = {}
            
            if hasattr(doc, 'metadata') and doc.metadata:
                doc_metadata = doc.metadata.copy()
                # Extract score from metadata
                doc_score = doc_metadata.pop('rerank_score', doc_metadata.pop('score', None))
            
            search_results.append(SearchResult(
                id=doc.id or f"doc_{len(search_results)}",
                content=doc.page_content,
                score=doc_score,
                metadata=doc_metadata
            ))
        
        # Update metadata
        metadata = SearchMetadata(
            search_mode=DEFAULT_SEARCH_MODE,
            retrieval_count=len(search_results),
            reranked=retriever.reranker_client is not None
        )
        
        return SearchResponse(
            success=True,
            query=query,
            results=search_results,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Milvus search failed: {e}")
        return SearchResponse(
            success=False,
            query=query,
            results=[],
            metadata=metadata,
            error=str(e)
        )


def main():
    """Main function to start the Hoover4 Milvus Search MCP Server."""
    logger.info("Starting Hoover4 Milvus Search MCP Server...")
    milvus_server.run(transport="streamable-http")


if __name__ == "__main__":
    main()