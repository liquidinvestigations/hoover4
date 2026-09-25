"""The image entry, `python -m agent_todo_server`.

It imports `main` from `agent_todo_server.server`, so the served `mcp` is the one that
`plan_tools` registers the plan tools on.
"""

from agent_todo_server.server import main

if __name__ == "__main__":
    main()
