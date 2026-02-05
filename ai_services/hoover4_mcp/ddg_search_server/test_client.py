#!/usr/bin/env python3
"""
Enhanced MCP client for testing the FastMCP DuckDuckGo Search Server.

This script provides both automated testing and interactive modes for testing
the DuckDuckGo search tools via MCP protocol over HTTP transport.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

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

    # Test 1: Text Search
    print("\nTest 1: Basic text search...")
    try:
        result = await call_tool(session, "ddg_text_search", {
            "query": "FastMCP Python framework"
        })

        if result.get("success"):
            print(f"Text search successful! Found {result['result_count']} results")
            print(f"   Query: {result['query']}")

            # Show first 2 results
            for i, item in enumerate(result["results"][:2], 1):
                print(f"\n   {i}. {item['title']}")
                print(f"      URL: {item['url']}")
                print(f"      Snippet: {item['snippet'][:80]}...")
        else:
            print(f"Text search failed: {result.get('error')}")

    except Exception as e:
        print(f"Text search test failed: {e}")

    # Test 2: News Search
    print("\nTest 2: News search...")
    try:
        result = await call_tool(session, "ddg_news_search", {
            "query": "artificial intelligence"
        })

        if result.get("success"):
            print(f"News search successful! Found {result['result_count']} results")
            print(f"   Query: {result['query']}")
            print(f"   Time limit: {result['metadata']['timelimit']}")

            # Show first 2 results
            for i, item in enumerate(result["results"][:2], 1):
                print(f"\n   {i}. {item['title']}")
                print(f"      Source: {item.get('source', 'N/A')}")
                print(f"      Date: {item.get('date', 'N/A')}")
                print(f"      URL: {item['url']}")
        else:
            print(f" News search failed: {result.get('error')}")

    except Exception as e:
        print(f"News search test failed: {e}")

    # Test 3: Another text search
    print("\nTest 3: Another text search...")
    try:
        result = await call_tool(session, "ddg_text_search", {
            "query": "Python 3.13 release"
        })

        if result.get("success"):
            print(f"Time-limited search successful! Found {result['result_count']} results")
            print(f"   Query: {result['query']}")
            print(f"   Time limit: {result['metadata']['timelimit']}")

            if result["results"]:
                item = result["results"][0]
                print(f"\n   Top result: {item['title']}")
                print(f"   URL: {item['url']}")
        else:
            print(f"Time-limited search failed: {result.get('error')}")

    except Exception as e:
        print(f"Time-limited search test failed: {e}")

    print("\nAutomated tests completed!")


async def run_interactive_mode(session: ClientSession, tools) -> None:
    """Run interactive mode for manual testing."""
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("Available commands:")
    print("  text <query>     - Search web")
    print("  news <query>     - Search news")
    print("  tools            - List available tools")
    print("  quit             - Exit interactive mode")
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
            elif command == 'text' and len(parts) > 1:
                query = parts[1]
                print(f"\nSearching: {query}")

                result = await call_tool(session, "ddg_text_search", {
                    "query": query
                })

                if result.get("success"):
                    print(f"Found {result['result_count']} results:")
                    for i, item in enumerate(result["results"], 1):
                        print(f"\n{i}. {item['title']}")
                        print(f"   {item['url']}")
                        print(f"   {item['snippet'][:100]}...")
                else:
                    print(f"Search failed: {result.get('error')}")

            elif command == 'news' and len(parts) > 1:
                query = parts[1]
                print(f"\nSearching news: {query}")

                result = await call_tool(session, "ddg_news_search", {
                    "query": query
                })

                if result.get("success"):
                    print(f"Found {result['result_count']} news results:")
                    for i, item in enumerate(result["results"], 1):
                        print(f"\n{i}. {item['title']}")
                        print(f"   Source: {item.get('source', 'N/A')} | Date: {item.get('date', 'N/A')}")
                        print(f"   {item['url']}")
                else:
                    print(f"News search failed: {result.get('error')}")

            else:
                print("Unknown command. Use 'text <query>', 'news <query>', 'tools', or 'quit'")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

    print("\nExiting interactive mode")


async def main():
    """Main function using streamable HTTP client pattern."""
    print("DuckDuckGo Search MCP Client")
    print("="*50)
    print("Make sure your server is running at http://localhost:8080/mcp")
    print("Usage: python test_client.py [--interactive]")
    print()

    # Check command line arguments
    interactive = len(sys.argv) > 1 and sys.argv[1] == "--interactive"

    try:
        # Connect to a streamable HTTP server
        async with streamablehttp_client("http://localhost:8080/mcp") as (
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
