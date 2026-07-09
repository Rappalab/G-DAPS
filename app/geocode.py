import os
import csv
import math
import requests
from functools import lru_cache
from app.config import env_str, PROJECT_ROOT


def _sites_csv_path():
    candidates = [
        env_str("GDAPS_SITES_CSV", str(PROJECT_ROOT / "gdaps_web_sites.csv")),
        os.path.join(os.path.dirname(__file__), "gdaps_web_sites.csv"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "gdaps_web_sites.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


@lru_cache(maxsize=1)
def _load_sites_for_geocode():
    path = _sites_csv_path()
    if not path:
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    rows.append({
                        "site_id": r.get("site_id", ""),
                        "city": r.get("시군", ""),
                        "dong": r.get("행정구역_상세", ""),
                        "name": r.get("시설명", ""),
                        "address": r.get("주소", ""),
                        "lat": float(r.get("위도")),
                        "lon": float(r.get("경도")),
                    })
                except Exception:
                    continue
    except Exception:
        return []
    return rows


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def local_reverse_geocode_hint(lat: float, lon: float):
    """VWorld 미연동 시 경보시설 CSV를 이용해 가장 가까운 시군/시설명을 행정구역 힌트로 반환."""
    sites = _load_sites_for_geocode()
    if not sites:
        return {}
    nearest = min(sites, key=lambda s: _haversine_km(lat, lon, s["lat"], s["lon"]))
    dist = _haversine_km(lat, lon, nearest["lat"], nearest["lon"])
    city = nearest.get("city") or "경기도"
    dong = nearest.get("dong") or ""
    name = nearest.get("name") or "인근 경보시설"
    full = f"{city} {dong}".strip() if dong else f"{city} {name} 인근"
    return {"full": full, "sido": "경기도", "sigungu": city, "eupmyeondong": dong, "nearest_site": name, "distance_km": round(dist, 2), "source": "local_sites_hint"}


def vworld_reverse_geocode(lat: float, lon: float):
    key = os.getenv("VWORLD_KEY", "").strip()
    if not key:
        return {}
    url = env_str("VWORLD_ADDRESS_API_URL", "https://api.vworld.kr/req/address")
    params = {
        "service":"address","request":"getaddress","version":"2.0","crs":"epsg:4326",
        "point": f"{lon},{lat}","format":"json","type":"both","key": key
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    resp = j.get("response", {})
    if resp.get("status") != "OK":
        return {}
    results = resp.get("result", []) or []
    if not results:
        return {}
    best = results[0]
    out = {"full": best.get("text","")}
    st = best.get("structure") or {}
    if st:
        out["sido"] = st.get("level1")
        out["sigungu"] = st.get("level2")
        out["eupmyeondong"] = st.get("level4L") or st.get("level4A") or st.get("level3")
    return {k:v for k,v in out.items() if v}


def reverse_geocode_admin(lat: float, lon: float):
    """행정구역 산출: VWorld 우선, 실패 시 로컬 경보시설 CSV 기반 힌트."""
    try:
        g = vworld_reverse_geocode(lat, lon)
        if g:
            g["source"] = "vworld"
            return g
    except Exception:
        pass
    return local_reverse_geocode_hint(lat, lon)


def local_search_place(query: str):
    q = (query or "").strip().lower().replace(" ", "")
    if not q:
        return None
    demo_places = {
        "경기도청북부청사": (37.747575, 127.071862, "경기도청 북부청사"),
        "북부청사": (37.747575, 127.071862, "경기도청 북부청사"),
        "경기도청": (37.289153, 127.053442, "경기도청 광교청사"),
        "수원시청": (37.263406, 127.028584, "수원시청"),
        "포천시청": (37.894914, 127.200352, "포천시청"),
        "가평군청": (37.831509, 127.509541, "가평군청"),
        "연천군청": (38.096435, 127.074755, "연천군청"),
        "파주시청": (37.759925, 126.779939, "파주시청"),
        "김포시청": (37.615246, 126.715632, "김포시청"),
        "양평군청": (37.491789, 127.487637, "양평군청"),
        "남양주시청": (37.636002, 127.216528, "남양주시청"),
        "용인시청": (37.241086, 127.177553, "용인시청"),
    }
    for key, (lat, lon, label) in demo_places.items():
        if q in key or key in q:
            return {"lat": lat, "lon": lon, "label": label, "source": "built_in_demo"}
    for s in _load_sites_for_geocode():
        hay = " ".join([s.get("city",""), s.get("dong",""), s.get("name",""), s.get("address","")]).lower().replace(" ", "")
        if q in hay:
            return {"lat": s["lat"], "lon": s["lon"], "label": f"{s.get('city','')} {s.get('name','')}", "source": "local_sites"}
    return None


def vworld_search_place(query: str):
    key = os.getenv("VWORLD_KEY", "").strip()
    if not key or not (query or "").strip():
        return None
    url = env_str("VWORLD_SEARCH_API_URL", "https://api.vworld.kr/req/search")
    params = {"service":"search", "request":"search", "version":"2.0", "crs":"EPSG:4326", "size":"1", "page":"1", "query": query, "type":"place", "format":"json", "key": key}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    items = (((j.get("response") or {}).get("result") or {}).get("items") or [])
    if not items:
        return None
    it = items[0]
    pt = it.get("point") or {}
    return {"lat": float(pt.get("y")), "lon": float(pt.get("x")), "label": it.get("title") or query, "source": "vworld_search"}


def search_place(query: str):
    local = local_search_place(query)
    if local:
        return local
    try:
        return vworld_search_place(query)
    except Exception:
        return None
