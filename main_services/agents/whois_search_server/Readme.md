# whois MCP server

Domain registration lookup, exposed as a single MCP tool.

Its build context is `main_services/agents`, not this directory, because `agent_common` is
vendored into the image at build time.
