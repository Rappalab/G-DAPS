import os
import requests
from urllib.parse import unquote
from app.config import env_list

CANDIDATE_URLS = env_list("SAFEMAP_FIRE_HISTORY_URLS", [
    "http://safemap.go.kr/openapi2/IF_0088",
    "https://safemap.go.kr/openapi2/IF_0088",
    "http://www.safemap.go.kr/openapi2/IF_0088",
    "https://www.safemap.go.kr/openapi2/IF_0088",
])

def fetch_fire_history_gyeonggi(pageNo=1, numOfRows=50):
    """SafeMap IF_0088. Filters ctprvn_cd=41 (Gyeonggi).
    Notes:
      - serviceKey is described as URL-encoded on SafeMap docs.
      - In practice, users often paste the encoded key containing '%'.
        We unquote once (to avoid double-encoding) and let requests encode params.
      - SafeMap sometimes redirects between http/https or www/no-www; we try multiple.
    """
    raw = os.getenv("SAFEMAP_KEY","").strip()
    if not raw:
        raise RuntimeError("SAFEMAP_KEY is empty")

    key = unquote(raw) if "%" in raw else raw

    params = {
        "serviceKey": key,
        "pageNo": int(pageNo),
        "numOfRows": int(numOfRows),
        "returnType": "json",   # docs: XML/JSON, default JSON. lowercase is safest.
    }

    last_err = None
    for url in CANDIDATE_URLS:
        try:
            # try without redirects first (to catch location)
            r = requests.get(url, params=params, timeout=12, allow_redirects=False)
            if r.status_code in (301,302,303,307,308):
                loc = r.headers.get("Location","")
                if loc:
                    r = requests.get(loc, params=params, timeout=12)
            # If server errors, capture body for diagnosis
            if r.status_code != 200:
                last_err = f"{r.status_code} at {url} body={r.text[:200]}"
                continue

            j = r.json()

            # structure: response->body->items->item (common)
            body = (j.get("response") or {}).get("body") if isinstance(j, dict) else None
            items = None
            if isinstance(body, dict):
                items = (body.get("items") or {}).get("item") or body.get("item")
            if items is None and isinstance(j, dict):
                items = j.get("items") or j.get("item")

            if items is None:
                return {"raw": j, "note":"items parse failed (check resultCode/resultMsg)"}

            if isinstance(items, dict):
                items = [items]

            gg = [it for it in items if str(it.get("ctprvn_cd","")) == "41"]
            return {"items": gg, "total": len(gg), "source_url": url}
        except Exception as e:
            last_err = str(e)
            continue

    raise RuntimeError(f"SafeMap IF_0088 failed. Last error: {last_err}")
