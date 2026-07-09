"""Korea Forest Service '금일산불발생현황(todayFire)' OpenAPI client.

Fetch today's wildfire occurrence list, normalize field names, and filter
Gyeonggi-do fires for G-DAPS automatic analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
import os
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any

import requests
from app.config import env_str

DEFAULT_TODAY_FIRE_URL = env_str("TODAY_FIRE_API_URL", "http://fd.forest.go.kr/ffas/openAPI/todayFire.do")

# Kept only for backward compatibility with old env names. Do not use this as the main filter.
GYEONGGI_BBOX = {
    "min_lat": float(os.getenv("GYEONGGI_MIN_LAT", "36.80")),
    "max_lat": float(os.getenv("GYEONGGI_MAX_LAT", "38.35")),
    "min_lon": float(os.getenv("GYEONGGI_MIN_LON", "126.30")),
    "max_lon": float(os.getenv("GYEONGGI_MAX_LON", "128.05")),
}

GYEONGGI_SIGUNGU = [
    "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시", "안산시", "고양시",
    "과천시", "구리시", "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시", "용인시", "파주시",
    "이천시", "안성시", "김포시", "화성시", "광주시", "양주시", "포천시", "여주시",
    "연천군", "가평군", "양평군",
]

NON_GYEONGGI_PREFIXES = (
    "서울", "서울특별시", "인천", "인천광역시",
    "강원", "강원도", "강원특별자치도",
    "충북", "충청북도", "충남", "충청남도", "세종", "세종특별자치시", "대전", "대전광역시",
    "전북", "전라북도", "전북특별자치도", "전남", "전라남도",
    "경북", "경상북도", "경남", "경상남도",
    "부산", "부산광역시", "대구", "대구광역시", "울산", "울산광역시",
    "광주광역시", "제주", "제주특별자치도",
)

# Conservative fallback polygon for records with missing address.
GYEONGGI_APPROX_POLYGON = [
    (126.48, 37.04), (126.63, 36.90), (127.10, 36.83), (127.45, 36.92),
    (127.72, 37.05), (127.90, 37.23), (127.88, 37.50), (127.72, 37.78),
    (127.43, 38.08), (127.08, 38.31), (126.72, 38.24), (126.48, 38.05),
    (126.30, 37.76), (126.33, 37.48), (126.45, 37.25), (126.48, 37.04),
]

OCCUR_TYPE = {"01": "GPS신고", "05": "수동신고"}
PROGRESS_STATUS = {"02": "진화중", "03": "진화완료", "05": "산불외종료"}
STEP_STATUS = {"00": "초기대응", "01": "산불 1단계", "02": "산불 2단계", "03": "산불 3단계", "99": "산불단계해제"}


@dataclass
class TodayFire:
    fire_id: str
    lon: Optional[float]
    lat: Optional[float]
    address: str
    report_date: str
    report_time: str
    occur_type_code: str
    occur_type_name: str
    status_code: str
    status_name: str
    step_code: str
    step_name: str
    is_gyeonggi: bool
    raw: Dict[str, Any]

    @property
    def reported_at(self) -> str:
        if self.report_date and self.report_time:
            try:
                return datetime.strptime(self.report_date + self.report_time[:6].zfill(6), "%Y%m%d%H%M%S").isoformat()
            except Exception:
                pass
        return ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reported_at"] = self.reported_at
        return d


def _norm_addr(address: str) -> str:
    return re.sub(r"\s+", "", address or "")


def _point_in_poly(lon: float, lat: float, poly) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > lat) != (yj > lat)):
            x_intersect = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_intersect:
                inside = not inside
        j = i
    return inside


def is_gyeonggi_fire(lon: Optional[float], lat: Optional[float], address: str) -> bool:
    """Return True only for Gyeonggi-do fires.

    The previous bbox filter included Seoul/Incheon/Gangwon/Chungcheong edge cases.
    Address province is trusted first. Coordinate fallback is used only when address is missing.
    """
    addr = _norm_addr(address)
    if addr.startswith("경기도") or addr.startswith("경기"):
        return True
    if any(addr.startswith(p) for p in NON_GYEONGGI_PREFIXES):
        return False
    if addr and any(sg in addr for sg in GYEONGGI_SIGUNGU):
        return True
    if not addr and lon is not None and lat is not None:
        return _point_in_poly(float(lon), float(lat), GYEONGGI_APPROX_POLYGON)
    return False


def _text(node: ET.Element, tag: str) -> str:
    for child in node.iter():
        if child.tag.split("}")[-1] == tag:
            return (child.text or "").strip()
    return ""


def _text_any(node: ET.Element, *tags: str) -> str:
    for tag in tags:
        v = _text(node, tag)
        if v != "":
            return v
    return ""


def _to_float(value: str) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except Exception:
        return None


def _looks_like_record(node: ET.Element) -> bool:
    tags = {c.tag.split("}")[-1] for c in node.iter()}
    return "frfrInfoId" in tags or "frfrSttmnLctnXcrd" in tags or "frfrSttmnAddr" in tags


def _find_record_nodes(root: ET.Element) -> List[ET.Element]:
    records = []
    for node in root.iter():
        if node is root:
            continue
        if _looks_like_record(node) and (_text(node, "frfrInfoId") or _text(node, "frfrSttmnAddr")):
            records.append(node)
    unique = []
    seen = set()
    for n in records:
        key = (
            _text(n, "frfrInfoId"),
            _text(n, "frfrSttmnLctnXcrd"),
            _text_any(n, "frfrSttmnlctnYcrd", "frfrSttmnLctnYcrd"),
            _text(n, "frfrSttmnDt"),
            _text(n, "frfrSttmnHms"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return unique


def parse_today_fire_xml(xml_text: str) -> List[TodayFire]:
    text = (xml_text or "").strip()
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        cleaned = re.sub(r"<\?xml[^>]*\?>", "", text).strip()
        root = ET.fromstring(f"<root>{cleaned}</root>")

    out: List[TodayFire] = []
    for node in _find_record_nodes(root):
        raw = {child.tag.split("}")[-1]: (child.text or "").strip() for child in node.iter() if child is not node}
        fire_id = _text(node, "frfrInfoId")
        lon = _to_float(_text(node, "frfrSttmnLctnXcrd"))
        lat = _to_float(_text_any(node, "frfrSttmnlctnYcrd", "frfrSttmnLctnYcrd"))
        address = _text(node, "frfrSttmnAddr")
        occur_code = _text(node, "frfrOccrrTpcd")
        occur_name = _text(node, "frfrOccrrTpcdNm") or _text(node, "frfrOrfrOccrrTpcdNm") or OCCUR_TYPE.get(occur_code, "")
        status_code = _text(node, "frfrPrgrsStcd")
        status_name = _text(node, "frfrPrgrsStcdNm") or PROGRESS_STATUS.get(status_code, "")
        step_code = _text(node, "frfrStepIssuCd")
        step_name = STEP_STATUS.get(step_code, step_code)

        if not fire_id:
            fire_id = "AUTO-" + "-".join([
                _text(node, "frfrSttmnDt") or "00000000",
                _text(node, "frfrSttmnHms") or "000000",
                f"{lat or 0:.6f}",
                f"{lon or 0:.6f}",
            ])

        out.append(TodayFire(
            fire_id=fire_id,
            lon=lon,
            lat=lat,
            address=address,
            report_date=_text(node, "frfrSttmnDt"),
            report_time=_text(node, "frfrSttmnHms"),
            occur_type_code=occur_code,
            occur_type_name=occur_name,
            status_code=status_code,
            status_name=status_name,
            step_code=step_code,
            step_name=step_name,
            is_gyeonggi=is_gyeonggi_fire(lon, lat, address),
            raw=raw,
        ))
    return out


def fetch_today_fires(timeout: int = 15) -> List[TodayFire]:
    url = os.getenv("TODAY_FIRE_API_URL", DEFAULT_TODAY_FIRE_URL).strip() or DEFAULT_TODAY_FIRE_URL
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return parse_today_fire_xml(r.text)


def fetch_today_fires_dict(gyeonggi_only: bool = False, active_only: bool = False) -> List[Dict[str, Any]]:
    fires = fetch_today_fires()
    if gyeonggi_only:
        fires = [f for f in fires if f.is_gyeonggi]
    if active_only:
        fires = [f for f in fires if f.status_code == "02" or "진화중" in f.status_name]
    return [f.to_dict() for f in fires]
