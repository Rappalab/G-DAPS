import streamlit as st
import os
import csv
import math
import urllib.parse
import datetime
import time
import requests
from app.config import env_str
import folium
from folium.plugins import MarkerCluster  # [P1] 마커 클러스터링
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from app.engine import compute_layers, dest_point
from app.geocode import vworld_reverse_geocode, search_place


# ──────────────────────────────────────────────
# 유틸 함수
# ──────────────────────────────────────────────

def api_url_with_token(base_url: str, token: str = "") -> str:
    token = (token or "").strip()
    if not token:
        return base_url
    joiner = "&" if "?" in base_url else "?"
    return base_url + joiner + "token=" + urllib.parse.quote(token)


def fetch_json(url: str, timeout: int = 20):
    try:
        r = requests.get(url, timeout=timeout)
    except Exception as e:
        return None, f"요청 실패: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    try:
        return r.json(), None
    except Exception:
        return None, f"JSON 파싱 실패: {r.text[:300]}"


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def format_distance_m(meters):
    try:
        meters = float(meters)
    except Exception:
        return "—"
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{meters:.0f} m"


def wind_dir_kor(deg: float) -> str:
    dirs = [
        "북풍", "북북동풍", "북동풍", "동북동풍",
        "동풍", "동남동풍", "남동풍", "남남동풍",
        "남풍", "남남서풍", "남서풍", "서남서풍",
        "서풍", "서북서풍", "북서풍", "북북서풍",
    ]
    idx = int((deg % 360) / 22.5 + 0.5) % 16
    return dirs[idx]



def set_ignition_point(lat: float, lon: float, label: str = ""):
    st.session_state.lat = float(lat)
    st.session_state.lon = float(lon)
    st.session_state.selected_warning_site_id = ""
    st.session_state.animation_frame = 1
    st.session_state.animate_fire = False
    st.session_state.demo_selected_label = label or "시연 발화점"


def lookup_demo_place(query: str):
    try:
        return search_place(query)
    except Exception:
        return None


def render_fire_risk_scale(std_value):
    try:
        v = int(float(std_value))
    except Exception:
        v = None

    levels = [
        (6, "6등급", "매우낮은<br/>위험", "#BFD8EA"),
        (5, "5등급", "낮은<br/>위험", "#C8EEE8"),
        (4, "4등급", "보통<br/>위험", "#BEEAD0"),
        (3, "3등급", "다소높은<br/>위험", "#F0F2B2"),
        (2, "2등급", "높은<br/>위험", "#F7C66A"),
        (1, "1등급", "매우높은<br/>위험", "#F8A3A6"),
    ]

    blocks = []
    for code, title, subtitle, color in levels:
        active = (v == code)
        border = "3px solid #111" if active else "1px solid rgba(0,0,0,0.2)"
        shadow = "0 2px 10px rgba(0,0,0,0.18)" if active else "none"
        blocks.append(
            f'<div style="flex:1; background:{color}; border:{border}; border-radius:16px; padding:14px 10px;'
            f'text-align:center; box-shadow:{shadow};">'
            f'<div style="font-size:22px; font-weight:800; color:#fff; letter-spacing:0.5px;">{title}</div>'
            f'<div style="margin-top:10px; font-size:16px; font-weight:800; color:rgba(0,0,0,0.55); line-height:1.1;">{subtitle}</div>'
            f'</div>'
        )

    html = (
        '<div style="display:flex; gap:10px; width:100%; align-items:stretch; margin:6px 0 2px 0;">'
        + "".join(blocks)
        + '</div>'
        + f'<div style="font-size:12px; color:rgba(0,0,0,0.55); margin-top:4px;">○ 현재 등급: <b>{v if v is not None else "—"}</b> (1이 가장 높고, 6이 가장 낮음)</div>'
    )
    components.html(html, height=150, scrolling=False)


def locate_sites_file():
    candidates = [
        env_str("GDAPS_SITES_CSV", os.path.join(os.path.dirname(os.path.dirname(__file__)), "gdaps_web_sites.csv")),
        os.path.join(os.path.dirname(__file__), "gdaps_web_sites.csv"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "gdaps_web_sites.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


@st.cache_data(show_spinner=False, ttl=3600)
def load_warning_sites_cached(path: str):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                lat = float(r.get("위도") or "")
                lon = float(r.get("경도") or "")
            except Exception:
                continue
            try:
                radius_m = float(r.get("반경_m") or 0)
            except Exception:
                radius_m = 0.0
            rows.append({
                "site_id": str(r.get("site_id", "")),
                "region": r.get("권역", ""),
                "city": r.get("시군", ""),
                "admin_detail": r.get("행정구역_상세", ""),
                "name": r.get("시설명", ""),
                "lat": lat,
                "lon": lon,
                "addr": r.get("주소", ""),
                "grade": r.get("출력등급_표준", ""),
                "class": r.get("출력분류", ""),
                "power_w": r.get("출력_W", ""),
                "radius_m": radius_m,
            })
    return rows


def load_warning_sites():
    path = locate_sites_file()
    if not path:
        return [], "gdaps_web_sites.csv 파일을 찾지 못했습니다."
    try:
        return load_warning_sites_cached(path), None
    except Exception as e:
        return [], f"경보시설 CSV 로드 실패: {e}"


# ──────────────────────────────────────────────
# [P2] 거리 계산 캐싱
# ──────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=300)
def enrich_nearest_sites_cached(fire_lat: float, fire_lon: float, sites_json: str):
    import json
    sites = json.loads(sites_json)
    enriched = []
    for site in sites:
        d = haversine_m(fire_lat, fire_lon, site["lat"], site["lon"])
        gap = d - float(site.get("radius_m") or 0)
        item = dict(site)
        item["distance_m"] = d
        item["coverage_gap_m"] = gap
        item["covered"] = gap <= 0
        enriched.append(item)
    enriched.sort(key=lambda x: x["distance_m"])
    return enriched


def enrich_nearest_sites(fire_lat, fire_lon, sites):
    import json
    sites_json = json.dumps(sites, ensure_ascii=False)
    return enrich_nearest_sites_cached(fire_lat, fire_lon, sites_json)


def find_site_by_id(sites, site_id):
    if not site_id:
        return None
    for s in sites:
        if str(s.get("site_id", "")) == str(site_id):
            return s
    return None


def nearest_site_to_click(click_lat, click_lon, sites, tolerance_m=220):
    best = None
    best_d = None
    for s in sites:
        d = haversine_m(click_lat, click_lon, s["lat"], s["lon"])
        if best_d is None or d < best_d:
            best = s
            best_d = d
    if best is not None and best_d is not None and best_d <= tolerance_m:
        return best
    return None


def render_selected_facility_box(display_site, selected=False):
    if not display_site:
        st.info("○ 경보시설 데이터를 아직 불러오지 못했습니다.")
        return

    status = "⚠️ 피해범위 내" if display_site["covered"] else "✅ 피해범위 밖"
    status_color = "#c0392b" if display_site["covered"] else "#1f7a1f"
    gap_text = (
        "피해범위 내부"
        if display_site["covered"]
        else f"피해범위까지 추가 {format_distance_m(display_site['coverage_gap_m'])}"
    )
    title = "📢 경보시설" if selected else "📍 화재 원점 기준 최근접 경보시설"
    border_color = "#2b8cbe" if selected else "rgba(0,0,0,0.12)"

    html = (
        f'<div style="padding:14px 16px; border:2px solid {border_color}; border-radius:16px; background:#fafafa; margin-top:4px;">'
        f'<div style="font-size:13px; font-weight:700; margin-bottom:6px; color:#555;">{title}</div>'
        f'<div style="font-size:18px; font-weight:800; margin-bottom:6px;">{display_site["name"] or "(시설명 없음)"}</div>'
        '<div style="font-size:13px; line-height:1.9;">'
        f'- 시군: {display_site["city"] or "—"}<br/>'
        f'- 직선거리: <b>{format_distance_m(display_site["distance_m"])}</b><br/>'
        f'- 가청반경: {format_distance_m(display_site["radius_m"])}<br/>'
        f'- 판정: <span style="color:{status_color}; font-weight:800;">{status}</span> ({gap_text})'
        '</div></div>'
    )
    components.html(html, height=185, scrolling=False)




def send_telegram_message(text: str):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return False, "텔레그램 환경변수(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)가 설정되지 않았습니다."

    url = f"{env_str('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return False, f"텔레그램 API 오류: {data}"
        return True, None
    except Exception as e:
        return False, f"텔레그램 전송 실패: {e}"


def build_telegram_alert(lat: float, lon: float, wd: float, ws: float, temp_c, rh_pct):
    try:
        geo = vworld_reverse_geocode(lat, lon) or {}
    except Exception:
        geo = {}

    sido = (geo.get("sido") or "").strip()
    sigungu = (geo.get("sigungu") or "").strip()
    eupmyeondong = (geo.get("eupmyeondong") or "").strip()
    location_text = " ".join([x for x in [sido, sigungu, eupmyeondong] if x]).strip()

    if not location_text:
        full = (geo.get("full") or "").strip()
        location_text = full if full else f"{lat:.6f}, {lon:.6f}"

    temp_text = f"{float(temp_c):.1f}℃" if temp_c is not None else "확인불가"
    rh_text = f"{float(rh_pct):.0f}%" if rh_pct is not None else "확인불가"

    return (
        "🚨 G-DAPS 산불 분석 알림\n\n"
        f"1. 원점(산불발화지점) : {location_text}\n"
        f"2. 기상현황 : {wind_dir_kor(wd)} ({wd:.0f}°), 풍속 {ws:.1f}m/s, 기온 {temp_text}, 습도 {rh_text}\n"
        f"3. 사이트 주소 : {env_str('PUBLIC_APP_URL', 'http://localhost:8504')}"
    )


# ──────────────────────────────────────────────
# 앱 시작
# ──────────────────────────────────────────────
st.set_page_config(page_title="G-DAPS", layout="wide")


def auth_gate():
    pw = os.getenv("UI_PASSWORD", "").strip()
    if not pw:
        return
    if st.session_state.get("authed") is True:
        return

    st.title("G-DAPS")
    st.caption("접속 비밀번호를 입력하세요.")
    typed = st.text_input("Password", type="password")
    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("로그인", use_container_width=True):
            if typed == pw:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다.")
    with col_b:
        if st.button("초기화", use_container_width=True):
            st.session_state["authed"] = False
            st.rerun()
    st.stop()


auth_gate()

st.title("G-DAPS v8")
st.caption("현재 기상 + 산불위험예보/산불발생이력(경기도) + 경보 가청범위 시각화 | ⚡ 지도 최적화 적용")

# 실시간 산불 API 자동분석 현황
try:
    latest_auto = st.session_state.get("auto_analysis_items") or []
    if latest_auto:
        latest = latest_auto[0]
        st.success(
            f"실시간 산불 자동분석 최근 결과: {latest.get('address') or '좌표 기반'} / "
            f"{latest.get('status_name') or ''} {latest.get('step_name') or ''} / "
            f"분석시각 {latest.get('analyzed_at') or '—'}"
        )
except Exception:
    pass

# ──────────────────────────────────────────────
# session_state 기본값
# ──────────────────────────────────────────────
st.session_state.setdefault("lat", 37.747575)
st.session_state.setdefault("lon", 127.071862)
st.session_state.setdefault("wd", 90.0)
st.session_state.setdefault("ws", 5.0)
st.session_state.setdefault("temp_c", None)
st.session_state.setdefault("rh_pct", None)
st.session_state.setdefault("steps", 6)
st.session_state.setdefault("drift", 0.35)
st.session_state.setdefault("brief_text", "")
st.session_state.setdefault("brief_updated_at", "")
st.session_state.setdefault("weather_source", "")
st.session_state.setdefault("warning_radius_km", 10)
st.session_state.setdefault("show_warning_circles", True)
st.session_state.setdefault("selected_warning_site_id", "")
st.session_state.setdefault("max_sites_to_draw", 30)
st.session_state.setdefault("use_cluster", False)
st.session_state.setdefault("map_tile", "OpenStreetMap")
st.session_state.setdefault("animate_fire", False)
st.session_state.setdefault("animation_frame", 1)
st.session_state.setdefault("animation_interval_ms", 900)
st.session_state.setdefault("auto_fire_items", [])
st.session_state.setdefault("auto_analysis_items", [])
st.session_state.setdefault("auto_last_scan", "")
st.session_state.setdefault("demo_click_mode", False)
st.session_state.setdefault("demo_click_points", [])
st.session_state.setdefault("last_map_click_sig", "")
st.session_state.setdefault("demo_selected_label", "")

warning_sites, warning_sites_err = load_warning_sites()

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.subheader("□ 발화점(수동 입력)")
    st.session_state.lat = st.number_input("위도(lat)", value=float(st.session_state.lat), format="%.6f")
    st.session_state.lon = st.number_input("경도(lon)", value=float(st.session_state.lon), format="%.6f")

    st.divider()
    st.subheader("□ 시연용 발화점 선택")
    demo_place = st.text_input("지명/시설명", value="", placeholder="예: 포천시청, 경기도청 북부청사, 장암동")
    col_demo1, col_demo2 = st.columns(2)
    with col_demo1:
        if st.button("지명으로 설정", use_container_width=True):
            found = lookup_demo_place(demo_place)
            if found:
                set_ignition_point(found["lat"], found["lon"], found.get("label", demo_place))
                st.success(f"발화점 설정: {found.get('label', demo_place)}")
                st.rerun()
            else:
                st.warning("검색 결과가 없습니다. 주요 시군청/경보시설명 또는 좌표를 입력해 주세요.")
    with col_demo2:
        if st.button("3회 클릭 초기화", use_container_width=True):
            st.session_state.demo_click_points = []
            st.session_state.last_map_click_sig = ""
            st.rerun()
    st.session_state.demo_click_mode = st.checkbox(
        "지도 3회 클릭으로 발화점 확정",
        value=bool(st.session_state.demo_click_mode),
        help="지도에서 3개 지점을 찍으면 그 중심점을 시연용 발화점으로 설정합니다."
    )
    if st.session_state.demo_click_mode:
        st.caption(f"○ 현재 클릭 {len(st.session_state.demo_click_points)}/3회")
    if st.session_state.demo_selected_label:
        st.caption(f"○ 현재 시연 발화점: {st.session_state.demo_selected_label}")

    st.divider()
    st.subheader("□ 사건 정보")
    fire_name = st.text_input("사건명", value="가정 산불(테스트)")
    start_dt = st.date_input("발생일", value=datetime.date.today())
    start_tm = st.time_input("발생시각", value=datetime.datetime.now().time().replace(second=0, microsecond=0))

    st.divider()
    st.subheader("□ 접속 설정")
    host = st.text_input("도메인/IP", value=env_str("API_HOST_DEFAULT", "localhost"))
    api_port = st.text_input("API 포트", value=env_str("API_PORT_PUBLIC", "5000"))
    token = st.text_input("token(옵션)", value="")

    st.divider()
    st.subheader("□ 풍향(기상청 기준)")
    st.caption("○ 풍향(wd)은 불어오는 방향(FROM) 기준으로 고정했습니다.")
    wd_mode = "FROM"

    st.divider()
    st.subheader("□ 현재 기상")
    if st.button("현재 기상 불러오기", use_container_width=True):
        url = f"http://{host}:{api_port}/weather?lat={st.session_state.lat}&lon={st.session_state.lon}"
        if token.strip():
            url += "&token=" + urllib.parse.quote(token.strip())
        data, err = fetch_json(url, timeout=10)
        if err:
            st.error(err)
        elif data:
            if "error" in data:
                st.error(data["error"])
            else:
                st.session_state.wd = float(data["wd"])
                st.session_state.ws = float(data["ws"])
                st.session_state.temp_c = data.get("temp_c")
                st.session_state.rh_pct = data.get("rh_pct")
                st.session_state.weather_source = data.get("source", "")
                st.success("현재 기상 반영 완료")

    st.divider()
    st.subheader("□ 기상(수동)")
    st.session_state.wd = st.number_input("풍향 wd (deg)", value=float(st.session_state.wd))
    st.session_state.ws = st.number_input("풍속 ws (m/s)", value=float(st.session_state.ws), min_value=0.0)
    st.session_state.temp_c = st.number_input(
        "기온(℃) (옵션)",
        value=float(st.session_state.temp_c) if st.session_state.temp_c is not None else 0.0
    )
    st.session_state.rh_pct = st.number_input(
        "습도(%) (옵션)",
        value=float(st.session_state.rh_pct) if st.session_state.rh_pct is not None else 0.0
    )

    st.divider()
    st.subheader("□ 예측")
    st.caption("○ 레이어 간격 = 최종시간(h) / steps. 예: 3h & steps=4 → 45분 간격")
    h = st.selectbox("최종 예측시간(h)", [1, 2, 3], index=2)
    st.session_state.steps = st.slider(
        "레이어 수(steps) ⚠️ 많을수록 느림",
        1, 8, int(st.session_state.steps)
    )
    st.session_state.drift = st.slider("중심 이동 계수(drift_coef)", 0.0, 1.0, float(st.session_state.drift), 0.05)

    st.divider()
    st.subheader("□ 경보시설 가청범위")
    st.session_state.show_warning_circles = st.checkbox(
        "가청반경 원 표시 (기본 ON)",
        value=bool(st.session_state.show_warning_circles),
        help="최근접(또는 선택) 시설의 가청반경 원을 지도에 표시합니다. 끄면 빠릅니다."
    )
    st.session_state.warning_radius_km = st.slider(
        "발화점 주변 표시범위(km)", 5, 50, int(st.session_state.warning_radius_km), 5
    )
    st.session_state.max_sites_to_draw = st.slider(
        "지도 최대 표시 시설 수", 10, 120, int(st.session_state.max_sites_to_draw), 10
    )

    st.divider()
    st.subheader("□ 재생 설정")
    st.session_state.animation_interval_ms = st.slider(
        "재생 속도(ms)", 300, 2000, int(st.session_state.animation_interval_ms), 100,
        help="분석 실행 후 자동 반복재생 속도입니다."
    )
    col_anim1, col_anim2 = st.columns(2)
    with col_anim1:
        if st.button("⏸ 재생 정지", use_container_width=True):
            st.session_state.animate_fire = False
    with col_anim2:
        if st.button("▶ 다시 재생", use_container_width=True):
            st.session_state.animate_fire = True

    st.divider()
    st.subheader("□ 지도 성능 설정")
    st.session_state.use_cluster = st.checkbox(
        "마커 클러스터링 사용 (권장)",
        value=bool(st.session_state.use_cluster),
        help="경보시설 마커를 zoom에 따라 자동으로 묶어줍니다."
    )
    tile_options = ["CartoDB positron", "OpenStreetMap", "CartoDB dark_matter"]
    st.session_state.map_tile = st.selectbox(
        "지도 타일",
        tile_options,
        index=tile_options.index(st.session_state.map_tile) if st.session_state.map_tile in tile_options else 0,
        help="CartoDB positron이 가장 가볍고 빠릅니다."
    )

    if warning_sites_err:
        st.warning(warning_sites_err)
    else:
        st.caption(f"○ 경보시설 {len(warning_sites)}개 중 발화점 주변 시설만 표시합니다.")

    st.divider()
    st.subheader("□ 실시간 산불 API")
    st.caption("○ 산림청 금일산불발생현황 API에서 경기도 산불을 감지합니다.")
    if st.button("금일 산불 조회", use_container_width=True):
        url = api_url_with_token(f"http://{host}:{api_port}/today_fire?gyeonggi_only=1", token)
        data, err = fetch_json(url, timeout=20)
        if err:
            st.error(err)
        elif data and data.get("error"):
            st.error(data["error"])
        else:
            st.session_state.auto_fire_items = data.get("items", []) if data else []
            st.session_state.auto_last_scan = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 조회만 해도 가장 최근 산불 좌표를 즉시 지도 중심/발화점으로 반영
            latest_fire = next((f for f in st.session_state.auto_fire_items if f.get("lat") is not None and f.get("lon") is not None), None)
            if latest_fire:
                st.session_state.lat = float(latest_fire["lat"])
                st.session_state.lon = float(latest_fire["lon"])
                st.session_state.animation_frame = 1
                st.session_state.animate_fire = False
            st.success(f"경기도 산불 {len(st.session_state.auto_fire_items)}건 조회")
            if latest_fire:
                st.info(f"최근 산불 위치를 지도에 반영했습니다: {latest_fire.get('address') or latest_fire.get('fire_id')}")
                st.rerun()

    if st.button("신규 산불 확인/최초 1회 분석", use_container_width=True):
        # 서버에서 경기도 신규 fire_id 최초 감지 시 1회만 분석하고, 기존 산불은 상태/단계만 갱신합니다.
        url = api_url_with_token(f"http://{host}:{api_port}/auto_scan?telegram=1&analyze_completed=1", token)
        data, err = fetch_json(url, timeout=90)
        if err:
            st.error(err)
        elif data and data.get("error"):
            st.error(data["error"])
        else:
            st.session_state.auto_fire_items = data.get("fires", data.get("processed", [])) if data else []
            st.session_state.auto_analysis_items = data.get("latest", []) if data else []
            st.session_state.auto_last_scan = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            analyzed = len(data.get("analyzed", [])) if data else 0
            st.success(f"자동조회 완료 / 신규 최초분석 {analyzed}건")
            latest = (data.get("latest") or [None])[0] if data else None
            if latest and latest.get("lat") and latest.get("lon"):
                st.session_state.lat = float(latest["lat"])
                st.session_state.lon = float(latest["lon"])
                w = latest.get("weather") or {}
                if w.get("wd") is not None:
                    st.session_state.wd = float(w.get("wd"))
                if w.get("ws") is not None:
                    st.session_state.ws = float(w.get("ws"))
                st.session_state.temp_c = w.get("temp_c", st.session_state.temp_c)
                st.session_state.rh_pct = w.get("rh_pct", st.session_state.rh_pct)
                st.session_state.animate_fire = True
                st.rerun()

    st.divider()
    st.subheader("□ 분석 실행(원버튼)")

# ──────────────────────────────────────────────
# 분석 실행
# ──────────────────────────────────────────────
st.caption("○ 발화점(지도 클릭/좌표 입력) 설정 후, 아래 버튼 1회로 현재기상 → 산불위험예보 → 브리핑을 순서대로 갱신합니다.")

if st.button("분석 실행", use_container_width=True):
    st.session_state.animation_frame = 1
    st.session_state.animate_fire = False
    with st.spinner("현재 기상 불러오는 중..."):
        url = f"http://{host}:{api_port}/weather?lat={st.session_state.lat}&lon={st.session_state.lon}"
        if token.strip():
            url += "&token=" + urllib.parse.quote(token.strip())
        data, err = fetch_json(url, timeout=15)
        if err:
            st.error("현재 기상 실패: " + err)
        else:
            st.session_state.wd = float(data["wd"])
            st.session_state.ws = float(data["ws"])
            st.session_state.temp_c = data.get("temp_c")
            st.session_state.rh_pct = data.get("rh_pct")
            st.session_state.weather_source = data.get("source", "")

    with st.spinner("산불위험예보(경기도) 불러오는 중..."):
        url = f"http://{host}:{api_port}/fire_risk"
        if token.strip():
            url += "?token=" + urllib.parse.quote(token.strip())
        data, err = fetch_json(url, timeout=20)
        st.session_state["fire_risk"] = {"error": err} if err else data

    with st.spinner("브리핑 생성 중..."):
        q = {
            "fire_name": fire_name,
            "lat": st.session_state.lat,
            "lon": st.session_state.lon,
            "wd": st.session_state.wd,
            "ws": st.session_state.ws,
            "temp_c": st.session_state.temp_c,
            "rh_pct": st.session_state.rh_pct,
            "h": h,
            "steps": st.session_state.steps,
            "wd_mode": wd_mode,
            "drift": st.session_state.drift,
            "weather_source": st.session_state.weather_source,
        }
        url = f"http://{host}:{api_port}/brief?" + urllib.parse.urlencode(q, safe=":+")
        if token.strip():
            url += "&token=" + urllib.parse.quote(token.strip())
        data, err = fetch_json(url, timeout=60)
        if err:
            st.error("브리핑 실패: " + err)
            st.session_state.brief_text = ""
            st.session_state.brief_updated_at = ""
        else:
            if isinstance(data, dict) and data.get("error"):
                st.error("브리핑 실패: " + data["error"])
                st.session_state.brief_text = ""
                st.session_state.brief_updated_at = ""
            else:
                st.session_state.brief_text = data.get("brief_text", "")
                st.session_state.brief_updated_at = data.get("updated_at", "")
                st.session_state.animation_frame = 1
                st.session_state.animate_fire = True
                st.success(f"분석 완료: {st.session_state.brief_updated_at} · 확산 재생 시작")

                telegram_text = build_telegram_alert(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.wd,
                    st.session_state.ws,
                    st.session_state.temp_c,
                    st.session_state.rh_pct,
                )
                tg_ok, tg_err = send_telegram_message(telegram_text)
                if tg_ok:
                    st.info("텔레그램 알림 전송 완료")
                else:
                    st.warning(tg_err)

# ──────────────────────────────────────────────
# 레이어 계산 + 거리 계산
# ──────────────────────────────────────────────
layers = compute_layers(
    st.session_state.lat,
    st.session_state.lon,
    st.session_state.wd,
    st.session_state.ws,
    h,
    st.session_state.steps,
    drift_coef=st.session_state.drift,
    wd_mode=wd_mode,
)
wd_to = layers[0]["wd_to"] if layers else st.session_state.wd

total_frames = len(layers)
if total_frames <= 0:
    st.session_state.animation_frame = 1
    st.session_state.animate_fire = False
else:
    try:
        st.session_state.animation_frame = int(st.session_state.animation_frame)
    except Exception:
        st.session_state.animation_frame = 1
    st.session_state.animation_frame = max(1, min(st.session_state.animation_frame, total_frames))

current_frame = min(st.session_state.animation_frame, total_frames) if total_frames > 0 else 1
visible_fire_layers = layers[:current_frame] if layers else []
current_layer = visible_fire_layers[-1] if visible_fire_layers else None

nearest_sites = enrich_nearest_sites(st.session_state.lat, st.session_state.lon, warning_sites) if warning_sites else []

visible_warning_sites = [
    s for s in nearest_sites
    if s["distance_m"] <= float(st.session_state.warning_radius_km) * 1000.0
][: int(st.session_state.max_sites_to_draw)]

selected_site = find_site_by_id(nearest_sites, st.session_state.selected_warning_site_id)
display_site = selected_site if selected_site else (nearest_sites[0] if nearest_sites else None)

# ──────────────────────────────────────────────
# 메인 레이아웃
# ──────────────────────────────────────────────
top_left, top_right = st.columns([1.45, 1])

with top_left:
    st.markdown("## □ 웹 지도")
    st.caption("○ 산불 예측과 경보시설을 함께 표시합니다. 기본은 지도 클릭으로 발화점 이동, 시연모드는 3회 클릭 중심점으로 발화점을 확정합니다.")
    if total_frames > 0:
        current_minutes = int(round(visible_fire_layers[-1]["hour"] * 60)) if visible_fire_layers else 0
        status_text = "자동 반복재생 중" if st.session_state.animate_fire else "재생 정지"
        st.caption(f"🎬 확산 재생: {current_frame}/{total_frames} 프레임 · 현재 {current_minutes}분 후 · {status_text}")

    map_center = [st.session_state.lat, st.session_state.lon]

    m = folium.Map(
        location=map_center,
        zoom_start=11,
        control_scale=True,
        prefer_canvas=True,
        tiles=st.session_state.map_tile,
        max_zoom=17,
    )

    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        tooltip="발화점",
        icon=folium.Icon(color="blue", icon="info-sign"),
    ).add_to(m)

    arrow_km = max(1.0, min(8.0, st.session_state.ws * 0.6))
    try:
        lat2, lon2 = dest_point(st.session_state.lat, st.session_state.lon, wd_to, arrow_km)
        folium.PolyLine(
            [(st.session_state.lat, st.session_state.lon), (lat2, lon2)],
            tooltip="풍향(확산 방향 참고)",
            weight=4,
            opacity=0.9,
        ).add_to(m)
    except Exception:
        pass

    fire_group = folium.FeatureGroup(name="🔥 확산 예측", show=True)
    for idx, layer in enumerate(visible_fire_layers, start=1):
        poly = layer["poly"]
        coords = [(y, x) for (x, y) in list(poly.exterior.coords)]
        is_current = (idx == len(visible_fire_layers))
        opacity = 0.30 if is_current else max(0.05, 0.16 - 0.01 * (len(visible_fire_layers) - idx))
        weight = 3 if is_current else 1.5
        folium.Polygon(
            locations=coords,
            fill=True,
            fill_opacity=opacity,
            weight=weight,
            smooth_factor=1.5,
            tooltip=f"{int(round(layer['hour'] * 60))}분 후",
        ).add_to(fire_group)
    fire_group.add_to(m)

    warning_group = folium.FeatureGroup(name="📢 경보시설", show=True)

    if st.session_state.use_cluster:
        cluster = MarkerCluster(
            options={
                "maxClusterRadius": 40,
                "disableClusteringAtZoom": 14,
            }
        )
        for site in visible_warning_sites:
            covered_color = "#2b8cbe" if site["covered"] else "#6a51a3"
            is_selected = str(site.get("site_id", "")) == str(st.session_state.selected_warning_site_id)
            folium.CircleMarker(
                location=[site["lat"], site["lon"]],
                radius=7 if is_selected else 5,
                color=covered_color,
                fill=True,
                fill_opacity=0.95,
                weight=2 if is_selected else 1,
                tooltip=f"{site['name']} / {format_distance_m(site['distance_m'])}",
            ).add_to(cluster)
        cluster.add_to(warning_group)
    else:
        for site in visible_warning_sites:
            covered_color = "#2b8cbe" if site["covered"] else "#6a51a3"
            is_selected = str(site.get("site_id", "")) == str(st.session_state.selected_warning_site_id)
            folium.CircleMarker(
                location=[site["lat"], site["lon"]],
                radius=7 if is_selected else 5,
                color=covered_color,
                fill=True,
                fill_opacity=0.95,
                weight=2 if is_selected else 1,
                tooltip=f"{site['name']} / {format_distance_m(site['distance_m'])}",
            ).add_to(warning_group)

    warning_group.add_to(m)

    if st.session_state.show_warning_circles:
        for site in visible_warning_sites:
            is_display = display_site and str(site.get("site_id", "")) == str(display_site.get("site_id", ""))
            covered_color = "#2b8cbe" if site["covered"] else "#6a51a3"
            folium.Circle(
                location=[site["lat"], site["lon"]],
                radius=float(site["radius_m"]),
                color=covered_color,
                fill=True,
                fill_opacity=0.15 if is_display else 0.06,
                weight=2.5 if is_display else 1,
                tooltip=f"{site['name']} 가청반경 {format_distance_m(site['radius_m'])}",
            ).add_to(m)

    # 시연용 3회 클릭 후보점 표시
    for idx, pt in enumerate(st.session_state.demo_click_points, start=1):
        folium.CircleMarker(
            location=[pt[0], pt[1]],
            radius=6,
            color="#ff5c2b",
            fill=True,
            fill_opacity=0.9,
            tooltip=f"시연 클릭 {idx}/3",
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    out = st_folium(
        m,
        height=560,
        width=None,
        returned_objects=["last_clicked"],
        key="gdaps_map",
    )

    if out and out.get("last_clicked"):
        click_lat = float(out["last_clicked"]["lat"])
        click_lon = float(out["last_clicked"]["lng"])
        click_sig = f"{click_lat:.6f},{click_lon:.6f}"

        if st.session_state.demo_click_mode:
            if click_sig != st.session_state.last_map_click_sig:
                st.session_state.last_map_click_sig = click_sig
                pts = list(st.session_state.demo_click_points) + [(click_lat, click_lon)]
                if len(pts) >= 3:
                    center_lat = sum(p[0] for p in pts[:3]) / 3.0
                    center_lon = sum(p[1] for p in pts[:3]) / 3.0
                    set_ignition_point(center_lat, center_lon, "지도 3회 클릭 중심점")
                    st.session_state.demo_click_points = []
                    st.session_state.demo_click_mode = False
                else:
                    st.session_state.demo_click_points = pts
                st.rerun()
        else:
            clicked_site = nearest_site_to_click(click_lat, click_lon, visible_warning_sites, tolerance_m=220)
            if clicked_site:
                if st.session_state.selected_warning_site_id != clicked_site["site_id"]:
                    st.session_state.selected_warning_site_id = clicked_site["site_id"]
                    st.rerun()
            else:
                moved = (
                    abs(st.session_state.lat - click_lat) > 1e-9
                    or abs(st.session_state.lon - click_lon) > 1e-9
                )
                if moved:
                    set_ignition_point(click_lat, click_lon, "지도 클릭 지점")
                    st.rerun()

with top_right:
    st.markdown("## □ 현재 기상")

    ws_label = f"{st.session_state.ws:.1f} m/s"
    temp_val = st.session_state.temp_c
    rh_val = st.session_state.rh_pct
    temp_label = f"{temp_val}℃" if temp_val is not None else "—"
    rh_label = f"{rh_val}%" if rh_val is not None else "—"

    weather_html = f"""
<div style="display:flex; gap:8px; margin-bottom:6px;">
  <div style="flex:1; background:#f8f9fa; border:1px solid #e0e0e0; border-radius:12px; padding:10px 8px; text-align:center;">
    <div style="font-size:11px; color:#888; margin-bottom:4px;">풍향</div>
    <div style="font-size:20px; font-weight:800; line-height:1.2;">{wind_dir_kor(st.session_state.wd)}</div>
    <div style="font-size:12px; color:#888; margin-top:2px;">{st.session_state.wd:.0f}°</div>
  </div>
  <div style="flex:1; background:#f8f9fa; border:1px solid #e0e0e0; border-radius:12px; padding:10px 8px; text-align:center;">
    <div style="font-size:11px; color:#888; margin-bottom:4px;">풍속</div>
    <div style="font-size:20px; font-weight:800;">{ws_label}</div>
  </div>
  <div style="flex:1; background:#f8f9fa; border:1px solid #e0e0e0; border-radius:12px; padding:10px 8px; text-align:center;">
    <div style="font-size:11px; color:#888; margin-bottom:4px;">기온</div>
    <div style="font-size:20px; font-weight:800;">{temp_label}</div>
  </div>
  <div style="flex:1; background:#f8f9fa; border:1px solid #e0e0e0; border-radius:12px; padding:10px 8px; text-align:center;">
    <div style="font-size:11px; color:#888; margin-bottom:4px;">습도</div>
    <div style="font-size:20px; font-weight:800;">{rh_label}</div>
  </div>
</div>
"""
    components.html(weather_html, height=95, scrolling=False)
    st.caption("○ 분석 실행을 누르면 현재 기상이 자동 반영됩니다.")

    if total_frames > 0:
        selected_frame = st.slider(
            "확산 시점 선택", 1, total_frames, int(current_frame), key="frame_slider"
        )
        if selected_frame != current_frame:
            st.session_state.animation_frame = selected_frame
            st.session_state.animate_fire = False
            st.rerun()

        st.session_state.animation_interval_ms = st.slider(
            "재생 속도(ms)", 300, 2000, int(st.session_state.animation_interval_ms), 100,
            help="자동 반복재생 속도입니다."
        )

        play_col1, play_col2, play_col3 = st.columns(3)
        with play_col1:
            if st.button("⏸ 일시정지", use_container_width=True, key="pause_main"):
                st.session_state.animate_fire = False
                st.rerun()
        with play_col2:
            if st.button("▶ 다시 재생", use_container_width=True, key="resume_main"):
                st.session_state.animate_fire = True
                st.rerun()
        with play_col3:
            if st.button("⏮ 처음으로", use_container_width=True, key="reset_main"):
                st.session_state.animation_frame = 1
                st.session_state.animate_fire = False
                st.rerun()

    st.markdown("### □ 발화점 기준 가까운 경보시설")
    if nearest_sites:
        top3 = nearest_sites[:3]
        cards_html = '<div style="display:flex; flex-direction:column; gap:4px;">'
        for i, s in enumerate(top3):
            covered = s["covered"]
            판정_color = "#c0392b" if covered else "#1f7a1f"
            판정_text = "⚠️ 피해범위 내" if covered else "✅ 피해범위 밖"
            is_sel = str(s.get("site_id", "")) == str(st.session_state.selected_warning_site_id)
            bg = "#e8f4ff" if is_sel else "#fafafa"
            border = "2px solid #2b8cbe" if is_sel else "1px solid #e0e0e0"
            cards_html += (
                f'<div style="background:{bg}; border:{border}; border-radius:9px; '
                f'padding:7px 12px; font-size:13px; line-height:1.7;">'
                f'<b>{i}. {s["name"]}</b> <span style="color:#888; font-size:12px;">({s["city"]})</span><br/>'
                f'직선거리: <b>{format_distance_m(s["distance_m"])}</b> &nbsp;|&nbsp; '
                f'가청반경: {format_distance_m(s["radius_m"])} &nbsp;|&nbsp; '
                f'<span style="color:{판정_color}; font-weight:700;">{판정_text}</span>'
                f'</div>'
            )
        cards_html += '</div>'
        components.html(cards_html, height=195, scrolling=False)
    else:
        st.info("경보시설 데이터가 없습니다.")

    render_selected_facility_box(display_site, selected=bool(selected_site))

# ──────────────────────────────────────────────
# 브리핑 (expander)
# ──────────────────────────────────────────────
st.divider()
st.markdown("## □ 브리핑")
if display_site:
    label = "선택 경보시설" if selected_site else "최근접 경보시설"
    st.caption(
        f"○ {label}: {display_site['name']} ({display_site['city']}) / "
        f"직선거리 {format_distance_m(display_site['distance_m'])} / "
        f"가청반경 {format_distance_m(display_site['radius_m'])} / "
        f"{'⚠️ 피해범위 내' if display_site['covered'] else '✅ 피해범위 밖'}"
    )
elif warning_sites_err:
    st.caption(f"○ 경보시설 연동 상태: {warning_sites_err}")

if st.session_state.brief_text:
    with st.expander(f"📋 브리핑 보기 (갱신: {st.session_state.brief_updated_at})", expanded=True):
        st.info(st.session_state.brief_text)
else:
    st.write("○ 아직 브리핑이 없습니다. 사이드바에서 분석 실행을 눌러주세요.")

if total_frames > 0 and st.session_state.animate_fire:
    time.sleep(max(0.3, float(st.session_state.animation_interval_ms) / 1000.0))
    next_frame = st.session_state.animation_frame + 1
    st.session_state.animation_frame = 1 if next_frame > total_frames else next_frame
    st.rerun()

# ──────────────────────────────────────────────
# 실시간 산불 API 결과
# ──────────────────────────────────────────────
st.divider()
st.markdown("## □ 실시간 산불 API 자동분석")
if st.session_state.get("auto_last_scan"):
    st.caption(f"○ 마지막 조회/스캔: {st.session_state.auto_last_scan}")

if st.session_state.get("auto_analysis_items"):
    rows = []
    for a in st.session_state.auto_analysis_items[:5]:
        rows.append({
            "산불ID": a.get("fire_id", ""),
            "주소": a.get("address", ""),
            "상태": a.get("status_name", ""),
            "단계": a.get("step_name", ""),
            "분석시각": a.get("analyzed_at", ""),
            "위도": a.get("lat", ""),
            "경도": a.get("lon", ""),
        })
    st.table(rows)
elif st.session_state.get("auto_fire_items"):
    st.info("금일 산불 조회 결과가 있습니다. 신규 산불은 최초 감지 시 1회 자동분석되며, 이후에는 저장된 분석결과를 확인합니다.")
    rows = []
    for f in st.session_state.get("auto_fire_items")[:10]:
        rows.append({
            "산불ID": f.get("fire_id", ""),
            "주소": f.get("address", ""),
            "상태": f.get("status_name", ""),
            "단계": f.get("step_name", ""),
            "신고일": f.get("report_date", ""),
            "신고시각": f.get("report_time", ""),
            "위도": f.get("lat", ""),
            "경도": f.get("lon", ""),
        })
    st.table(rows)
else:
    st.info("금일 산불 조회 결과가 없습니다. 자동조회는 금일 산불 목록과 상태/단계 갱신만 반복하고, 신규 산불만 최초 1회 분석합니다.")

# ──────────────────────────────────────────────
# 하단: 산불위험 + 안내
# ──────────────────────────────────────────────
st.divider()
bottom_left, bottom_right = st.columns([1.35, 1])

with bottom_left:
    st.markdown("## □ 산불예측(경기도 배경 위험도)")
    st.caption("○ 발화점 주변 위험을 직접 나타내는 값이 아니라, 경기도 전체의 바탕 위험도입니다.")

    fr = st.session_state.get("fire_risk")
    if not fr:
        st.info("산불위험예보를 아직 불러오지 않았습니다. 분석 실행을 눌러주세요.")
    elif "error" in fr:
        st.error(fr["error"])
    else:
        items = fr.get("items") or []
        gg = [it for it in items if "경기" in str(it.get("doname", ""))] or items

        def _key(it):
            return str(it.get("analdate", ""))

        gg_sorted = sorted(gg, key=_key, reverse=True)
        cur = gg_sorted[0] if gg_sorted else {}
        analdate = str(cur.get("analdate", "—"))
        std = cur.get("std", cur.get("riskgrade", "—"))
        meanavg = cur.get("meanavg", "—")
        maxi = cur.get("maxi", "—")
        mini = cur.get("mini", "—")

        hh = analdate[-2:] if isinstance(analdate, str) and len(analdate) >= 2 else str(analdate)
        cc1, cc2, cc3, cc4, cc5 = st.columns(5)
        cc1.metric("기준시각", f"{hh}시")
        cc2.metric("등급", str(std))
        cc3.metric("평균", str(meanavg))
        cc4.metric("최대", str(maxi))
        cc5.metric("최소", str(mini))
        st.caption("○ 평균/최대/최소는 경기도 전체 구역 기준 위험지수입니다. 숫자가 클수록 위험합니다.")
        st.caption(f"○ 기준시각(원문): {analdate}")
        render_fire_risk_scale(std)

with bottom_right:
    st.markdown("## □ 안내")
    exp_rows = [
        {"항목": "풍향", "뜻(쉽게)": "예: 남서풍(233°)처럼 방향명과 각도를 함께 표시합니다."},
        {"항목": "경보시설 클릭", "뜻(쉽게)": "지도에서 시설 점을 클릭하면 우측 정보가 해당 시설 기준으로 바뀝니다."},
        {"항목": "등급", "뜻(쉽게)": "1=가장 높음, 6=가장 낮음."},
        {"항목": "평균/최대/최소", "뜻(쉽게)": "경기도 전체 위험 수준을 참고하는 값입니다."},
        {"항목": "레이어 수(steps)", "뜻(쉽게)": "4 이하 권장. 많을수록 지도가 느려집니다."},
        {"항목": "마커 클러스터링", "뜻(쉽게)": "경보시설 많을 때 자동으로 묶어줘 훨씬 빠릅니다."},
    ]
    st.table(exp_rows)
