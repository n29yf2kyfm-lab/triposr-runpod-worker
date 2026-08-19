"""WGS84 <-> OSGB36 British National Grid.

Needed because every UK open elevation dataset is on the National Grid
(EPSG:27700) while phones and addresses give WGS84 lat/lon. Environment
Agency LIDAR tiles are named by OS grid square, so finding the right tile
for a property means doing this conversion properly.

Pure stdlib on purpose — no pyproj, no numpy. It is ~100 lines of
well-documented geodesy, it runs anywhere, and it keeps the test suite
dependency-free.

Accuracy: the Helmert transformation used here is good to roughly 5 m,
which is far inside a 5 km LIDAR tile and fine for picking one. It is NOT
good enough to position a building footprint — for that, use the footprint
polygon's own coordinates rather than transforming a single point.
"""
import math

# Airy 1830 ellipsoid — the datum the National Grid is built on.
_AIRY_A = 6377563.396
_AIRY_B = 6356256.909

# WGS84 ellipsoid.
_WGS84_A = 6378137.000
_WGS84_B = 6356752.314245

# National Grid transverse Mercator parameters.
_F0 = 0.9996012717          # scale factor on the central meridian
_LAT0 = math.radians(49.0)  # true origin latitude
_LON0 = math.radians(-2.0)  # true origin longitude
_E0 = 400000.0              # easting of true origin
_N0 = -100000.0             # northing of true origin

# Helmert transformation, WGS84 -> OSGB36.
_TX, _TY, _TZ = -446.448, 125.157, -542.060
_S = 20.4894e-6
_RX = math.radians(-0.1502 / 3600.0)
_RY = math.radians(-0.2470 / 3600.0)
_RZ = math.radians(-0.8421 / 3600.0)

# The 100km grid-square lettering. OS uses a 5x5 grid (no 'I') for both the
# 500km and 100km squares, with the origin south-west of Cornwall.
_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"


def _to_cartesian(lat, lon, height, a, b):
    e2 = (a * a - b * b) / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    x = (nu + height) * math.cos(lat) * math.cos(lon)
    y = (nu + height) * math.cos(lat) * math.sin(lon)
    z = ((1 - e2) * nu + height) * math.sin(lat)
    return x, y, z


def _from_cartesian(x, y, z, a, b):
    e2 = (a * a - b * b) / (a * a)
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1 - e2))
    # Iterate — converges in a handful of passes at these latitudes.
    for _ in range(10):
        nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat_new = math.atan2(z + e2 * nu * math.sin(lat), p)
        if abs(lat_new - lat) < 1e-12:
            lat = lat_new
            break
        lat = lat_new
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    lon = math.atan2(y, x)
    height = p / math.cos(lat) - nu
    return lat, lon, height


def wgs84_to_osgb36(lat_deg, lon_deg, height=0.0):
    """WGS84 lat/lon (degrees) -> OSGB36 lat/lon (radians)."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    x, y, z = _to_cartesian(lat, lon, height, _WGS84_A, _WGS84_B)
    # Helmert: rotate, scale, translate.
    x2 = _TX + x * (1 + _S) + (-_RZ) * y + _RY * z
    y2 = _TY + _RZ * x + y * (1 + _S) + (-_RX) * z
    z2 = _TZ + (-_RY) * x + _RX * y + z * (1 + _S)
    return _from_cartesian(x2, y2, z2, _AIRY_A, _AIRY_B)


def latlon_to_easting_northing(lat_deg, lon_deg):
    """WGS84 lat/lon (degrees) -> National Grid easting/northing (metres)."""
    lat, lon, _ = wgs84_to_osgb36(lat_deg, lon_deg)

    a, b = _AIRY_A, _AIRY_B
    e2 = (a * a - b * b) / (a * a)
    n = (a - b) / (a + b)
    n2, n3 = n * n, n * n * n

    sin_lat, cos_lat, tan_lat = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * _F0 / math.sqrt(1 - e2 * sin_lat ** 2)
    rho = a * _F0 * (1 - e2) / (1 - e2 * sin_lat ** 2) ** 1.5
    eta2 = nu / rho - 1

    d_lat, s_lat = lat - _LAT0, lat + _LAT0
    m = b * _F0 * (
        (1 + n + 1.25 * n2 + 1.25 * n3) * d_lat
        - (3 * n + 3 * n2 + 2.625 * n3) * math.sin(d_lat) * math.cos(s_lat)
        + (1.875 * n2 + 1.875 * n3) * math.sin(2 * d_lat) * math.cos(2 * s_lat)
        - (35.0 / 24.0) * n3 * math.sin(3 * d_lat) * math.cos(3 * s_lat)
    )

    i = m + _N0
    ii = (nu / 2) * sin_lat * cos_lat
    iii = (nu / 24) * sin_lat * cos_lat ** 3 * (5 - tan_lat ** 2 + 9 * eta2)
    iiia = (nu / 720) * sin_lat * cos_lat ** 5 * (61 - 58 * tan_lat ** 2
                                                  + tan_lat ** 4)
    iv = nu * cos_lat
    v = (nu / 6) * cos_lat ** 3 * (nu / rho - tan_lat ** 2)
    vi = (nu / 120) * cos_lat ** 5 * (5 - 18 * tan_lat ** 2 + tan_lat ** 4
                                      + 14 * eta2 - 58 * tan_lat ** 2 * eta2)

    d = lon - _LON0
    northing = i + ii * d ** 2 + iii * d ** 4 + iiia * d ** 6
    easting = _E0 + iv * d + v * d ** 3 + vi * d ** 5
    return easting, northing


def grid_square(easting, northing):
    """Two-letter OS 100km grid square for a point, e.g. 'TQ'.

    The standard OS indexing: the first letter names the 500km square and
    the second the 100km square within it, both lettered A-Z omitting 'I',
    running west-to-east then north-to-south from a false origin south-west
    of the Scilly Isles.
    """
    e100 = int(math.floor(easting / 100000))
    n100 = int(math.floor(northing / 100000))
    if not (0 <= e100 <= 6 and 0 <= n100 <= 12):
        raise ValueError(
            f"easting/northing {easting:.0f},{northing:.0f} is outside the "
            f"National Grid — this dataset covers Great Britain only.")
    i1 = (19 - n100) - (19 - n100) % 5 + (e100 + 10) // 5
    i2 = (19 - n100) * 5 % 25 + e100 % 5
    return _LETTERS[i1] + _LETTERS[i2]


def grid_ref(easting, northing, digits=4):
    """Standard OS grid reference, e.g. 'TQ 3080 8040' at 4 digits."""
    square = grid_square(easting, northing)
    divisor = 10 ** (5 - digits)
    e = int(math.floor((easting % 100000) / divisor))
    n = int(math.floor((northing % 100000) / divisor))
    return f"{square}{e:0{digits}d}{n:0{digits}d}"


def lidar_tile_name(easting, northing, tile_km=5):
    """Name of the Environment Agency LIDAR tile containing this point.

    EA composite products are published in 5 km tiles named by the 10 km
    square plus a quadrant letter — e.g. 'TQ38ne'. The naming is what makes
    tile URLs derivable from a coordinate, which is how this gets automated
    despite there being no formal download API.
    """
    square = grid_square(easting, northing)
    e_in = easting % 100000
    n_in = northing % 100000
    e10 = int(e_in // 10000)
    n10 = int(n_in // 10000)
    if tile_km == 10:
        return f"{square}{e10}{n10}"
    # 5km quadrant within the 10km square.
    east_half = (e_in % 10000) >= 5000
    north_half = (n_in % 10000) >= 5000
    quadrant = ("n" if north_half else "s") + ("e" if east_half else "w")
    return f"{square}{e10}{n10}{quadrant}"


def bbox_around(easting, northing, radius_m=60.0):
    """Axis-aligned bounding box in National Grid metres.

    60 m default comfortably contains a domestic property and its immediate
    neighbours — enough context to separate the target roof from what abuts
    it, without pulling a whole street.
    """
    return (easting - radius_m, northing - radius_m,
            easting + radius_m, northing + radius_m)


def easting_northing_to_latlon(easting, northing, tol_m=1e-4, max_iter=12):
    """National Grid metres -> WGS84 lat/lon (degrees). The inverse.

    Everything upstream converts ONE way — an address becomes a grid
    reference, and a grid reference picks a LIDAR tile. Going back the
    other way is what a height field needs: a DSM arrives on the grid,
    and to drape imagery on it or hand it to anything geographic, each
    cell has to become a lat/lon.

    Solved by iteration on the forward projection rather than by writing
    the series out backwards. The forward transform is the one that has
    been checked against the OS worked example, so inverting it
    numerically inherits that check instead of introducing a second set
    of coefficients to get wrong. It converges in a handful of steps at
    UK latitudes; a metre of easting is ~1.5e-5 degrees of longitude, so
    the default tolerance is a tenth of a millimetre.

    Raises ValueError off the grid or if it does not converge — a silent
    near-miss here would put a building metres from where it stands, and
    the projection is happy to return a mathematically valid answer for a
    coordinate nowhere near Britain.
    """
    # The National Grid covers 0-700 km east, 0-1300 km north. Outside
    # that the transverse Mercator still SOLVES; the answer just is not a
    # place in Great Britain.
    if not (-1000.0 <= easting <= 800000.0
            and -1000.0 <= northing <= 1400000.0):
        raise ValueError(
            f"E {easting:.1f} N {northing:.1f} is not on the National Grid "
            f"of Great Britain (0-700000 east, 0-1300000 north)")
    # Seed from a spherical approximation about the true origin.
    lat = 49.0 + (northing + 100000.0) / 111320.0
    lon = -2.0 + (easting - 400000.0) / (111320.0 * math.cos(math.radians(53.0)))
    for _ in range(max_iter):
        e_try, n_try = latlon_to_easting_northing(lat, lon)
        de, dn = easting - e_try, northing - n_try
        if abs(de) < tol_m and abs(dn) < tol_m:
            return lat, lon
        # Local scale: how far a small step in degrees moves us on the grid.
        step = 1e-6
        e_dlat, n_dlat = latlon_to_easting_northing(lat + step, lon)
        e_dlon, n_dlon = latlon_to_easting_northing(lat, lon + step)
        j11, j21 = (e_dlat - e_try) / step, (n_dlat - n_try) / step
        j12, j22 = (e_dlon - e_try) / step, (n_dlon - n_try) / step
        det = j11 * j22 - j12 * j21
        if abs(det) < 1e-12:
            break
        lat += (de * j22 - dn * j12) / det
        lon += (dn * j11 - de * j21) / det
    raise ValueError(
        f"grid reference E {easting:.1f} N {northing:.1f} did not invert to "
        f"a lat/lon within {tol_m} m after {max_iter} steps — check it is "
        f"inside Great Britain")
