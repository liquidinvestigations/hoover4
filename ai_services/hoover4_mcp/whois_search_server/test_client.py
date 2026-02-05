#!/usr/bin/env python3
"""
Enhanced MCP client for testing the FastMCP WHOIS Server.

This script provides both automated testing and interactive modes for testing
the WHOIS lookup tools via MCP protocol over HTTP transport.
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

    # Test 1: Basic WHOIS Lookup
    print("\nTest 1: Basic WHOIS lookup...")
    try:
        result = await call_tool(session, "whois_lookup", {
            "domain": "google.com"
        })

        if result.get("success"):
            print(f"WHOIS lookup successful!")
            print(f"   Domain: {result['domain']}")

            # Show detailed data
            data = result.get('data', {})
            print(f"   Registrar: {data.get('registrar', 'N/A')}")
            print(f"   Creation Date: {data.get('creation_date', 'N/A')}")
            print(f"   Expiration Date: {data.get('expiration_date', 'N/A')}")
            print(f"   Last Updated: {data.get('last_updated', 'N/A')}")

            # Registrant information
            if any([data.get('registrant_name'), data.get('registrant_organization'), data.get('registrant_country')]):
                print(f"   Registrant:")
                if data.get('registrant_name'):
                    print(f"     Name: {data.get('registrant_name')}")
                if data.get('registrant_organization'):
                    print(f"     Organization: {data.get('registrant_organization')}")
                if data.get('registrant_country'):
                    print(f"     Country: {data.get('registrant_country')}")
                if data.get('registrant_state'):
                    print(f"     State: {data.get('registrant_state')}")
                if data.get('registrant_city'):
                    print(f"     City: {data.get('registrant_city')}")

            # Status information
            if data.get('status'):
                print(f"   Status: {', '.join(data.get('status', [])[:3])}")

            # Name servers
            if data.get('name_servers'):
                print(f"   Name Servers ({len(data.get('name_servers', []))}): {', '.join(data.get('name_servers', [])[:3])}")

            # Admin emails
            if data.get('admin_email'):
                print(f"   Admin Emails: {', '.join(data.get('admin_email', [])[:2])}")

            # DNSSEC
            if data.get('dnssec'):
                print(f"   DNSSEC: {data.get('dnssec')}")

            # Show metadata
            metadata = result.get('metadata', {})
            print(f"   Lookup Time: {metadata.get('lookup_time', 'N/A')}")
            print(f"   Timeout Used: {metadata.get('timeout_used', 'N/A')}s")
            print(f"   Raw Data Available: {metadata.get('raw_available', 'N/A')}")
        else:
            print(f"WHOIS lookup failed: {result.get('error')}")

    except Exception as e:
        print(f"WHOIS lookup test failed: {e}")

    # Test 2: WHOIS Lookup for another domain (timeout via env vars)
    print("\nTest 2: WHOIS lookup for example.com (timeout via environment variables)...")
    try:
        result = await call_tool(session, "whois_lookup", {
            "domain": "example.com"
        })

        if result.get("success"):
            print(f"Example.com lookup successful!")
            print(f"   Domain: {result['domain']}")

            # Show detailed data
            data = result.get('data', {})
            metadata = result.get('metadata', {})

            print(f"   Registrar: {data.get('registrar', 'N/A')}")
            print(f"   Creation Date: {data.get('creation_date', 'N/A')}")
            print(f"   Expiration Date: {data.get('expiration_date', 'N/A')}")
            print(f"   Last Updated: {data.get('last_updated', 'N/A')}")

            # Registrant information
            if any([data.get('registrant_name'), data.get('registrant_organization'), data.get('registrant_country')]):
                print(f"   Registrant:")
                if data.get('registrant_name'):
                    print(f"     Name: {data.get('registrant_name')}")
                if data.get('registrant_organization'):
                    print(f"     Organization: {data.get('registrant_organization')}")
                if data.get('registrant_country'):
                    print(f"     Country: {data.get('registrant_country')}")
                if data.get('registrant_state'):
                    print(f"     State: {data.get('registrant_state')}")
                if data.get('registrant_city'):
                    print(f"     City: {data.get('registrant_city')}")

            # Status and other info
            if data.get('status'):
                print(f"   Status: {', '.join(data.get('status', [])[:3])}")
            if data.get('name_servers'):
                print(f"   Name Servers ({len(data.get('name_servers', []))}): {', '.join(data.get('name_servers', [])[:2])}")
            if data.get('admin_email'):
                print(f"   Admin Emails: {', '.join(data.get('admin_email', [])[:2])}")
            if data.get('dnssec'):
                print(f"   DNSSEC: {data.get('dnssec')}")

            print(f"   Timeout Used: {metadata.get('timeout_used', 'N/A')}s")
            print(f"   Raw Data Available: {metadata.get('raw_available', 'N/A')}")
        else:
            print(f"Example.com lookup failed: {result.get('error')}")

    except Exception as e:
        print(f"Example.com lookup test failed: {e}")

    # Test 3: Domain with URL cleanup
    print("\nTest 3: Domain with URL cleanup...")
    try:
        result = await call_tool(session, "whois_lookup", {
            "domain": "https://www.github.com/some/path"
        })

        if result.get("success"):
            print(f"URL cleanup lookup successful!")
            print(f"   Cleaned Domain: {result['domain']}")

            # Show detailed data
            data = result.get('data', {})
            metadata = result.get('metadata', {})

            print(f"   Registrar: {data.get('registrar', 'N/A')}")
            print(f"   Creation Date: {data.get('creation_date', 'N/A')}")
            print(f"   Expiration Date: {data.get('expiration_date', 'N/A')}")
            print(f"   Last Updated: {data.get('last_updated', 'N/A')}")

            # Registrant information
            if any([data.get('registrant_name'), data.get('registrant_organization'), data.get('registrant_country')]):
                print(f"   Registrant:")
                if data.get('registrant_name'):
                    print(f"     Name: {data.get('registrant_name')}")
                if data.get('registrant_organization'):
                    print(f"     Organization: {data.get('registrant_organization')}")
                if data.get('registrant_country'):
                    print(f"     Country: {data.get('registrant_country')}")

            # Name servers
            if data.get('name_servers'):
                print(f"   Name Servers ({len(data['name_servers'])}): {', '.join(data['name_servers'][:3])}")

            # Other info
            if data.get('status'):
                print(f"   Status: {', '.join(data.get('status', [])[:2])}")
            if data.get('admin_email'):
                print(f"   Admin Emails: {', '.join(data.get('admin_email', [])[:2])}")
            if data.get('dnssec'):
                print(f"   DNSSEC: {data.get('dnssec')}")

            print(f"   Lookup Time: {metadata.get('lookup_time', 'N/A')}")
            print(f"   Timeout Used: {metadata.get('timeout_used', 'N/A')}s")
        else:
            print(f"URL cleanup lookup failed: {result.get('error')}")

    except Exception as e:
        print(f"URL cleanup lookup test failed: {e}")

    print("\nAutomated tests completed!")


async def run_interactive_mode(session: ClientSession, tools) -> None:
    """Run interactive mode for manual testing."""
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("Available commands:")
    print("  whois <domain>       - Lookup domain WHOIS")
    print("  whoistm <domain>     - Lookup with custom timeout")
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
            elif command == 'whois' and len(parts) > 1:
                domain = parts[1]
                print(f"\nLooking up: {domain}")

                result = await call_tool(session, "whois_lookup", {
                    "domain": domain
                })

                if result.get("success"):
                    print(f"\nWHOIS Information for {result['domain']}:")

                    data = result.get('data', {})

                    # Basic info
                    print(f"Registrar: {data.get('registrar', 'N/A')}")
                    print(f"Creation Date: {data.get('creation_date', 'N/A')}")
                    print(f"Expiration Date: {data.get('expiration_date', 'N/A')}")
                    print(f"Last Updated: {data.get('last_updated', 'N/A')}")

                    # Registrant info
                    if data.get('registrant_name'):
                        print(f"\nRegistrant:")
                        print(f"  Name: {data.get('registrant_name', 'N/A')}")
                        print(f"  Organization: {data.get('registrant_organization', 'N/A')}")
                        print(f"  Country: {data.get('registrant_country', 'N/A')}")
                        print(f"  State: {data.get('registrant_state', 'N/A')}")
                        print(f"  City: {data.get('registrant_city', 'N/A')}")

                    # Name servers
                    if data.get('name_servers'):
                        print(f"\nName Servers ({len(data['name_servers'])}):")
                        for ns in data['name_servers'][:5]:  # Show max 5
                            print(f"  - {ns}")

                    # Status
                    if data.get('status'):
                        print(f"\nStatus:")
                        for status in data['status'][:3]:  # Show max 3
                            print(f"  - {status}")
                else:
                    print(f"WHOIS lookup failed: {result.get('error')}")

            elif command == 'whoistm' and len(parts) > 1:
                domain = parts[1]
                print("\nNote: Timeout is now configured via environment variables only (WHOIS_DEFAULT_TIMEOUT)")

                print(f"\nLooking up: {domain}")

                result = await call_tool(session, "whois_lookup", {
                    "domain": domain
                })

                if result.get("success"):
                    print(f"\nWHOIS lookup successful!")
                    data = result.get('data', {})
                    metadata = result.get('metadata', {})

                    print(f"Domain: {result['domain']}")
                    print(f"Registrar: {data.get('registrar', 'N/A')}")
                    print(f"Creation: {data.get('creation_date', 'N/A')}")
                    print(f"Expires: {data.get('expiration_date', 'N/A')}")
                    print(f"Last Updated: {data.get('last_updated', 'N/A')}")

                    # Registrant info if available
                    if any([data.get('registrant_name'), data.get('registrant_organization'), data.get('registrant_country')]):
                        print(f"\nRegistrant Info:")
                        if data.get('registrant_name'):
                            print(f"  Name: {data.get('registrant_name')}")
                        if data.get('registrant_organization'):
                            print(f"  Organization: {data.get('registrant_organization')}")
                        if data.get('registrant_country'):
                            print(f"  Country: {data.get('registrant_country')}")

                    # Technical details
                    if data.get('name_servers'):
                        print(f"Name Servers ({len(data.get('name_servers', []))}): {', '.join(data.get('name_servers', [])[:3])}")
                    if data.get('status'):
                        print(f"Status: {', '.join(data.get('status', [])[:3])}")
                    if data.get('admin_email'):
                        print(f"Admin Emails: {', '.join(data.get('admin_email', [])[:2])}")
                    if data.get('dnssec'):
                        print(f"DNSSEC: {data.get('dnssec')}")

                    print(f"\nMetadata:")
                    print(f"  Lookup Time: {metadata.get('lookup_time', 'N/A')}")
                    print(f"  Timeout Used: {metadata.get('timeout_used', 'N/A')}s")
                    print(f"  Raw Data Available: {metadata.get('raw_available', 'N/A')}")
                else:
                    print(f" WHOIS lookup failed: {result.get('error')}")

            else:
                print("Unknown command. Use 'whois <domain>', 'whoistm <domain>', 'tools', or 'quit'")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

    print("\nExiting interactive mode")


async def main():
    """Main function using streamable HTTP client pattern."""
    print("WHOIS Lookup MCP Client")
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
