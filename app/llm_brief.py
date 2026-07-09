import os
from app.config import env_str
import json
import time
import re
from typing import Any, Dict, Iterable, List, Optional

CACHE_PATH = os.path.join(os.path.dirname(__file__), "brief_cache.json")


def _load_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": None, "brief_text": "", "inputs": {}}


def _save_cache(payload: dict):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _to_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def format_hour_label(hour: float) -> str:
    minutes = int(round(float(hour) * 60))
    if minutes < 60:
        return f"{minutes}분"
    h = minutes // 60
    m = minutes % 60
    if m == 0:
        return f"{h}시간"
    return f"{h}시간 {m}분"


def _clean_area(area: Any) -> str:
    text = str(area or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text or text in {"None", "null", "-"}:
        return "행정구역 미확인"
    # VWorld full address가 너무 길 경우 행정동 중심으로 간결화
    parts = text.split()
    if len(parts) >= 4 and parts[0].endswith("도"):
        return " ".join(parts[:4])
    if len(parts) >= 3 and ("경기" in parts[0] or parts[0].endswith("도")):
        return " ".join(parts[:3])
    return text


def _unique(seq: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in seq:
        x = _clean_area(x)
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_std(risk_summary: str) -> Optional[int]:
    text = str(risk_summary or "")
    m = re.search(r"(?:std|riskgrade)\s*=\s*([1-6])", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-6])\s*등급", text)
    if m:
        return int(m.group(1))
    return None


def _severity(inputs: Dict[str, Any]) -> tuple[str, List[str], str]:
    ws = _to_float(inputs.get("ws"), 0.0) or 0.0
    rh = _to_float(inputs.get("rh_pct"), None)
    temp = _to_float(inputs.get("temp_c"), None)
    std = _extract_std(inputs.get("fire_risk_summary", ""))

    score = 0
    reasons: List[str] = []

    if ws >= 9:
        score += 3
        reasons.append(f"풍속 {ws:.1f}m/s로 강풍 수준")
    elif ws >= 5:
        score += 2
        reasons.append(f"풍속 {ws:.1f}m/s로 확산 가능성 있음")
    elif ws >= 2.5:
        score += 1
        reasons.append(f"풍속 {ws:.1f}m/s로 완만한 확산 가능")
    else:
        reasons.append(f"풍속 {ws:.1f}m/s로 바람 영향은 제한적")

    if rh is not None:
        if rh <= 25:
            score += 2
            reasons.append(f"습도 {rh:.0f}%로 매우 건조")
        elif rh <= 40:
            score += 1
            reasons.append(f"습도 {rh:.0f}%로 건조 경향")

    if temp is not None:
        if temp >= 32:
            score += 1
            reasons.append(f"기온 {temp:.1f}℃로 고온")

    # 산불위험예보: 1이 가장 높고 6이 가장 낮음
    if std is not None:
        if std <= 2:
            score += 2
            reasons.append(f"산불위험예보 {std}등급(높은 위험권)")
        elif std == 3:
            score += 1
            reasons.append("산불위험예보 3등급(주의 필요)")
        elif std >= 5:
            reasons.append(f"산불위험예보 {std}등급(상대적으로 낮은 위험권)")

    if score >= 5:
        return "높음", reasons, "초기부터 직접피해 예상지역 중심으로 주민안전 안내와 현장통제를 병행해야 합니다."
    if score >= 3:
        return "중간", reasons, "확산 방향과 인접지역을 계속 확인하면서 단계적 안내가 필요합니다."
    return "낮음", reasons, "현재 입력값 기준 급격한 확산 가능성은 제한적이나, 현장 변화 확인은 필요합니다."


def _rows(inputs: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for r in inputs.get("time_area_rows", []) or []:
        hour = r.get("hour")
        area = _clean_area(r.get("direct"))
        try:
            label = format_hour_label(float(hour))
        except Exception:
            label = str(hour or "시간 미상")
        rows.append({"time": label, "area": area})
    return rows


def _message_samples(direct_areas: List[str], level: str) -> Dict[str, str]:
    main_area = direct_areas[0] if direct_areas else "발화점 인근 지역"
    direct_join = ", ".join(direct_areas[:4]) if direct_areas else main_area
    emergency = (
        f"[경기도 재난안내] {main_area} 산불 확산 우려. 인근 주민은 창문을 닫고, "
        "마을방송·재난문자·현장통제 안내에 따라 대피 준비 바랍니다."
    )
    urgent = (
        f"[위급재난문자 검토] {direct_join} 방향으로 산불 접근 가능. "
        "현장 지휘부의 대피명령 시 즉시 지정 대피장소로 이동 바랍니다."
    )
    safety = (
        f"[안전안내] {direct_join} 및 인접지역은 연기 유입과 교통통제 가능성이 있습니다. "
        "입산을 자제하고 우회도로 및 지자체 안내를 확인 바랍니다."
    )
    if level == "낮음":
        urgent = "[위급재난문자] 현재 단계에서는 대피명령 등 현장 상황 확인 후 발송 검토"
    return {"emergency": emergency, "urgent": urgent, "safety": safety}


def _build_rule_based_brief(inputs: Dict[str, Any]) -> str:
    rows = _rows(inputs)
    direct_areas = _unique([r["area"] for r in rows if r.get("area")])
    level, reasons, conclusion = _severity(inputs)
    msg = _message_samples(direct_areas, level)

    fire_name = str(inputs.get("fire_name") or "산불 상황").strip()
    lat = _to_float(inputs.get("lat"), 0.0) or 0.0
    lon = _to_float(inputs.get("lon"), 0.0) or 0.0
    wd = _to_float(inputs.get("wd"), 0.0) or 0.0
    ws = _to_float(inputs.get("ws"), 0.0) or 0.0
    temp = inputs.get("temp_c")
    rh = inputs.get("rh_pct")
    weather_source = str(inputs.get("weather_source") or "수동/미표기").strip()
    risk_summary = str(inputs.get("fire_risk_summary") or "미연동").strip()
    hist_summary = str(inputs.get("fire_history_summary") or "미연동").strip()

    direct_lines = "\n".join([f"- {r['time']}: {r['area']}" for r in rows]) or "- 행정구역 미확인: 좌표·행정구역 연동 확인 필요"
    unique_lines = "\n".join([f"- {a}" for a in direct_areas]) or "- 발화점 인근 지역(행정구역 미확인)"

    if direct_areas:
        indirect_lines = "\n".join([f"- {a} 주변 인접 읍면동: 연기·비화·교통통제 주의" for a in direct_areas[:6]])
    else:
        indirect_lines = "- 발화점 주변 풍하 방향 인접지역: 행정구역 확인 후 추가 안내"

    reason_lines = "\n".join([f"- {x}" for x in reasons]) or "- 입력 기상값 기준 특이 위험요인 확인 필요"

    temp_label = f"{_to_float(temp, 0):.1f}℃" if temp not in (None, "") else "미확인"
    rh_label = f"{_to_float(rh, 0):.0f}%" if rh not in (None, "") else "미확인"

    return f"""□ 1. 상황 개요
- 사건명: {fire_name}
- 발화점: 위도 {lat:.6f}, 경도 {lon:.6f}
- 기상: 풍향 {wd:.0f}°, 풍속 {ws:.1f}m/s, 기온 {temp_label}, 습도 {rh_label}
- 기상 출처: {weather_source}

□ 2. 시간대별 직접피해 예상지역
{direct_lines}

□ 3. 우선 확인 대상지역
{unique_lines}

□ 4. 간접피해·주의권 지역
{indirect_lines}

□ 5. 재난문자 발송 권고
- 직접피해(긴급재난문자): {msg['emergency']}
- 직접피해(위급재난문자): {msg['urgent']}
- 간접피해(안전안내문자): {msg['safety']}

□ 6. 단계별 현장 조치
- 0~30분: 발화점 인근 주민 주의 안내, 진입로 확보, 산림·소방 출동상황 확인
- 30~60분: 직접피해 예상지역 중심으로 마을방송·재난문자 발송 검토, 취약시설 우선 확인
- 1시간 이후: 풍하 방향 인접 읍면동까지 연기·비화 가능성 모니터링, 필요 시 대피안내 확대
- 공통: 실제 화선, 풍향 변화, CCTV·신고·현장 지휘부 정보를 우선 반영

□ 7. 경보시설·대피 안내
- 발화점 및 직접피해 예상지역 주변 경보시설 가청범위 확인
- 가청범위 밖 마을은 차량방송, 이장단 연락망, 재난문자 보완 필요
- 대피 안내 시 고령자·장애인·요양시설 등 이동취약계층을 우선 확인

□ 8. 위험 판단: {level}
{reason_lines}
- 종합의견: {conclusion}

□ 9. 참고 정보
- 산불위험예보: {risk_summary}
- 최근 산불발생이력: {hist_summary}

○ 불확실성/추가확인
- 본 결과는 예측 중심 경로 기준의 자동 산출자료입니다.
- 실제 확산 범위는 지형, 연료 상태, 순간풍속, 진화상황에 따라 달라질 수 있습니다.
- 재난문자 발송과 대피명령은 현장 지휘부 판단과 시군 상황판단회의 결과를 우선 적용해야 합니다.""".strip()


def generate_brief(inputs: dict) -> dict:
    text = _build_rule_based_brief(inputs)
    payload = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": "G-DAPS-rule-based-brief-v1-no-llm",
        "brief_text": text,
        "inputs": inputs,
    }
    _save_cache(payload)
    return payload


def get_cached_brief() -> dict:
    return _load_cache()
