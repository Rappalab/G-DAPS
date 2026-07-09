from flask import Flask, request, Response, jsonify
import os
import datetime

from app.config import env_str

from app.weather_provider import fetch_weather_kma, fetch_weather_open_meteo
from app.llm_brief import generate_brief, get_cached_brief
from app.engine import compute_layers, dest_point
from app.geocode import reverse_geocode_admin, search_place
from app.fire_risk import fetch_fire_risk_gyeonggi
from app.safemap_fire import fetch_fire_history_gyeonggi
from app.today_fire_api import fetch_today_fires_dict
from app.wildfire_monitor import scan_once
from app.wildfire_db import list_events, list_analyses, latest_analysis, get_latest_analysis_by_fire_id

app = Flask(__name__)
GDAPS_TOKEN = env_str("GDAPS_TOKEN", "")

def _require_token():
    if not GDAPS_TOKEN:
        return True
    return request.args.get("token", "") == GDAPS_TOKEN

def _coords_str(poly):
    return ",".join([f"{x:.6f},{y:.6f},0" for x, y in list(poly.exterior.coords)])

def _style_poly(style_id: str, color_aabbggrr: str):
    return f'<Style id="{style_id}"><PolyStyle><color>{color_aabbggrr}</color><outline>1</outline></PolyStyle><LineStyle><color>ff000000</color><width>2</width></LineStyle></Style>'

def _style_line(style_id: str, color_aabbggrr="ff00ffff", width=5):
    return f'<Style id="{style_id}"><LineStyle><color>{color_aabbggrr}</color><width>{width}</width></LineStyle></Style>'

def _timespan(begin_iso: str, end_iso: str):
    return f"<TimeSpan><begin>{begin_iso}</begin><end>{end_iso}</end></TimeSpan>"

@app.get("/health")
def health():
    return "ok"

@app.get("/auth_check")
def auth_check():
    """UI password check for static server deployment.

    If UI_PASSWORD is empty, login is disabled and the UI is allowed.
    """
    pw = env_str("UI_PASSWORD", "")
    if not pw:
        return jsonify({"ok": True, "password_required": False})
    if request.args.get("pw", "") == pw:
        return jsonify({"ok": True, "password_required": True})
    return jsonify({"ok": False, "password_required": True}), 403

@app.get("/weather")
def weather():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    lat = float(request.args.get("lat", "37.4138"))
    lon = float(request.args.get("lon", "127.5183"))
    provider = os.getenv("WEATHER_PROVIDER", "KMA").upper().strip()
    try:
        w = fetch_weather_open_meteo(lat, lon) if provider == "OPEN_METEO" else fetch_weather_kma(lat, lon)
        return jsonify(w)
    except Exception as e:
        return jsonify({"error": str(e), "provider": provider}), 500

@app.get("/fire_risk")
def fire_risk():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        return jsonify(fetch_fire_risk_gyeonggi())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/fire_history")
def fire_history():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    pageNo = int(request.args.get("pageNo","1"))
    numOfRows = int(request.args.get("numOfRows","50"))
    try:
        return jsonify(fetch_fire_history_gyeonggi(pageNo=pageNo, numOfRows=numOfRows))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/place_search")
def place_search():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify({"error": "q is required"}), 400
        item = search_place(q)
        if not item:
            return jsonify({"error": "검색 결과 없음", "query": q}), 404
        return jsonify(item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/today_fire")
def today_fire():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        gyeonggi_only = request.args.get("gyeonggi_only", "1") not in ("0", "false", "False")
        active_only = request.args.get("active_only", "0") in ("1", "true", "True")
        return jsonify({"items": fetch_today_fires_dict(gyeonggi_only=gyeonggi_only, active_only=active_only)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/auto_scan")
@app.get("/auto_scan")
def auto_scan():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        send_notify = request.args.get("telegram", "1") not in ("0", "false", "False")
        analyze_completed = request.args.get("analyze_completed", "1") in ("1", "true", "True")
        return jsonify(scan_once(analyze_completed=analyze_completed, send_notify=send_notify))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/auto_events")
def auto_events():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        limit = int(request.args.get("limit", "50"))
        return jsonify({"items": list_events(limit=limit, gyeonggi_only=True)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/auto_analyses")
def auto_analyses():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        limit = int(request.args.get("limit", "20"))
        return jsonify({"items": list_analyses(limit=limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/auto_analysis")
def auto_analysis_by_fire_id():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        fire_id = request.args.get("fire_id", "").strip()
        if not fire_id:
            return jsonify({"error": "fire_id is required"}), 400
        item = get_latest_analysis_by_fire_id(fire_id)
        return jsonify({"item": item} if item else {"item": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/auto_latest")
def auto_latest():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        return jsonify(latest_analysis() or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/brief")
def brief():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")
    try:
        fire_name = request.args.get("fire_name", "가정 산불")
        lat = float(request.args.get("lat", "37.4138"))
        lon = float(request.args.get("lon", "127.5183"))
        wd  = float(request.args.get("wd", "90"))
        ws  = float(request.args.get("ws", "5"))
        temp_c = request.args.get("temp_c", "")
        rh_pct = request.args.get("rh_pct", "")
        h   = float(request.args.get("h", "3"))
        steps = int(request.args.get("steps", "6"))
        wd_mode = request.args.get("wd_mode", "FROM").upper()
        drift_coef = float(request.args.get("drift", "0.35"))
        weather_source = request.args.get("weather_source", "")

        layers = compute_layers(lat, lon, wd, ws, h, steps, drift_coef=drift_coef, wd_mode=wd_mode)

        # time -> admin (center-based, best-effort)
        rows = []
        for layer in layers:
            g = reverse_geocode_admin(layer["center_lat"], layer["center_lon"])
            direct = g.get("full") or (g.get("sigungu","") + " " + g.get("eupmyeondong","")).strip()
            rows.append({"hour": layer["hour"], "direct": direct})

        # Optional: include fire risk/history summaries (Gyeonggi-only)
        risk_summary = "(미연동)"
        hist_summary = "(미연동)"
        try:
            rr = fetch_fire_risk_gyeonggi()
            its = rr.get("items") or []
            if its:
                it0 = its[0]
                risk_summary = f"analdate={it0.get('analdate','?')}, std={it0.get('std','?')}, mean={it0.get('meanavg','?')}, max={it0.get('maxi','?')}, min={it0.get('mini','?')}"
        except Exception:
            pass

        # SafeMap은 승인 전일 수 있어 실패해도 무시(미연동)
        try:
            hh = fetch_fire_history_gyeonggi(pageNo=1, numOfRows=10)
            its = hh.get("items") or []
            if its:
                most = its[0]
                hist_summary = f"최근 {len(its)}건(샘플), 최근 발생일={most.get('occu_date','?')}, 지역={most.get('adres','?')}"
        except Exception:
            pass

        payload = generate_brief({
            "fire_name": fire_name,
            "lat": lat, "lon": lon,
            "wd": wd, "ws": ws,
            "temp_c": temp_c if temp_c != "" else None,
            "rh_pct": rh_pct if rh_pct != "" else None,
            "h": h, "steps": steps,
            "wd_mode": wd_mode,
            "drift_coef": drift_coef,
            "weather_source": weather_source,
            "time_area_rows": rows,
            "fire_risk_summary": risk_summary,
            "fire_history_summary": hist_summary,
        })
        return jsonify(payload)
    except Exception as e:
        # Always return JSON so Streamlit won't crash on .json()
        return jsonify({"error": f"/brief failed: {str(e)}"}), 500

@app.get("/kml")

def kml():
    if not _require_token():
        return Response("forbidden", status=403, mimetype="text/plain")

    lat = float(request.args.get("lat", "37.4138"))
    lon = float(request.args.get("lon", "127.5183"))
    wd  = float(request.args.get("wd", "90"))
    ws  = float(request.args.get("ws", "5"))
    h   = float(request.args.get("h", "3"))
    steps = int(request.args.get("steps", "6"))
    drift_coef = float(request.args.get("drift", "0.35"))
    wd_mode = request.args.get("wd_mode", "FROM").upper()

    t0 = request.args.get("t0", "").strip()
    name = request.args.get("name", "G-DAPS 산불(가정)").strip()

    colors = ["b30000ff","8a0000ff","700000ff","5a0000ff","450000ff","330000ff",
              "260000ff","1a0000ff","140000ff","100000ff","0d0000ff","0a0000ff"]

    base_dt = None
    if t0:
        try:
            base_dt = datetime.datetime.fromisoformat(t0)
        except Exception:
            base_dt = None

    cached = get_cached_brief()
    brief_text = (cached.get("brief_text") or "").strip()
    brief_updated = cached.get("updated_at") or ""

    layers = compute_layers(lat, lon, wd, ws, h, steps, drift_coef=drift_coef, wd_mode=wd_mode)
    wd_to = layers[0]["wd_to"] if layers else wd

    styles = []
    placemarks = []

    styles.append(_style_line("wind_arrow", "ff00ffff", 5))
    arrow_len_km = max(1.0, min(8.0, ws * 0.6))
    try:
        lat2, lon2 = dest_point(lat, lon, wd_to, arrow_len_km)
        placemarks.append(f"<Placemark><name>풍향</name><styleUrl>#wind_arrow</styleUrl><LineString><tessellate>1</tessellate><coordinates>{lon:.6f},{lat:.6f},0 {lon2:.6f},{lat2:.6f},0</coordinates></LineString></Placemark>")
    except Exception:
        pass

    placemarks.append(f"<Placemark><name>발화점</name><Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point></Placemark>")

    for i, layer in enumerate(layers, start=1):
        hour = layer["hour"]
        poly = layer["poly"]
        style_id = f"pred_{i}"
        styles.append(_style_poly(style_id, colors[min(i-1, len(colors)-1)]))
        time_block = ""
        if base_dt:
            dt = h / max(1, steps)
            begin = (base_dt + datetime.timedelta(hours=dt*(i-1))).isoformat()
            end = (base_dt + datetime.timedelta(hours=dt*i)).isoformat()
            time_block = _timespan(begin, end)

        desc = ""
        if brief_text and i == len(layers):
            safe = brief_text.replace("\n", "<br/>")
            desc = f"<description><![CDATA[<b>자동 브리핑</b> (갱신: {brief_updated})<br/>{safe}]]></description>"

        placemarks.append(f"<Placemark><name>{name} (+{hour:.2f}h)</name>{desc}{time_block}<styleUrl>#{style_id}</styleUrl><Polygon><outerBoundaryIs><LinearRing><coordinates>{_coords_str(poly)}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")

    kml_text = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>G-DAPS</name>'
                + "".join(styles) + "".join(placemarks) + "</Document></kml>")
    return Response(kml_text, mimetype="application/vnd.google-earth.kml+xml", headers={"Cache-Control":"no-store"})
