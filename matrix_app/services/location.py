import re
import math
import requests

UP_DISTRICTS = [
    {"name": "Lucknow", "lat": 26.8467, "lng": 80.9462},
    {"name": "Ghaziabad", "lat": 28.6692, "lng": 77.4538},
    {"name": "Kanpur Nagar", "lat": 26.4499, "lng": 80.3319},
    {"name": "Agra", "lat": 27.1767, "lng": 78.0081},
    {"name": "Varanasi", "lat": 25.3176, "lng": 82.9739},
    {"name": "Prayagraj", "lat": 25.4358, "lng": 81.8463},
    {"name": "Meerut", "lat": 28.9845, "lng": 77.7064},
    {"name": "Bareilly", "lat": 28.3670, "lng": 79.4304},
    {"name": "Aligarh", "lat": 27.8974, "lng": 78.0880},
    {"name": "Moradabad", "lat": 28.8351, "lng": 78.7749},
    {"name": "Gorakhpur", "lat": 26.7606, "lng": 83.3731},
    {"name": "Jhansi", "lat": 25.4484, "lng": 78.5685},
    {"name": "Gautam Buddha Nagar", "lat": 28.5355, "lng": 77.3910},
    {"name": "Ayodhya", "lat": 26.7922, "lng": 82.1998},
    {"name": "Mathura", "lat": 27.4924, "lng": 77.6737},
    {"name": "Saharanpur", "lat": 29.9640, "lng": 77.5460},
    {"name": "Firozabad", "lat": 27.1500, "lng": 78.4000},
    {"name": "Muzaffarnagar", "lat": 29.4700, "lng": 77.7000},
    {"name": "Sitapur", "lat": 27.5600, "lng": 80.6800},
    {"name": "Hardoi", "lat": 27.3800, "lng": 80.1200},
    {"name": "Lakhimpur Kheri", "lat": 27.9400, "lng": 80.7700},
    {"name": "Rae Bareli", "lat": 26.2200, "lng": 81.2400},
    {"name": "Unnao", "lat": 26.5400, "lng": 80.4900},
    {"name": "Sultanpur", "lat": 26.2600, "lng": 82.0700},
    {"name": "Amethi", "lat": 26.1500, "lng": 81.8000},
    {"name": "Barabanki", "lat": 26.9200, "lng": 81.1800},
    {"name": "Bahraich", "lat": 27.5700, "lng": 81.6000},
    {"name": "Gonda", "lat": 27.1300, "lng": 81.9600},
    {"name": "Basti", "lat": 26.8100, "lng": 82.7200},
    {"name": "Deoria", "lat": 26.5000, "lng": 83.7800},
    {"name": "Kushinagar", "lat": 26.7400, "lng": 83.9100},
    {"name": "Ballia", "lat": 25.7600, "lng": 84.1500},
    {"name": "Mau", "lat": 25.9500, "lng": 83.5600},
    {"name": "Azamgarh", "lat": 26.0600, "lng": 83.1800},
    {"name": "Jaunpur", "lat": 25.7500, "lng": 82.6900},
    {"name": "Ghazipur", "lat": 25.5800, "lng": 83.5800},
    {"name": "Mirzapur", "lat": 25.1500, "lng": 82.5800},
    {"name": "Sonbhadra", "lat": 24.4100, "lng": 83.0400},
    {"name": "Banda", "lat": 25.4800, "lng": 80.3300},
    {"name": "Etawah", "lat": 26.7800, "lng": 79.0200},
    {"name": "Bulandshahr", "lat": 28.4100, "lng": 77.8500},
    {"name": "Shahjahanpur", "lat": 27.8800, "lng": 79.9000},
    {"name": "Rampur", "lat": 28.8100, "lng": 79.0300},
    {"name": "Bijnor", "lat": 29.3700, "lng": 78.1400},
    {"name": "Amroha", "lat": 28.9000, "lng": 78.4700},
    {"name": "Sambhal", "lat": 28.5800, "lng": 78.5500}
]

def get_nearest_district(lat: float, lng: float) -> str:
    min_dist = float('inf')
    nearest = "Lucknow"
    for d in UP_DISTRICTS:
        dist = math.hypot(d["lat"] - lat, d["lng"] - lng)
        if dist < min_dist:
            min_dist = dist
            nearest = d["name"]
    return nearest

def deduct_location(lat: float, lng: float) -> str:
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10"
    headers = {
        "User-Agent": "UP-Police-Media-Search-Engine/1.0"
    }
    try:
        # Tightened from 2.0s — this sits in the critical path of the
        # first-visit location splash; get_nearest_district (pure math, no
        # network) is a perfectly good fallback, so there's no reason to let
        # a slow/rate-limited Nominatim response eat more of that budget.
        response = requests.get(url, headers=headers, timeout=1.2)
        if response.status_code == 200:
            data = response.json()
            address = data.get("address", {})
            district_raw = (
                address.get("state_district") or
                address.get("county") or
                address.get("district") or
                address.get("city") or
                address.get("town") or
                ""
            )
            district_clean = re.sub(r"\b(District|City)\b", "", district_raw, flags=re.IGNORECASE).strip()
            if district_clean:
                return district_clean
        return get_nearest_district(lat, lng)
    except Exception:
        return get_nearest_district(lat, lng)
