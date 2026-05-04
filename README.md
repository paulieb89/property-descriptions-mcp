<!-- mcp-name: io.github.paulieb89/property-descriptions-mcp -->

# property-descriptions-mcp

UK property listing description generator. Give an AI assistant a postcode or address — it fetches comparable sales, EPC ratings, and Rightmove listings, then writes three copy variants ready for Rightmove, social media, and email.

[![PyPI](https://img.shields.io/pypi/v/property-descriptions-mcp)](https://pypi.org/project/property-descriptions-mcp/)
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=property-descriptions&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fproperty-descriptions-mcp.fly.dev%2Fmcp%22%7D)
[![Install in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_Server-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=property-descriptions&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fproperty-descriptions-mcp.fly.dev%2Fmcp%22%7D&quality=insiders)
[![Install in Cursor](https://img.shields.io/badge/Cursor-Install_Server-000000?style=flat-square&logoColor=white)](https://cursor.com/en/install-mcp?name=property-descriptions&config=eyJ0eXBlIjoiaHR0cCIsInVybCI6Imh0dHBzOi8vcHJvcGVydHktZGVzY3JpcHRpb25zLW1jcC5mbHkuZGV2L21jcCJ9)

---

## Data Sources

| Source | API | Auth |
|--------|-----|------|
| Land Registry (PPD) | `landregistry.data.gov.uk` SPARQL | None |
| EPC Register | `epc.opendatacommunities.org` | API key (optional — degrades gracefully) |
| Rightmove | rightmove.co.uk (scraping, polite) | None |
| postcodes.io | `api.postcodes.io` | None |

---

## Tools

| Tool | Description |
|------|-------------|
| `get_property_data` | Fetch comparable sales, EPC data, and Rightmove listings for a postcode or address |
| `get_listing_detail` | Full Rightmove listing detail including photos, by URL or listing ID |
| `format_for_portals` | Format property data into portal-ready copy variants |

---

## Connect

### Hosted (no install)

```json
{
  "mcpServers": {
    "property-descriptions": {
      "type": "http",
      "url": "https://property-descriptions-mcp.fly.dev/mcp"
    }
  }
}
```

### Local (uvx)

```json
{
  "mcpServers": {
    "property-descriptions": {
      "type": "stdio",
      "command": "uvx",
      "args": ["property-descriptions-mcp"]
    }
  }
}
```

EPC credentials are optional — the server degrades gracefully without them. If you want full EPC data:

| Key | Where to get it |
|-----|----------------|
| `EPC_API_EMAIL` / `EPC_API_KEY` | [epc.opendatacommunities.org](https://epc.opendatacommunities.org) — free registration |

---

## Demo

```
Write a property listing for 14 Acacia Avenue, NG5 3AA — 3-bed semi, asking £250,000
```

The agent calls `get_property_data` to pull recent sales and EPC data, then writes three copy variants (professional, luxury, family), a Rightmove summary under 300 characters, a social caption, and eight feature bullets.

---

## Licence

MIT
