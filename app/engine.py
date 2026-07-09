import math
from shapely.geometry import Polygon

def dest_point(lat, lon, bearing_deg, dist_km):
    R = 6371.0
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    d = dist_km / R
    lat2 = math.asin(math.sin(lat1)*math.cos(d) + math.cos(lat1)*math.sin(d)*math.cos(br))
    lon2 = lon1 + math.atan2(math.sin(br)*math.sin(d)*math.cos(lat1), math.cos(d)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2)+540)%360-180

def wd_to_from(wd_deg: float) -> float:
    return (wd_deg + 180.0) % 360.0

def _km_to_deg(lat, dx_km, dy_km):
    dlat = dy_km / 111.0
    dlon = dx_km / (111.0 * math.cos(math.radians(lat)) + 1e-9)
    return dlat, dlon

def teardrop_polygon(lat_c, lon_c, major_km, minor_km, bearing_deg, skew=0.65, upwind_shrink=0.55, n=120):
    th = math.radians(bearing_deg)
    ux, uy = math.sin(th), math.cos(th)
    px, py = -uy, ux

    pts = []
    for i in range(n):
        a = 2*math.pi*i/n
        xu = major_km * math.cos(a)
        yv = minor_km * math.sin(a)

        f = xu / (major_km + 1e-9)
        if f >= 0:
            sc = 1.0 + skew * (f**1.3)
        else:
            sc = 1.0 - (1.0 - upwind_shrink) * ((-f)**1.1)

        xu2 = xu * sc
        yv2 = yv * (0.9 + 0.1*sc)

        dx = xu2*ux + yv2*px
        dy = xu2*uy + yv2*py
        dlat, dlon = _km_to_deg(lat_c, dx, dy)
        pts.append((lon_c + dlon, lat_c + dlat))

    return Polygon(pts).buffer(0)

def compute_layers(lat, lon, wd_input, ws, h, steps, drift_coef=0.35, wd_mode="TO"):
    steps = max(1, min(12, int(steps)))
    h = max(0.25, min(6.0, float(h)))
    dt = h / steps

    wd_to = float(wd_input)
    if str(wd_mode).upper() == "FROM":
        wd_to = wd_to_from(wd_to)

    out = []
    for i in range(1, steps+1):
        hour = dt*i
        major_km = max(0.4, (ws * 3.6) * hour * 0.42)
        minor_km = max(0.25, major_km * 0.40)
        drift_km = max(0.0, (ws * 3.6) * hour * float(drift_coef))
        clat, clon = dest_point(lat, lon, wd_to, drift_km) if drift_km > 0 else (lat, lon)
        poly = teardrop_polygon(clat, clon, major_km, minor_km, wd_to)
        out.append({"i": i, "hour": hour, "center_lat": clat, "center_lon": clon, "poly": poly,
                    "major_km": major_km, "minor_km": minor_km, "wd_to": wd_to, "drift_km": drift_km})
    return out
