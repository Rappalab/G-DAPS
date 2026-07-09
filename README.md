# G-DAPS 일반 서버 탑재형 배포본

이 배포본은 Docker 없이 서버에 올릴 수 있도록 정리한 버전입니다.
GitHub에는 소스코드, `requirements.txt`, `.env.example`, 실행 스크립트, systemd/nginx 예시만 올리고, 실제 API 키가 들어가는 `.env`는 올리지 않습니다.

## 1. 구성

```text
app/                     Flask API, Streamlit 앱, 분석 로직
ui/                      정적 지도 UI
scripts/                 서버 실행 스크립트
deploy/nginx/            nginx 설정 예시
deploy/systemd/          systemd 서비스 예시
data/.gitkeep            운영 DB 저장 폴더 자리표시자
.env.example             환경변수 예시, 실제 키 없음
.gitignore               .env, DB, 업로드 파일 제외
requirements.txt         Python 패키지
```

Docker 관련 파일(`Dockerfile`, `docker-compose.yml`)과 운영 중 생성된 DB·업로드 파일·캐시 파일은 GitHub 업로드용 배포본에서 제외했습니다.

## 2. 서버 설치 예시

서버에서 `/opt/gdaps` 기준으로 설치하는 예시입니다.

```bash
sudo mkdir -p /opt/gdaps
sudo chown -R $USER:$USER /opt/gdaps

# GitHub에서 받은 소스 복사 또는 git clone 후
cd /opt/gdaps
bash scripts/install_server.sh

# 실제 운영값 입력
nano .env
```

`.env`에는 `.env.example`을 참고해 API 키, 공개 접속 주소, 포트 등을 입력합니다.

## 3. 단독 실행 테스트

```bash
cd /opt/gdaps
source .venv/bin/activate
bash scripts/start_api.sh
```

다른 터미널에서 확인합니다.

```bash
curl http://127.0.0.1:5000/health
```

정상이라면 `ok`가 출력됩니다.

## 4. nginx로 지도 UI 제공

정적 지도 UI는 nginx가 제공하고, `/api/` 요청은 Flask API로 프록시합니다.

```bash
sudo cp deploy/nginx/gdaps.conf /etc/nginx/conf.d/gdaps.conf
sudo nginx -t
sudo systemctl reload nginx
```

기본 설정은 `http://서버주소:8504`로 접속합니다. 포트를 바꾸려면 `deploy/nginx/gdaps.conf`의 `listen 8504;` 값을 수정하세요.

## 5. systemd 등록

```bash
sudo cp deploy/systemd/gdaps-api.service /etc/systemd/system/
sudo cp deploy/systemd/gdaps-monitor.service /etc/systemd/system/
# Streamlit 화면도 별도 운영할 때만 복사
sudo cp deploy/systemd/gdaps-streamlit.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now gdaps-api.service
sudo systemctl enable --now gdaps-monitor.service
```

상태 확인:

```bash
systemctl status gdaps-api.service
systemctl status gdaps-monitor.service
journalctl -u gdaps-api.service -f
```

Streamlit을 별도로 쓰려면 다음을 실행합니다.

```bash
sudo systemctl enable --now gdaps-streamlit.service
```

## 6. GitHub 업로드 시 주의

반드시 `.env` 파일은 올리지 마세요. 이 배포본의 `.gitignore`는 다음 항목을 제외합니다.

- `.env`, `.env.*`
- `data/*.db`, `*.sqlite*`
- `uploads/`, `db/`, `__pycache__/`
- `Dockerfile`, `docker-compose*.yml`

GitHub 업로드 전 확인:

```bash
git status --ignored
```

## 7. 주요 환경변수

| 변수명 | 설명 |
|---|---|
| `PUBLIC_APP_URL` | 텔레그램 알림 등에 표시할 접속 주소 |
| `FLASK_PORT` | Flask API 포트, 기본 5000 |
| `STREAMLIT_PORT` | Streamlit 포트, 기본 8501 |
| `GDAPS_DB_PATH` | SQLite DB 경로 |
| `KMA_SERVICE_KEY` | 기상청 API 키 |
| `VWORLD_KEY` | VWorld API 키 |
| `KFS_FIRE_RISK_KEY` | 산림청 산불위험 API 키 |
| `SAFEMAP_KEY` | 생활안전지도 API 키 |
| `GEMINI_API_KEY` | LLM 사용 시 Gemini 키 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 알림 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 수신 채팅 ID |
| `TODAY_FIRE_API_URL` | 금일 산불 발생 현황 API 주소 |

