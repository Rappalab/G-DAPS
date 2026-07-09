"""Automatic G-DAPS analysis pipeline for detected Gyeonggi wildfire events."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, Tuple
import os

import requests
from app.config import env_str

from app.engine import compute_layers
from app.weather_provider import fetch_weather_kma, fetch_weather_open_meteo
from app.wildfire_db import insert_analysis


def _wind_to_kor(deg: float) -> str:
    dirs = ["북풍", "북북동풍", "북동풍", "동북동풍", "동풍", "동남동풍", "남동풍", "남남동풍", "남풍", "남남서풍", "남서풍", "서남서풍", "서풍", "서북서풍", "북서풍", "북북서풍"]
    return dirs[int((deg % 360) / 22.5 + 0.5) % 16]


def send_telegram(text: str) -> Tuple[bool, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False, "telegram env not configured"
    try:
        r = requests.post(
            f"{env_str('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return False, str(data)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def run_auto_analysis(fire: Dict[str, Any], hours: float = 3, steps: int = 6, drift: float = 0.35, send_notify: bool = True) -> Dict[str, Any]:
    lat = float(fire["lat"])
    lon = float(fire["lon"])
    provider = os.getenv("WEATHER_PROVIDER", "KMA").upper().strip()
    weather = fetch_weather_open_meteo(lat, lon) if provider == "OPEN_METEO" else fetch_weather_kma(lat, lon)

    wd = float(weather.get("wd", 90.0))
    ws = float(weather.get("ws", 5.0))
    layers = compute_layers(lat, lon, wd, ws, hours, steps, drift_coef=drift, wd_mode="FROM")
    layer_summary = []
    for layer in layers:
        layer_summary.append({
            "minute": int(round(layer["hour"] * 60)),
            "center_lat": layer["center_lat"],
            "center_lon": layer["center_lon"],
            "major_km": layer["major_km"],
            "minor_km": layer["minor_km"],
            "drift_km": layer["drift_km"],
        })

    analysis = {
        "model": "G-DAPS v8 teardrop auto-analysis",
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "hours": hours,
        "steps": steps,
        "drift": drift,
        "wd_mode": "FROM",
        "layers": layer_summary,
    }

    temp = weather.get("temp_c")
    rh = weather.get("rh_pct")
    temp_text = f"{float(temp):.1f}℃" if temp is not None else "확인불가"
    rh_text = f"{float(rh):.0f}%" if rh is not None else "확인불가"
    brief = (
        "🚨 G-DAPS 산불 자동분석 알림\n\n"
        f"□ 산불ID: {fire.get('fire_id')}\n"
        f"□ 위치: {fire.get('address') or f'{lat:.6f}, {lon:.6f}'}\n"
        f"□ 신고시각: {fire.get('report_date','')} {fire.get('report_time','')}\n"
        f"□ 진행상태: {fire.get('status_name','')} / {fire.get('step_name','')}\n"
        f"□ 기상: {_wind_to_kor(wd)}({wd:.0f}°), 풍속 {ws:.1f}m/s, 기온 {temp_text}, 습도 {rh_text}\n"
        f"□ 분석: {int(hours*60)}분 / {steps}단계 자동 확산 시각화 완료\n"
        f"□ 접속: {env_str('PUBLIC_APP_URL', 'http://localhost:8504')}"
    )

    telegram_sent = False
    telegram_message = "skipped"
    if send_notify:
        telegram_sent, telegram_message = send_telegram(brief)

    analysis_id = insert_analysis(
        fire_id=str(fire.get("fire_id")),
        lat=lat,
        lon=lon,
        weather=weather,
        analysis=analysis,
        brief_text=brief,
        telegram_sent=telegram_sent,
    )
    return {
        "analysis_id": analysis_id,
        "fire": fire,
        "weather": weather,
        "analysis": analysis,
        "brief_text": brief,
        "telegram_sent": telegram_sent,
        "telegram_message": telegram_message,
    }
