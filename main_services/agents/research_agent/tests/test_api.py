import asyncio
import json
import httpx
import uuid
import secrets

def generate_langfuse_trace_id() -> str:
    """Generate a 32-character lowercase hex string for Langfuse trace IDs."""
    return secrets.token_hex(16)

async def test_api_interactive_chat():
    """Test API with interactive chat interface using HTTP requests."""

    # API configuration
    api_base_url = "http://localhost:9090"  # Default FastAPI port
    health_url = f"{api_base_url}/health"
    chat_url = f"{api_base_url}/chat/stream"

    print("Testing Research Agent API...")
    print("=" * 50)

    # Test health endpoint first
    print("🔍 Checking API health...")
    try:
        async with httpx.AsyncClient() as client:
            health_response = await client.get(health_url)
            health_data = health_response.json()

            if health_response.status_code == 200 and health_data.get("status") == "healthy":
                print(" API is healthy and ready")
                print(f"   Message: {health_data.get('message')}")
            else:
                print(" API health check failed")
                print(f"   Status: {health_data.get('status')}")
                print(f"   Message: {health_data.get('message')}")
                return

    except httpx.ConnectError:
        print(" Cannot connect to API. Make sure the API server is running on localhost:9090")
        print("   Start the API with: uvicorn research_agent.api:app --host 0.0.0.0 --port 9090")
        return
    except Exception as e:
        print(f" Health check failed: {e}")
        return

    print("\n🚀 Starting interactive chat session...")
    print("Type 'quit' or 'exit' to end the session")
    print("-" * 50)

    # Interactive chat loop
    session_id = generate_langfuse_trace_id()
    user_id = generate_langfuse_trace_id()
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

            # Generate message ID for this interaction
            message_id = generate_langfuse_trace_id()

            # Make streaming request to API
            async with httpx.AsyncClient() as client:
                try:
                    # Prepare request data
                    request_data = {
                        "session_id": session_id,
                        "user_id": user_id,
                        "message_id": message_id,
                        "query": user_input,
                        "chat_history": chat_history
                    }

                    # Make streaming request
                    async with client.stream(
                        "POST",
                        chat_url,
                        json=request_data,
                        timeout=30.0
                    ) as response:

                        if response.status_code != 200:
                            print(f" API request failed with status {response.status_code}")
                            error_text = await response.aread()
                            print(f"   Error: {error_text.decode()}")
                            continue

                        # Process streaming response
                        ai_response_content = ""
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                try:
                                    # Parse JSON data from SSE format
                                    json_data = line[6:]  # Remove "data: " prefix
                                    event = json.loads(json_data)

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
                                    elif event_type == "error":
                                        print(f" Error: {content}", flush=True)
                                    elif is_complete:
                                        print()  # New line at the end
                                        # Add the conversation to chat history
                                        chat_history.append({"type": "human", "content": user_input})
                                        chat_history.append({"type": "ai", "content": ai_response_content})
                                        break

                                except json.JSONDecodeError as e:
                                    print(f" Failed to parse JSON: {e}")
                                    print(f"   Raw line: {line}")
                                    continue

                except httpx.TimeoutException:
                    print(" Request timed out")
                except httpx.RequestError as e:
                    print(f" Request failed: {e}")
                except Exception as e:
                    print(f" Unexpected error: {e}")

            print()  # Add line break after response

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


async def test_api_basic_functionality():
    """Test basic API functionality without interactive chat."""

    api_base_url = "http://localhost:9090"
    health_url = f"{api_base_url}/health"
    chat_url = f"{api_base_url}/chat/stream"
    root_url = f"{api_base_url}/"
    user_id = generate_langfuse_trace_id()
    session_id = generate_langfuse_trace_id()

    print("Testing basic API functionality...")
    print("=" * 50)

    async with httpx.AsyncClient() as client:
        try:
            # Test root endpoint
            print("🔍 Testing root endpoint...")
            root_response = await client.get(root_url)
            if root_response.status_code == 200:
                root_data = root_response.json()
                print(" Root endpoint working")
                print(f"   Message: {root_data.get('message')}")
                print(f"   Version: {root_data.get('version')}")
                print(f"   Status: {root_data.get('status')}")

                # Validate new response structure
                config = root_data.get('configuration', {})
                endpoints = root_data.get('endpoints', {})
                print(f"   Agent Name: {config.get('agent_name')}")
                print(f"   MCP Servers Count: {config.get('mcp_servers_count')}")
                print(f"   LLM Model: {config.get('llm_model')}")
                print(f"   Available Endpoints: {list(endpoints.keys())}")
            else:
                print(f" Root endpoint failed: {root_response.status_code}")

            # Test health endpoint
            print("\n🔍 Testing health endpoint...")
            health_response = await client.get(health_url)
            if health_response.status_code == 200:
                health_data = health_response.json()
                print(" Health endpoint working")
                print(f"   Status: {health_data.get('status')}")
                print(f"   Message: {health_data.get('message')}")
            else:
                print(f" Health endpoint failed: {health_response.status_code}")

            # Test chat endpoint with a simple query
            print("\n🔍 Testing chat endpoint...")
            message_id = generate_langfuse_trace_id()
            test_request = {
                "session_id": session_id,
                "user_id": user_id,
                "message_id": message_id,
                "query": "Hello, can you help me?",
                "chat_history": []
            }

            async with client.stream("POST", chat_url, json=test_request) as response:
                if response.status_code == 200:
                    print(" Chat endpoint working")
                    print("   Response stream:")

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                json_data = line[6:]
                                event = json.loads(json_data)
                                print(f"   {event}")

                                if event.get("is_task_complete"):
                                    break
                            except json.JSONDecodeError:
                                continue
                else:
                    print(f" Chat endpoint failed: {response.status_code}")
                    error_text = await response.aread()
                    print(f"   Error: {error_text.decode()}")

            # Test feedback endpoints
            print("\n🔍 Testing feedback endpoints...")

            # Test message feedback endpoint
            message_feedback_url = f"{api_base_url}/feedback/message"
            message_feedback_data = {
                "score_id": generate_langfuse_trace_id(),
                "message_id": message_id,
                "user_id": user_id,
                "feedback": "Great response!",
                "rating": 5
            }

            feedback_response = await client.post(message_feedback_url, json=message_feedback_data)
            if feedback_response.status_code == 200:
                print(" Message feedback endpoint working")
                feedback_data = feedback_response.json()
                print(f"   Response: {feedback_data.get('message')}")
            else:
                print(f" Message feedback endpoint failed: {feedback_response.status_code}")
                error_text = await feedback_response.aread()
                print(f"   Error: {error_text.decode()}")

            # Test session feedback endpoint
            session_feedback_url = f"{api_base_url}/feedback/session"
            session_feedback_data = {
                "score_id": generate_langfuse_trace_id(),
                "session_id": session_id,
                "user_id": user_id,
                "feedback": "Excellent session!",
                "rating": 5
            }

            session_feedback_response = await client.post(session_feedback_url, json=session_feedback_data)
            if session_feedback_response.status_code == 200:
                print(" Session feedback endpoint working")
                session_feedback_data_response = session_feedback_response.json()
                print(f"   Response: {session_feedback_data_response.get('message')}")
            else:
                print(f" Session feedback endpoint failed: {session_feedback_response.status_code}")
                error_text = await session_feedback_response.aread()
                print(f"   Error: {error_text.decode()}")

            # Test delete feedback endpoint
            delete_feedback_url = f"{api_base_url}/feedback/{message_feedback_data['score_id']}"
            delete_response = await client.delete(delete_feedback_url)
            if delete_response.status_code == 200:
                print(" Delete feedback endpoint working")
                delete_data = delete_response.json()
                print(f"   Response: {delete_data.get('message')}")
            else:
                print(f" Delete feedback endpoint failed: {delete_response.status_code}")
                error_text = await delete_response.aread()
                print(f"   Error: {error_text.decode()}")

        except httpx.ConnectError:
            print(" Cannot connect to API. Make sure the API server is running on localhost:9090")
        except Exception as e:
            print(f" Test failed: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--basic":
        asyncio.run(test_api_basic_functionality())
    else:
        asyncio.run(test_api_interactive_chat())
