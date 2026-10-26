"""Single source of truth for traffic status labels and the congestion rules.

The simulator, training pipeline, model, API and dashboard all import from here,
so a label can never be spelled two different ways.
"""

LOW, MEDIUM, HIGH = "LOW", "MEDIUM", "HIGH"
STATUSES = (LOW, MEDIUM, HIGH)

# Thresholds (documented in the README)
HIGH_MAX_SPEED_KMH = 20      # slower than this AND crowded -> HIGH
HIGH_MIN_CARS = 60
MEDIUM_MAX_SPEED_KMH = 35    # slower than this -> at least MEDIUM
MEDIUM_MIN_CARS = 60         # this many vehicles -> at least MEDIUM

# Valid input ranges (used to validate user/API input)
MAX_CARS = 500
MAX_SPEED_KMH = 150


def classify(cars, speed):
    """Rule-based congestion level from vehicle count and average speed (km/h).

    HIGH   : speed < 20 km/h and at least 60 vehicles (slow and crowded)
    MEDIUM : speed < 35 km/h or at least 60 vehicles (not HIGH)
    LOW    : otherwise
    """
    if speed < HIGH_MAX_SPEED_KMH and cars >= HIGH_MIN_CARS:
        return HIGH
    if speed < MEDIUM_MAX_SPEED_KMH or cars >= MEDIUM_MIN_CARS:
        return MEDIUM
    return LOW


def normalize_status(value):
    """Map any spelling ('High', 'HIGH CONGESTION', ' medium ') to a standard status."""
    text = str(value).strip().upper()
    if text.startswith("HIGH"):
        return HIGH
    if text in STATUSES:
        return text
    raise ValueError(f"Unknown traffic status: {value!r}")


def validate_reading(cars, speed):
    """Return (cars:int, speed:float) or raise ValueError with a clear message."""
    try:
        cars_f, speed_f = float(cars), float(speed)
    except (TypeError, ValueError):
        raise ValueError("cars and speed must be numbers")
    if cars_f != cars_f or speed_f != speed_f or cars_f in (float("inf"),) or speed_f in (float("inf"),):
        raise ValueError("cars and speed must be finite numbers")
    if not 0 <= cars_f <= MAX_CARS:
        raise ValueError(f"cars must be between 0 and {MAX_CARS}")
    if not 0 <= speed_f <= MAX_SPEED_KMH:
        raise ValueError(f"speed must be between 0 and {MAX_SPEED_KMH} km/h")
    return int(round(cars_f)), round(speed_f, 1)
