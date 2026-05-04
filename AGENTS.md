# property-descriptions-mcp — Agent Usage Guide

UK property listing description generator. Fetches live market data and writes portal-ready copy in three tones.

## Connection

**Hosted:** `https://property-descriptions-mcp.fly.dev/mcp`
**Local:** `uvx property-descriptions-mcp`

## Available Tools

- `get_property_data` — fetch comparable sales, EPC ratings, and Rightmove listings for a postcode or address; pass `price` and `bedrooms` to personalise the context
- `get_listing_detail` — full Rightmove listing detail including photos, by URL or listing ID; useful when the agent needs to describe specific rooms
- `format_for_portals` — format property data into portal-ready copy: three tone variants (professional, luxury, family), Rightmove summary (≤300 chars), social caption, email subject, and feature bullets

## Usage Tips

- Call `get_property_data` first — it returns the market context that `format_for_portals` uses
- Pass `address` as well as `postcode` to `get_property_data` for better EPC matching
- EPC credentials are optional — the server degrades gracefully, using comps and Rightmove data alone
- `get_listing_detail` is most useful when the property has Rightmove photos and you want room-accurate descriptions
