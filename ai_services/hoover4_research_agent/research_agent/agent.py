import os
from typing import List, Any, AsyncIterable, Sequence, TypedDict, Annotated, Dict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from research_agent.chat_model import ThinkingChatOpenAI
from pydantic import TypeAdapter
import json
from json import JSONDecodeError
from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

def recurse_json_decode(d):
    try:
        if isinstance(d, dict):
            return {k: recurse_json_decode(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [recurse_json_decode(item) for item in d]
        elif isinstance(d, str):
            return recurse_json_decode(json.loads(d))
        else:
            return d
    except (JSONDecodeError, TypeError):
        return d

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


class MCPGatewayAgent:
    """An agent that gateways to other agents via MCP."""

    def __init__(self, mcp_servers: List[str], name: str, system_prompt: str, llm_model: str = None):
        """Initialize the MCP Gateway Agent with MCP servers."""
        self.name = name
        self.mcp_servers = mcp_servers
        self.system_prompt = system_prompt
        self.llm_model = llm_model
        self.tools_type_adapter = TypeAdapter(Dict[str, Any])
        self.graph = None
        self.langfuse_handler = self._create_langfuse_handler()

    def _create_langfuse_handler(self) -> Optional[CallbackHandler]:
        """Create Langfuse callback handler if credentials are available."""
        langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        
        if langfuse_public_key and langfuse_secret_key:
            try:
                # Initialize Langfuse client with environment variables
                Langfuse(
                    public_key=langfuse_public_key,
                    secret_key=langfuse_secret_key,
                    host=langfuse_host
                )
                return CallbackHandler()
            except Exception as e:
                print(f"Warning: Failed to initialize Langfuse: {e}")
                return None
        return None

    async def initialize(self):
        """Initialize the agent graph with MCP tools."""
        if self.graph is None:
            self.graph = await self._create_graph()

    async def _create_graph(self):
        """Create the agent graph with MCP tools."""
        # Set up MCP servers
        servers = {
            f"mcp_server_{i}": {"url": url, "transport": "streamable_http"}
            for i, url in enumerate(self.mcp_servers)
        }
        
        # Create MCP client and get tools
        client = MultiServerMCPClient(servers)
        tools = await client.get_tools()
        
        # Get LLM configuration from environment variables
        llm_api_key = os.getenv("LLM_API_KEY")
        llm_base_url = os.getenv("LLM_BASE_URL")
        llm_model_env = self.llm_model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        
        if not llm_api_key:
            raise ValueError("LLM_API_KEY environment variable is required")
        
        # Create ChatOpenAI instance with environment configuration
        llm_kwargs = {
            "api_key": llm_api_key, 
            "model": llm_model_env,
            "temperature": llm_temperature,
            "streaming": True,
            "stream_usage": True,
        }
        if llm_base_url:
            llm_kwargs["base_url"] = llm_base_url
            
        llm = ThinkingChatOpenAI(**llm_kwargs).bind_tools(tools)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        agent_runnable = prompt | { "messages": llm } 
        
        builder = StateGraph(AgentState)
        builder.add_node("agent", agent_runnable)
        tool_node = ToolNode(tools)
        builder.add_node("tools", tool_node)

        def should_continue(state: AgentState):
            last_message = state["messages"][-1]
            if getattr(last_message, "tool_calls", None):
                return "tools"
            return END

        builder.set_entry_point("agent")
        builder.add_conditional_edges("agent", should_continue)
        builder.add_edge("tools", "agent")

        return builder.compile()

    async def stream(self, query: str, chat_history: List[Dict[str, str]] = None, session_id: str = None, user_id: str = None) -> AsyncIterable[dict[str, Any]]:
        # Initialize the agent if not already done
        await self.initialize()
        
        # Build messages from chat history and current query
        messages = []
        if chat_history:
            for msg in chat_history:
                if msg["type"] == "human":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["type"] == "ai":
                    messages.append(AIMessage(content=msg["content"]))
        
        # Add current query
        messages.append(HumanMessage(content=query))
        
        inputs = {"messages": messages}

        # Prepare config with Langfuse callback if available
        config = {}
        if self.langfuse_handler and user_id and session_id:
            config["callbacks"] = [self.langfuse_handler]
            config["metadata"] = {
                "langfuse_user_id": user_id,
                "langfuse_session_id": session_id,
                "langfuse_tags": [self.name]
            }

        llm_started = False
        is_reasoning = False
        is_response = False

        all_content = ""

        async for event in self.graph.astream_events(inputs, version="v2", config=config):
            kind = event["event"]
            node = event["metadata"].get("langgraph_node")

            if node == "agent":
                if kind == "on_chain_start" and not llm_started:
                    yield {
                        "is_task_complete": False,
                        "type": "start",
                        "content": "",
                    }
                    llm_started = True
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if isinstance(chunk, AIMessageChunk):
                        # Handle reasoning content
                        reasoning_content = chunk.additional_kwargs.get("reasoning_content", {})
                        if reasoning_content:
                            if not is_reasoning:
                                is_reasoning = True
                                is_response = False
                                yield {
                                    "is_task_complete": False,
                                    "type": "start_reasoning",
                                    "content": "",
                                }
                            yield {
                                "is_task_complete": False,
                                "type": "reasoning",
                                "content": reasoning_content,
                            }
                        
                        # Handle regular content
                        if chunk.content:
                            chunk_content = chunk.content
                            if isinstance(chunk_content, list):
                                chunk_content = "".join([x["text"] for x in chunk_content if x.get("type") == "text"])
                            if not is_response:
                                is_reasoning = False
                                is_response = True
                                yield {
                                    "is_task_complete": False,
                                    "type": "start_response",
                                    "content": "",
                                }
                            yield {
                                "is_task_complete": False,
                                "type": "response",
                                "content": chunk_content,
                            }
                            all_content += chunk_content

            if node == "tools":
                llm_started = False
                if kind == "on_tool_start":
                    yield {
                        "is_task_complete": False,
                        "type": "start_tool",
                        "content": recurse_json_decode(self.tools_type_adapter.dump_python(event["data"])),
                    }
                elif kind == "on_tool_end":
                    yield {
                        "is_task_complete": False,
                        "type": "end_tool",
                        "content": recurse_json_decode(self.tools_type_adapter.dump_python(event["data"])),
                    }
        
        yield {
            "is_task_complete": True,
            "type": "end",
            "content": all_content,
        }


async def build_agent(mcp_servers: List[str], name: str, system_prompt: str, llm_model: str = None) -> MCPGatewayAgent:
    """
    Builder function that creates a langgraph agent with MCP tools.
    
    Args:
        mcp_servers: List of MCP server URLs to connect to
        name: Name of the agent
        system_prompt: System prompt for the agent
        llm_model: Optional LLM model override
        
    Returns:
        MCPGatewayAgent: Configured agent instance
    """
    # Create the agent and initialize it
    agent = MCPGatewayAgent(mcp_servers, name, system_prompt, llm_model)
    await agent.initialize()
    return agent
