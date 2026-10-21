"""Towns of BNBC 2020 with their seismic zone coefficient and basic wind speed, and where they
are, for the location suggestion of the soil report's site.

The zone coefficients Z are BNBC 2020 Part 6 Table 6.2.15 ("Seismic zone coefficient Z for
some important towns of Bangladesh"), the zones those of Table 6.2.14 (Z = 0.12, 0.20, 0.28,
0.36 for zones 1-4); the basic wind speeds V are Table 6.2.8 ("Basic wind speeds, V, for
selected locations in Bangladesh"), both read from the code (Bangladesh Gazette, 11 February
2021). The names are the code's spellings; a town that one table lists and the other does not
has ``None`` for the missing value.

The coordinates (latitude, longitude of the town centre, WGS 84, to about 0.01°, 1 km) were
written from general geographic knowledge, not from a survey; check them against GeoNames
(https://www.geonames.org, CC BY 4.0) before relying on a distance to a few km. The suggestion
only names the nearest listed town; the zone boundaries of Figure 6.2.24 and the wind speed
map of Figure 6.2.1 govern, and the engineer confirms the location in Project Settings.
"""

from __future__ import annotations

from typing import NamedTuple

from saengine.gis.crs import haversine_km


class Town(NamedTuple):
    name: str
    latitude: float
    longitude: float
    #: Seismic zone coefficient Z (Table 6.2.15), or None when the table does not list it.
    z: float | None
    #: Basic wind speed V [m/s] (Table 6.2.8), or None when the table does not list it.
    wind_speed: float | None


#: Zone of each coefficient (Table 6.2.14).
ZONES = {0.12: 1, 0.20: 2, 0.28: 3, 0.36: 4}

# fmt: off
TOWNS: tuple[Town, ...] = (
    Town("Angarpota", 26.28, 88.95, None, 47.8),
    Town("Bagerhat", 22.65, 89.79, 0.12, 77.5),
    Town("Bandarban", 22.20, 92.22, 0.28, 62.5),
    Town("Barguna", 22.16, 90.13, 0.12, 80.0),
    Town("Barisal", 22.70, 90.35, 0.12, 78.7),
    Town("Bhola", 22.69, 90.65, 0.12, 69.5),
    Town("Bogra", 24.85, 89.37, 0.28, 61.9),
    Town("Brahmanbaria", 23.96, 91.11, 0.28, 56.7),
    Town("Chandpur", 23.23, 90.67, 0.20, 50.6),
    Town("Chapai Nawabganj", 24.60, 88.27, 0.12, 41.4),
    Town("Chittagong", 22.36, 91.78, 0.28, 80.0),
    Town("Chuadanga", 23.64, 88.84, 0.12, 61.9),
    Town("Comilla", 23.46, 91.18, 0.20, 61.4),
    Town("Cox's Bazar", 21.43, 92.01, 0.28, 80.0),
    Town("Dahagram", 26.27, 88.93, None, 47.8),
    Town("Dhaka", 23.81, 90.41, 0.20, 65.7),
    Town("Dinajpur", 25.63, 88.64, 0.20, 41.4),
    Town("Faridpur", 23.61, 89.84, 0.20, 63.1),
    Town("Feni", 23.02, 91.40, 0.20, 64.1),
    Town("Gaibandha", 25.33, 89.54, 0.28, 65.6),
    Town("Gazipur", 24.00, 90.42, 0.20, 66.5),
    Town("Gopalganj", 23.01, 89.83, 0.12, 74.5),
    Town("Habiganj", 24.38, 91.42, 0.36, 54.2),
    Town("Hatiya", 22.35, 91.12, None, 80.0),
    Town("Ishurdi", 24.13, 89.07, None, 69.5),
    Town("Joypurhat", 25.10, 89.02, 0.20, 56.7),  # Table 6.2.15: "Jaipurhat"
    Town("Jamalpur", 24.94, 89.94, 0.36, 56.7),
    Town("Jessore", 23.17, 89.21, 0.12, 64.1),
    Town("Jhalakati", 22.64, 90.20, 0.12, 80.0),
    Town("Jhenaidah", 23.54, 89.15, 0.12, 65.0),
    Town("Khagrachhari", 23.12, 91.98, 0.28, 56.7),
    Town("Khulna", 22.85, 89.54, 0.12, 73.3),
    Town("Kutubdia", 21.82, 91.86, None, 80.0),
    Town("Kishoreganj", 24.43, 90.79, 0.36, 64.7),
    Town("Kurigram", 25.81, 89.64, 0.36, 65.6),
    Town("Kushtia", 23.90, 89.12, 0.20, 66.9),
    Town("Lakshmipur", 22.94, 90.84, 0.20, 51.2),
    Town("Lalmonirhat", 25.92, 89.45, 0.28, 63.7),
    Town("Madaripur", 23.16, 90.19, 0.20, 68.1),
    Town("Magura", 23.49, 89.42, 0.12, 65.0),
    Town("Maheshkhali", 21.55, 91.95, None, 80.0),
    Town("Manikganj", 23.86, 90.00, 0.20, 58.2),
    Town("Meherpur", 23.76, 88.63, 0.12, 58.2),
    Town("Mongla", 22.48, 89.60, 0.12, None),
    Town("Moulvibazar", 24.48, 91.78, 0.36, 53.0),
    Town("Munshiganj", 23.54, 90.53, 0.20, 57.1),
    Town("Mymensingh", 24.75, 90.42, 0.36, 67.4),
    Town("Naogaon", 24.81, 88.93, 0.20, 55.2),
    Town("Narail", 23.17, 89.51, 0.12, 68.6),
    Town("Narayanganj", 23.62, 90.50, 0.20, 61.1),
    Town("Narsingdi", 23.93, 90.72, 0.28, 59.7),
    Town("Natore", 24.42, 89.00, 0.20, 61.9),
    Town("Netrokona", 24.88, 90.73, 0.36, 65.6),
    Town("Nilphamari", 25.93, 88.86, 0.12, 44.7),
    Town("Noakhali", 22.87, 91.10, 0.20, 57.1),
    Town("Pabna", 24.01, 89.24, 0.20, 63.1),
    Town("Panchagarh", 26.33, 88.55, 0.20, 41.4),
    Town("Patuakhali", 22.36, 90.33, 0.12, 80.0),
    Town("Pirojpur", 22.58, 89.97, 0.12, 80.0),
    Town("Rajbari", 23.76, 89.64, 0.20, 59.1),
    Town("Rajshahi", 24.37, 88.60, 0.12, 49.2),
    Town("Rangamati", 22.65, 92.18, 0.28, 56.7),
    Town("Rangpur", 25.74, 89.28, 0.28, 65.3),
    Town("Satkhira", 22.72, 89.07, 0.12, 57.6),
    Town("Shariatpur", 23.24, 90.43, 0.20, 61.9),
    Town("Sherpur", 25.02, 89.98, 0.36, 62.5),
    Town("Sirajganj", 24.46, 89.71, 0.28, 50.6),
    Town("Srimangal", 24.31, 91.73, 0.36, 50.6),
    Town("St. Martin's Island", 20.62, 92.32, None, 80.0),
    Town("Sunamganj", 25.07, 91.40, 0.36, 61.1),
    Town("Sylhet", 24.90, 91.87, 0.36, 61.1),
    Town("Sandwip", 22.49, 91.45, None, 80.0),
    Town("Tangail", 24.25, 89.92, 0.28, 50.6),
    Town("Teknaf", 20.86, 92.30, None, 80.0),
    Town("Thakurgaon", 26.03, 88.46, 0.20, 41.4),
)
# fmt: on

#: The Project Settings location id (``library.bnbc.LOCATIONS``) of a town, where there is one.
SETTINGS_IDS = {
    "Dhaka": "dhaka",
    "Chittagong": "chattogram",
    "Cox's Bazar": "coxsbazar",
    "Khulna": "khulna",
    "Rajshahi": "rajshahi",
    "Sylhet": "sylhet",
    "Barisal": "barishal",
    "Rangpur": "rangpur",
    "Mymensingh": "mymensingh",
    "Comilla": "cumilla",
}


def nearest(latitude: float, longitude: float, *, need: str | None = None) -> tuple[Town, float]:
    """The nearest town and its distance [km]; ``need`` "z" or "wind" skips the towns the
    table of that value does not list."""
    towns = [
        t
        for t in TOWNS
        if need is None
        or (need == "z" and t.z is not None)
        or (need == "wind" and t.wind_speed is not None)
    ]
    return min(
        ((t, haversine_km(latitude, longitude, t.latitude, t.longitude)) for t in towns),
        key=lambda pair: pair[1],
    )
