# saveon-mcp

An MCP server that gives Claude live prices and stock from one Save-On-Foods store: 9th & Jasper, 10180 109 Street NW, downtown Edmonton. Ask what is on sale this week, search for an ingredient, or have Claude plan dinners from the flyer. It reads the same public storefront API that saveonfoods.com uses, so prices match the website.

It covers one store at a time and is read only. It does not place orders, sign in to More Rewards, or show personalised offers.

## What you get

Five tools and one prompt.

- `search_products` searches the catalogue with live prices and returns the match count plus a slim product list.
  Parameters: `query`, `category_id`, `on_sale_only`, `sort` (`relevance`, `price`, `price desc`), `limit`, `skip`.
  Fields per product: sku, name, price, unit price, on sale, sale end date, availability, category.
- `product_details` returns one product by sku: regular and sale price, ingredients with the allergen statement, nutrition facts per serving, country of origin flags and an image URL. Fresh meat and produce usually carry no ingredients or nutrition.
- `price_check` prices a whole shopping list in one call. For each item it returns the best match (preferring an on-sale hit), the cheapest match, and an estimated total.
- `find_stores` lists Save-On-Foods locations in a city with the store id, address, hours, phone and pickup or delivery availability.
- `list_categories` returns the department tree (Meat & Seafood, Fruits & Vegetables, Pantry, and so on) with the ids you pass to `search_products`.
- `meal_ideas` is a prompt that walks Claude through pulling deals per department and proposing priced dinners.

Questions it answers well:

- What is on sale for dinner this week?
- Find the cheapest tofu.
- Everything on sale in Meat & Seafood, cheapest first.
- Plan three dinners under $20 each from the flyer.
- Price this list: ground beef, taco kit, shredded cheese, sour cream.
- Does the Tex Mex cheese contain anything besides milk?

## Setup

You need Python 3.13 or newer and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/d3v0psdan/saveonfoods-mcp.git
cd saveonfoods-mcp
uv sync
uv run python check.py   # hits the live API; prints "ok: ..." when the mapping still works
```

Register it with Claude Code so every project can use it:

```sh
claude mcp add -s user saveon-foods -- uv --directory /path/to/saveon-mcp run server.py
```

For Claude Desktop, add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "saveon-foods": {
      "command": "uv",
      "args": ["--directory", "/path/to/saveon-mcp", "run", "server.py"]
    }
  }
}
```

Restart the client. The tools show up as `saveon-foods`.

## Using a different store

The store is set by the `SAVEON_STORE_ID` environment variable and defaults to `6613` (9th & Jasper). Any Save-On-Foods location works. To find a store number, list the stores and look at `retailerStoreId`:

```sh
curl -H "X-Site-Host: https://www.saveonfoods.com" \
  "https://storefrontgateway.saveonfoods.com/api/stores?take=300"
```

Then pass it at registration:

```sh
claude mcp add -s user -e SAVEON_STORE_ID=6609 saveon-foods -- uv --directory /path/to/saveon-mcp run server.py
```

## How it works

The website talks to `storefrontgateway.saveonfoods.com`. The only header the gateway requires is `X-Site-Host: https://www.saveonfoods.com`. No login, no API key.

The site's own search endpoint, `/api/stores/{id}/search`, sits behind a Cloudflare challenge and returns 403 to anything that is not a browser. The per-category endpoint, `/api/stores/{id}/categories/{categoryId}/search`, is open and accepts the same `q`, `sort`, `skip`, `take` and `fpromotions` parameters. The server sends every query to that endpoint rooted at the Grocery department (id `30372`), which covers the whole store.

`fpromotions=True` limits results to promoted items. Sale prices are temporary price reductions that run Thursday to Wednesday, and the server reads the end date from the active entry in `tprPrice`. The promotion index lags a little and returns a few items with no active markdown, so the server drops those when `on_sale_only` is set. The API caps page size at 100.

Responses are cut down to eight fields per product so a 50 item result stays small enough to reason over.

## Files

- `server.py` is the whole server: HTTP client, five tools, one prompt.
- `check.py` is the smallest check that fails if the API or the field mapping breaks. Run it after any change.
- `pyproject.toml` and `uv.lock` pin the dependencies: `mcp` and `httpx`.

## Known gaps

- Search results show the current price only. Call `product_details` for the regular price of a sale item.
- `price_check` runs one search per item, so a 20 item list takes a few seconds.
- The gateway is unofficial. If Save-On-Foods changes it, `check.py` is the first thing that will fail.

## License

[MIT](LICENSE).
