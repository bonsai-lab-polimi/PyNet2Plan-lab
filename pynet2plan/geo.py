"""
pynet2plan.geo
=============

Small geography helper used to place network nodes at real-world city
locations, and to draw the topology over a real map.

Two layers of geocoding are provided:

1. An offline database of ~180 well-known world cities (``_CITY_DB``), so
   that "add a network from a list of city names" works out of the box,
   with no internet connection and no extra dependencies.
2. An optional online fallback via OpenStreetMap Nominatim (through the
   third-party ``geopy`` package), used only when a name is not found in
   the offline database and ``allow_online=True``.

It also provides:

    haversine_km(lat1, lon1, lat2, lon2)
        great-circle distance in km, used as the "length" of a link
        between two geocoded nodes.

    lonlat_to_webmercator(lon, lat)
        projects WGS84 degrees to EPSG:3857 meters, the coordinate system
        used by OpenStreetMap map tiles (and therefore by the GUI's
        "View > Map background" option, backed by the optional
        ``contextily`` package).
"""

from __future__ import annotations

import math

# lower-case city name -> (latitude, longitude) in degrees.
# Coordinates are approximate city-centre locations, sufficient for
# network-planning demos (not for precision GIS work).
_CITY_DB: dict[str, tuple[float, float]] = {
    # --- Italy -----------------------------------------------------
    "milan": (45.4642, 9.1900), "milano": (45.4642, 9.1900),
    "rome": (41.9028, 12.4964), "roma": (41.9028, 12.4964),
    "naples": (40.8518, 14.2681), "napoli": (40.8518, 14.2681),
    "turin": (45.0703, 7.6869), "torino": (45.0703, 7.6869),
    "palermo": (38.1157, 13.3615),
    "genoa": (44.4056, 8.9463), "genova": (44.4056, 8.9463),
    "bologna": (44.4949, 11.3426),
    "florence": (43.7696, 11.2558), "firenze": (43.7696, 11.2558),
    "bari": (41.1171, 16.8719),
    "catania": (37.5079, 15.0830),
    "venice": (45.4408, 12.3155), "venezia": (45.4408, 12.3155),
    "verona": (45.4384, 10.9916),
    "padua": (45.4064, 11.8768), "padova": (45.4064, 11.8768),
    "trieste": (45.6495, 13.7768),
    "brescia": (45.5416, 10.2118),
    "parma": (44.8015, 10.3279),
    "modena": (44.6471, 10.9252),
    "reggio calabria": (38.1113, 15.6619),
    "cagliari": (39.2238, 9.1217),
    "perugia": (43.1122, 12.3888),
    "pisa": (43.7228, 10.4017),
    "como": (45.8081, 9.0852),
    "bergamo": (45.6983, 9.6773),

    # --- Western / Central Europe -----------------------------------
    "paris": (48.8566, 2.3522),
    "london": (51.5074, -0.1278),
    "berlin": (52.5200, 13.4050),
    "madrid": (40.4168, -3.7038),
    "barcelona": (41.3874, 2.1686),
    "lisbon": (38.7223, -9.1393),
    "porto": (41.1579, -8.6291),
    "seville": (37.3891, -5.9845), "sevilla": (37.3891, -5.9845),
    "valencia": (39.4699, -0.3763),
    "zaragoza": (41.6488, -0.8891),
    "malaga": (36.7213, -4.4214), "málaga": (36.7213, -4.4214),
    "murcia": (37.9922, -1.1307),
    "bilbao": (43.2630, -2.9350),
    "amsterdam": (52.3676, 4.9041),
    "rotterdam": (51.9244, 4.4777),
    "brussels": (50.8503, 4.3517),
    "antwerp": (51.2194, 4.4025),
    "vienna": (48.2082, 16.3738),
    "zurich": (47.3769, 8.5417),
    "geneva": (46.2044, 6.1432),
    "bern": (46.9480, 7.4474),
    "munich": (48.1351, 11.5820),
    "frankfurt": (50.1109, 8.6821),
    "hamburg": (53.5511, 9.9937),
    "cologne": (50.9375, 6.9603),
    "stockholm": (59.3293, 18.0686),
    "oslo": (59.9139, 10.7522),
    "copenhagen": (55.6761, 12.5683),
    "helsinki": (60.1699, 24.9384),
    "warsaw": (52.2297, 21.0122),
    "krakow": (50.0647, 19.9450),
    "gdansk": (54.3520, 18.6466),
    "prague": (50.0755, 14.4378),
    "budapest": (47.4979, 19.0402),
    "athens": (37.9838, 23.7275),
    "dublin": (53.3498, -6.2603),
    "edinburgh": (55.9533, -3.1883),
    "glasgow": (55.8642, -4.2518),
    "manchester": (53.4808, -2.2426),
    "birmingham": (52.4862, -1.8904),
    "zagreb": (45.8150, 15.9819),
    "ljubljana": (46.0569, 14.5058),
    "belgrade": (44.7866, 20.4489),
    "bucharest": (44.4268, 26.1025),
    "sofia": (42.6977, 23.3219),
    "bratislava": (48.1486, 17.1077),
    "luxembourg": (49.6116, 6.1319),
    "nice": (43.7102, 7.2620),
    "lyon": (45.7640, 4.8357),
    "marseille": (43.2965, 5.3698),
    "toulouse": (43.6047, 1.4442),
    "riga": (56.9496, 24.1052),
    "vilnius": (54.6872, 25.2797),
    "tallinn": (59.4370, 24.7536),

    # --- Eastern Europe / West Asia ----------------------------------
    "kyiv": (50.4501, 30.5234), "kiev": (50.4501, 30.5234),
    "moscow": (55.7558, 37.6173),
    "minsk": (53.9006, 27.5590),
    "istanbul": (41.0082, 28.9784),
    "ankara": (39.9334, 32.8597),
    "reykjavik": (64.1466, -21.9426),
    "tel aviv": (32.0853, 34.7818),
    "jerusalem": (31.7683, 35.2137),
    "tehran": (35.6892, 51.3890),
    "baghdad": (33.3152, 44.3661),
    "dubai": (25.2048, 55.2708),
    "abu dhabi": (24.4539, 54.3773),
    "doha": (25.2854, 51.5310),
    "riyadh": (24.7136, 46.6753),

    # --- North America -------------------------------------------------
    "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698),
    "san francisco": (37.7749, -122.4194),
    "seattle": (47.6062, -122.3321),
    "boston": (42.3601, -71.0589),
    "washington": (38.9072, -77.0369),
    "washington dc": (38.9072, -77.0369),
    "miami": (25.7617, -80.1918),
    "dallas": (32.7767, -96.7970),
    "atlanta": (33.7490, -84.3880),
    "denver": (39.7392, -104.9903),
    "phoenix": (33.4484, -112.0740),
    "palo alto": (37.4419, -122.1430),
    "san diego": (32.7157, -117.1611),
    "salt lake city": (40.7608, -111.8910),
    "boulder": (40.0150, -105.2705),
    "lincoln": (40.8136, -96.7026),
    "champaign": (40.1164, -88.2434),
    "pittsburgh": (40.4406, -79.9959),
    "ann arbor": (42.2808, -83.7430),
    "ithaca": (42.4440, -76.5019),
    "princeton": (40.3573, -74.6672),
    "college park": (38.9807, -76.9369),
    "toronto": (43.6532, -79.3832),
    "montreal": (45.5019, -73.5674),
    "vancouver": (49.2827, -123.1207),
    "ottawa": (45.4215, -75.6972),
    "mexico city": (19.4326, -99.1332),
    "guadalajara": (20.6597, -103.3496),
    "monterrey": (25.6866, -100.3161),
    "havana": (23.1136, -82.3666),

    # --- South America ---------------------------------------------
    "sao paulo": (-23.5505, -46.6333),
    "rio de janeiro": (-22.9068, -43.1729),
    "buenos aires": (-34.6037, -58.3816),
    "santiago": (-33.4489, -70.6693),
    "lima": (-12.0464, -77.0428),
    "bogota": (4.7110, -74.0721),
    "caracas": (10.4806, -66.9036),
    "montevideo": (-34.9011, -56.1645),
    "quito": (-0.1807, -78.4678),

    # --- Asia --------------------------------------------------------
    "tokyo": (35.6762, 139.6503),
    "osaka": (34.6937, 135.5023),
    "seoul": (37.5665, 126.9780),
    "beijing": (39.9042, 116.4074),
    "shanghai": (31.2304, 121.4737),
    "hong kong": (22.3193, 114.1694),
    "shenzhen": (22.5431, 114.0579),
    "singapore": (1.3521, 103.8198),
    "bangkok": (13.7563, 100.5018),
    "jakarta": (-6.2088, 106.8456),
    "manila": (14.5995, 120.9842),
    "kuala lumpur": (3.1390, 101.6869),
    "new delhi": (28.6139, 77.2090), "delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "bangalore": (12.9716, 77.5946),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "karachi": (24.8607, 67.0011),
    "islamabad": (33.6844, 73.0479),
    "dhaka": (23.8103, 90.4125),
    "hanoi": (21.0278, 105.8342),
    "ho chi minh city": (10.8231, 106.6297),
    "taipei": (25.0330, 121.5654),

    # --- Africa ------------------------------------------------------
    "cairo": (30.0444, 31.2357),
    "lagos": (6.5244, 3.3792),
    "nairobi": (-1.2921, 36.8219),
    "johannesburg": (-26.2041, 28.0473),
    "cape town": (-33.9249, 18.4241),
    "casablanca": (33.5731, -7.5898),
    "tunis": (36.8065, 10.1815),
    "algiers": (36.7538, 3.0588),
    "addis ababa": (9.0300, 38.7400),
    "accra": (5.6037, -0.1870),
    "dakar": (14.7167, -17.4677),

    # --- Oceania -----------------------------------------------------
    "sydney": (-33.8688, 151.2093),
    "melbourne": (-37.8136, 144.9631),
    "brisbane": (-27.4698, 153.0251),
    "perth": (-31.9505, 115.8605),
    "auckland": (-36.8485, 174.7633),
    "wellington": (-41.2865, 174.7762),
}


def list_known_cities() -> list[str]:
    """Names recognised by the offline database (for autocompletion/help)."""
    return sorted(_CITY_DB.keys())


def _lookup_offline(name: str) -> tuple[float, float] | None:
    key = name.strip().lower()
    if key in _CITY_DB:
        return _CITY_DB[key]
    # allow "City, Country" / "City, ST" style input
    base = key.split(",")[0].strip()
    return _CITY_DB.get(base)


def geocode(name: str, allow_online: bool = True, timeout: float = 5.0) -> tuple[float, float] | None:
    """Return (lat, lon) in degrees for a city name, or None if not found.

    Looks in the bundled offline database first (no network needed). If not
    found there and ``allow_online`` is True, falls back to OpenStreetMap
    Nominatim via the optional ``geopy`` package (requires internet access
    and ``pip install geopy``); any failure there (missing package, no
    connection, timeout, no match) is treated as "not found".
    """
    hit = _lookup_offline(name)
    if hit is not None:
        return hit
    if allow_online:
        try:
            from geopy.geocoders import Nominatim  # type: ignore
            geolocator = Nominatim(user_agent="pynet2plan")
            loc = geolocator.geocode(name, timeout=timeout)
            if loc is not None:
                return (loc.latitude, loc.longitude)
        except Exception:
            pass
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def lonlat_to_webmercator(lon: float, lat: float) -> tuple[float, float]:
    """Project WGS84 (lon, lat) degrees to EPSG:3857 (Web Mercator) meters.

    This is the coordinate system used by OpenStreetMap/Google-style map
    tiles, so nodes placed with this projection line up correctly with the
    optional map background (see pynet2plan.plotting / contextily).
    """
    r = 6378137.0
    x = math.radians(lon) * r
    lat_clamped = max(min(lat, 89.9), -89.9)
    y = r * math.log(math.tan(math.pi / 4 + math.radians(lat_clamped) / 2))
    return x, y


def webmercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Inverse of lonlat_to_webmercator: EPSG:3857 meters -> WGS84 degrees."""
    r = 6378137.0
    lon = math.degrees(x / r)
    lat = math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2)
    return lon, lat


def draw_offline_graticule(ax, lon_step: float = 5.0, lat_step: float = 5.0,
                            ocean_color: str = "#cfe3f4", line_color: str = "#ffffff",
                            label_color: str = "#4a5b68"):
    """Draw a lightweight, fully offline "map-like" background.

    This is *not* a traced/real coastline (which would need bundled
    geographic data this package doesn't ship) -- it is an ocean-tinted
    background with a longitude/latitude graticule, computed directly from
    the same Web-Mercator projection used to place city nodes. It needs no
    internet connection and no extra dependencies, so it always works as a
    fallback for the real OpenStreetMap tile background (see
    pynet2plan.plotting, which uses the optional 'contextily' package for that).

    Call this *after* the axes data limits are set (e.g. after plotting
    nodes/links and calling autoscale), so it only draws grid lines/labels
    within the current view.
    """
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    ax.set_facecolor(ocean_color)
    for spine in ax.spines.values():
        spine.set_edgecolor("#5b6b78")
        spine.set_linewidth(1.4)

    lon_min, lat_min = webmercator_to_lonlat(xlim[0], ylim[0])
    lon_max, lat_max = webmercator_to_lonlat(xlim[1], ylim[1])

    def _frange(a, b, step):
        start = math.floor(min(a, b) / step) * step
        v = start
        while v <= max(a, b) + step:
            yield v
            v += step

    for lon in _frange(lon_min, lon_max, lon_step):
        x, _ = lonlat_to_webmercator(lon, 0)
        if xlim[0] <= x <= xlim[1]:
            ax.axvline(x, color=line_color, lw=1.3, zorder=0.5)
            ax.text(x, ylim[0], f" {lon:.0f}\u00b0", fontsize=8, color=label_color,
                    va='bottom', ha='center', zorder=0.6, fontweight='medium')
    for lat in _frange(lat_min, lat_max, lat_step):
        _, y = lonlat_to_webmercator(0, lat)
        if ylim[0] <= y <= ylim[1]:
            ax.axhline(y, color=line_color, lw=1.3, zorder=0.5)
            ax.text(xlim[0], y, f"{lat:.0f}\u00b0 ", fontsize=8, color=label_color,
                    va='center', ha='left', zorder=0.6, fontweight='medium')

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.text(0.99, 0.01, "offline lon/lat grid \u2014 not a real map",
             transform=ax.transAxes, ha='right', va='bottom', fontsize=7.5,
             color=label_color, style='italic', zorder=10,
             bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='none', alpha=0.75))
