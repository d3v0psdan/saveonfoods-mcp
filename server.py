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
        "Use search_products to find items (set on_sale_only for this week's deals) and "
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
