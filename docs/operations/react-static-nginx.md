# React production 정적 배포 (선택 적용)

| Field | Value |
| --- | --- |
| Status | Current template; opt-in |
| Last verified | 2026-10-22 |
| Scope | React `ui/dist`의 호스트 루트 배포와 기존 API 프록시 |
| Sources | `scripts/dev_up.sh`, `ui/vite.config.ts`, `ui/src/lib/api.ts`, `ui/src/lib/admission.ts`, `src/scenario_db/api/app.py`, `deploy/nginx/scenariodb-react.conf` |
| Validation | 공식 Nginx 1.30.6 임시 컨테이너의 `nginx -t` 및 컨테이너 내부 모의 API HTTP 검사. 운영 서버 미적용. |

[Nginx 설정 템플릿](../../deploy/nginx/scenariodb-react.conf)은 검토 후 별도로 적용하는
산출물이다. 기존 `dev_up.sh`, 실행 중 API/UI, 서버의 Nginx 설정을 자동으로 바꾸지 않는다.
현재 개발 실행은 API `127.0.0.1:18000`, Vite `127.0.0.1:3000`이며,
정적 배포를 선택하면 Nginx가 React 파일을 직접 제공한다.
API 실행·DB·인증 설정은 [Ubuntu 배포 가이드](deployment-ubuntu.md)를 따른다.

## 빌드와 적용 준비

Node.js 24와 lockfile을 사용해 **배포할 revision의** 정적 파일을 만든다.
호스트 루트(`/`)용 asset URL은 CLI 옵션으로 지정하며 UI 소스 설정은 변경하지 않는다.
기존 hash URL(`#/...`)과 같은 origin의 `/api/v1`을 그대로 사용한다.

```bash
cd /opt/scenariodb/implementation/ui
npm ci
npm test
npm run build -- --base=/
```

배포 디렉터리는 애플리케이션 저장소와 분리한다. 예를 들어
`/opt/scenariodb/ui/releases/<revision>/`에 `dist/`의 **내용**을 복사하고
검토된 release를 가리키는 `/opt/scenariodb/ui/current`를 준비한다.
Nginx 계정이 읽을 수 있어야 한다. 이전 release와 hashed assets는 열린 브라우저의
지연 로딩 및 rollback 기간 동안 유지한다. 기존 HTML이 참조하는 이전 asset URL도
계속 제공하도록 새 release의 `assets/`에 보존하거나 공용 immutable asset 저장소를 사용한다.

템플릿의 `server_name`, `root`, API 주소를 실제 환경에 맞게 검토한다.
`dev_up.sh --api-port`를 사용했다면 프록시의 `18000`도 같은 값으로 맞춘다.
템플릿은 호스트 루트용이며 `/scenariodb/` 같은 하위 경로 설치는 별도 설정이 필요하다.
기존 사이트의 TLS·내부 접근 제어를 유지한다. 템플릿의 `listen 80`은 내부 HTTP 예시이며,
API 키를 전달하는 실제 접속 경로에는 기존 TLS 또는 승인된 보호 구간을 사용한다.
Streamlit의 선택적 `/viewer/` 경로와 `18502` 포트도 기존 가이드처럼 포함되어 있다.

운영자가 적용하기로 결정한 뒤 `sites-enabled` 또는 `conf.d` 한 곳에만 설치하고
`nginx -t`를 통과한 설정을 reload한다. 기존 API 또는 Vite 프로세스를 이 문서의 검증을
위해 중지할 필요는 없다. API의 시작 방식·worker 수와 기존 개발 실행은 그대로 둘 수 있다.
정적 UI 전환을 확인한 이후에만 운영 절차에 따라 불필요한 Vite 개발 서버를 정리한다.

## 경로, 캐시, 긴 요청

- `/api/`, `/health/live`, `/health/ready`, `/docs`, `/redoc`, `/openapi.json`은
  URI와 query를 보존해 API로 전달한다. API 오류를 SPA HTML로 바꾸지 않는다.
- API key ID·secret 및 Authorization 헤더를 보존한다. Nginx의 API 응답 캐시는 꺼져 있다.
  서버가 반환한 401/403/429와 `Retry-After`를 그대로 전달하며 POST를 자동 재전송하지 않는다.
- 성공한 hashed `/assets/` 파일만 1년 `immutable`이다. HTML과 일반 정적 파일은
  `no-cache`로 재검증한다. 없는 asset은 404이며 HTML fallback이나 immutable 캐시를 받지 않는다.
- `proxy_read_timeout`·`proxy_send_timeout` **600초**, 연결 5초는 이 선택적 템플릿의 예시다.
  기존 Ubuntu 예제는 이 값을 지정하지 않아 Nginx 기본 read timeout 60초를 사용했다.
  read timeout은 응답 전체 실행시간이 아니라 upstream read 사이의 무응답 간격이다.
  현재 계산 API에는 공통 강제 실행 deadline이 없다. 긴 동기 계산의 측정값에 맞춰
  프록시·외부 로드밸런서 한도를 함께 검토한다. timeout 이후 자동 POST 재시도를 추가하지 않는다.
- UI의 HTTP 429 admission 대기 예산 **120초**는 별도이며 그대로 유지된다.
  프록시 timeout이나 브라우저 요청 취소가 이미 실행 중인 계산을 강제 종료하지 않는다.

위 timeout·재시도 의미는 [Nginx proxy 문서](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_read_timeout),
캐시 헤더는 [headers 문서](https://nginx.org/en/docs/http/ngx_http_headers_module.html#add_header)를 따른다.
API worker/DB 예산은 [리소스 예산 문서](performance-budgets.md)를 함께 확인한다.

## 격리 검증과 전환 확인

저장소 루트에서 공식 Nginx 이미지로 문법을 확인할 수 있다. 컨테이너는 포트를 공개하지 않고
운영 API/DB에 접속하지 않는다. 이미지 pull에는 별도 네트워크 접근이 필요하다.

```bash
docker run --rm --network none --entrypoint nginx \
  --mount "type=bind,src=$PWD/deploy/nginx/scenariodb-react.conf,dst=/etc/nginx/conf.d/default.conf,readonly" \
  --mount "type=bind,src=$PWD/ui/dist,dst=/opt/scenariodb/ui/current,readonly" \
  nginx:stable-alpine -t
```

실제 전환 시에는 대상 서버에서 `nginx -t`를 다시 실행하고, 승인된 staging 주소로
HTML의 재검증 헤더, hashed JS/CSS의 immutable 헤더, 없는 asset의 404,
health 응답, 기존 hash 링크의 직접 열기, 인증 실패/성공 및 긴 계산을 확인한다.
이 템플릿의 격리 검증은 실제 Ubuntu 설치 버전·TLS·사내 인증·운영 계산 지연의 검증을 대신하지 않는다.
rollback은 이전 정적 release/검토된 Nginx 설정으로 되돌리는 방식이며 DB 변경은 필요 없다.
