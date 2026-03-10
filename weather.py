import requests
import time
from db import get_connection

CITIES = [
    {"name": "Northfield, NJ",     "lat": 39.3676, "lon": -74.5571, "unit": "fahrenheit", "wind_unit": "mph"},
    {"name": "Fort Lauderdale, FL", "lat": 26.1224, "lon": -80.1373, "unit": "fahrenheit", "wind_unit": "mph"},
    {"name": "Amsterdam",           "lat": 52.3676, "lon":  4.9041,  "unit": "celsius",    "wind_unit": "kmh"},
]

def _condition(code):
    """Map WMO weather code to a simple label."""
    if code == 0:                          return "Sunny"
    if code in (1, 2):                     return "Partly Cloudy"
    if code == 3:                          return "Cloudy"
    if code in (45, 48):                   return "Foggy"
    if code in range(51, 68):              return "Rain"
    if code in range(71, 78):              return "Snow"
    if code in range(80, 83):              return "Rain"
    if code in range(85, 87):              return "Snow"
    if code in range(95, 100):             return "Storm"
    return "Mixed"

def fetch_city(city):
    """Fetch current conditions + today's dominant condition for a single city."""
    params = {
        "latitude":         city["lat"],
        "longitude":        city["lon"],
        "current":          "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m",
        "daily":            "weather_code",
        "temperature_unit": city["unit"],
        "wind_speed_unit":  city["wind_unit"],
        "forecast_days":    1,
    }
    for attempt in range(3):
        try:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=15)
            break
        except requests.exceptions.SSLError:
            if attempt == 2:
                raise
            time.sleep(5)
    data = r.json()
    c = data["current"]
    daily_code = data["daily"]["weather_code"][0]

    temp       = c["temperature_2m"]
    feels_like = c["apparent_temperature"]
    is_celsius = city["unit"] == "celsius"

    return {
        "name":      city["name"],
        "temp":      temp,
        "feels":     feels_like,
        "unit":      "°C" if is_celsius else "°F",
        "temp_f":    round(temp * 9/5 + 32, 1) if is_celsius else None,
        "feels_f":   round(feels_like * 9/5 + 32, 1) if is_celsius else None,
        "humidity":  c["relative_humidity_2m"],
        "wind":      c["wind_speed_10m"],
        "wind_unit": city["wind_unit"],
        "condition": _condition(daily_code),
    }

def fetch_and_store():
    """Pull current conditions for Northfield NJ and save to DB."""
    home = fetch_city(CITIES[0])
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO weather (temp_f, humidity_pct, wind_mph) VALUES (%s, %s, %s)",
        (home["temp"], home["humidity"], home["wind"])
    )
    conn.commit()
    conn.close()
    return home

def fetch_all():
    """Return current conditions for all cities."""
    return [fetch_city(c) for c in CITIES]
