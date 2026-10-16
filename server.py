"""MCP server for the Save-On-Foods at 9th & Jasper (10180 109 St NW, downtown Edmonton).

Wraps the public storefront gateway that saveonfoods.com itself calls. The site's
/search endpoint sits behind a Cloudflare challenge, so every query goes through the
per-category search endpoint rooted at the Grocery department, which is open.
"""

import os
from functools import lru_cache
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer

STORE_ID = os.environ.get("SAVEON_STORE_ID", "6613")
GROCERY_ROOT = "30372"
PAGE_LIMIT = 100  # the API rejects take > 100

http = httpx.Client(
    base_url=f"https://storefrontgateway.saveonfoods.com/api/stores/{STORE_ID}",
    headers={"X-Site-Host": "https://www.saveonfoods.com", "Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    timeout=20,
)

mcp = MCPServer(
    "saveon-foods",
    instructions=(
        "Live catalogue and prices for the Save-On-Foods at 9th & Jasper, downtown Edmonton. "
        "Use search_products to find items (set on_sale_only for this week's deals), price_check to "
        "cost a whole shopping list in one call, product_details for ingredients and nutrition, and "
        "list_categories to discover department ids. Sale prices run Thursday to Wednesday."
    ),
)


def _get(path: str, **params) -> dict:
    response = http.get(path, params={k: v for k, v in params.items() if v not in (None, "", False)})
    response.raise_for_status()
    return response.json()


def _slim(product: dict) -> dict:
    active_sale = next((t for t in product.get("tprPrice") or [] if t.get("active")), None)
    default_category = (product.get("defaultCategory") or [{}])[0]
    return {
        "sku": product["sku"],
        "name": product["name"],
        "price": product["price"],
        "price_numeric": product.get("priceNumeric"),
        "unit_price": product.get("pricePerUnit"),
        "on_sale": product.get("priceSource") == "tpr",
        "sale_ends": active_sale.get("effectiveUntil") if active_sale else None,
        "available": product.get("available"),
        "category": default_category.get("categoryBreadcrumb"),
    }


@mcp.tool()
def search_products(
    query: str = "",
    category_id: str = GROCERY_ROOT,
    on_sale_only: bool = False,
    sort: Literal["relevance", "price", "price desc"] = "relevance",
    limit: int = 25,
    skip: int = 0,
) -> dict:
    """Search what the store stocks right now, with live prices.

    query: free text ("chicken thighs", "tofu"); empty lists the whole category.
    category_id: a department id from list_categories; defaults to all of Grocery.
    on_sale_only: only items with a current promotion (this week's deals).
    Returns the API's total match count plus up to `limit` (max 100) slimmed products; page with `skip`.
    """
    data = _get(
        f"/categories/{category_id}/search",
        q=query,
        take=min(limit, PAGE_LIMIT),
        skip=skip,
        sort=sort,
        fpromotions="True" if on_sale_only else None,
    )
    items = [_slim(p) for p in data["items"]]
    if on_sale_only:
        # ponytail: the fpromotions index is slightly stale and returns a few items with no
        # active markdown; drop them here so on_sale_only means what it says (pages may run short).
        items = [p for p in items if p["on_sale"]]
    return {"total": data["total"], "items": items}


@lru_cache(maxsize=1)
def _hierarchy() -> dict:
    return _get("/categoryhierarchy")


def _find(node: dict, identifier: str) -> dict | None:
    if node.get("identifier") == identifier:
        return node
    for child in node.get("children", []):
        if found := _find(child, identifier):
            return found
    return None


@mcp.tool()
def list_categories(parent_id: str = GROCERY_ROOT, depth: int = 1) -> list[dict]:
    """List departments under parent_id (default: top-level Grocery departments such as
    Meat & Seafood, Fruits & Vegetables, Deli & Ready Made Meals). Use the returned ids
    as category_id in search_products. depth 2 includes sub-departments."""
    parent = _find(_hierarchy(), parent_id)
    if parent is None:
        raise ValueError(f"unknown category id {parent_id}")

    def walk(node: dict, remaining: int) -> list[dict]:
        return [
            {
                "id": child["identifier"],
                "name": child["displayName"],
                **({"children": walk(child, remaining - 1)} if remaining > 1 else {}),
            }
            for child in node.get("children", [])
        ]

    return walk(parent, depth)


@mcp.tool()
def product_details(sku: str) -> dict:
    """Full detail for one product by sku (from search_products): regular and sale price,
    ingredients with allergen statement, nutrition facts per serving, country attributes
    and image URL. Fresh meat and produce usually carry no ingredients or nutrition."""
    d = _get(f"/products/{sku}")
    tpr = d.get("tprInfo") or {}
    nutrition = ((d.get("nutritionProfiles") or {}).get("nutrition")) or {}
    return {
        "sku": d["sku"],
        "name": d["name"],
        "brand": d.get("brand"),
        "description": d.get("description"),
        "price": d.get("price"),
        "regular_price": d.get("wasPrice"),
        "unit_price": d.get("unitPrice"),
        "on_sale": d.get("priceSource") == "tpr",
        "sale_ends": tpr.get("effectiveUntil"),
        "available": d.get("available"),
        "category": d.get("defaultCategory"),
        "ingredients": d.get("ingredients") or None,
        "serving": (d.get("servingSize") or {}).get("description") or None,
        "nutrition": {
            name: f"{v['size']:g} {v['abbreviation']}" + (f" ({v['percentDailyValue']:g}% DV)" if v.get("percentDailyValue") is not None else "")
            for name, v in nutrition.items()
        },
        "attributes": {k: v for k, v in (d.get("attributes") or {}).items() if v is True},
        "image": (d.get("primaryImage") or {}).get("default"),
    }


@mcp.tool()
def price_check(items: list[str], prefer_sale: bool = True) -> dict:
    """Price a shopping list in one call. For each item returns the best match (first
    relevance hit, or the first on-sale hit when prefer_sale is set) and the cheapest
    available match, plus an estimated total of the best matches. Items with no match
    are listed under `missing`."""
    priced, missing = [], []
    for item in items:
        hits = [p for p in search_products(item, limit=10)["items"] if p["available"]]
        if not hits:
            missing.append(item)
            continue
        best = next((p for p in hits if p["on_sale"]), hits[0]) if prefer_sale else hits[0]
        cheapest = min(hits, key=lambda p: p["price_numeric"] or float("inf"))
        priced.append({"item": item, "best_match": best, "cheapest": cheapest})
    total = sum(p["best_match"]["price_numeric"] or 0 for p in priced)
    return {"items": priced, "missing": missing, "estimated_total": round(total, 2)}


@mcp.tool()
def find_stores(city: str = "Edmonton") -> list[dict]:
    """Save-On-Foods locations in a city with the store id to use as SAVEON_STORE_ID,
    address, hours, phone and whether pickup or delivery is offered."""
    data = http.get("https://storefrontgateway.saveonfoods.com/api/stores", params={"take": 300})
    data.raise_for_status()
    return [
        {
            "store_id": s["retailerStoreId"],
            "name": s["name"],
            "address": f"{s['addressLine1']}, {s['city']}, {s['countyProvinceState']} {s['postCode']}",
            "hours": s.get("openingHours"),
            "phone": s.get("phone"),
            "services": s.get("shoppingModes", []),
        }
        for s in data.json()["items"]
        if city.lower() in (s.get("city") or "").lower()
    ]


@mcp.prompt()
def meal_ideas(preferences: str = "") -> str:
    """Suggest meals built around what is on sale this week at the downtown store."""
    return (
        "Plan 3 to 5 dinners from this week's deals at the Save-On-Foods at 9th & Jasper.\n"
        "1. Call list_categories, then search_products with on_sale_only=true for Meat & Seafood, "
        "Fruits & Vegetables, Dairy & Eggs, Pantry and Deli & Ready Made Meals (limit 50 each).\n"
        "2. Build each meal around one or two sale proteins or produce items. Fill gaps with "
        "search_products on the specific ingredient so every item is confirmed in stock.\n"
        "3. For each meal list the ingredients with store price, the approximate total, and a "
        "two-line cooking outline. Flag anything that is not on sale.\n"
        f"Preferences and constraints: {preferences or 'none given'}."
    )


if __name__ == "__main__":
    mcp.run()
