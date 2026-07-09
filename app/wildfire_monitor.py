"""Poll todayFire API and trigger automatic G-DAPS analysis for new active Gyeonggi fires.

CLI examples:
    python -m app.wildfire_monitor --once
    python -m app.wildfire_monitor --loop --interval 120
"""
from __future__ import annotations

import argparse
import time
from typing import Dict, Any, List

from app.today_fire_api import fetch_today_fires_dict
from app.wildfire_db import upsert_event, has_analysis, list_analyses
from app.auto_analyzer import run_auto_analysis


def scan_once(analyze_completed: bool = False, send_notify: bool = True) -> Dict[str, Any]:
    fires = fetch_today_fires_dict(gyeonggi_only=True, active_only=False)
    processed: List[Dict[str, Any]] = []
    analyzed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for fire in fires:
        is_new, changed = upsert_event(fire)
        processed.append({"fire_id": fire.get("fire_id"), "is_new": is_new, "changed": changed, "status": fire.get("status_name")})

        # 운영 원칙:
        # - 주기 스캔은 금일 산불 목록/진화상태/단계만 계속 갱신합니다.
        # - 분석 토큰을 쓰는 자동분석은 경기도 신규 fire_id를 최초 감지한 순간 1회만 수행합니다.
        # - 같은 fire_id는 진화상태/단계가 변경되어도 분석을 재실행하지 않습니다.
        active = fire.get("status_code") == "02" or "진화중" in str(fire.get("status_name") or "")
        if has_analysis(str(fire.get("fire_id"))):
            skipped.append({"fire_id": fire.get("fire_id"), "reason": "already analyzed; status updated only"})
            continue
        if not is_new:
            skipped.append({"fire_id": fire.get("fire_id"), "reason": "known fire; status updated only"})
            continue
        if not active and not analyze_completed:
            skipped.append({"fire_id": fire.get("fire_id"), "reason": "not active"})
            continue
        if fire.get("lat") is None or fire.get("lon") is None:
            skipped.append({"fire_id": fire.get("fire_id"), "reason": "missing coordinate"})
            continue
        result = run_auto_analysis(fire, send_notify=send_notify)
        analyzed.append({"fire_id": fire.get("fire_id"), "analysis_id": result.get("analysis_id"), "telegram_sent": result.get("telegram_sent")})

    return {
        "total_gyeonggi": len(fires),
        "fires": fires,
        "processed": processed,
        "analyzed": analyzed,
        "skipped": skipped,
        "latest": list_analyses(limit=5),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--analyze-completed", action="store_true")
    args = p.parse_args()

    if args.loop:
        while True:
            print(scan_once(analyze_completed=args.analyze_completed, send_notify=not args.no_telegram))
            time.sleep(max(30, args.interval))
    else:
        print(scan_once(analyze_completed=args.analyze_completed, send_notify=not args.no_telegram))


if __name__ == "__main__":
    main()
