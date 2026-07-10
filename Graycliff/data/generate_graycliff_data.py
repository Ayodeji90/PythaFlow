"""Generate a realistic synthetic dataset for the Graycliff demo.

Graycliff hasn't shared real POS data yet, so the demo platform runs on
synthetic data shaped like a luxury Nassau fine-dining operation: strong
winter tourism peak, Fri/Sat dinner spikes, holiday surges, a deep wine
program, and the estate's signature chocolate and cigar lines.

Usage:
    python data/generate_graycliff_data.py

Writes CSVs to data/seed/: menu.csv, guests.csv, orders.csv,
order_items.csv, inventory.csv, events.csv, reservations.csv.
Deterministic (seeded) so rebuilds produce identical data.
"""

import csv
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)

TODAY = date(2026, 7, 10)
HISTORY_DAYS = 365
SEED_DIR = Path(__file__).parent / "seed"

# ---------------------------------------------------------------------------
# Menu — (name, category, price, cost, tags, description)
# ---------------------------------------------------------------------------
MENU = [
    # Starters
    ("Bahamian Conch Fritters", "Starter", 24, 6.5, "conch,seafood,fried,local", "Golden conch fritters with calypso rémoulade"),
    ("Stone Crab Claws", "Starter", 38, 14, "crab,seafood,chilled,local", "Chilled Bahamian stone crab with mustard aioli"),
    ("Seared Foie Gras", "Starter", 34, 12, "foie-gras,rich,french", "Seared foie gras, guava glaze, brioche"),
    ("Tuna Tartare", "Starter", 28, 9, "tuna,seafood,raw,light", "Yellowfin tartare, plantain crisps, citrus soy"),
    ("Escargot Bourguignonne", "Starter", 26, 7, "escargot,french,garlic", "Burgundy snails, garlic-herb butter"),
    ("Caribbean Lobster Bisque", "Starter", 22, 6, "lobster,soup,seafood,rich", "Silky lobster bisque, cognac cream"),
    ("Conch Chowder Graycliff", "Starter", 19, 5, "conch,soup,local,spiced", "House conch chowder, dark rum, thyme"),
    ("Caesar Salad Tableside", "Starter", 21, 5.5, "salad,classic,tableside", "Prepared tableside with white anchovies"),
    ("Heirloom Tomato & Burrata", "Starter", 23, 7, "salad,vegetarian,fresh", "Island tomatoes, burrata, basil oil"),
    # Mains
    ("Grilled Bahamian Lobster Thermidor", "Main", 92, 30, "lobster,seafood,signature,grilled", "Whole local lobster, thermidor glaze"),
    ("Pan-Seared Grouper", "Main", 58, 17, "grouper,seafood,local", "Nassau grouper, lemon beurre blanc"),
    ("Wagyu Beef Tenderloin A5", "Main", 145, 52, "wagyu,beef,premium", "Japanese A5 wagyu, truffle jus"),
    ("Rack of Lamb Provencale", "Main", 68, 22, "lamb,french,herbs", "Herb-crusted rack, ratatouille"),
    ("Duck a l'Orange", "Main", 62, 19, "duck,french,classic", "Crispy duckling, Grand Marnier orange sauce"),
    ("Filet Mignon au Poivre", "Main", 74, 24, "beef,steak,peppercorn", "Center-cut filet, green peppercorn cream"),
    ("Chateaubriand for Two", "Main", 190, 62, "beef,steak,sharing,tableside", "Carved tableside, sauce béarnaise"),
    ("Blackened Mahi-Mahi", "Main", 54, 15, "mahi,seafood,spiced,local", "Cajun-blackened mahi, mango salsa"),
    ("Seafood Linguine Graycliff", "Main", 56, 16, "pasta,seafood,lobster,shrimp", "Lobster, shrimp, scallops, saffron cream"),
    ("Cracked Conch, Peas 'n' Rice", "Main", 46, 12, "conch,local,fried,classic", "Island classic with island-spiced rice"),
    ("Vegetarian Wellington", "Main", 44, 10, "vegetarian,pastry,mushroom", "Wild mushroom & spinach wellington"),
    ("Chef's Five-Course Tasting", "Tasting", 165, 50, "tasting,signature,chef", "Five-course seasonal degustation"),
    # Desserts
    ("Graycliff Chocolate Souffle", "Dessert", 24, 5, "chocolate,souffle,signature", "Estate chocolate soufflé, vanilla anglaise"),
    ("Guava Duff with Rum Butter", "Dessert", 16, 3.5, "guava,local,classic", "Bahamian guava duff, aged rum butter"),
    ("Creme Brulee Madagascar", "Dessert", 15, 3, "custard,vanilla,classic", "Madagascar vanilla bean brûlée"),
    ("Key Lime Tart", "Dessert", 14, 3, "citrus,tart,light", "Key lime curd, toasted meringue"),
    ("Chocolatier Truffle Selection", "Dessert", 22, 5, "chocolate,truffles,signature", "Six truffles from Graycliff Chocolatier"),
    ("Baked Alaska Flambe", "Dessert", 26, 6, "flambe,tableside,classic", "Flamed tableside with 151 rum"),
    # Wine
    ("Chateau Margaux 2015", "Wine", 950, 400, "wine,red,bordeaux,premium", "Premier Grand Cru Classé, Margaux"),
    ("Opus One 2018", "Wine", 650, 270, "wine,red,napa,premium", "Napa Valley Bordeaux blend"),
    ("Dom Perignon 2013", "Wine", 480, 195, "wine,champagne,premium", "Vintage champagne, Épernay"),
    ("Graycliff Private Reserve Cabernet", "Wine", 220, 75, "wine,red,house,signature", "From the Graycliff cellar collection"),
    ("Barolo Riserva (glass)", "Wine", 28, 10, "wine,red,italian,glass", "Nebbiolo, Piedmont"),
    ("Chablis Grand Cru (glass)", "Wine", 26, 9, "wine,white,burgundy,glass", "Les Clos, mineral and precise"),
    ("Pinot Noir Russian River (glass)", "Wine", 22, 8, "wine,red,california,glass", "Silky, red-fruited"),
    ("Sauvignon Blanc Marlborough (glass)", "Wine", 16, 5, "wine,white,newzealand,glass", "Crisp, citrus, aromatic"),
    ("Sommelier Wine Pairing Flight", "Wine", 85, 30, "wine,pairing,tasting", "Paired pours for the tasting menu"),
    # Cocktails & beverages
    ("Graycliff Royale", "Beverage", 22, 5, "cocktail,champagne,signature", "Champagne, hibiscus, gold sugar rim"),
    ("Bahama Mama", "Beverage", 16, 3.5, "cocktail,rum,tropical", "Two rums, coconut, island juices"),
    ("Classic Martini", "Beverage", 18, 4, "cocktail,gin,classic", "Stirred, olive or twist"),
    ("Espresso Martini", "Beverage", 17, 4, "cocktail,coffee", "Espresso, vodka, coffee liqueur"),
    ("Bahamian Switcha Lemonade", "Beverage", 9, 1.5, "mocktail,citrus,local", "Fresh native limes, cane sugar"),
    ("San Pellegrino 750ml", "Beverage", 8, 2, "water,sparkling", "Sparkling mineral water"),
    # Cigars (post-dinner lounge)
    ("Graycliff Chateau Grand Cru Cigar", "Cigar", 65, 16, "cigar,signature,lounge", "Rolled at the estate factory"),
    ("Graycliff Turbo Cigar", "Cigar", 48, 12, "cigar,signature,lounge", "Medium-bodied estate blend"),
]

# Wine pairing map: main-dish name -> wine name (drives the upsell demo)
PAIRINGS = {
    "Grilled Bahamian Lobster Thermidor": "Chablis Grand Cru (glass)",
    "Pan-Seared Grouper": "Sauvignon Blanc Marlborough (glass)",
    "Wagyu Beef Tenderloin A5": "Chateau Margaux 2015",
    "Rack of Lamb Provencale": "Barolo Riserva (glass)",
    "Duck a l'Orange": "Pinot Noir Russian River (glass)",
    "Filet Mignon au Poivre": "Opus One 2018",
    "Chateaubriand for Two": "Chateau Margaux 2015",
    "Blackened Mahi-Mahi": "Sauvignon Blanc Marlborough (glass)",
    "Seafood Linguine Graycliff": "Chablis Grand Cru (glass)",
    "Cracked Conch, Peas 'n' Rice": "Sauvignon Blanc Marlborough (glass)",
    "Vegetarian Wellington": "Pinot Noir Russian River (glass)",
    "Chef's Five-Course Tasting": "Sommelier Wine Pairing Flight",
    "Graycliff Chocolate Souffle": "Dom Perignon 2013",
    "Chocolatier Truffle Selection": "Graycliff Private Reserve Cabernet",
}

# Item popularity weights within each category (index-aligned per category order)
POPULARITY = {
    "Bahamian Conch Fritters": 9, "Stone Crab Claws": 5, "Seared Foie Gras": 4,
    "Tuna Tartare": 6, "Escargot Bourguignonne": 2, "Caribbean Lobster Bisque": 6,
    "Conch Chowder Graycliff": 7, "Caesar Salad Tableside": 6, "Heirloom Tomato & Burrata": 4,
    "Grilled Bahamian Lobster Thermidor": 10, "Pan-Seared Grouper": 9,
    "Wagyu Beef Tenderloin A5": 3, "Rack of Lamb Provencale": 5, "Duck a l'Orange": 2,
    "Filet Mignon au Poivre": 7, "Chateaubriand for Two": 2, "Blackened Mahi-Mahi": 6,
    "Seafood Linguine Graycliff": 6, "Cracked Conch, Peas 'n' Rice": 7, "Vegetarian Wellington": 2,
    "Chef's Five-Course Tasting": 3,
    "Graycliff Chocolate Souffle": 9, "Guava Duff with Rum Butter": 7, "Creme Brulee Madagascar": 5,
    "Key Lime Tart": 5, "Chocolatier Truffle Selection": 4, "Baked Alaska Flambe": 3,
    "Chateau Margaux 2015": 1, "Opus One 2018": 1, "Dom Perignon 2013": 2,
    "Graycliff Private Reserve Cabernet": 4, "Barolo Riserva (glass)": 5,
    "Chablis Grand Cru (glass)": 6, "Pinot Noir Russian River (glass)": 6,
    "Sauvignon Blanc Marlborough (glass)": 8, "Sommelier Wine Pairing Flight": 2,
    "Graycliff Royale": 6, "Bahama Mama": 8, "Classic Martini": 6, "Espresso Martini": 6,
    "Bahamian Switcha Lemonade": 5, "San Pellegrino 750ml": 7,
    "Graycliff Chateau Grand Cru Cigar": 3, "Graycliff Turbo Cigar": 4,
}

FIRST_NAMES = ["James", "Olivia", "Michael", "Sophia", "Robert", "Emma", "David", "Isabella",
               "William", "Charlotte", "Richard", "Amelia", "Thomas", "Grace", "Daniel",
               "Chloe", "Marcus", "Elena", "Pierre", "Ingrid", "Hans", "Marie", "Carlos",
               "Lucia", "Andre", "Natasha", "Kwame", "Aaliyah", "Trevor", "Simone"]
LAST_NAMES = ["Thompson", "Rolle", "Ferguson", "Smith", "Johnson", "Williams", "Müller",
              "Dubois", "Rossi", "García", "Anderson", "Clarke", "Bethel", "Knowles",
              "Moss", "Pinder", "Sands", "Butler", "Davies", "O'Brien", "Nakamura",
              "Petrov", "Larsson", "van der Berg", "Martin", "Taylor", "Moore", "Wright"]
COUNTRIES = ["United States"] * 45 + ["Canada"] * 12 + ["United Kingdom"] * 12 + \
            ["Bahamas"] * 10 + ["Germany"] * 6 + ["France"] * 5 + ["Switzerland"] * 4 + \
            ["Italy"] * 3 + ["Brazil"] * 3

# ---------------------------------------------------------------------------
# Demand model
# ---------------------------------------------------------------------------
MONTH_FACTOR = {1: 1.30, 2: 1.35, 3: 1.30, 4: 1.15, 5: 0.95, 6: 0.85,
                7: 0.90, 8: 0.70, 9: 0.60, 10: 0.75, 11: 1.00, 12: 1.35}
DOW_FACTOR = {0: 0.70, 1: 0.80, 2: 0.90, 3: 1.00, 4: 1.30, 5: 1.40, 6: 1.00}

SPECIAL_DATES = {
    date(2025, 7, 10): (1.3, "Bahamas Independence Day"),
    date(2025, 8, 4): (1.2, "Emancipation Day"),
    date(2025, 12, 24): (1.5, "Christmas Eve"),
    date(2025, 12, 25): (1.4, "Christmas Day"),
    date(2025, 12, 26): (1.5, "Boxing Day Junkanoo"),
    date(2025, 12, 31): (2.0, "New Year's Eve Gala"),
    date(2026, 1, 1): (1.4, "New Year's Day Junkanoo"),
    date(2026, 2, 14): (1.8, "Valentine's Day"),
    date(2026, 4, 3): (1.3, "Good Friday"),
    date(2026, 4, 5): (1.4, "Easter Sunday"),
    date(2026, 5, 10): (1.6, "Mother's Day"),
    date(2026, 6, 21): (1.3, "Father's Day"),
    date(2026, 7, 4): (1.2, "US Independence Day"),
    date(2026, 7, 10): (1.3, "Bahamas Independence Day"),
}


def parties_for(day: date) -> int:
    base = 26.0
    factor = MONTH_FACTOR[day.month] * DOW_FACTOR[day.weekday()]
    special = SPECIAL_DATES.get(day, (1.0, ""))[0]
    noise = random.gauss(1.0, 0.10)
    return max(4, round(base * factor * special * noise))


def main() -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    # --- menu.csv ---
    menu_rows = []
    id_by_name = {}
    for i, (name, cat, price, cost, tags, desc) in enumerate(MENU, start=1):
        id_by_name[name] = i
        menu_rows.append({
            "id": i, "name": name, "category": cat, "price": price, "cost": cost,
            "tags": tags, "description": desc,
            "pairing_item_id": "",  # filled below
            "active": 1,
        })
    for dish, wine in PAIRINGS.items():
        menu_rows[id_by_name[dish] - 1]["pairing_item_id"] = id_by_name[wine]

    # --- guests.csv ---
    guests = []
    for gid in range(1, 501):
        first, last = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
        # Spend-frequency skew: a small VIP core dines often
        r = random.random()
        if r < 0.06:
            tier, weight = "VIP", 12
        elif r < 0.22:
            tier, weight = "Gold", 5
        else:
            tier, weight = "Standard", 1
        guests.append({
            "id": gid, "name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower().replace(' ', '').replace(chr(39), '')}{gid}@example.com",
            "tier": tier, "weight": weight,
            "country": random.choice(COUNTRIES),
            "hotel_guest": 1 if random.random() < 0.4 else 0,
            "dietary": random.choices(
                ["none", "pescatarian", "vegetarian", "gluten-free", "shellfish-allergy"],
                weights=[70, 10, 8, 7, 5])[0],
        })
    guest_pool = [g["id"] for g in guests for _ in range(g["weight"])]

    # --- orders + order_items ---
    by_cat = {}
    for row in menu_rows:
        by_cat.setdefault(row["category"], []).append(row)

    def pick(cat: str):
        rows = by_cat[cat]
        weights = [POPULARITY[r["name"]] for r in rows]
        return random.choices(rows, weights=weights)[0]

    orders, order_items = [], []
    oid = iid = 0
    start = TODAY - timedelta(days=HISTORY_DAYS)
    for offset in range(HISTORY_DAYS + 1):
        day = start + timedelta(days=offset)
        for _ in range(parties_for(day)):
            oid += 1
            covers = random.choices([1, 2, 3, 4, 5, 6], weights=[8, 42, 18, 20, 7, 5])[0]
            guest_id = random.choice(guest_pool) if random.random() < 0.65 else ""
            # Dinner-heavy service; lunch is a smaller sitting
            if random.random() < 0.25:
                hour, minute = random.randint(12, 14), random.choice([0, 15, 30, 45])
            else:
                hour, minute = random.randint(18, 21), random.choice([0, 15, 30, 45])
            placed = datetime(day.year, day.month, day.day, hour, minute)
            total = 0.0
            lines = {}

            def add(item, qty=1):
                nonlocal total
                lines[item["id"]] = lines.get(item["id"], 0) + qty
                total += item["price"] * qty

            for _cover in range(covers):
                if random.random() < 0.05:
                    add(pick("Tasting"))
                    if random.random() < 0.5:
                        add(next(r for r in by_cat["Wine"] if r["name"] == "Sommelier Wine Pairing Flight"))
                else:
                    if random.random() < 0.62:
                        add(pick("Starter"))
                    if random.random() < 0.88:
                        add(pick("Main"))
                    if random.random() < 0.48:
                        add(pick("Dessert"))
                if random.random() < 0.58:
                    add(pick("Wine" if random.random() < 0.45 else "Beverage"))
            if random.random() < 0.07:
                add(pick("Cigar"))

            for item_id, qty in lines.items():
                iid += 1
                price = menu_rows[item_id - 1]["price"]
                order_items.append({"id": iid, "order_id": oid, "item_id": item_id,
                                    "qty": qty, "unit_price": price})
            orders.append({
                "id": oid, "placed_at": placed.isoformat(sep=" "),
                "service_date": day.isoformat(), "guest_id": guest_id,
                "covers": covers, "table_no": random.randint(1, 22),
                "channel": random.choices(["dine-in", "qr-menu", "room-service"],
                                          weights=[70, 20, 10])[0],
                "total": round(total, 2),
            })

    # --- inventory.csv (deliberate waste-risk and stockout cases for the demo) ---
    OVERSTOCKED = {"Duck a l'Orange": 58, "Escargot Bourguignonne": 44,
                   "Vegetarian Wellington": 40, "Baked Alaska Flambe": 35}
    UNDERSTOCKED = {"Grilled Bahamian Lobster Thermidor": 9, "Pan-Seared Grouper": 12,
                    "Bahamian Conch Fritters": 10}
    inventory = []
    for row in menu_rows:
        name = row["name"]
        if name in OVERSTOCKED:
            stock = OVERSTOCKED[name]
        elif name in UNDERSTOCKED:
            stock = UNDERSTOCKED[name]
        elif row["category"] == "Wine":
            stock = random.randint(12, 120)
        elif row["category"] == "Cigar":
            stock = random.randint(40, 90)
        else:
            stock = random.randint(18, 45)
        shelf = {"Starter": 3, "Main": 3, "Tasting": 2, "Dessert": 4,
                 "Wine": 3650, "Beverage": 365, "Cigar": 730}[row["category"]]
        # Bestsellers carry a deep par level, so the understocked ones
        # actually trip the low-stock alert on the dashboard.
        par = 25 if name in UNDERSTOCKED else max(8, int(stock * 0.6))
        inventory.append({
            "item_id": row["id"], "stock": stock,
            "par_level": par,
            "unit": "bottles" if row["category"] == "Wine" else "portions",
            "shelf_life_days": shelf,
            "last_restock": (TODAY - timedelta(days=random.randint(0, 3))).isoformat(),
        })

    # --- events.csv (next 60 days — feeds marketing generator & forecast context) ---
    events = []
    def ev(d, name, etype, impact):
        events.append({"date": d.isoformat(), "name": name, "type": etype, "impact": impact})
    ev(date(2026, 7, 10), "Bahamas Independence Day", "holiday", "high")
    ev(date(2026, 8, 3), "Emancipation Day", "holiday", "medium")
    for offset in range(60):
        d = TODAY + timedelta(days=offset)
        if d.weekday() == 5 and d.month == 7:
            ev(d, "Junkanoo Summer Festival, Bay Street", "festival", "high")
        if d.weekday() in (1, 3, 5):
            ev(d, "Cruise ship arrivals, Nassau Harbour", "cruise", "medium")
    ev(date(2026, 7, 24), "Graycliff Wine Cellar Dinner", "hotel_event", "high")
    ev(date(2026, 8, 21), "Graycliff Chocolatier Pairing Evening", "hotel_event", "high")
    events.sort(key=lambda e: e["date"])

    # --- reservations.csv (next 14 days) ---
    reservations = []
    rid = 0
    for offset in range(14):
        d = TODAY + timedelta(days=offset)
        for _ in range(round(parties_for(d) * 0.45)):
            rid += 1
            g = random.choice(guests)
            reservations.append({
                "id": rid, "guest_id": g["id"], "guest_name": g["name"],
                "date": d.isoformat(),
                "time": random.choice(["18:00", "18:30", "19:00", "19:30", "20:00", "20:30"]),
                "party_size": random.choices([2, 3, 4, 5, 6], weights=[45, 15, 25, 8, 7])[0],
                "status": "confirmed", "source": random.choice(["phone", "web", "hotel-concierge"]),
            })

    # --- write ---
    def dump(name, rows, drop=()):
        path = SEED_DIR / name
        rows = [{k: v for k, v in r.items() if k not in drop} for r in rows]
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"  {name:22s} {len(rows):>7,} rows")

    print(f"Writing seed data to {SEED_DIR}/")
    dump("menu.csv", menu_rows)
    dump("guests.csv", guests, drop=("weight",))
    dump("orders.csv", orders)
    dump("order_items.csv", order_items)
    dump("inventory.csv", inventory)
    dump("events.csv", events)
    dump("reservations.csv", reservations)
    revenue = sum(o["total"] for o in orders)
    print(f"\n12-month synthetic revenue: ${revenue:,.0f} "
          f"({len(orders):,} orders, avg check ${revenue/len(orders):.2f})")


if __name__ == "__main__":
    main()
