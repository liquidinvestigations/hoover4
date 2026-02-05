#!/usr/bin/env python3
"""
Enhanced MCP client for testing the FastMCP Milvus Search Server.

This script provides both automated testing and interactive modes for testing
the simplified Milvus search functionality via MCP protocol over HTTP transport.
The server now only exposes a query parameter, with all other configuration
handled via environment variables.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def call_tool(session: ClientSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call a tool with the given arguments.

    Args:
        session: MCP client session
        tool_name: Name of the tool to call
        arguments: Arguments to pass to the tool

    Returns:
        Tool response as a dictionary
    """
    try:
        logger.debug(f"Calling tool {tool_name} with args: {arguments}")

        response = await session.call_tool(tool_name, arguments)

        if not response.content:
            raise RuntimeError(f"No response content from tool {tool_name}")

        result = response.structuredContent

        logger.debug(f"Tool {tool_name} returned: {result.get('success', False)}")

        return result

    except Exception as e:
        logger.error(f"Tool call failed for {tool_name}: {e}")
        raise


async def run_automated_tests(session: ClientSession) -> None:
    """Run a comprehensive set of automated tests."""
    print("\n" + "="*60)
    print("RUNNING AUTOMATED TESTS")
    print("="*60)

    # Test 1: Basic RAG Query
    print("\nTest 1: Basic RAG query...")
    try:
        result = await call_tool(session, "milvus_search", {
            "query": "What is artificial intelligence?"
        })

        if result.get("success"):
            print(f"Search query successful!")
            print(f"   Query: {result['query']}")
            print(f"   Results found: {len(result.get('results', []))}")

            # Show metadata
            metadata = result.get('metadata', {})
            print(f"   Search mode: {metadata.get('search_mode', 'N/A')}")
            print(f"   Retrieval count: {metadata.get('retrieval_count', 'N/A')}")
            print(f"   Reranked: {metadata.get('reranked', 'N/A')}")

            # Show first result if available
            results = result.get('results', [])
            if results:
                doc = results[0]
                print(f"\n   First result:")
                print(f"   ID: {doc.get('id', 'N/A')}")
                if doc.get('score'):
                    print(f"   Score: {doc['score']:.3f}")
                print(f"   Content: {doc.get('content', '')[:100]}...")
        else:
            print(f"Search query failed: {result.get('error')}")

    except Exception as e:
        print(f"RAG query test failed: {e}")

    # Test 2: Machine Learning Query
    print("\nTest 2: Machine learning search query...")
    try:
        result = await call_tool(session, "milvus_search", {
            "query": "How does machine learning work?"
        })

        if result.get("success"):
            print(f"Machine learning search successful!")
            print(f"   Query: {result['query']}")
            print(f"   Results found: {len(result.get('results', []))}")

            # Show metadata
            metadata = result.get('metadata', {})
            print(f"   Search mode: {metadata.get('search_mode', 'N/A')}")
            print(f"   Retrieval count: {metadata.get('retrieval_count', 'N/A')}")
            print(f"   Reranked: {metadata.get('reranked', 'N/A')}")

            # Show first result if available
            results = result.get('results', [])
            if results:
                doc = results[0]
                print(f"\n   First result:")
                print(f"   ID: {doc.get('id', 'N/A')}")
                if doc.get('score'):
                    print(f"   Score: {doc['score']:.3f}")
                print(f"   Content: {doc.get('content', '')[:100]}...")
        else:
            print(f"Machine learning search failed: {result.get('error')}")

    except Exception as e:
        print(f"Machine learning search test failed: {e}")

    # Test 3: Vector Database Query
    print("\nTest 3: Vector database search query...")
    try:
        result = await call_tool(session, "milvus_search", {
            "query": "What are the key benefits of vector databases?"
        })

        if result.get("success"):
            print(f"Vector database search successful!")
            print(f"   Query: {result['query']}")
            print(f"   Results found: {len(result.get('results', []))}")

            # Show metadata
            metadata = result.get('metadata', {})
            print(f"   Search mode: {metadata.get('search_mode', 'N/A')}")
            print(f"   Retrieval count: {metadata.get('retrieval_count', 'N/A')}")
            print(f"   Reranked: {metadata.get('reranked', 'N/A')}")

            # Show first two results if available
            results = result.get('results', [])
            if results:
                for i, doc in enumerate(results[:2], 1):
                    print(f"\n   Result {i}:")
                    print(f"   ID: {doc.get('id', 'N/A')}")
                    if doc.get('score'):
                        print(f"   Score: {doc['score']:.3f}")
                    print(f"   Content: {doc.get('content', '')[:100]}...")
        else:
            print(f"Vector database search failed: {result.get('error')}")

    except Exception as e:
        print(f"Vector database search test failed: {e}")

    print("\nAutomated tests completed!")


async def run_interactive_mode(session: ClientSession, tools) -> None:
    """Run interactive mode for manual testing."""
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("Available commands:")
    print("  search <query>       - Search for documents")
    print("  tools                - List available tools")
    print("  quit                 - Exit interactive mode")
    print("-"*60)

    while True:
        try:
            user_input = input("\n> ").strip()
            if not user_input:
                continue

            parts = user_input.split(' ', 1)
            command = parts[0].lower()

            if command == 'quit':
                break
            elif command == 'tools':
                print(f"\nAvailable tools ({len(tools)}):")
                for tool in tools:
                    print(f"  - {tool.name}: {tool.description}")
            elif command == 'search' and len(parts) > 1:
                query = parts[1]
                print(f"\nSearching: {query}")

                result = await call_tool(session, "milvus_search", {
                    "query": query
                })

                if result.get("success"):
                    print(f"\nSearch Results:")
                    print(f"   Query: {result['query']}")

                    results = result.get('results', [])
                    print(f"   Found {len(results)} results")

                    # Show metadata
                    metadata = result.get('metadata', {})
                    print(f"   Search mode: {metadata.get('search_mode', 'N/A')}")
                    print(f"   Retrieval count: {metadata.get('retrieval_count', 'N/A')}")
                    print(f"   Reranked: {metadata.get('reranked', 'N/A')}")

                    # Show top results
                    if results:
                        print(f"\nTop Results:")
                        for i, doc in enumerate(results[:3], 1):  # Show max 3 results
                            print(f"\n{i}. Document ID: {doc.get('id', 'N/A')}")
                            if doc.get('score'):
                                print(f"   Score: {doc['score']:.3f}")
                            print(f"   Content: {doc.get('content', '')[:150]}...")

                            # Show document metadata if available
                            doc_metadata = doc.get('metadata', {})
                            if doc_metadata:
                                print(f"   Metadata: {list(doc_metadata.keys())}")
                else:
                    print(f"Search failed: {result.get('error')}")

            else:
                print("Unknown command. Use 'search <query>', 'tools', or 'quit'")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

    print("\nExiting interactive mode")


async def main():
    """Main function using streamable HTTP client pattern."""
    print("Hoover4 Milvus Search MCP Client")
    print("="*50)
    print("Make sure your server is running at http://localhost:8082/mcp")
    print("Tests the simplified milvus_search tool (query parameter only)")
    print("Usage: python test_client.py [--interactive]")
    print()

    # Check command line arguments
    interactive = len(sys.argv) > 1 and sys.argv[1] == "--interactive"

    try:
        # Connect to a streamable HTTP server
        async with streamablehttp_client("http://localhost:8082/mcp") as (
            read_stream,
            write_stream,
            _,
        ):
            print("Transport connected")

            # Create a session using the client streams
            async with ClientSession(read_stream, write_stream) as session:
                print("Session created")

                # Initialize the connection
                await session.initialize()
                print("Session initialized")

                # List available tools
                tools_response = await session.list_tools()
                tools = tools_response.tools
                print(f"\n Found {len(tools)} available tools:")
                for tool in tools:
                    print(f"  - {tool.name}: {tool.description}")

                if interactive:
                    await run_interactive_mode(session, tools)
                else:
                    await run_automated_tests(session)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        logger.exception(f"Application failed: {e}")
        print(f"\nApplication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
