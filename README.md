# Property Description Generator

MCP server that gives AI assistants the data to write property listing descriptions.
Upload a postcode. Get comparable sales, EPC ratings, and local market context.
The AI writes copy in three tones with portal-ready formats.

## For Estate Agents

This tool connects to Claude, ChatGPT, or any AI assistant that supports MCP.
You provide a property address. The AI fetches real market data and writes:

- **Property photos**: AI sees the actual listing images to describe rooms accurately
- **Three copy variants**: Professional, Luxury, Family-friendly
- **Rightmove summary**: Under 300 characters, portal-ready
- **Social media caption**: Instagram/Facebook ready
- **Email subject line**: Under 60 characters
- **Key feature bullets**: 8-10 points for portal listings

Try the demo: https://property-descriptions-mcp.fly.dev/

## For Developers

### Run Locally

    git clone [repo]
    cd property-descriptions-mcp
    uv sync
    uv run property-descriptions          # HTTP on :8080
    uv run property-descriptions --stdio  # For Claude Desktop

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

    {
        "mcpServers": {
            "property-descriptions": {
                "command": "uv",
                "args": ["run", "--with", "fastmcp>=3.2.4", "--with", "property-shared>=1.6.1",
                         "fastmcp", "run", "src/property_descriptions_mcp/server.py"]
            }
        }
    }

### Connect to Claude Code

    claude mcp add property-descriptions -- uv run --with fastmcp --with property-shared fastmcp run src/property_descriptions_mcp/server.py

### Deploy

    fly deploy

### Environment

    EPC_API_EMAIL    # Optional: EPC Register credentials
    EPC_API_KEY      # Optional: degrades gracefully without

No OpenAI key required. The AI is external — this is just the data layer.
