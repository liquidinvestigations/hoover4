#!/usr/bin/env python3
"""
Main application entry point for the Research Agent API.
"""

import os
import uvicorn
from research_agent.api import app
from dotenv import load_dotenv


if __name__ == "__main__":
    load_dotenv()
    
    # Get configuration from environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() in ("true", "1", "yes")
    
    print(f"🚀 Starting Research Agent API...")
    print(f"🌐 Server: http://{host}:{port}")
    print("📝 Configuration: Reading from environment variables")
    
    uvicorn.run(
        "research_agent.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
