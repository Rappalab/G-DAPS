import os
import math
import datetime
import requests
from app.config import env_str

def _dfs_xy_conv(lat: float, lon: float):
    RE = 6371.00877
    GRID = 5.0
    SLAT1 = 30.0
    SLAT2 = 60.0
    OLON = 126.0
    OLAT = 38.0
    XO = 43
    YO = 136
    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD
    sn = math.tan(math.pi*0.25 + slat2*0.5)/math.tan(math.pi*0.25 + slat1*0.5)
    sn = math.log(math.cos(slat1)/math.cos(slat2))/math.log(sn)
    sf = math.tan(math.pi*0.25 + slat1*0.5)
    sf = (sf**sn)*math.cos(slat1)/sn
    ro = math.tan(math.pi*0.25 + olat*0.5)
    ro = re*sf/(ro**sn)
    ra = math.tan(math.pi*0.25 + (lat*DEGRAD)*0.5)
    ra = re*sf/(ra**sn)
    theta = lon*DEGRAD - olon
    if theta > math.pi: theta -= 2*math.pi
    if theta < -math.pi: theta += 2*math.pi
    theta *= sn
    x = int(math.floor(ra*math.sin(theta) + XO + 0.5))
    y = int(math.floor(ro - ra*math.cos(theta) + YO + 0.5))
    return x, y

def _kma_base_datetime_kst(now=None):
    if now is None:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    t = now - datetime.timedelta(minutes=40)
    return t.strftime("%Y%m%d"), t.strftime("%H") + "00"

def fetch_weather_kma(lat: float, lon: float):
    service_key = os.getenv("KMA_SERVICE_KEY", "").strip()
    if not service_key:
        raise RuntimeError("KMA_SERVICE_KEY is empty")

    nx, ny = _dfs_xy_conv(lat, lon)
    base_date, base_time = _kma_base_datetime_kst()

    url = env_str("KMA_CURRENT_WEATHER_URL", "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst")
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 100,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    items = data["response"]["body"]["items"]["item"]

    vec=wsd=t1h=reh=None
    for it in items:
        cat = it.get("category")
        val = it.get("obsrValue")
        if cat == "VEC": vec = float(val)
        elif cat == "WSD": wsd = float(val)
        elif cat == "T1H": t1h = float(val)
        elif cat == "REH": reh = float(val)

    if vec is None or wsd is None:
        raise RuntimeError("KMA response missing VEC/WSD")

    return {
        "wd": vec, "ws": wsd,
        "temp_c": t1h, "rh_pct": reh,
        "source": "KMA(getUltraSrtNcst)",
        "nx": nx, "ny": ny,
        "base_date": base_date, "base_time": base_time
    }

def fetch_weather_open_meteo(lat: float, lon: float):
    url = env_str("OPEN_METEO_API_URL", "https://api.open-meteo.com/v1/forecast")
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "wind_speed_10m,wind_direction_10m,temperature_2m,relative_humidity_2m",
        "timezone": "Asia/Seoul",
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    cur = j.get("current", {})
    ws_kmh = float(cur["wind_speed_10m"])
    wd = float(cur["wind_direction_10m"])
    temp = cur.get("temperature_2m")
    rh = cur.get("relative_humidity_2m")
    return {
        "wd": wd, "ws": ws_kmh / 3.6,
        "temp_c": float(temp) if temp is not None else None,
        "rh_pct": float(rh) if rh is not None else None,
        "source": "Open-Meteo(current)",
        "note": "wind_speed_10m km/h -> m/s"
    }
