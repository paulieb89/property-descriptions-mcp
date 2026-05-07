# CLAUDE.md

## What This Is

MCP server for generating UK property listing descriptions. Exposes data tools
backed by the property-shared PyPI package. The calling LLM writes the descriptions.
The server fetches the data.

## Architecture

Tool layer only. No internal AI agents. No pydantic-ai. No nested LLM calls.
- get_property_data: Fetches comps, EPC, listings, location from property-shared
- get_listing_detail: Fetches a Rightmove listing's full details
- format_for_portals: Display tool — renders LLM's descriptions in dashboard UI

## Stack

- FastMCP v3 (from fastmcp import FastMCP) — NOT mcp.server.fastmcp
- property-shared from PyPI — all UK property data
- Python 3.11+
- Deployed to Fly.io

## Commands

    # Run locally (stdio for Claude Desktop)
    uv run --env-file .env property-descriptions --stdio

    # Run locally (HTTP for browser/remote clients)
    uv run --env-file .env property-descriptions

    # Deploy
    fly deploy

    # Test with MCP Inspector
    npx @modelcontextprotocol/inspector http://localhost:8080/mcp

## Key Files

| File | Purpose |
|------|---------|
| src/property_descriptions_mcp/server.py | FastMCP server: tools, resources, routes |
| src/property_descriptions_mcp/ui/dashboard.html | MCP App UI rendered inside Claude |
| src/property_descriptions_mcp/ui/demo.html | Browser demo page + email capture |

## Environment

    EPC_API_EMAIL              # EPC Register API credential
    EPC_API_KEY                # EPC Register API credential
    COMPANIES_HOUSE_API_KEY    # Companies House API
    PORT                       # HTTP port (default 8080)

Secrets are stored in .env locally (gitignored) and as Fly secrets in production.
Local: uv run --env-file .env ...
Prod:  fly secrets set KEY=value --app property-descriptions-mcp

No OpenAI key needed. No database. No Supabase.

## Design Rules

- No border-radius. Sharp edges. 1px borders.
- BOUCH colours: charcoal #1C1917, orange #D97757, cream #FAF9F5
- Space Mono body, Bebas Neue headings
- Dashboard: professional, compact, monospace labels
- Demo page: sells the tool, not BOUCH consulting
