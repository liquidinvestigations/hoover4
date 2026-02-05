import asyncio
import uuid
import json
from research_agent.agent import build_agent

import dotenv

dotenv.load_dotenv()

async def test_agent_interactive_chat():
    """Test agent with interactive chat interface using localhost:8080."""
    
    # Create agent with localhost:8080 MCP server
    mcp_servers = ["http://localhost:8080/mcp"]
    system_prompt = "You are a helpful research assistant. Use the available tools to help users with their queries."
    
    # Build the agent
    agent = await build_agent(
        mcp_servers=mcp_servers,
        name="test_agent",
        system_prompt=system_prompt
    )

    print("Agent initialized successfully!")
    print("Starting interactive chat session...")
    print("Type 'quit' or 'exit' to end the session")
    print("-" * 50)

    # Interactive chat loop
    chat_history = []
    is_thinking = False

    while True:
        try:
            # Get user input
            user_input = input(">>> ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            print()  # Add line break after user input
            
            # Stream the agent's response
            ai_response_content = ""
            async for event in agent.stream(user_input, chat_history):
                event_type = event.get("type", "")
                content = event.get("content", "")
                is_complete = event.get("is_task_complete", False)
                
                if event_type == "start_reasoning" and not is_thinking:
                    print("--thinking--", end="", flush=True)
                    is_thinking = True
                elif event_type == "reasoning" and is_thinking:
                    print(content, end="", flush=True)
                elif event_type == "start_response" and is_thinking:
                    print("--end thinking--", end="", flush=True)
                    is_thinking = False
                elif event_type == "response":
                    print(content, end="", flush=True)
                    ai_response_content += content
                elif event_type == "start_tool":
                    print("[Tool started]", flush=True)
                    print(json.dumps(content, indent=2), flush=True)
                elif event_type == "end_tool":
                    print("[Tool completed]", flush=True)
                    print(json.dumps(content, indent=2), flush=True)
                elif is_complete:
                    print()  # New line at the end
                    # Add the conversation to chat history
                    chat_history.append({"type": "human", "content": user_input})
                    chat_history.append({"type": "ai", "content": ai_response_content})
                    break
            
            print()  # Add line break after response
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    asyncio.run(test_agent_interactive_chat())
