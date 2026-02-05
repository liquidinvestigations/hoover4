"""FastMCP WHOIS Server.

A modern MCP server using FastMCP for WHOIS domain lookup functionality.
"""

import asyncio
import logging
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

try:
    import whois
    WHOIS_AVAILABLE = True
except ImportError:
    whois = None
    WHOIS_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default configuration from environment variables
DEFAULT_TIMEOUT = int(os.getenv("WHOIS_DEFAULT_TIMEOUT", "30"))
MAX_ALLOWED_TIMEOUT = int(os.getenv("WHOIS_MAX_ALLOWED_TIMEOUT", "300"))  # Maximum timeout limit


# Structured data models for WHOIS operations
class WhoisMetadata(BaseModel):
    """Metadata for WHOIS operations."""
    
    lookup_time: str = Field(description="ISO timestamp of when the lookup was performed")
    timeout_used: int = Field(description="Timeout value used for the lookup")
    raw_available: bool = Field(description="Whether raw WHOIS data is available")


class WhoisData(BaseModel):
    """Structured WHOIS domain information."""
    
    domain_name: Optional[str] = Field(default=None, description="Domain name")
    registrar: Optional[str] = Field(default=None, description="Domain registrar")
    creation_date: Optional[str] = Field(default=None, description="Domain creation date")
    expiration_date: Optional[str] = Field(default=None, description="Domain expiration date")
    last_updated: Optional[str] = Field(default=None, description="Last update date")
    status: Optional[List[str]] = Field(default=None, description="Domain status")
    name_servers: Optional[List[str]] = Field(default=None, description="Name servers")
    registrant_name: Optional[str] = Field(default=None, description="Registrant name")
    registrant_organization: Optional[str] = Field(default=None, description="Registrant organization")
    registrant_country: Optional[str] = Field(default=None, description="Registrant country")
    registrant_state: Optional[str] = Field(default=None, description="Registrant state")
    registrant_city: Optional[str] = Field(default=None, description="Registrant city")
    admin_email: Optional[List[str]] = Field(default=None, description="Admin email addresses")
    dnssec: Optional[str] = Field(default=None, description="DNSSEC status")


class WhoisLookupResponse(BaseModel):
    """Response structure for WHOIS lookup."""
    
    success: bool = Field(description="Whether the lookup was successful")
    domain: str = Field(description="The domain that was queried")
    data: WhoisData = Field(description="Structured WHOIS data")
    metadata: WhoisMetadata = Field(description="Lookup metadata")
    error: Optional[str] = Field(default=None, description="Error message if lookup failed")


# Create FastMCP instance
whois_server = FastMCP(
    name=os.getenv("SERVER_NAME", "whois_lookup"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", "Domain registration information lookup with structured data output for domain analysis."),
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8083")),
)


# Health check endpoint for monitoring
@whois_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Basic health check endpoint."""
    return JSONResponse({"status": "ok", "service": "whois-lookup"})


# Helper function to validate lookup parameters
def validate_lookup_params(domain: str, timeout: int = DEFAULT_TIMEOUT):
    """Validate lookup parameters and return error message if invalid."""
    if not domain or not domain.strip():
        return "Error: Domain cannot be empty"
    
    if timeout <= 0 or timeout > MAX_ALLOWED_TIMEOUT:
        return f"Error: timeout must be between 1 and {MAX_ALLOWED_TIMEOUT} seconds"
    
    return None


def format_whois_data(domain_data) -> WhoisData:
    """Format WHOIS data into a structured format."""
    if not domain_data:
        return WhoisData()
    
    # Handle both dict and object responses
    def safe_get(obj, key, default=None):
        if hasattr(obj, key):
            return getattr(obj, key, default)
        elif isinstance(obj, dict):
            return obj.get(key, default)
        return default
    
    # Format dates
    def format_date(date_val):
        if not date_val:
            return None
        if isinstance(date_val, list) and date_val:
            date_val = date_val[0]
        if isinstance(date_val, datetime):
            return date_val.isoformat()
        return str(date_val)
    
    # Clean up list fields
    def clean_list(value):
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return value
    
    # Extract common fields
    return WhoisData(
        domain_name=safe_get(domain_data, "domain_name"),
        registrar=safe_get(domain_data, "registrar"),
        creation_date=format_date(safe_get(domain_data, "creation_date")),
        expiration_date=format_date(safe_get(domain_data, "expiration_date")),
        last_updated=format_date(safe_get(domain_data, "updated_date")),
        status=clean_list(safe_get(domain_data, "status")),
        name_servers=clean_list(safe_get(domain_data, "name_servers")),
        registrant_name=safe_get(domain_data, "name"),
        registrant_organization=safe_get(domain_data, "org"),
        registrant_country=safe_get(domain_data, "country"),
        registrant_state=safe_get(domain_data, "state"),
        registrant_city=safe_get(domain_data, "city"),
        admin_email=clean_list(safe_get(domain_data, "emails")),
        dnssec=safe_get(domain_data, "dnssec")
    )


@whois_server.tool(
    name="whois_lookup",
    description="""Perform WHOIS lookup for a domain. Retrieves detailed registration information including registrar, dates, name servers, and contact information.

Args:
    domain: str
        The domain name to lookup (e.g., 'example.com')
""",
    structured_output=True,
)
async def whois_lookup(domain: str) -> WhoisLookupResponse:
    """Perform WHOIS lookup for a domain.
    
    Args:
        domain: The domain name to lookup
    """
    # Create metadata object
    lookup_time = datetime.now().isoformat()
    metadata = WhoisMetadata(
        lookup_time=lookup_time,
        timeout_used=DEFAULT_TIMEOUT,
        raw_available=False
    )
    
    # Validate parameters
    error = validate_lookup_params(domain, DEFAULT_TIMEOUT)
    if error:
        return WhoisLookupResponse(
            success=False,
            domain=domain,
            data=WhoisData(),
            metadata=metadata,
            error=error
        )
    
    if not WHOIS_AVAILABLE:
        return WhoisLookupResponse(
            success=False,
            domain=domain,
            data=WhoisData(),
            metadata=metadata,
            error="WHOIS library not available. Install with: pip install python-whois"
        )
    
    try:
        logger.info(f"Performing WHOIS lookup for: {domain}")
        
        # Clean domain (remove http/https, www, etc.)
        clean_domain = domain.lower()
        clean_domain = clean_domain.replace("http://", "").replace("https://", "")
        clean_domain = clean_domain.replace("www.", "")
        clean_domain = clean_domain.split("/")[0]  # Remove path if any
        
        # Run WHOIS lookup in executor to avoid blocking
        loop = asyncio.get_event_loop()
        
        def perform_whois():
            return whois.whois(clean_domain)
        
        # Use timeout
        try:
            domain_data = await asyncio.wait_for(
                loop.run_in_executor(None, perform_whois),
                timeout=DEFAULT_TIMEOUT
            )
        except asyncio.TimeoutError:
            return WhoisLookupResponse(
                success=False,
                domain=clean_domain,
                data=WhoisData(),
                metadata=metadata,
                error=f"WHOIS lookup timed out after {DEFAULT_TIMEOUT} seconds"
            )
        
        # Format the data
        formatted_data = format_whois_data(domain_data)
        
        # Update metadata
        metadata = WhoisMetadata(
            lookup_time=lookup_time,
            timeout_used=DEFAULT_TIMEOUT,
            raw_available=bool(domain_data)
        )
        
        return WhoisLookupResponse(
            success=True,
            domain=clean_domain,
            data=formatted_data,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"WHOIS lookup failed for {domain}: {e}")
        return WhoisLookupResponse(
            success=False,
            domain=domain,
            data=WhoisData(),
            metadata=metadata,
            error=str(e)
        )

def main():
    """Main function to start the WHOIS Lookup MCP Server."""
    if not WHOIS_AVAILABLE:
        logger.warning("WHOIS library not available. Install with: pip install python-whois")
    
    logger.info("Starting WHOIS Lookup MCP Server...")
    whois_server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
