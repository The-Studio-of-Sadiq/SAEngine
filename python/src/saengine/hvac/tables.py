"""BNBC 2020 Part 8 Chapter 2 (air-conditioning) and Part 3 Chapter 4 (energy) values as data.

Every BNBC value is transcribed from the rendered page of the Bangladesh Gazette edition of
11 February 2021 (``bnbc-2020-part2.pdf`` for Part 8, ``bnbc-2020-part1.pdf`` for Part 3);
``PAGES`` gives the PDF page of each table or clause. Values marked "SAEngine" or "from memory"
in their comment are not BNBC's: they are documented assumptions where the code is silent, and
the report lists them (``ASSUMPTIONS``) so that the engineer checks them.

Units: °C, %, l/s, m², W/m², persons per 100 m² as the tables give them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where each table or clause is (PDF page of the Gazette edition).
PAGES: dict[str, str] = {
    "8.2.1": "Part 8 Table 8.2.1 (Sec 2.7.2.1), part2 p859-860",
    "8.2.2": "Part 8 Table 8.2.2 (Sec 2.7.2.2), part2 p862, notes p863",
    "8.2.3": "Part 8 Table 8.2.3, part2 p863-869",
    "2.12.2": "Part 8 Sec 2.12.2.1-2.12.2.3, part2 p915",
    "8.2.9a": "Part 8 Table 8.2.9(a), part2 p916",
    "3.4.2": "Part 3 Table 3.4.2 (Sec 4.4.1), part1 p186",
    "3.4.3": "Part 3 Table 3.4.3 (Sec 4.4.1.3), part1 p187",
    "4.4.3": "Part 3 Sec 4.4.3.1 and Figure 3.4.2, part1 p188-189",
    "4.5.1": "Part 3 Sec 4.5.1.2, part1 p191",
    "3.4.5": "Part 3 Table 3.4.5 (Sec 4.5.2), part1 p192",
    "2.7.2.1b": "Part 8 Sec 2.7.2.1(b), part2 p860",
}

# ─────────────────────── Table 8.2.2: outside design conditions (summer) ───────────────────────


@dataclass(frozen=True)
class Station:
    """One row of Table 8.2.2: the outside design conditions of a station [°C].

    ``cooling`` holds (DB, MWB) at 0.4 %, 1 % and 2 % (columns 2-7, note b: for the cooling load);
    ``evaporation`` (WB, MDB) at the same levels (columns 8-13, note c: cooling towers and
    evaporative equipment); ``range`` the mean daily range of the dry bulb (column 14, note d).
    """

    key: str
    name: str
    cooling: dict[str, tuple[float, float]]
    evaporation: dict[str, tuple[float, float]]
    range: float
    #: Site latitude [°N] and longitude [°E] for the sun: from memory, to be checked (BNBC gives
    #: none). Dhaka's 23.7 N 90.4 E is SAEngine's default.
    latitude: float
    longitude: float


def _station(
    key: str, name: str, row: tuple[float, ...], lat: float, lon: float
) -> tuple[str, Station]:
    db04, mwb04, db1, mwb1, db2, mwb2, wb04, mdb04, wb1, mdb1, wb2, mdb2, rng = row
    return key, Station(
        key,
        name,
        {"0.4": (db04, mwb04), "1": (db1, mwb1), "2": (db2, mwb2)},
        {"0.4": (wb04, mdb04), "1": (wb1, mdb1), "2": (wb2, mdb2)},
        rng,
        lat,
        lon,
    )


#: Table 8.2.2, columns (2)-(14) of each station, as printed (Dhaka's 0.4 % DB is printed 35.55).
STATIONS: dict[str, Station] = dict(
    [
        _station("barisal", "Barisal",
                 (35.5, 28.5, 34.5, 28.5, 34.0, 28.0, 30.0, 33.0, 29.5, 33.0, 29.0, 32.0, 5.0),
                 22.70, 90.37),
        _station("bogra", "Bogra",
                 (36.5, 28.5, 35.5, 28.5, 34.5, 28.0, 31.5, 33.5, 30.0, 33.0, 29.0, 33.0, 5.5),
                 24.85, 89.37),
        _station("chandpur", "Chandpur",
                 (35.5, 28.5, 34.5, 28.5, 34.0, 28.0, 29.5, 33.0, 29.5, 33.0, 29.0, 32.5, 5.0),
                 23.23, 90.65),
        _station("chittagong", "Chittagong",
                 (34.0, 28.5, 33.5, 28.5, 33.0, 28.0, 29.5, 32.5, 29.0, 32.5, 28.5, 32.0, 4.5),
                 22.35, 91.82),
        _station("comilla", "Comilla",
                 (35.0, 27.5, 34.5, 27.5, 34.0, 27.5, 29.0, 33.0, 28.5, 32.5, 28.0, 32.0, 5.5),
                 23.46, 91.18),
        _station("coxsbazar", "Cox's Bazar",
                 (34.0, 27.5, 33.5, 27.5, 33.0, 27.5, 29.0, 31.0, 29.0, 30.0, 29.0, 30.0, 5.0),
                 21.45, 91.97),
        _station("dhaka", "Dhaka",
                 (35.55, 27.5, 35.0, 27.0, 34.5, 27.0, 29.0, 33.0, 28.5, 29.0, 28.5, 29.0, 5.0),
                 23.70, 90.40),
        _station("dinajpur", "Dinajpur",
                 (36.0, 28.5, 35.0, 28.0, 34.5, 28.0, 30.0, 32.5, 29.0, 33.0, 29.0, 33.0, 5.5),
                 25.63, 88.64),
        _station("faridpur", "Faridpur",
                 (36.5, 28.5, 35.5, 28.0, 34.5, 28.0, 29.5, 33.0, 29.0, 33.0, 29.0, 33.0, 5.0),
                 23.61, 89.84),
        _station("ishurdi", "Ishurdi",
                 (37.5, 27.0, 36.5, 27.0, 35.5, 28.0, 30.0, 34.5, 29.0, 33.5, 29.0, 33.5, 6.0),
                 24.13, 89.07),
        _station("jessore", "Jessore",
                 (38.0, 28.5, 37.0, 28.5, 36.0, 28.0, 30.0, 35.0, 30.0, 35.0, 29.5, 34.0, 6.5),
                 23.17, 89.21),
        _station("khulna", "Khulna",
                 (36.5, 29.0, 36.0, 28.0, 35.5, 28.0, 30.0, 34.0, 30.0, 34.0, 29.5, 33.5, 5.0),
                 22.82, 89.55),
        _station("mongla", "Mongla",
                 (37.0, 31.0, 36.0, 30.5, 35.0, 30.0, 33.0, 34.0, 32.5, 34.0, 32.0, 33.5, 5.0),
                 22.47, 89.60),
        _station("mymensingh", "Mymensingh",
                 (35.0, 28.0, 34.0, 28.0, 33.5, 27.5, 29.5, 33.0, 29.0, 32.5, 28.5, 32.0, 4.5),
                 24.75, 90.40),
        _station("patuakhali", "Patuakhali",
                 (35.5, 28.5, 35.0, 28.5, 34.5, 28.5, 30.0, 33.0, 30.0, 33.0, 29.5, 32.5, 5.0),
                 22.36, 90.33),
        _station("rajshahi", "Rajshahi",
                 (35.5, 29.0, 34.5, 28.5, 34.0, 29.0, 31.5, 33.0, 31.0, 32.5, 30.0, 31.5, 5.0),
                 24.37, 88.60),
        _station("rangamati", "Rangamati",
                 (35.5, 26.0, 34.5, 27.0, 34.0, 27.5, 28.5, 33.5, 28.0, 32.5, 28.0, 32.5, 6.0),
                 22.65, 92.17),
        _station("rangpur", "Rangpur",
                 (35.5, 28.5, 34.5, 28.0, 34.0, 28.0, 29.5, 30.5, 29.5, 30.0, 29.5, 30.0, 5.0),
                 25.75, 89.25),
        _station("sylhet", "Sylhet",
                 (35.5, 27.0, 34.5, 27.0, 34.0, 26.5, 28.5, 32.5, 28.0, 32.5, 28.0, 32.5, 5.5),
                 24.90, 91.87),
        _station("tangail", "Tangail",
                 (36.0, 27.5, 35.5, 27.5, 34.5, 27.5, 29.0, 33.5, 28.5, 33.0, 28.5, 33.0, 5.5),
                 24.25, 89.92),
    ]
)  # fmt: skip
STATION_KEYS: tuple[str, ...] = tuple(STATIONS)

#: Sec 2.12.2.1: "the outdoor design temperature shall be selected from columns of 2 percent value
#: of Table 8.2.2 for cooling".
DESIGN_LEVEL = "2"
#: Note b of Table 8.2.2: the percentages are of the hours of the summer months May through
#: September; SAEngine runs a design day on the 21st of each of them (the sun differs by month).
DESIGN_MONTHS = (5, 6, 7, 8, 9)
#: Sec 2.12.2.2: "Indoor design temperature shall not be less than 24 °C for cooling unless
#: otherwise required for specific application."
INDOOR_DB = 24.0
#: Sec 2.7.2.1(b): outdoor and indoor dry bulbs differ by at most 11 °C (else an ante-room).
MAX_INDOOR_OUTDOOR_DIFFERENCE = 11.0

#: Project Settings site locations (library/bnbc.py) -> the Table 8.2.2 station.
SETTINGS_STATION = {
    "dhaka": "dhaka",
    "chattogram": "chittagong",
    "coxsbazar": "coxsbazar",
    "khulna": "khulna",
    "rajshahi": "rajshahi",
    "sylhet": "sylhet",
    "barishal": "barisal",
    "rangpur": "rangpur",
    "mymensingh": "mymensingh",
    "cumilla": "comilla",
}

# ─────────────────────────── Table 8.2.1: inside design conditions ───────────────────────────


@dataclass(frozen=True)
class Inside:
    """One row of Table 8.2.1: acceptable inside design conditions for summer."""

    row: int
    label: str
    db: tuple[float, float]  # dry bulb range [°C]
    rh: tuple[float, float] | None  # relative humidity range [%]; None where printed "--"


INSIDE: dict[int, Inside] = {
    r.row: r
    for r in (
        Inside(1, "Restaurants, Cafeteria and Dining Hall", (23, 26), (55, 60)),
        Inside(2, "Kitchens", (28, 31), None),
        Inside(3, "Office buildings", (23, 26), (50, 60)),
        Inside(4, "Bank/Insurance/Commercial building", (23, 26), (45, 55)),
        Inside(5, "Departmental stores", (23, 26), (50, 60)),
        Inside(6, "Hotel guest rooms", (23, 26), (50, 60)),
        Inside(7, "Ball room/meeting room", (23, 26), (40, 60)),
        Inside(8, "Class rooms", (23, 26), (50, 60)),
        Inside(9, "Auditoriums", (23, 26), (50, 60)),
        Inside(10, "Recovery rooms", (24, 26), (45, 55)),
        Inside(11, "Patient rooms", (24, 26), (45, 55)),
        Inside(12, "Operation theatres", (17, 27), (45, 55)),
        Inside(13, "Delivery room", (20, 23), (45, 55)),
        Inside(14, "ICU/CCU", (20, 23), (30, 60)),
        Inside(15, "New born Intensive care", (22.5, 25.5), (30, 60)),
        Inside(16, "Treatment room", (23, 25), (30, 60)),
        Inside(17, "Trauma room", (17, 27), (45, 55)),
        Inside(18, "Endoscopy/Bronchoscopy", (20, 23), (30, 60)),
        Inside(19, "X-ray (diagnostic & treatment)", (25.5, 27), (40, 50)),
        Inside(20, "X-ray (surgery/critical area and catherization)", (21, 24), (30, 60)),
        Inside(21, "Laboratory (diagnostics)", (22.5, 24.5), (30, 60)),
        Inside(22, "Art Galleries/Museums", (17, 22), (40, 55)),
        Inside(23, "Libraries", (20, 22), (45, 55)),
        Inside(24, "Radio studio/Television studio", (23, 26), (45, 55)),
        Inside(25, "Telephone terminal rooms", (22, 26), (40, 50)),
        Inside(26, "Airport terminal/ bus terminal", (23, 26), (50, 60)),
    )
}

# ─────────────────── Table 8.2.3: minimum ventilation rates (and occupancy) ───────────────────


@dataclass(frozen=True)
class Ventilation:
    """One row of Table 8.2.3: outdoor air in the breathing zone per person (``perPerson``,
    l/s) and per floor area (``perArea``, l/s per m²), the default occupant density (persons per
    100 m² of net occupiable floor area, note a) and the exhaust rate. None where the table
    prints "-". ``exhaust`` is l/s per m² unless ``exhaustNote`` says otherwise (per room, per
    water closet, per car)."""

    key: str
    label: str
    group: str
    perPerson: float | None
    perArea: float | None
    density: float | None
    exhaust: float | None = None
    exhaustNote: str = ""
    #: Living areas of dwellings: 0.35 air changes per hour but not less than 7.5 l/s a person.
    ach: float | None = None
    #: Row of Table 8.2.1 whose inside conditions apply (SAEngine's choice of the nearest row).
    inside: int | None = None


_V = Ventilation
#: Table 8.2.3 as printed (part2 p863-869). Rows that only refer elsewhere ("see food and
#: beverage service", "see public spaces", "see storage", "see education") are left out.
VENTILATION: dict[str, Ventilation] = {
    r.key: r
    for r in (
        # Correctional facilities (p863)
        _V("cellsNoPlumbing", "Correctional: cells without plumbing fixtures", "correctional",
           2.5, 0.6, 25),
        _V("cellsPlumbing", "Correctional: cells with plumbing fixtures", "correctional",
           2.5, 0.6, 25, 5.0),
        _V("guardStations", "Correctional: guard stations", "correctional", 2.5, 0.3, 15),
        _V("dayRoom", "Correctional: day room", "correctional", 2.5, 0.3, 30),
        _V("bookingWaiting", "Correctional: booking/waiting", "correctional", 3.75, 0.3, 50),
        # Dry cleaners, laundries (p864)
        _V("coinDryCleaner", "Coin-operated dry cleaner", "laundry", 3.75, None, 20),
        _V("coinLaundry", "Coin-operated laundries", "laundry", 3.75, 0.3, 20),
        _V("commercialDryCleaner", "Commercial dry cleaner", "laundry", 15, None, 30),
        _V("commercialLaundry", "Commercial laundry", "laundry", 12.5, None, 10),
        _V("laundryStorage", "Laundry storage, pick up", "laundry", 3.75, 0.6, 30),
        # Education (p864)
        _V("auditorium", "Education: auditoriums", "education", 2.5, 0.3, 150, inside=9),
        _V("mediaCenter", "Education: media center", "education", 5, 0.6, 25, inside=8),
        _V("sportsLocker", "Education: sports locker rooms", "education", None, None, None, 2.5),
        _V("musicTheaterDance", "Education: music/theater/dance", "education", 5, 0.3, 35,
           inside=8),
        _V("smokingLoungeEducation", "Education: smoking lounges", "education", 30, None, 70),
        _V("dayCare", "Day care (through age 4)", "education", 5, 0.9, 25, inside=8),
        _V("classroom5to8", "Classrooms (ages 5-8)", "education", 5, 0.6, 25, inside=8),
        _V("classroom9plus", "Classrooms (age 9 plus)", "education", 5, 0.6, 35, inside=8),
        _V("lectureClassroom", "Lecture classroom", "education", 3.75, 0.3, 65, inside=8),
        _V("lectureHall", "Lecture hall (fixed seats)", "education", 3.75, 0.3, 150, inside=9),
        _V("artClassroom", "Art classroom", "education", 10, 0.9, 20, 3.5, inside=8),
        _V("scienceLab", "Science laboratories", "education", 5, 0.9, 25, 5.0, inside=8),
        _V("woodMetalShop", "Wood/metal shops", "education", 5, 0.9, 20, 2.5),
        _V("computerLab", "Computer lab", "education", 5, 0.6, 25, inside=8),
        _V("multiuseAssembly", "Multiuse assembly", "education", 3.75, 0.3, 100, inside=9),
        _V("lockerDressing", "Locker/dressing rooms", "education", None, None, None, 1.25),
        # Food and beverage service (p865)
        _V("bar", "Bars, cocktail lounges", "food", 3.75, 0.9, 100, inside=1),
        _V("cafeteria", "Cafeteria, fast food", "food", 3.75, 0.9, 100, inside=1),
        _V("diningRoom", "Dining rooms", "food", 3.75, 0.9, 70, inside=1),
        _V("kitchenCooking", "Kitchens (cooking)", "food", None, None, None, 3.5, inside=2),
        # Hospitals, nursing and convalescent homes (p865)
        _V("autopsy", "Autopsy rooms", "hospital", None, None, None, 2.5),
        _V("medicalProcedure", "Medical procedure rooms", "hospital", 7.5, None, 20, inside=16),
        _V("operatingRoom", "Operating rooms", "hospital", 15, None, 20, inside=12),
        _V("patientRoom", "Patient rooms", "hospital", 12.5, None, 10, inside=11),
        _V("physicalTherapy", "Physical therapy", "hospital", 7.5, None, 20, inside=16),
        _V("recoveryIcu", "Recovery and ICU", "hospital", 7.5, None, 20, inside=10),
        # Hotels, motels, resorts and dormitories (p865)
        _V("hotelAssembly", "Hotel: multipurpose assembly", "hotel", 2.5, 0.3, 120, inside=7),
        _V("hotelBathroom", "Hotel: bathrooms/toilet-private", "hotel", None, None, None, None,
           "12.5/25 l/s per room (note f)"),
        _V("hotelBedroom", "Hotel: bedroom/living room", "hotel", 2.5, 0.3, 10, inside=6),
        _V("hotelConference", "Hotel: conference/meeting", "hotel", 2.5, 0.3, 50, inside=7),
        _V("dormitory", "Dormitory sleeping areas", "hotel", 2.5, 0.3, 20, inside=6),
        _V("casino", "Gambling casinos", "hotel", 3.75, 0.9, 120, inside=7),
        _V("hotelLobby", "Hotel: lobbies/pre-function", "hotel", 3.75, 0.3, 30, inside=6),
        # Offices (p866)
        _V("conferenceRoom", "Office: conference rooms", "office", 2.5, 0.3, 50, inside=7),
        _V("officeSpace", "Office spaces", "office", 2.5, 0.3, 5, inside=3),
        _V("reception", "Office: reception areas", "office", 2.5, 0.3, 30, inside=3),
        _V("dataEntry", "Office: telephone/data entry", "office", 2.5, 0.3, 60, inside=3),
        _V("entryLobby", "Office: main entry lobbies", "office", 2.5, 0.3, 10, inside=3),
        # Private dwellings, single and multiple (p866)
        _V("garageCommon", "Dwellings: garages, common for multiple units", "dwelling",
           None, None, None, 3.75),
        _V("garageSeparate", "Dwellings: garages, separate for each dwelling", "dwelling",
           None, None, None, None, "50 l/s per car"),
        _V("dwellingKitchen", "Dwellings: kitchens", "dwelling", None, None, None, None,
           "12.5/50 l/s per room (note f)"),
        _V("livingArea", "Dwellings: living areas", "dwelling", 7.5, None, None, ach=0.35,
           inside=6),
        _V("dwellingToilet", "Dwellings: toilet rooms and bath rooms", "dwelling",
           None, None, None, None, "10/25 l/s per room (note f)"),
        # Public spaces (p866-867)
        _V("corridor", "Public spaces: corridors", "public", None, 0.3, None),
        _V("elevatorCar", "Elevator car", "public", None, None, None, 5.0),
        _V("showerRoom", "Shower room (per shower head)", "public", None, None, None, None,
           "25/10 l/s per shower head (note f)"),
        _V("smokingLounge", "Smoking lounges", "public", 30, None, 70),
        _V("publicToilet", "Toilet rooms - public", "public", None, None, None, None,
           "25/30 l/s per water closet or urinal (note e)"),
        _V("worship", "Places of religious worship", "public", 2.5, 0.3, 120, inside=9),
        _V("courtroom", "Courtrooms", "public", 2.5, 0.3, 70, inside=7),
        _V("legislative", "Legislative chambers", "public", 2.5, 0.3, 50, inside=7),
        _V("library", "Libraries", "public", 2.5, 0.6, 10, inside=23),
        _V("museumChildren", "Museums (children's)", "public", 3.75, 0.6, 40, inside=22),
        _V("museum", "Museums/galleries", "public", 3.75, 0.3, 40, inside=22),
        # Retail stores, sales floors and showroom floors (p867)
        _V("sales", "Retail: sales (except as below)", "retail", 3.75, 0.6, 15, inside=5),
        _V("dressingRoom", "Retail: dressing rooms", "retail", None, None, None, 1.25),
        _V("mall", "Mall common areas", "retail", 3.75, 0.3, 40, inside=5),
        _V("shipping", "Retail: shipping and receiving", "retail", None, 0.6, None),
        _V("smokingLoungeRetail", "Retail: smoking lounges", "retail", 30, None, 70),
        _V("storageRoom", "Retail: storage rooms", "retail", None, 0.6, None),
        # Specialty shops (p867)
        _V("fuelStation", "Automotive motor-fuel dispensing stations", "specialty",
           None, None, None, 7.5),
        _V("barber", "Barber", "specialty", 3.75, 0.3, 25, 2.5, inside=5),
        _V("beautySalon", "Beauty and nail salons", "specialty", 10, 0.6, 25, 3.0, inside=5),
        _V("embalming", "Embalming room", "specialty", None, None, None, 10.0),
        _V("petShop", "Pet shops (animal areas)", "specialty", 3.75, 0.9, 10, 4.5),
        _V("supermarket", "Supermarkets", "specialty", 3.75, 0.3, 8, inside=5),
        # Sports and amusement (p868)
        _V("disco", "Disco/dance floors", "sports", 10, 0.3, 100, inside=7),
        _V("bowling", "Bowling alleys (seating areas)", "sports", 5, 0.6, 40),
        _V("arcade", "Game arcades", "sports", 3.75, 0.9, 20),
        _V("iceArena", "Ice arenas without combustion engines", "sports", None, 0.30, None, 2.5),
        _V("gym", "Gym, stadium, arena (play area)", "sports", None, 0.30, None),
        _V("spectator", "Spectator areas", "sports", 3.75, 0.3, 150, inside=9),
        _V("pool", "Swimming pools (pool and deck area)", "sports", None, 2.4, None),
        _V("aerobics", "Health club/aerobics room", "sports", 10, 0.3, 40),
        _V("weightRoom", "Health club/weight room", "sports", 10, 0.3, 10),
        # Storage (p868)
        _V("parkingGarage", "Repair garages, enclosed parking garages", "storage",
           None, None, None, 3.75),
        _V("warehouse", "Warehouses", "storage", None, 0.3, None),
        # Theaters (p868)
        _V("theaterLobby", "Theaters: lobbies", "theater", 2.5, 0.3, 150, inside=9),
        _V("stage", "Stages, studios", "theater", 5, 0.3, 70, inside=24),
        _V("ticketBooth", "Ticket booths", "theater", 2.5, 0.3, 60, inside=9),
        # Transportation (p868)
        _V("platform", "Transportation: platforms", "transport", 3.75, 0.3, 100, inside=26),
        _V("transportWaiting", "Transportation waiting", "transport", 3.75, 0.3, 100, inside=26),
        # Workrooms (p869)
        _V("bankVault", "Bank vaults/safe deposit", "workroom", 2.5, 0.3, 5, inside=4),
        _V("darkroom", "Darkrooms", "workroom", None, None, None, 5.0),
        _V("copyRoom", "Copy, printing rooms", "workroom", 2.5, 0.3, 4, 2.5, inside=3),
        _V("meatProcessing", "Meat processing", "workroom", 7.5, None, 10),
        _V("pharmacy", "Pharmacy (prep. area)", "workroom", 2.5, 0.9, 10, inside=21),
        _V("photoStudio", "Photo studios", "workroom", 2.5, 0.6, 10, inside=24),
        _V("computerRoom", "Computer (without printing)", "workroom", 2.5, 0.3, 4, inside=25),
    )
}  # fmt: skip
VENTILATION_KEYS: tuple[str, ...] = tuple(VENTILATION)

# ───────────────────── Table 3.4.5: maximum allowable lighting power density ─────────────────────

#: Table 3.4.5 (part1 p192) [W/m²]: the maximum, taken as the design lighting when none is given.
LPD = {
    "offices": 9.0,  # E1 and E2
    "retail": 13.0,  # F1 and F2
    "hotels": 9.0,  # A5
    "hospitals": 11.0,  # D1
    "apartments": 7.0,  # A1, A2 and A3
    "educational": 11.0,  # B
    "coveredParking": 3.0,  # all occupancies
    "openParking": 1.6,  # all occupancies
}
#: The Table 3.4.5 row of each ventilation group (SAEngine); groups without one take the
#: offices' value and the report says so.
GROUP_LPD = {
    "office": "offices",
    "workroom": "offices",
    "retail": "retail",
    "specialty": "retail",
    "hotel": "hotels",
    "hospital": "hospitals",
    "dwelling": "apartments",
    "education": "educational",
    "storage": "coveredParking",
}

# ─────────────────────── Tables 8.2.9(a) / 3.4.2 and 3.4.3: glazing ───────────────────────

#: Table 8.2.9(a) = Table 3.4.2: the SHGC limit (and SC) by window-to-wall ratio [%].
SHGC_BY_WWR = {
    10: (0.85, 0.98), 20: (0.60, 0.69), 30: (0.50, 0.57), 40: (0.40, 0.46), 50: (0.35, 0.40),
    60: (0.33, 0.38), 70: (0.31, 0.36), 80: (0.30, 0.34), 90: (0.27, 0.31),
}  # fmt: skip
#: Table 3.4.3: SHGC correction A for an overhang of projection factor (depth / window height).
OVERHANG_A = {
    0.0: 0.00, 0.1: 0.05, 0.2: 0.09, 0.3: 0.14, 0.4: 0.19, 0.5: 0.24, 0.6: 0.28, 0.7: 0.33,
    0.8: 0.38, 0.9: 0.43, 1.0: 0.47,
}  # fmt: skip
#: Sec 4.4.3.1 and Figure 3.4.2: a horizontal sunshade at least 0.234 x the window height deep.
OVERHANG_FACTOR = 0.234
#: Sec 4.5.1.2(a)-(c): the least window area, as a share of the room's external wall area, for
#: rooms less than 8 m deep (20 %), 8 to 14 m deep (30 %) and more than 14 m deep (35 %)
#: (:func:`default_wwr`).
#: Sec 4.5.1.2(a): the ratio for a room less than 8 m deep.
DEFAULT_WWR = 0.20


def default_wwr(depth: float) -> float:
    """The window-to-wall ratio SAEngine assumes for a facade the engineer has not given: Sec
    4.5.1.2's least window area for a room of ``depth`` [m] (a whole-story zone takes the plan's
    depth behind the facade: the deepest room it may hold, the larger, safe-side glazing)."""
    if depth < 8.0:
        return 0.20
    return 0.30 if depth <= 14.0 else 0.35


def shgc_limit(wwr: float) -> float:
    """The Table 8.2.9(a) SHGC limit for a window-to-wall ratio (0-1): the row at or above it
    (a larger ratio has the smaller, stricter limit); 0.85 up to 10 %."""
    percent = wwr * 100.0
    for ratio in sorted(SHGC_BY_WWR):
        if percent <= ratio + 1e-9:
            return SHGC_BY_WWR[ratio][0]
    return SHGC_BY_WWR[90][0]


# ───────────────────────────── where BNBC is silent (to be checked) ─────────────────────────────

#: Equipment (plug) loads by ventilation group [W/m²]: BNBC gives none. From memory, to be
#: checked: ASHRAE Handbook of Fundamentals (2017) Ch 18 office load factors (light 5.4, medium
#: 10.8 W/m²); the other groups SAEngine's guesses.
EQUIPMENT = {
    "office": 10.8,
    "workroom": 10.8,
    "education": 5.4,
    "dwelling": 5.0,
    "hotel": 5.0,
    "hospital": 10.8,
    "retail": 5.4,
    "specialty": 5.4,
    "food": 5.4,
}
EQUIPMENT_DEFAULT = 5.0

#: Total metabolic heat per person [W] (sensible + latent; EnergyPlus splits it): from memory, to
#: be checked: ASHRAE Handbook of Fundamentals Ch 18 Table 1 (moderately active office work 130,
#: standing light work / walking 160 (retail, restaurants), dancing 250, athletics 525).
ACTIVITY = {"retail": 160.0, "specialty": 160.0, "food": 160.0, "sports": 250.0}
ACTIVITY_DEFAULT = 130.0

#: Cooling supply air leaving the coil [°C] and its humidity ratio [kg/kg] for the design
#: airflow (Sizing:Zone): SAEngine practice (a 11 °C supply difference at 24 °C), to be checked.
SUPPLY_AIR_TEMPERATURE = 13.0
SUPPLY_AIR_HUMIDITY = 0.008
#: Design-day wind [m/s] and site elevation [m]: BNBC gives none; from memory, to be checked.
DESIGN_WIND_SPEED = 2.0
SITE_ELEVATION = 10.0
#: Bangladesh Standard Time, UTC+6.
TIME_ZONE = 6.0

ASSUMPTIONS = [
    "Station latitudes and longitudes (Table 8.2.2 gives none): from memory, to be checked.",
    (
        "Equipment loads by use (BNBC gives none): ASHRAE Fundamentals Ch 18 office load factors, "
        "from memory, to be checked."
    ),
    (
        "Metabolic heat per person by use: ASHRAE Fundamentals Ch 18 Table 1, from memory, to be "
        "checked."
    ),
    "Design-day wind speed 2 m/s and site elevation 10 m: from memory, to be checked.",
    (
        "Cooling supply air 13 °C at 0.008 kg/kg for the design airflow: SAEngine practice, to be "
        "checked."
    ),
]


def station_for(city: str | None, location: str | None) -> tuple[Station, list[str]]:
    """The Table 8.2.2 station of the design (``city``) or of the Project Settings site
    (``location``); Dhaka when neither gives one."""
    if city:
        return STATIONS[city], []
    key = SETTINGS_STATION.get(location or "")
    if key:
        return STATIONS[key], []
    note = (
        f"site location '{location}' has no Table 8.2.2 station: Dhaka is used (set the HVAC "
        "design city)"
        if location
        else "no site location: Dhaka (Table 8.2.2) is used"
    )
    return STATIONS["dhaka"], [note]


def inside_conditions(use: str) -> tuple[float, float, str]:
    """Default indoor dry bulb [°C] and relative humidity [%] of a use, and where they come
    from: 24 °C (Sec 2.12.2.2) kept within the Table 8.2.1 row's range, and the row's upper
    humidity (the least energy, Sec 2.12.2.3); office buildings' row for a use without one."""
    row = VENTILATION[use].inside or 3
    inside = INSIDE[row]
    low, high = inside.db
    db = min(max(INDOOR_DB, low), high)
    rh = inside.rh[1] if inside.rh else 60.0
    source = (
        f"{db:g} °C (Sec 2.12.2.2, within Table 8.2.1 row {row} {inside.label} {low:g}-{high:g} "
        f"°C), {rh:g} % RH (upper value of the row, Sec 2.12.2.3)"
    )
    if inside.rh is None:
        source += " (the row gives no humidity: office buildings' 60 % taken)"
    return db, rh, source
