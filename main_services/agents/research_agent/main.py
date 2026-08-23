#!/usr/bin/env python3
"""
Main application entry point for the Research Agent API.
"""

import logging
import os
import uvicorn
from research_agent.api import app
from dotenv import load_dotenv


if __name__ == "__main__":
    load_dotenv()

    # The package's own loggers, not uvicorn's. `log_level` below configures uvicorn
    # alone: without this the root logger has no handler, Python's last-resort handler
    # takes over, and everything the agent logs below WARNING is discarded, including
    # the compaction trail, whose whole purpose is to be readable after the fact.
    logging.basicConfig(
        level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

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
