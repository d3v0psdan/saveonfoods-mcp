"""Smallest check that fails if the storefront API or our mapping breaks: uv run python check.py"""

import re

import server

deals = server.search_products("chicken", on_sale_only=True, limit=5)
assert deals["total"] > 0 and deals["items"], deals
assert all(p["on_sale"] for p in deals["items"]), deals["items"]
assert deals["items"][0]["price"].startswith("$"), deals["items"][0]

cheapest = server.search_products("tofu", sort="price", limit=10)["items"]
prices = [float(re.search(r"[\d.]+", p["price"]).group()) for p in cheapest]
assert len(prices) > 1 and prices == sorted(prices), prices

departments = {c["name"]: c["id"] for c in server.list_categories()}
assert departments["Meat & Seafood"] == "30791", departments
assert any(c.get("children") for c in server.list_categories("30791", depth=2)), "depth 2 returned no sub-departments"

detail = server.product_details(deals["items"][0]["sku"])
assert detail["regular_price"] and detail["on_sale"], detail
cheese = next(
    d for d in (server.product_details(p["sku"]) for p in server.search_products("shredded cheese", limit=8)["items"])
    if d["ingredients"]
)
assert "milk" in cheese["ingredients"].lower() and "Calories" in cheese["nutrition"], cheese

basket = server.price_check(["ground beef", "sour cream", "zzqxv-nothing"])
assert basket["estimated_total"] > 0 and basket["missing"] == ["zzqxv-nothing"], basket

stores = {s["store_id"]: s["name"] for s in server.find_stores("Edmonton")}
assert stores.get("6613") == "9th & Jasper", stores

print("ok:", deals["total"], "chicken items on sale;", cheapest[0]["name"], cheapest[0]["price"])
