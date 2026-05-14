import requests

# Test Open-Meteo API
# Get last 5 days rainfall (historical)
lat, lon = 39.9, 116.4
url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&past_days=5&forecast_days=3&timezone=auto"

res = requests.get(url)
print(res.json())
