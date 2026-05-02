"""
Smoke test for get_listing_detail — measures token cost of image responses.

Usage:
    uv run python scripts/smoke_test.py <rightmove_url_or_id> [max_images] [offset]

Examples:
    uv run python scripts/smoke_test.py https://www.rightmove.co.uk/properties/123456789
    uv run python scripts/smoke_test.py 123456789 8 0
    uv run python scripts/smoke_test.py 123456789 4 8   # second page

Runs in two modes:
    - baseline: calls fetch_listing directly, reports per-image cost
    - live:     calls running MCP server at http://localhost:8080/mcp

Token methodology:
    Text tokens  — tiktoken cl100k_base (GPT tokenizer, reasonable proxy for text)
    Image tokens — Claude vision formula: ceil(w/750) * ceil(h/750) * 1601 + 85
                   tiktoken is NOT used for images; base64 strings are not text tokens.
"""

import asyncio
import base64
import io
import json
import struct
import sys
import time
from typing import Any

import httpx
import tiktoken


ENCODING = tiktoken.get_encoding("cl100k_base")
SERVER_URL = "http://localhost:8080/mcp"


def count_tokens(text: str) -> int:
    return len(ENCODING.encode(text))


def fmt_tokens(n: int) -> str:
    return f"~{n:,}"


def fmt_kb(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract (width, height) from JPEG bytes without Pillow."""
    i = 0
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        i += 2
        if marker == 0xD9:
            break
        if marker in (0xC0, 0xC1, 0xC2):  # SOF0, SOF1, SOF2
            h, w = struct.unpack_from(">HH", data, i + 3)
            return w, h
        length = struct.unpack_from(">H", data, i)[0]
        i += length
    return None


def claude_image_tokens(w: int, h: int) -> int:
    """Claude vision token cost: tiled into 750x750 cells, 1601 tokens each + 85 base."""
    import math
    tiles = math.ceil(w / 750) * math.ceil(h / 750)
    return tiles * 1601 + 85


async def baseline(property_url_or_id: str, max_images: int, offset: int) -> None:
    """Fetch listing directly via property_core, calculate real token costs."""
    print(f"\n{'='*65}")
    print("BASELINE (direct property_core call — no server needed)")
    print(f"{'='*65}")

    from property_core import fetch_listing

    t0 = time.perf_counter()
    listing = fetch_listing(property_url_or_id)
    elapsed = time.perf_counter() - t0

    listing_dict = listing.model_dump() if hasattr(listing, "model_dump") else {}

    image_urls: list[str] = listing_dict.get("images") or []
    total_images = len(image_urls)
    listing_id = listing_dict.get("id") or listing_dict.get("property_id") or property_url_or_id

    print(f"\nListing:          {listing_id}")
    print(f"Fetch time:       {elapsed:.2f}s")
    print(f"Images available: {total_images}")
    print(f"Fetching:         {max_images} (offset {offset})")

    text_payload = json.dumps(listing_dict, default=str)
    text_tokens = count_tokens(text_payload)

    slice_ = image_urls[offset : offset + max_images]

    print(f"\n{'─'*65}")
    print(f"{'#':<4} {'Dimensions':<14} {'Size':>8}  {'Claude tokens':>14}")
    print(f"{'─'*65}")

    total_image_tokens = 0
    total_bytes = 0

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for i, url in enumerate(slice_, start=offset + 1):
            try:
                r = await client.get(url)
                r.raise_for_status()
                raw = r.content
                total_bytes += len(raw)

                dims = jpeg_dimensions(raw)
                if dims:
                    w, h = dims
                    img_tokens = claude_image_tokens(w, h)
                    dim_str = f"{w}×{h}"
                else:
                    img_tokens = 1601 + 85  # assume 1 tile if unknown
                    dim_str = "unknown"

                total_image_tokens += img_tokens
                short_url = ("…" + url[-48:]) if len(url) > 51 else url
                print(f"[{i:<2}] {dim_str:<14} {fmt_kb(len(raw)):>8}  {fmt_tokens(img_tokens):>14}")
            except Exception as e:
                short_url = ("…" + url[-48:]) if len(url) > 51 else url
                print(f"[{i:<2}] {'ERROR':<14} {'─':>8}  {'─':>14}  ({e})")

    print(f"{'─'*65}")
    print(f"\nText payload tokens (tiktoken):   {fmt_tokens(text_tokens)}")
    print(f"Image tokens ({len(slice_)} images, Claude): {fmt_tokens(total_image_tokens)}")
    print(f"Total image bytes:                {fmt_kb(total_bytes)}")
    print(f"Grand total tokens:               {fmt_tokens(text_tokens + total_image_tokens)}")
    print()


async def live(property_url_or_id: str, max_images: int, offset: int) -> None:
    """Call the running MCP server via fastmcp.Client and measure response token cost."""
    from fastmcp import Client
    from mcp.types import ImageContent, TextContent

    print(f"\n{'='*65}")
    print(f"LIVE (MCP server at {SERVER_URL})")
    print(f"{'='*65}")

    t0 = time.perf_counter()
    try:
        async with Client(SERVER_URL) as client:
            result = await client.call_tool(
                "get_listing_detail",
                {
                    "property_url_or_id": property_url_or_id,
                    "max_images": max_images,
                    "image_offset": offset,
                },
            )
            content_blocks = result.content
            structured_content = result.structured_content or {}
    except Exception as e:
        print(f"\n  Server not reachable: {e}")
        print("  Start the server with: uv run property-descriptions")
        return
    elapsed = time.perf_counter() - t0

    text_blocks = [b for b in content_blocks if isinstance(b, TextContent)]
    image_blocks = [b for b in content_blocks if isinstance(b, ImageContent)]

    text_tokens = sum(count_tokens(b.text) for b in text_blocks)
    structured_tokens = count_tokens(json.dumps(structured_content, default=str))

    print(f"\nServer response time:             {elapsed:.2f}s")
    print(f"Content blocks:                   {len(content_blocks)}")
    print(f"  Text: {len(text_blocks)}   Image: {len(image_blocks)}")

    print(f"\n{'─'*65}")
    print(f"{'#':<4} {'Dimensions':<14} {'Size':>8}  {'Claude tokens':>14}")
    print(f"{'─'*65}")

    total_image_tokens = 0
    for i, block in enumerate(image_blocks, 1):
        raw = base64.b64decode(block.data + "==")
        dims = jpeg_dimensions(raw)
        if dims:
            w, h = dims
            img_tokens = claude_image_tokens(w, h)
            dim_str = f"{w}×{h}"
        else:
            img_tokens = 1601 + 85
            dim_str = "unknown"
        total_image_tokens += img_tokens
        print(f"[{i:<2}] {dim_str:<14} {fmt_kb(len(raw)):>8}  {fmt_tokens(img_tokens):>14}")

    print(f"{'─'*65}")
    print(f"\nText content tokens (tiktoken):   {fmt_tokens(text_tokens)}")
    print(f"Structured content tokens:        {fmt_tokens(structured_tokens)}")
    print(f"Image tokens ({len(image_blocks)} images, Claude): {fmt_tokens(total_image_tokens)}")
    print(f"Grand total tokens:               {fmt_tokens(text_tokens + structured_tokens + total_image_tokens)}")
    print()


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    property_url_or_id = sys.argv[1]
    max_images = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    offset = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    print(f"\nSmoke test — property: {property_url_or_id}")
    print(f"max_images={max_images}  offset={offset}")

    await baseline(property_url_or_id, max_images, offset)
    await live(property_url_or_id, max_images, offset)


if __name__ == "__main__":
    asyncio.run(main())
