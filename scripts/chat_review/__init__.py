"""Review completed chat deliveries without changing the application."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Load shared contracts from the mounted checkout, including in worker containers.
for source in (ROOT / "main_services/processing",
               ROOT / "main_services/agents/research_agent"):
    sys.path.insert(0, str(source))
