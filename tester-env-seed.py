#!/usr/bin/env python3
"""Deterministic Grocy seed data and its verification for the tester-env baseline.

Theme: a shared household ("Maple Street") runs its kitchen stock in Grocy.

  Master data  4 locations (default Fridge + Freezer/Pantry/Cellar),
               5 quantity units (default Piece/Pack + Bottle/Can/Loaf),
               6 product groups, 2 shopping locations (stores).
  Products    12 products (10 with stock, dish soap out of stock and below its
               minimum, coffee beans discontinued/inactive), 2 fixed barcodes.
  Stock       12 stock entries with fixed purchased/best-before dates and
               prices; whole milk has two entries so FEFO order is visible.
  Lists       "Weekly groceries" (the default list, renamed) with 3 items and
               "Weekend market" with 2 items (one note-only).
  Recipes     "Winter vegetable soup", 4 servings, 3 positions, fully in stock.
  Chores      4 chores with fixed start dates; one has a fixed tracked
               execution so its next execution is derived from a fixed date.
  Tasks       3 tasks (one overdue, one open, one completed) in 2 categories.

All writes go through the documented object and stock API with the admin
session cookie; no direct SQLite access. Every date is an absolute fixed date,
so the visible state does not drift with the wall clock. Seed wipes only its
own business data (products, lists, recipes, chores, tasks and the master data
it creates) and rebuilds it, so re-running seed is idempotent.

Usage:
  tester-env-seed.py seed   <base-url>   # e.g. http://localhost:8088
  tester-env-seed.py verify <base-url>
"""

import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

USERNAME = "admin"
PASSWORD = "admin"

# --- Master data -----------------------------------------------------------

# name, description, is_freezer
LOCATIONS = [
    ("Freezer", "Chest freezer in the utility room", 1),
    ("Pantry", "Dry goods cupboard next to the oven", 0),
    ("Cellar", "Bulk storage and drinks", 0),
]
DEFAULT_LOCATION = "Fridge"

# name, plural
QUANTITY_UNITS = [
    ("Bottle", "Bottles"),
    ("Can", "Cans"),
    ("Loaf", "Loaves"),
]
DEFAULT_QUANTITY_UNITS = ["Piece", "Pack"]

PRODUCT_GROUPS = [
    ("Dairy & eggs", "Chilled dairy, butter and eggs"),
    ("Bakery", "Bread and baked goods"),
    ("Produce", "Fresh and frozen vegetables"),
    ("Pantry staples", "Dry goods, rice and stock"),
    ("Drinks", "Water and coffee"),
    ("Household", "Cleaning supplies"),
]

# name, description
SHOPPING_LOCATIONS = [
    ("Corner Grocer", "Neighbourhood shop, open until 21:00"),
    ("Riverside Market", "Saturday farmers market"),
]

# name, description, group, location, shopping location, qu, min stock, active
PRODUCTS = [
    ("Whole milk", "Semi-skimmed, 1 L bottle", "Dairy & eggs", "Fridge",
     "Corner Grocer", "Bottle", 2, 1),
    ("Free-range eggs", "Six medium eggs", "Dairy & eggs", "Fridge",
     "Corner Grocer", "Pack", 1, 1),
    ("Sourdough loaf", "Baked on Saturday mornings", "Bakery", "Pantry",
     "Riverside Market", "Loaf", 0, 1),
    ("Unsalted butter", "250 g block", "Dairy & eggs", "Fridge",
     "Corner Grocer", "Pack", 1, 1),
    ("Greek yoghurt", "500 g tub, plain", "Dairy & eggs", "Fridge",
     "Corner Grocer", "Pack", 2, 1),
    ("Cherry tomatoes", "250 g punnet", "Produce", "Fridge",
     "Riverside Market", "Pack", 0, 1),
    ("Frozen peas", "1 kg bag", "Produce", "Freezer",
     "Corner Grocer", "Pack", 1, 1),
    ("Basmati rice", "1 kg bag", "Pantry staples", "Pantry",
     "Corner Grocer", "Pack", 1, 1),
    ("Vegetable stock cubes", "Six cubes per pack", "Pantry staples", "Pantry",
     "Corner Grocer", "Pack", 1, 1),
    ("Sparkling water", "500 ml bottle", "Drinks", "Cellar",
     "Corner Grocer", "Bottle", 6, 1),
    ("Dish soap", "Lemon scented, 500 ml", "Household", "Pantry",
     "Corner Grocer", "Bottle", 2, 1),
    ("Coffee beans", "Medium roast, 250 g; delisted when the grinder broke",
     "Drinks", "Pantry", "Corner Grocer", "Pack", 1, 0),
]

# product -> one or more (amount, best before, purchased, price) stock entries
STOCK_ENTRIES = {
    "Whole milk": [
        (3, "2026-11-29", "2026-11-16", 1.19),
        (2, "2026-12-06", "2026-11-21", 1.19),
    ],
    "Free-range eggs": [(2, "2026-12-02", "2026-11-15", 2.49)],
    "Sourdough loaf": [(1, "2026-11-24", "2026-11-21", 3.20)],
    "Unsalted butter": [(2, "2027-01-15", "2026-11-05", 2.10)],
    "Greek yoghurt": [(1, "2026-11-26", "2026-11-19", 1.75)],
    "Cherry tomatoes": [(2, "2026-11-27", "2026-11-20", 1.40)],
    "Frozen peas": [(2, "2027-04-30", "2026-09-30", 1.60)],
    "Basmati rice": [(3, "2027-10-31", "2026-10-12", 3.49)],
    "Vegetable stock cubes": [(3, "2027-05-31", "2026-10-12", 1.85)],
    "Sparkling water": [(8, "2027-08-31", "2026-11-08", 0.45)],
}

PRODUCT_BARCODES = [
    ("Whole milk", "4001234567890"),
    ("Free-range eggs", "4009876543217"),
]

# name, description, items [(product or None, amount, note)]
SHOPPING_LISTS = [
    ("Weekly groceries", "Saturday shop at the Corner Grocer", [
        ("Dish soap", 2, "Lemon scent"),
        ("Greek yoghurt", 2, "500 g tubs"),
        ("Coffee beans", 1, "Whole beans, medium roast"),
    ]),
    ("Weekend market", "Saturday morning at the Riverside Market", [
        ("Cherry tomatoes", 1, "Ask for the vine ones"),
        (None, 0, "Collect the bread order"),
    ]),
]
DEFAULT_LIST = "Weekly groceries"

# name, description, period type, interval, period days, period config,
# start date, tracked time or None
CHORES = [
    ("Water the herbs", "Kitchen window herbs and the balcony pots", "daily",
     2, 1, None, "2026-11-23 08:00:00", None),
    ("Clean the fridge", "Empty, wipe and check the dates", "monthly",
     1, 1, None, "2026-11-28 10:00:00", None),
    ("Defrost the freezer", "Move frozen goods to the cellar freezer", "yearly",
     1, 1, None, "2026-12-15 09:00:00", None),
    ("Take out the recycling", "Paper, glass and plastics go out together",
     "weekly", 1, 1, "monday", "2026-11-10 09:30:00", "2026-11-17 09:30:00"),
]

# name, description
TASK_CATEGORIES = [
    ("Household", "Maintenance around the flat"),
    ("Garden", "Balcony and shared courtyard"),
]

# name, description, due date, done, done timestamp, category
TASKS = [
    # due dates are date-only, exactly what the task form's date picker writes
    ("Order a replacement fridge filter", "The current filter was fitted in April",
     "2026-11-10", 0, None, "Household"),
    ("Clean the gutters", "Before the first storm of the season",
     "2026-11-29", 0, None, "Garden"),
    ("Book the boiler service", "Annual service, quote accepted",
     "2026-11-05", 1, "2026-11-05 14:20:00", "Household"),
]

RECIPE = ("Winter vegetable soup", "A weeknight soup built from the pantry", 4)
# product, amount, note
RECIPE_POSITIONS = [
    ("Cherry tomatoes", 2, "Or one 400 g can of chopped tomatoes"),
    ("Frozen peas", 1, None),
    ("Vegetable stock cubes", 2, "Two cubes per litre of water"),
]

# --- Expected state --------------------------------------------------------

EXPECTED_STOCK = {
    name: sum(entry[0] for entry in entries)
    for name, entries in STOCK_ENTRIES.items()
}
EXPECTED_STOCK.update({"Dish soap": 0, "Coffee beans": 0})


class ApiError(Exception):
    pass


class Grocy:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method, path, body=None, form=False):
        data = None
        headers = {}
        if body is not None:
            if form:
                data = urllib.parse.urlencode(body).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    def login(self):
        status, _ = self.request("GET", "/login")
        if status != 200:
            raise ApiError("GET /login returned HTTP %s" % status)
        status, _ = self.request(
            "POST", "/login", {"username": USERNAME, "password": PASSWORD}, form=True)
        # A successful login answers 302 on /login; following it lands on the
        # entry page (HTTP 200). Either way the session cookie must exist.
        if status not in (200, 302):
            raise ApiError("POST /login returned HTTP %s" % status)
        if not any(cookie.name.startswith("grocy_session") for cookie in self.jar):
            raise ApiError("login did not return a grocy session cookie")

    def json(self, method, path, body=None):
        status, text = self.request(method, path, body)
        if status not in (200, 204):
            raise ApiError("%s %s returned HTTP %s: %s"
                           % (method, path, status, text[:300]))
        if not text:
            return None
        return json.loads(text)

    def objects(self, entity):
        return self.json("GET", "/api/objects/" + entity)

    def delete(self, entity, object_id):
        status, text = self.request("DELETE", "/api/objects/%s/%s" % (entity, object_id))
        if status not in (200, 204):
            raise ApiError("DELETE %s/%s returned HTTP %s: %s"
                           % (entity, object_id, status, text[:300]))

    def create(self, entity, payload):
        result = self.json("POST", "/api/objects/" + entity, payload)
        return int(result["created_object_id"])

    def html(self, path):
        status, text = self.request("GET", path)
        if status != 200:
            raise ApiError("GET %s returned HTTP %s" % (path, status))
        return text


def wipe(client):
    """Remove the business data this seed owns, dependencies first."""
    for entity in ("meal_plan", "shopping_list", "recipes_pos", "recipes",
                   "products", "product_barcodes", "chores", "tasks",
                   "task_categories", "shopping_lists", "product_groups",
                   "shopping_locations", "locations", "quantity_units"):
        for row in client.objects(entity):
            name = row.get("name")
            if entity == "locations" and name == DEFAULT_LOCATION:
                continue
            if entity == "quantity_units" and name in DEFAULT_QUANTITY_UNITS:
                continue
            # Keep the migration's default list (id 1) and the two lists the
            # seed owns; only their items are wiped.
            if entity == "shopping_lists" and (row["id"] == 1 or name in
                                               [row[0] for row in SHOPPING_LISTS]):
                continue
            client.delete(entity, row["id"])


def seed(base_url):
    client = Grocy(base_url)
    client.login()
    wipe(client)

    locations = {}
    for name, description, is_freezer in LOCATIONS:
        locations[name] = client.create("locations", {
            "name": name, "description": description, "is_freezer": is_freezer})
    fridge_id = next(row["id"] for row in client.objects("locations")
                     if row["name"] == DEFAULT_LOCATION)

    units = {row["name"]: row["id"] for row in client.objects("quantity_units")}
    for name, plural in QUANTITY_UNITS:
        units[name] = client.create("quantity_units", {
            "name": name, "name_plural": plural})

    groups = {}
    for name, description in PRODUCT_GROUPS:
        groups[name] = client.create("product_groups", {
            "name": name, "description": description})

    stores = {}
    for name, description in SHOPPING_LOCATIONS:
        stores[name] = client.create("shopping_locations", {
            "name": name, "description": description})

    products = {}
    for (name, description, group, location, store, unit, min_stock,
         active) in PRODUCTS:
        products[name] = client.create("products", {
            "name": name,
            "description": description,
            "product_group_id": groups[group],
            "location_id": fridge_id if location == DEFAULT_LOCATION else locations[location],
            "shopping_location_id": stores[store],
            "qu_id_purchase": units[unit],
            "qu_id_stock": units[unit],
            "qu_id_price": units[unit],
            "min_stock_amount": min_stock,
            "default_best_before_days": 0,
            "active": active,
        })

    for product, barcode in PRODUCT_BARCODES:
        client.create("product_barcodes", {
            "product_id": products[product], "barcode": barcode, "amount": 1})

    for product, entries in STOCK_ENTRIES.items():
        for amount, best_before, purchased, price in entries:
            client.json("POST", "/api/stock/products/%s/add" % products[product], {
                "amount": amount,
                "best_before_date": best_before,
                "purchased_date": purchased,
                "price": price,
                "transaction_type": "purchase",
            })

    lists = {row["name"]: row["id"] for row in client.objects("shopping_lists")}
    if DEFAULT_LIST in lists:
        default_list_id = lists[DEFAULT_LIST]
    elif 1 in lists.values():
        # Migration 0019 ships the default list with id 1; rename it so plain
        # /shoppinglist keeps working on a fixed list id.
        default_list_id = 1
        client.json("PUT", "/api/objects/shopping_lists/1", {"name": DEFAULT_LIST})
    else:
        default_list_id = client.create("shopping_lists", {"name": DEFAULT_LIST})
    for name, description, items in SHOPPING_LISTS:
        if name == DEFAULT_LIST:
            list_id = default_list_id
            client.json("PUT", "/api/objects/shopping_lists/%s" % list_id,
                        {"name": name, "description": description})
        else:
            list_id = lists.get(name) or client.create(
                "shopping_lists", {"name": name, "description": description})
        for product, amount, note in items:
            client.create("shopping_list", {
                "shopping_list_id": list_id,
                "product_id": products[product] if product else None,
                "amount": amount,
                "note": note,
            })

    chores = {}
    for (name, description, period_type, interval, period_days, period_config,
         start_date, tracked_time) in CHORES:
        chores[name] = client.create("chores", {
            "name": name,
            "description": description,
            "period_type": period_type,
            "period_interval": interval,
            "period_days": period_days,
            "period_config": period_config,
            "start_date": start_date,
            "track_date_only": 0,
            "rollover": 0,
            "active": 1,
        })
        if tracked_time:
            client.json("POST", "/api/chores/%s/execute" % chores[name],
                        {"tracked_time": tracked_time})

    categories = {}
    for name, description in TASK_CATEGORIES:
        categories[name] = client.create("task_categories", {
            "name": name, "description": description})
    for name, description, due_date, done, done_timestamp, category in TASKS:
        client.create("tasks", {
            "name": name,
            "description": description,
            "due_date": due_date,
            "done": done,
            "done_timestamp": done_timestamp,
            "category_id": categories[category],
            "assigned_to_user_id": 1,
        })

    recipe_id = client.create("recipes", {
        "name": RECIPE[0],
        "description": RECIPE[1],
        "base_servings": RECIPE[2],
    })
    for product, amount, note in RECIPE_POSITIONS:
        client.create("recipes_pos", {
            "recipe_id": recipe_id,
            "product_id": products[product],
            "amount": amount,
            "note": note,
        })

    print("    products:  %d (%d with stock, %d stock entries)"
          % (len(PRODUCTS), len(STOCK_ENTRIES), sum(len(v) for v in STOCK_ENTRIES.values())))
    print("    lists:     Weekly groceries (3 items), Weekend market (2 items)")
    print("    chores:    %d, tasks: %d, recipes: 1" % (len(CHORES), len(TASKS)))


# --- Verification ----------------------------------------------------------

def verify(base_url):
    client = Grocy(base_url)
    client.login()
    failures = []

    def check(label, condition, detail=""):
        if condition:
            print("    ok   %s" % label)
        else:
            print("    FAIL %s %s" % (label, detail))
            failures.append(label)

    def by_name(rows):
        return {row["name"]: row for row in rows}

    def finish():
        if failures:
            print("==> Verify FAILED (%d checks)" % len(failures))
            sys.exit(1)

    locations = by_name(client.objects("locations"))
    check("locations are Fridge/Freezer/Pantry/Cellar",
          sorted(locations) == sorted([DEFAULT_LOCATION] + [row[0] for row in LOCATIONS]),
          sorted(locations))
    check("Freezer is flagged as a freezer location",
          locations.get("Freezer", {}).get("is_freezer") == 1)

    units = by_name(client.objects("quantity_units"))
    check("quantity units are Piece/Pack/Bottle/Can/Loaf",
          sorted(units) == sorted(DEFAULT_QUANTITY_UNITS + [row[0] for row in QUANTITY_UNITS]),
          sorted(units))
    check("Bottle plural is Bottles", units.get("Bottle", {}).get("name_plural") == "Bottles")

    groups = by_name(client.objects("product_groups"))
    check("6 product groups", sorted(groups) == sorted(row[0] for row in PRODUCT_GROUPS),
          sorted(groups))
    stores = by_name(client.objects("shopping_locations"))
    check("shopping locations are Corner Grocer/Riverside Market",
          sorted(stores) == sorted(row[0] for row in SHOPPING_LOCATIONS), sorted(stores))
    # Everything below resolves names through these maps; a missing master-data
    # row means the database is not seeded, so stop with the failures above.
    finish()

    products = by_name(client.objects("products"))
    check("12 products", sorted(products) == sorted(row[0] for row in PRODUCTS),
          len(products))
    for (name, _description, group, location, _store, unit, min_stock, active) in PRODUCTS:
        product = products.get(name, {})
        check("product %s attributes" % name,
              product.get("product_group_id") == groups[group]["id"]
              and product.get("location_id") == locations[location]["id"]
              and product.get("qu_id_stock") == units[unit]["id"]
              and product.get("min_stock_amount") == min_stock
              and product.get("active") == active)
    finish()

    for product, barcode in PRODUCT_BARCODES:
        details = client.json("GET", "/api/stock/products/by-barcode/" + barcode)
        check("barcode %s resolves to %s" % (barcode, product),
              details["product"]["id"] == products[product]["id"])

    for product, entries in STOCK_ENTRIES.items():
        details = client.json("GET", "/api/stock/products/%s/entries"
                              % products[product]["id"])
        actual = sorted((float(row["amount"]), row["best_before_date"],
                         row["purchased_date"], float(row["price"]))
                        for row in details)
        expected = sorted((float(amount), best_before, purchased, price)
                          for amount, best_before, purchased, price in entries)
        check("stock entries for %s" % product, actual == expected,
              "%s != %s" % (actual, expected))
    stock_amounts = {
        row["product"]["name"]: float(row["amount"])
        for row in client.json("GET", "/api/stock")
    }
    for name, amount in EXPECTED_STOCK.items():
        check("stock amount for %s is %s" % (name, amount),
              stock_amounts.get(name, 0.0) == float(amount),
              stock_amounts.get(name, 0.0))

    lists = {row["name"]: row for row in client.objects("shopping_lists")}
    check("2 shopping lists", sorted(lists) == sorted(
        name for name, _description, _items in SHOPPING_LISTS), sorted(lists))
    items = client.objects("shopping_list")
    product_names = {row["id"]: name for name, row in products.items()}
    for name, _description, expected_items in SHOPPING_LISTS:
        actual = sorted(
            ((product_names.get(row["product_id"]), float(row["amount"]), row["note"])
             for row in items if row["shopping_list_id"] == lists[name]["id"]),
            key=lambda item: (item[0] or "", item[1], item[2] or ""))
        expected = sorted(((product, float(amount), note)
                           for product, amount, note in expected_items),
                          key=lambda item: (item[0] or "", item[1], item[2] or ""))
        check("items of %s" % name, actual == expected, "%s != %s" % (actual, expected))
    finish()

    chores = {row["chore_name"]: row for row in client.json("GET", "/api/chores")}
    check("4 chores", sorted(chores) == sorted(row[0] for row in CHORES), sorted(chores))
    next_execution = {
        "Water the herbs": "2026-11-23 08:00:00",
        "Clean the fridge": "2026-11-28 10:00:00",
        "Defrost the freezer": "2026-12-15 09:00:00",
        "Take out the recycling": "2026-11-23 09:30:00",
    }
    for name, expected in next_execution.items():
        check("next execution of %s is %s" % (name, expected),
              (chores.get(name) or {}).get("next_estimated_execution_time") == expected,
              (chores.get(name) or {}).get("next_estimated_execution_time"))
    finish()
    details = client.json("GET", "/api/chores/%s" % chores["Take out the recycling"]["id"])
    check("recycling last tracked at 2026-11-17 09:30:00",
          details["last_tracked"] == "2026-11-17 09:30:00",
          details["last_tracked"])

    categories = by_name(client.objects("task_categories"))
    check("2 task categories", sorted(categories) == sorted(
        row[0] for row in TASK_CATEGORIES), sorted(categories))
    tasks = by_name(client.objects("tasks"))
    check("3 tasks", sorted(tasks) == sorted(row[0] for row in TASKS), sorted(tasks))
    check("'Order a replacement fridge filter' is open and due 2026-11-10",
          tasks.get("Order a replacement fridge filter", {}).get("done") == 0
          and tasks["Order a replacement fridge filter"].get("due_date") == "2026-11-10")
    check("'Book the boiler service' is done since 2026-11-05 14:20:00",
          tasks.get("Book the boiler service", {}).get("done") == 1
          and tasks["Book the boiler service"].get("done_timestamp") == "2026-11-05 14:20:00")

    recipes = by_name(client.objects("recipes"))
    recipe = recipes.get(RECIPE[0], {})
    check("recipe %s exists with 4 servings" % RECIPE[0],
          recipe.get("base_servings") == 4 and recipe.get("desired_servings") == 4)
    finish()
    positions = sorted(
        (product_names[row["product_id"]], float(row["amount"]))
        for row in client.objects("recipes_pos") if row["recipe_id"] == recipe["id"])
    check("recipe positions", positions == sorted(
        (product, float(amount)) for product, amount, _note in RECIPE_POSITIONS),
        positions)
    fulfillment = client.json("GET", "/api/recipes/%s/fulfillment" % recipe["id"])
    check("recipe is fully in stock and costs 8.10",
          fulfillment["need_fulfilled"] == 1
          and fulfillment["missing_products_count"] == 0
          and abs(float(fulfillment["costs"]) - 8.10) < 0.001,
          fulfillment)

    pages = {
        "/stockoverview": ["Stock overview", "Whole milk", "Dish soap", "Fridge"],
        "/products": ["Whole milk", "Vegetable stock cubes", "Dairy &amp; eggs"],
        "/shoppinglist": ["Weekly groceries", "Weekend market", "Dish soap"],
        "/chores": ["Take out the recycling", "Water the herbs"],
        "/recipes": [RECIPE[0]],
        "/tasks": ["Order a replacement fridge filter", "Clean the gutters"],
    }
    for path, needles in pages.items():
        body = client.html(path)
        missing = [needle for needle in needles if needle not in body]
        check("%s renders %s" % (path, ", ".join(needles)), not missing, missing)

    finish()
    print("    seed data: all checks passed")

def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("seed", "verify"):
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "seed":
        print("==> Seeding deterministic household data through the Grocy API...")
        seed(sys.argv[2])
        print("==> Seed complete.")
    else:
        print("==> Verifying seeded household data...")
        verify(sys.argv[2])


if __name__ == "__main__":
    main()
