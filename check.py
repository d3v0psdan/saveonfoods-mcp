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
assert server.list_categories("30791", depth=2)[0]["children"], "sub-departments missing"

print("ok:", deals["total"], "chicken items on sale;", cheapest[0]["name"], cheapest[0]["price"])
