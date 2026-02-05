#!/usr/bin/env python3
"""
Enhanced MCP client for testing the FastMCP Wikipedia Server.

This script provides both automated testing and interactive modes for testing
the Wikipedia search and summary tools via MCP protocol over HTTP transport.
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

    # Test 1: Wikipedia Search
    print("\nTest 1: Basic Wikipedia search...")
    try:
        result = await call_tool(session, "wikipedia_search", {
            "query": "artificial intelligence"
        })

        if result.get("success"):
            print(f"Wikipedia search successful!")
            print(f"   Query: {result['query']}")
            print(f"   Results found: {len(result.get('results', []))}")

            # Show metadata from response
            print(f"   Language: {result.get('language', 'N/A')}")
            print(f"   Result count: {result.get('result_count', 'N/A')}")

            # Show first 2 results
            results = result.get('results', [])
            for i, item in enumerate(results[:2], 1):
                print(f"\n   {i}. {item['title']}")
                print(f"      URL: {item['url']}")
        else:
            print(f"Wikipedia search failed: {result.get('error')}")

    except Exception as e:
        print(f"Wikipedia search test failed: {e}")

    # Test 2: Wikipedia Summary
    print("\nTest 2: Wikipedia summary...")
    try:
        result = await call_tool(session, "wikipedia_summary", {
            "query": "Python programming language"
        })

        if result.get("success"):
            print(f"Wikipedia summary successful!")
            print(f"   Query: {result['query']}")
            print(f"   Title: {result['title']}")
            print(f"   Summary length: {len(result.get('summary', ''))} characters")
            print(f"   URL: {result['url']}")

            # Show summary preview
            summary = result.get('summary', '')
            if summary:
                print(f"\n   Summary preview: {summary[:150]}...")
        else:
            print(f"Wikipedia summary failed: {result.get('error')}")

    except Exception as e:
        print(f"Wikipedia summary test failed: {e}")

    # Test 3: Search Test (language configured via environment)
    print("\nTest 3: Search test (language from environment)...")
    try:
        result = await call_tool(session, "wikipedia_search", {
            "query": "machine learning"
        })

        if result.get("success"):
            print(f"Search successful!")
            print(f"   Query: {result['query']}")
            print(f"   Language: {result.get('language', 'N/A')}")
            print(f"   Results: {len(result.get('results', []))}")

            # Show first result
            results = result.get('results', [])
            if results:
                print(f"\n   First result: {results[0]['title']}")
                print(f"   URL: {results[0]['url']}")
        else:
            print(f" Search failed: {result.get('error')}")

    except Exception as e:
        print(f"Search test failed: {e}")

    # Test 4: Summary Test (length configured via environment)
    print("\nTest 4: Summary test (length from environment)...")
    try:
        result = await call_tool(session, "wikipedia_summary", {
            "query": "Albert Einstein"
        })

        if result.get("success"):
            print(f"Summary successful!")
            print(f"   Title: {result['title']}")
            print(f"   Language: {result.get('language', 'N/A')}")
            print(f"   Sentences: {result.get('sentences', 'N/A')}")
            print(f"   Summary: {result['summary'][:100]}...")
        else:
            print(f" Summary failed: {result.get('error')}")

    except Exception as e:
        print(f"Summary test failed: {e}")

    print("\nAutomated tests completed!")


async def run_interactive_mode(session: ClientSession, tools) -> None:
    """Run interactive mode for manual testing."""
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("Available commands:")
    print("  search <query>       - Search Wikipedia")
    print("  summary <query>      - Get article summary")
    print("  tools                - List available tools")
    print("  quit                 - Exit interactive mode")
    print()
    print("Note: Language, max results, and summary sentences are configured via environment variables")
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
                print(f"\nSearching Wikipedia: {query}")

                result = await call_tool(session, "wikipedia_search", {
                    "query": query
                })

                if result.get("success"):
                    print(f"\nFound {len(result.get('results', []))} results:")
                    for i, item in enumerate(result.get('results', []), 1):
                        print(f"{i}. {item['title']}")
                        print(f"   {item['url']}")
                        print()
                else:
                    print(f"Search failed: {result.get('error')}")

            elif command == 'summary' and len(parts) > 1:
                query = parts[1]
                print(f"\nGetting summary: {query}")

                result = await call_tool(session, "wikipedia_summary", {
                    "query": query
                })

                if result.get("success"):
                    print(f"\nSummary for: {result['title']}")
                    print(f"URL: {result['url']}")
                    print(f"\nSummary:")
                    print(result.get('summary', 'No summary available'))
                else:
                    print(f"Summary failed: {result.get('error')}")

            else:
                print("Unknown command. Use 'search <query>', 'summary <query>', 'tools', or 'quit'")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

    print("\nExiting interactive mode")


async def main():
    """Main function using streamable HTTP client pattern."""
    print("Wikipedia Search MCP Client")
    print("="*50)
    print("Make sure your server is running at http://localhost:8083/mcp")
    print("Usage: python test_client.py [--interactive]")
    print()

    # Check command line arguments
    interactive = len(sys.argv) > 1 and sys.argv[1] == "--interactive"

    try:
        # Connect to a streamable HTTP server
        async with streamablehttp_client("http://localhost:8083/mcp") as (
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
