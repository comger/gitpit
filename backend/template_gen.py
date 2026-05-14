"""
Historical weather data fetcher for template generation.
Uses Open-Meteo Archive API (free, no key required).
Provides hourly precipitation → disaggregated to 5-minute intervals.
Also simulates water level using physics engine for template completeness.
"""
import json
import numpy as np
import urllib.request
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import io


def fetch_historical_precip(
    lat: float,
    lon: float,
    start_date: str,   # "YYYY-MM-DD"
    end_date: str,     # "YYYY-MM-DD"
) -> List[Dict]:
    """
    Fetch hourly precipitation from Open-Meteo archive API.
    Returns list of {timestamp (ISO), precipitation_mm}.
    """
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&hourly=precipitation,temperature_2m"
        f"&timezone=Asia%2FShanghai"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "GisPit/2.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])

    return [
        {"timestamp": t, "precip_mm": float(p) if p is not None else 0.0}
        for t, p in zip(times, precip)
    ]


def disaggregate_to_5min(hourly_records: List[Dict]) -> List[Dict]:
    """
    Disaggregate hourly precipitation to 5-minute intervals.
    Uses a simple pulse disaggregation: uniform within the hour with
    a small random perturbation to make it more realistic.
    """
    result = []
    rng = np.random.default_rng(42)

    for rec in hourly_records:
        t = datetime.fromisoformat(rec["timestamp"])
        hourly_mm = rec["precip_mm"]

        # Generate 12 five-minute values that sum to hourly total
        if hourly_mm <= 0:
            weights = np.zeros(12)
        else:
            # Random disaggregation (more intense at middle of hour)
            raw = rng.exponential(1.0, 12)
            weights = raw / raw.sum() * hourly_mm

        for i in range(12):
            t5 = t + timedelta(minutes=i * 5)
            result.append({
                "timestamp": t5.strftime("%Y-%m-%d %H:%M:%S"),
                "rainfall_mm": round(float(weights[i]), 3),
            })

    return result


def simulate_water_level(
    records_5min: List[Dict],
    area_km2: float,
    tc_hours: float,
    slope_s0: float,
    w_channel: float,
    cn: float = 75,
    n_manning: float = 0.04,
) -> List[Dict]:
    """
    Apply physics engine to simulate water level for each 5-minute step.
    Used to fill in the water_level_m column in the template.
    """
    from routing_engine import PhysicsForecaster

    fc = PhysicsForecaster(area_km2, tc_hours, slope_s0, w_channel, cn, n_manning)
    UH_LEN = len(fc._uh)
    rain_arr = np.array([r["rainfall_mm"] for r in records_5min])

    # Net rainfall
    from routing_engine import scs_runoff
    net = np.array([scs_runoff(p, cn) for p in rain_arr])

    # Full convolution
    flow_full = np.convolve(net, fc._uh)

    from routing_engine import manning_depth
    result = []
    for i, rec in enumerate(records_5min):
        q = float(flow_full[i]) if i < len(flow_full) else 0.0
        h = manning_depth(q, w_channel, slope_s0, n_manning) if q > 0 else 0.0
        result.append({
            **rec,
            "water_level_m": round(h, 4),
            "flow_m3s": round(q, 3),
        })

    return result


def generate_template_csv(
    lat: float,
    lon: float,
    area_km2: float,
    tc_hours: float,
    slope_s0: float,
    w_channel: float,
    cn: float = 75,
    n_manning: float = 0.04,
    years: int = 1,
) -> bytes:
    """
    Generate a full CSV template with 5-min historical rainfall + simulated
    water level for the specified station parameters. Matches the PINN input format.
    """
    end_dt = datetime.now() - timedelta(days=30)  # leave 30-day buffer
    start_dt = end_dt - timedelta(days=365 * years)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    # Fetch hourly historical precipitation
    hourly = fetch_historical_precip(lat, lon, start_date, end_date)

    # Disaggregate to 5-minute
    records_5min = disaggregate_to_5min(hourly)

    # Simulate water level
    records = simulate_water_level(
        records_5min, area_km2, tc_hours, slope_s0, w_channel, cn, n_manning
    )

    # Write CSV with observational data only
    lines = ["timestamp,rainfall_mm,h_up_m,water_level_m,flow_m3s"]
    
    for r in records:
        # h_up_m is default 0.0 unless user has data
        lines.append(
            f"{r['timestamp']},{r['rainfall_mm']},0.00,{r['water_level_m']},0.0"
        )

    return "\n".join(lines).encode("utf-8")
