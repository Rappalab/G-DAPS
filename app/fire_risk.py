import os
import requests
from app.config import env_str, env_list

BASE = env_str("KFS_FIRE_RISK_BASE_URL", "http://apis.data.go.kr/1400377/forestPoint")
EP_NATION = env_str("KFS_FIRE_RISK_NATION_URL", BASE + "/forestPointListGeongugSearch")
CANDIDATES = env_list("KFS_FIRE_RISK_URLS", [
    BASE + "/forestPointListSidoSearch",
    BASE + "/forestPointListSigunguSearch",
    BASE + "/forestPointListEmdSearch",
    EP_NATION,
])

def fetch_fire_risk_gyeonggi():
    from urllib.parse import unquote

    raw = os.getenv("KFS_FIRE_RISK_KEY","").strip()
    key = unquote(raw) if "%" in raw else raw
    if not key:
        raise RuntimeError("KFS_FIRE_RISK_KEY is empty")

    last_err = None
    for url in CANDIDATES:
        try:
            params = {"ServiceKey": key, "pageNo": 1, "numOfRows": 200, "_type":"json", "excludeForecast": 0}
            r = requests.get(url, params=params, timeout=12)
            if r.status_code == 404:
                last_err = f"404 at {url}"
                continue
            r.raise_for_status()
            j = r.json()

            body = (j.get("response") or {}).get("body") if isinstance(j, dict) else None
            items = None
            if isinstance(body, dict):
                items = (body.get("items") or {}).get("item") or body.get("item")
            if items is None and isinstance(j, dict):
                items = j.get("items") or j.get("item")

            if items is None:
                return {"source_url": url, "raw": j, "note":"items parse failed"}

            if isinstance(items, dict):
                items = [items]

            filtered = [it for it in items if "doname" in it and "경기" in str(it.get("doname",""))]
            if not filtered:
                filtered = items

            return {"source_url": url, "items": filtered[:200]}
        except Exception as e:
            last_err = str(e)
            continue

    raise RuntimeError(f"Failed to fetch fire risk. Last error: {last_err}")
