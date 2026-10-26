"""Traffic analysis: emission estimate, air-quality indicator, emergency corridor.

IMPORTANT: all inputs are simulated, and every output here is an *educational estimate*,
not a measurement and not an official standard.
"""
from .traffic_rules import HIGH

SEGMENT_KM = 1.0          # assumed length of each monitored road segment
MIN_SPEED_FOR_EF = 5.0    # avoids division blow-up at standstill


def emission_factor_g_per_km(speed_kmh):
    """Illustrative CO2 emission factor per vehicle (g/km) as a function of speed.

    EF(v) = 90 + 2400 / v   (v clamped to >= 5 km/h)
    Real vehicles emit the most per km at crawling speeds and least at ~60-80 km/h; this
    curve reproduces that shape (about 130 g/km at 60 km/h, 170 at 30, 250 at 15, 570 at 5).
    It is NOT calibrated against COPERT/IPCC data.
    """
    return 90.0 + 2400.0 / max(float(speed_kmh), MIN_SPEED_FOR_EF)


def get_carbon_kg(cars, speed, segment_km=SEGMENT_KM):
    """Estimated CO2 (kg) emitted by `cars` vehicles crossing one segment at `speed` km/h."""
    grams = cars * segment_km * emission_factor_g_per_km(speed)
    return round(grams / 1000.0, 2)


# Air-quality indicator thresholds on estimated CO2 load per segment (kg).
AQI_GOOD_BELOW = 6.0
AQI_MODERATE_BELOW = 15.0


def get_air_quality(carbon_kg):
    """Simulated air-quality *indicator* (Good / Moderate / Poor) from the CO2 estimate.

    This is not the official AQI: no pollutant concentrations (PM2.5, NO2...) are measured.
    """
    if carbon_kg < AQI_GOOD_BELOW:
        return "Good"
    if carbon_kg < AQI_MODERATE_BELOW:
        return "Moderate"
    return "Poor"


def emergency_corridor(road_readings):
    """Recommend the monitored road with the lowest estimated travel delay.

    `road_readings` is a list of dicts (road, cars, speed, status), typically the average of
    the latest few readings per road. Score = minutes to drive one segment at the current
    speed (60 * km / speed); roads currently HIGH are avoided unless every road is HIGH.
    Ties are broken by fewer vehicles. Returns None when there is no data.

    Limitation: no road-network connectivity exists in the data, so this ranks the monitored
    roads against each other. It is not a city-wide route (no Dijkstra / A*).
    """
    ranked = []
    for r in road_readings:
        try:
            speed = max(float(r["speed"]), MIN_SPEED_FOR_EF)
            cars = int(r["cars"])
        except (KeyError, TypeError, ValueError):
            continue  # skip incomplete rows rather than crash
        ranked.append({
            "road": r["road"], "status": r.get("status"), "cars": cars,
            "speed": round(speed, 1), "eta_minutes": round(60.0 * SEGMENT_KM / speed, 1),
        })
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x["status"] == HIGH, x["eta_minutes"], x["cars"]))
    return {"recommended": ranked[0], "ranking": ranked, "segment_km": SEGMENT_KM}
