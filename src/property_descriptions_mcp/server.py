import os
import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.apps import AppConfig, ResourceCSP
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
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]

    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return _to_dict(model_dump())

    dict_method = getattr(obj, "dict", None)
    if callable(dict_method):
        return _to_dict(dict_method())

    return str(obj)


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
        comps_raw = PPDService().comps(
            postcode=postcode,
            property_type=property_type,
            months=24,
            address=address,
        )
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
        epc_raw = await EPCClient().search_by_postcode(postcode, address=address)
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
        location_raw = await PostcodeClient().lookup(postcode)
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

        fetched = fetch_listings(search_url)
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


@mcp.tool()
async def get_listing_detail(property_url_or_id: str) -> dict:
    """Get full details of a Rightmove listing.

    Returns the existing description, images, key features, floor plans,
    and agent info. Use to improve on existing copy or reference images.

    Args:
        property_url_or_id: Rightmove property URL or numeric ID
    """

    listing = fetch_listing(property_url_or_id)
    return _to_dict(listing)


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


def main():
    import sys

    if "--stdio" in sys.argv:
        mcp.run()
    else:
        port = int(os.environ.get("PORT", "8080"))
        host = os.environ.get("HOST", "0.0.0.0")
        mcp.run(transport="http", host=host, port=port, stateless_http=True)


if __name__ == "__main__":
    main()
