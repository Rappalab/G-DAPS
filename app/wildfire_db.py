"""SQLite persistence for G-DAPS automatic wildfire detection/analysis."""
from __future__ import annotations

import json
import os
import sqlite3
from app.config import data_path, env_str
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

DEFAULT_DB_PATH = env_str("GDAPS_DB_PATH", data_path("gdaps.db"))


def get_db_path() -> str:
    path = os.getenv("GDAPS_DB_PATH", DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS wildfire_events (
            fire_id TEXT PRIMARY KEY,
            lon REAL,
            lat REAL,
            address TEXT,
            report_date TEXT,
            report_time TEXT,
            reported_at TEXT,
            occur_type_code TEXT,
            occur_type_name TEXT,
            status_code TEXT,
            status_name TEXT,
            step_code TEXT,
            step_name TEXT,
            is_gyeonggi INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            last_raw_json TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS wildfire_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fire_id TEXT,
            analyzed_at TEXT,
            lon REAL,
            lat REAL,
            weather_json TEXT,
            analysis_json TEXT,
            brief_text TEXT,
            telegram_sent INTEGER DEFAULT 0,
            FOREIGN KEY(fire_id) REFERENCES wildfire_events(fire_id)
        )
        """)
        conn.commit()


def upsert_event(fire: Dict[str, Any]) -> Tuple[bool, bool]:
    """Insert/update event. Returns (is_new, changed_status_or_step)."""
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    fire_id = str(fire.get("fire_id") or "").strip()
    if not fire_id:
        raise ValueError("fire_id is required")

    with connect() as conn:
        old = conn.execute("SELECT * FROM wildfire_events WHERE fire_id=?", (fire_id,)).fetchone()
        is_new = old is None
        changed = False
        if old is not None:
            changed = (
                str(old["status_code"] or "") != str(fire.get("status_code") or "")
                or str(old["step_code"] or "") != str(fire.get("step_code") or "")
            )
        conn.execute("""
        INSERT INTO wildfire_events (
            fire_id, lon, lat, address, report_date, report_time, reported_at,
            occur_type_code, occur_type_name, status_code, status_name, step_code, step_name,
            is_gyeonggi, first_seen_at, last_seen_at, last_raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fire_id) DO UPDATE SET
            lon=excluded.lon,
            lat=excluded.lat,
            address=excluded.address,
            report_date=excluded.report_date,
            report_time=excluded.report_time,
            reported_at=excluded.reported_at,
            occur_type_code=excluded.occur_type_code,
            occur_type_name=excluded.occur_type_name,
            status_code=excluded.status_code,
            status_name=excluded.status_name,
            step_code=excluded.step_code,
            step_name=excluded.step_name,
            is_gyeonggi=excluded.is_gyeonggi,
            last_seen_at=excluded.last_seen_at,
            last_raw_json=excluded.last_raw_json
        """, (
            fire_id,
            fire.get("lon"), fire.get("lat"), fire.get("address", ""),
            fire.get("report_date", ""), fire.get("report_time", ""), fire.get("reported_at", ""),
            fire.get("occur_type_code", ""), fire.get("occur_type_name", ""),
            fire.get("status_code", ""), fire.get("status_name", ""),
            fire.get("step_code", ""), fire.get("step_name", ""),
            1 if fire.get("is_gyeonggi") else 0,
            now, now, json.dumps(fire, ensure_ascii=False),
        ))
        conn.commit()
        return is_new, changed


def has_analysis(fire_id: str) -> bool:
    init_db()
    with connect() as conn:
        r = conn.execute("SELECT 1 FROM wildfire_analyses WHERE fire_id=? LIMIT 1", (fire_id,)).fetchone()
        return r is not None


def insert_analysis(fire_id: str, lat: float, lon: float, weather: Dict[str, Any], analysis: Dict[str, Any], brief_text: str = "", telegram_sent: bool = False) -> int:
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute("""
        INSERT INTO wildfire_analyses (fire_id, analyzed_at, lon, lat, weather_json, analysis_json, brief_text, telegram_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fire_id, now, lon, lat,
            json.dumps(weather, ensure_ascii=False),
            json.dumps(analysis, ensure_ascii=False),
            brief_text,
            1 if telegram_sent else 0,
        ))
        conn.commit()
        return int(cur.lastrowid)



def _analysis_row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    for key in ["weather_json", "analysis_json"]:
        try:
            d[key.replace("_json", "")] = json.loads(d.get(key) or "{}")
        except Exception:
            d[key.replace("_json", "")] = {}
    return d


def list_events(limit: int = 50, gyeonggi_only: bool = True) -> List[Dict[str, Any]]:
    init_db()
    where = "WHERE is_gyeonggi=1" if gyeonggi_only else ""
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM wildfire_events {where} ORDER BY last_seen_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def list_analyses(limit: int = 20, gyeonggi_only: bool = True) -> List[Dict[str, Any]]:
    init_db()
    where = "WHERE COALESCE(e.is_gyeonggi, 0)=1" if gyeonggi_only else ""
    with connect() as conn:
        rows = conn.execute(f"""
        SELECT a.*, e.address, e.status_name, e.step_name, e.report_date, e.report_time, e.is_gyeonggi
        FROM wildfire_analyses a
        LEFT JOIN wildfire_events e ON e.fire_id = a.fire_id
        {where}
        ORDER BY a.analyzed_at DESC
        LIMIT ?
        """, (limit,)).fetchall()
        return [_analysis_row_to_dict(r) for r in rows]


def get_latest_analysis_by_fire_id(fire_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        r = conn.execute("""
        SELECT a.*, e.address, e.status_name, e.step_name, e.report_date, e.report_time, e.is_gyeonggi
        FROM wildfire_analyses a
        LEFT JOIN wildfire_events e ON e.fire_id = a.fire_id
        WHERE a.fire_id=? AND COALESCE(e.is_gyeonggi, 0)=1
        ORDER BY a.analyzed_at DESC
        LIMIT 1
        """, (str(fire_id),)).fetchone()
        return _analysis_row_to_dict(r) if r else None


def latest_analysis() -> Optional[Dict[str, Any]]:
    rows = list_analyses(limit=1, gyeonggi_only=True)
    return rows[0] if rows else None


def cleanup_non_gyeonggi_analyses() -> int:
    init_db()
    with connect() as conn:
        cur = conn.execute("""
        DELETE FROM wildfire_analyses
        WHERE fire_id IN (
            SELECT fire_id FROM wildfire_events WHERE COALESCE(is_gyeonggi, 0) != 1
        )
        """)
        conn.commit()
        return int(cur.rowcount or 0)
