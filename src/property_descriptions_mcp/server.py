import os
import json
from pathlib import Path
from typing import Any

import anyio
import httpx
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from fastmcp.apps import AppConfig, ResourceCSP
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

from property_core import (
    PPDService,
    EPCClient,
    PostcodeClient,
    RightmoveLocationAPI,
    fetch_listings,
    fetch_listing,
    enrich_comps_with_epc,
    compute_enriched_stats,
    classify_price_position,
    estimate_value_range,
)


PPD_TIMEOUT_S = float(os.environ.get("PPD_TIMEOUT_S", "4"))
EPC_TIMEOUT_S = float(os.environ.get("EPC_TIMEOUT_S", "4"))
POSTCODE_TIMEOUT_S = float(os.environ.get("POSTCODE_TIMEOUT_S", "3"))
RIGHTMOVE_TIMEOUT_S = float(os.environ.get("RIGHTMOVE_TIMEOUT_S", "4"))
IMAGE_TIMEOUT_S = float(os.environ.get("IMAGE_TIMEOUT_S", "5"))

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse


RESOURCE_URI = "ui://property-descriptions/dashboard"


mcp = FastMCP(
    "Property Descriptions",
    instructions="""UK property description generator for estate agents.

Tools available:
- get_property_data: Fetch comparable sales, EPC, current listings, and location data for any UK postcode. Call this first.
- get_listing_detail: Get a Rightmove listing's full details (description, images, key features).
- format_for_portals: Display your written descriptions in the interactive dashboard with copy buttons.

Workflow:
1. User gives you an address/postcode (and optionally a Rightmove URL or images)
2. Call get_property_data to understand the market context
3. Write three description variants (Professional, Luxury, Family-friendly) grounded in the data
4. Write portal formats: Rightmove summary (max 300 chars), social caption, email subject, bullet points
5. Call format_for_portals to display everything in the dashboard

You are the copywriter. The tools give you data. You write the descriptions.
Each description should be 150-200 words. Key features should be 5-7 bullet points.
Ground every claim in the data — name real streets, cite real comparable prices, reference the actual EPC rating.""",
)


def _to_dict(obj: Any) -> Any:
    """Recursively convert Pydantic models / nested structures to plain dicts.

    Drops None-valued dict entries to keep MCP responses lean. property_core
    Pydantic models declare many optional fields (EPC enrichment, escalation
    metadata) that are always null in typical responses and waste LLM context.

    The image-bytes vision flow in get_listing_detail is unaffected: the
    `images` URL list is a populated list[str], not None.
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]

    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return _to_dict(model_dump(exclude_none=True))

    dict_method = getattr(obj, "dict", None)
    if callable(dict_method):
        return _to_dict(dict_method())

    return str(obj)


async def _run_sync_with_timeout(fn, timeout_s: float, *args, **kwargs):
    with anyio.fail_after(timeout_s):
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


def _compact_comps(comps: Any, limit: int = 10) -> list[dict]:
    items = []
    if comps is None:
        return items

    if isinstance(comps, dict) and "transactions" in comps:
        comps = comps.get("transactions")

    if not isinstance(comps, list):
        try:
            comps = list(comps)
        except Exception:
            return items

    for c in comps[:limit]:
        d = _to_dict(c)
        if not isinstance(d, dict):
            continue
        items.append(
            {
                "address": d.get("address") or d.get("full_address") or d.get("paon") or "",
                "postcode": d.get("postcode") or "",
                "price": d.get("price") or d.get("amount") or d.get("transaction_price"),
                "date": d.get("date") or d.get("transaction_date") or d.get("transfer_date"),
                "property_type": d.get("property_type") or d.get("ptype") or "",
            }
        )

    return items


def _summarise_numbers(values: list[int | float]) -> dict:
    clean = [v for v in values if isinstance(v, (int, float))]
    if not clean:
        return {}
    clean_sorted = sorted(clean)
    return {
        "count": len(clean_sorted),
        "min": clean_sorted[0],
        "max": clean_sorted[-1],
        "median": clean_sorted[len(clean_sorted) // 2],
    }


@mcp.tool(app=AppConfig(resource_uri=RESOURCE_URI))
async def get_property_data(
    postcode: str,
    address: str | None = None,
    price: int | None = None,
    bedrooms: int | None = None,
    property_type: str | None = None,
) -> ToolResult:
    """Fetch property market data for writing informed descriptions.

    Returns comparable sales, EPC energy data, current market listings,
    and location context. Use this data to ground your descriptions in facts.

    Args:
        postcode: UK postcode (e.g. "NG2 7PP")
        address: Street address for EPC matching (e.g. "14 Musters Road")
        price: Asking price in GBP — used for market positioning
        bedrooms: Number of bedrooms — filters comparable listings
        property_type: F (flat), D (detached), S (semi-detached), T (terrace)
    """

    subject = {
        "postcode": postcode,
        "address": address,
        "price": price,
        "bedrooms": bedrooms,
        "property_type": property_type,
    }

    errors: dict[str, str] = {}

    comps_raw = None
    try:
        comps_raw = await _run_sync_with_timeout(
            PPDService().comps,
            PPD_TIMEOUT_S,
            postcode=postcode,
            property_type=property_type,
            months=24,
            address=address,
        )
    except TimeoutError:
        errors["ppd_comps"] = f"timed out after {PPD_TIMEOUT_S}s"
    except Exception as e:
        errors["ppd_comps"] = str(e)

    comps_top = _compact_comps(_to_dict(comps_raw), limit=10)
    comp_prices = [c.get("price") for c in comps_top if c.get("price") is not None]
    comp_stats = _summarise_numbers([p for p in comp_prices if isinstance(p, (int, float))])
    comps_summary = ""
    if comp_stats:
        comps_summary = (
            f"{comp_stats.get('count', 0)} comps shown • "
            f"median £{int(comp_stats.get('median', 0)):,} • "
            f"range £{int(comp_stats.get('min', 0)):,}–£{int(comp_stats.get('max', 0)):,}"
        )

    epc_raw = None
    try:
        with anyio.fail_after(EPC_TIMEOUT_S):
            epc_raw = await EPCClient().search_by_postcode(postcode, address=address)
    except TimeoutError:
        errors["epc"] = f"timed out after {EPC_TIMEOUT_S}s"
    except Exception as e:
        errors["epc"] = str(e)

    epc_first = None
    try:
        if isinstance(epc_raw, list) and epc_raw:
            epc_first = _to_dict(epc_raw[0])
        elif epc_raw is not None:
            epc_first = _to_dict(epc_raw)
    except Exception as e:
        errors["epc_parse"] = str(e)

    enriched_stats = None
    if comps_raw is not None and epc_raw is not None:
        try:
            enriched = await enrich_comps_with_epc(comps_raw, epc_raw)
            enriched_stats = _to_dict(compute_enriched_stats(enriched))
        except Exception as e:
            errors["enrichment"] = str(e)

    location_raw = None
    try:
        with anyio.fail_after(POSTCODE_TIMEOUT_S):
            location_raw = await PostcodeClient().lookup(postcode)
    except TimeoutError:
        errors["postcode_lookup"] = f"timed out after {POSTCODE_TIMEOUT_S}s"
    except Exception as e:
        errors["postcode_lookup"] = str(e)

    location = {}
    try:
        location_d = _to_dict(location_raw)
        if isinstance(location_d, dict):
            location = {
                "admin_district": location_d.get("admin_district") or location_d.get("adminDistrict"),
                "admin_ward": location_d.get("admin_ward") or location_d.get("adminWard"),
                "region": location_d.get("region"),
                "country": location_d.get("country"),
                "rural_urban": location_d.get("rural_urban")
                or location_d.get("rural_urban_classification")
                or location_d.get("ruralUrbanClassification"),
                "longitude": location_d.get("longitude"),
                "latitude": location_d.get("latitude"),
            }
    except Exception as e:
        errors["postcode_parse"] = str(e)

    listings = {}
    try:
        api = RightmoveLocationAPI()
        try:
            search_url = api.build_search_url(
                postcode=postcode,
                radius=0.25,
                bedrooms=bedrooms,
                property_type=property_type,
            )
        except TypeError:
            search_url = api.build_search_url(postcode=postcode, radius=0.25)

        fetched = await _run_sync_with_timeout(fetch_listings, RIGHTMOVE_TIMEOUT_S, search_url)
        fetched_d = _to_dict(fetched)

        results = []
        if isinstance(fetched_d, dict) and "listings" in fetched_d:
            results = fetched_d.get("listings") or []
        elif isinstance(fetched_d, list):
            results = fetched_d

        prices = []
        for r in results:
            if isinstance(r, dict):
                p = r.get("price") or r.get("asking_price") or r.get("amount")
                if isinstance(p, (int, float)):
                    prices.append(p)

        listings_stats = _summarise_numbers(prices)
        if listings_stats:
            listings_summary = (
                f"{listings_stats.get('count', 0)} listings • "
                f"median £{int(listings_stats.get('median', 0)):,}"
            )
        else:
            listings_summary = f"{len(results)} listings"

        listings = {
            "count": len(results),
            "summary": listings_summary,
        }
    except TimeoutError:
        errors["rightmove"] = f"timed out after {RIGHTMOVE_TIMEOUT_S}s"
    except Exception as e:
        errors["rightmove"] = str(e)

    analysis: dict[str, Any] = {}
    try:
        if price is not None and comps_raw is not None:
            analysis["price_position"] = _to_dict(classify_price_position(price=price, comps=comps_raw))
    except Exception as e:
        errors["price_position"] = str(e)

    try:
        if comps_raw is not None:
            analysis["estimated_value_range"] = _to_dict(estimate_value_range(comps=comps_raw))
    except Exception as e:
        errors["estimate_value_range"] = str(e)

    payload = {
        "kind": "property_data",
        "subject": subject,
        "comps": {
            "top": comps_top,
            "summary": comps_summary,
            "stats": comp_stats,
            "enriched_stats": enriched_stats,
        },
        "epc": {
            "rating": (epc_first or {}).get("current_energy_rating")
            or (epc_first or {}).get("currentEnergyRating")
            or (epc_first or {}).get("rating"),
            "raw": None,
        },
        "location": location,
        "listings": listings,
        "analysis": analysis,
        "errors": errors,
    }

    text = (
        f"Property data for {postcode}. "
        f"Comps shown: {len(comps_top)}. "
        f"EPC: {payload['epc'].get('rating') or 'n/a'}. "
        f"Listings: {payload.get('listings', {}).get('count', 0) or 0}."
    )

    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
    )


async def _fetch_images(
    urls: list[str],
    max_images: int,
    offset: int,
    timeout_s: float,
) -> list[Image]:
    slice_ = urls[offset : offset + max_images]
    images = []
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        for url in slice_:
            try:
                r = await client.get(url)
                r.raise_for_status()
                fmt = "jpeg" if "jpeg" in r.headers.get("content-type", "") else "png"
                images.append(Image(data=r.content, format=fmt))
            except Exception:
                pass
    return images


@mcp.tool()
async def get_listing_detail(
    property_url_or_id: str,
    max_images: int = 8,
    image_offset: int = 0,
) -> ToolResult:
    """Get full details of a Rightmove listing including property photos.

    Returns the existing description, key features, agent info, and images.
    Images are fetched from Rightmove CDN and returned as visual content so
    you can see the property and write better-informed descriptions.

    Use image_offset to paginate: if the listing has 12 images and you fetched
    8, call again with image_offset=8 to get the remaining 4.

    Args:
        property_url_or_id: Rightmove property URL or numeric ID
        max_images: Number of photos to fetch and return (default 8)
        image_offset: Start index for pagination (default 0)
    """

    listing = await _run_sync_with_timeout(fetch_listing, IMAGE_TIMEOUT_S, property_url_or_id)
    listing_dict = _to_dict(listing)

    image_urls: list[str] = listing_dict.get("images") or []
    total_images = len(image_urls)

    images = await _fetch_images(image_urls, max_images, image_offset, IMAGE_TIMEOUT_S)

    summary = (
        f"Listing {property_url_or_id}. "
        f"Images: {len(images)} fetched (offset {image_offset}, {total_images} total)."
    )

    return ToolResult(
        content=[TextContent(type="text", text=summary), *[img.to_image_content() for img in images]],
        structured_content={
            **listing_dict,
            "images_total": total_images,
            "images_fetched": len(images),
            "images_offset": image_offset,
        },
    )


@mcp.tool(app=AppConfig(resource_uri=RESOURCE_URI))
async def format_for_portals(
    address: str,
    postcode: str | None = None,
    price: int | None = None,
    bedrooms: int | None = None,
    property_type: str | None = None,
    professional_headline: str = "",
    professional_description: str = "",
    professional_features: list[str] | None = None,
    luxury_headline: str = "",
    luxury_description: str = "",
    luxury_features: list[str] | None = None,
    family_headline: str = "",
    family_description: str = "",
    family_features: list[str] | None = None,
    rightmove_summary: str = "",
    social_caption: str = "",
    portal_features: list[str] | None = None,
    email_subject: str = "",
) -> ToolResult:
    """Display formatted property descriptions in the interactive dashboard.

    Call this AFTER you have written all three description variants and
    portal formats. The dashboard renders them with copy-to-clipboard buttons.

    Args:
        address: Full property address
        professional_headline: Professional tone headline (8-12 words)
        professional_description: Professional description (150-200 words)
        professional_features: Professional key selling points (5-7 items)
        luxury_headline: Luxury/aspirational headline
        luxury_description: Luxury description (150-200 words)
        luxury_features: Luxury key selling points
        family_headline: Family-friendly headline
        family_description: Family-friendly description (150-200 words)
        family_features: Family-friendly key selling points
        rightmove_summary: Rightmove portal summary (MAX 300 characters)
        social_caption: Instagram/Facebook caption (100-150 chars, emoji OK)
        portal_features: Portal bullet points (8-10 items)
        email_subject: Email subject line (MAX 60 characters)
    """

    payload = {
        "kind": "descriptions",
        "address": address,
        "postcode": postcode,
        "subject": {
            "price": price,
            "bedrooms": bedrooms,
            "property_type": property_type,
        },
        "variants": {
            "professional": {
                "headline": professional_headline,
                "description": professional_description,
                "features": professional_features or [],
            },
            "luxury": {
                "headline": luxury_headline,
                "description": luxury_description,
                "features": luxury_features or [],
            },
            "family": {
                "headline": family_headline,
                "description": family_description,
                "features": family_features or [],
            },
        },
        "portal": {
            "rightmove_summary": rightmove_summary,
            "social_caption": social_caption,
            "features": portal_features or [],
            "email_subject": email_subject,
        },
    }

    text = f"Dashboard rendered descriptions for {address}{f' ({postcode})' if postcode else ''}."

    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
    )


@mcp.resource(
    RESOURCE_URI,
    name="Property Description Dashboard",
    app=AppConfig(
        csp=ResourceCSP(
            resource_domains=["https://unpkg.com"],
        ),
    ),
)
def dashboard() -> str:
    """Interactive dashboard for reviewing and copying generated descriptions."""

    return (Path(__file__).parent / "ui" / "dashboard.html").read_text(encoding="utf-8")


@mcp.custom_route("/", methods=["GET"])
async def demo_page(request: Request):
    demo_file = Path(__file__).parent / "ui" / "demo.html"
    if demo_file.exists():
        return FileResponse(demo_file)
    return HTMLResponse(
        "<h1>Property Descriptions MCP Server</h1><p>Connect via MCP at /mcp</p>"
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/.well-known/glama.json", methods=["GET"])
async def glama_connector_manifest(request: Request) -> JSONResponse:
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [{"email": "paul@bouch.dev"}],
    })


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def server_card(request: Request) -> JSONResponse:
    return JSONResponse({"serverInfo": {"name": "property-descriptions-mcp", "version": "0.2.2"}})


class _AcceptNormalizer:
    """Stamp Accept to the MCP-spec value on /mcp only, so json_response=True never 406s.

    Anthropic sends mixed Accept headers per request type (application/json for
    initialize, text/event-stream for tools/list). Only stamp the MCP endpoint —
    leave /health, /.well-known/* with their original Accept headers.
    """
    def __init__(self, app, mcp_path: bytes = b"/mcp"):
        self.app = app
        self._mcp_path = mcp_path.rstrip(b"/")

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path", "").rstrip("/").encode() == self._mcp_path:
            headers = [
                (b"accept", b"application/json, text/event-stream")
                if name.lower() == b"accept"
                else (name, value)
                for name, value in scope.get("headers", [])
            ]
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


def main():
    import sys
    import uvicorn
    from fastmcp.server.http import create_streamable_http_app

    if "--stdio" in sys.argv:
        mcp.run()
    else:
        port = int(os.environ.get("PORT", "8080"))
        host = os.environ.get("HOST", "0.0.0.0")
        app = create_streamable_http_app(
            mcp,
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
        )
        uvicorn.run(
            _AcceptNormalizer(app),
            host=host,
            port=port,
            forwarded_allow_ips="*",
            proxy_headers=True,
            lifespan="on",
            log_level="info",
        )


if __name__ == "__main__":
    main()
