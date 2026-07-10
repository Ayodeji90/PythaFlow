# fetch_bahamas_restaurants.py
"""Utility script to fetch a list of restaurants in the Bahamas using the Google Places API.

Prerequisites
-------------
* A Google Cloud project with the **Places API** enabled.
* An API key with the appropriate permissions. Store the key in an environment variable
  named ``GOOGLE_PLACES_API_KEY`` (or replace ``os.getenv`` with a literal string – **do not**
  commit the key to the repository).
* ``requests`` library – install with ``pip install requests``.

Usage
-----
```bash
export GOOGLE_PLACES_API_KEY=YOUR_KEY_HERE
python scripts/fetch_bahamas_restaurants.py > bahamas_restaurants.csv
```
The script writes a CSV to stdout with the following columns:
```
name, address, latitude, longitude, rating, user_ratings_total, place_id, website, phone_number
```
Only restaurants with a rating of **4.0** or higher and at least **30** user ratings are kept –
this filters out low‑traffic venues and gives you a solid starting set for outreach.
"""

import os
import sys
import csv
import time
from typing import List, Dict, Any
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
if not API_KEY:
    sys.stderr.write("Error: GOOGLE_PLACES_API_KEY environment variable not set.\n")
    sys.exit(1)

# Bahamas country code (ISO 3166‑1 alpha‑2) – used to restrict the search.
COUNTRY_CODE = "BS"
# Search radius in metres – 50 km is a reasonable default to cover the main islands.
RADIUS = 50000
# Minimum rating and review count to keep a venue.
MIN_RATING = 4.0
MIN_USER_RATINGS = 30
# Google Places endpoint URLs
NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def fetch_nearby(lat: float, lng: float, next_page_token: str = None) -> Dict[str, Any]:
    """Call the Nearby Search endpoint.

    Parameters
    ----------
    lat, lng: float
        Latitude and longitude of the centre point.
    next_page_token: str, optional
        Token for pagination – if supplied, ``pagetoken`` is sent instead of location.
    """
    params = {
        "key": API_KEY,
        "type": "restaurant",
        "radius": RADIUS,
        "language": "en",
    }
    if next_page_token:
        params["pagetoken"] = next_page_token
    else:
        params["location"] = f"{lat},{lng}"
        params["keyword"] = "restaurant"
        params["region"] = COUNTRY_CODE
    response = requests.get(NEARBY_SEARCH_URL, params=params)
    response.raise_for_status()
    return response.json()


def fetch_details(place_id: str) -> Dict[str, Any]:
    """Retrieve additional fields for a place.

    Returns a dictionary with ``name``, ``formatted_address``, ``website``, ``international_phone_number``
    and other useful fields.
    """
    params = {
        "key": API_KEY,
        "place_id": place_id,
        "fields": "name,formatted_address,geometry,website,international_phone_number,rating,user_ratings_total",
        "language": "en",
    }
    resp = requests.get(DETAILS_URL, params=params)
    resp.raise_for_status()
    return resp.json().get("result", {})


def centre_points() -> List[Dict[str, float]]:
    """Return a set of latitude/longitude points that roughly cover the Bahamas.

    The Bahamas is an archipelago; we use a few central points to ensure coverage.
    """
    return [
        {"lat": 25.0343, "lng": -77.3963},  # Nassau (New Providence)
        {"lat": 26.5333, "lng": -78.7000},  # Freeport (Grand Bahama)
        {"lat": 23.5061, "lng": -75.7597},  # George Town (Exuma)
        {"lat": 24.7000, "lng": -77.7667},  # Fresh Creek (Andros)
    ]


def main() -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow([
        "name",
        "address",
        "latitude",
        "longitude",
        "rating",
        "user_ratings_total",
        "place_id",
        "website",
        "phone_number",
    ])

    seen_place_ids = set()
    for centre in centre_points():
        next_token = None
        while True:
            data = fetch_nearby(centre["lat"], centre["lng"], next_token)
            for entry in data.get("results", []):
                place_id = entry.get("place_id")
                if not place_id or place_id in seen_place_ids:
                    continue
                seen_place_ids.add(place_id)
                # Basic filters – rating & review count are available in the nearby result.
                rating = entry.get("rating", 0)
                user_ratings = entry.get("user_ratings_total", 0)
                if rating < MIN_RATING or user_ratings < MIN_USER_RATINGS:
                    continue
                # Pull detailed info for fields not present in the nearby response.
                details = fetch_details(place_id)
                name = details.get("name", entry.get("name", ""))
                address = details.get("formatted_address", entry.get("vicinity", ""))
                # The 50 km radius around some islands reaches Florida and the
                # Turks & Caicos — keep only venues actually in the Bahamas.
                if "bahamas" not in address.lower():
                    continue
                geometry = details.get("geometry", {}).get("location", {})
                lat = geometry.get("lat")
                lng = geometry.get("lng")
                website = details.get("website", "")
                phone = details.get("international_phone_number", "")
                writer.writerow([
                    name,
                    address,
                    lat,
                    lng,
                    rating,
                    user_ratings,
                    place_id,
                    website,
                    phone,
                ])
            # Pagination – if a next_page_token is present we must wait a short period before using it.
            next_token = data.get("next_page_token")
            if not next_token:
                break
            time.sleep(2)  # Google recommends a short pause before the next request.

if __name__ == "__main__":
    main()