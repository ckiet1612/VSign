# E2E

## Tổng quan và giám sát runtime

`workspace_runtime.mjs` đọc `/health`, `/metadata` từ backend thật đang chọn,
kiểm tra tự cập nhật, làm mới, đổi endpoint, dừng polling khi rời trang và
layout 320/390/768/1365 px. Các tình huống lỗi mạng, metadata sai và timeout
dùng network fixture; không tắt backend thật, bật camera hay gửi/lưu mẫu.

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_SMOKE_URL=http://127.0.0.1:5174 \
VSIGN_INFERENCE_URL=http://127.0.0.1:8002 \
VSIGN_CANDIDATE_URL=http://localhost:8003 \
node tests/e2e/workspace_runtime.mjs
```

Các URL phải khớp cấu hình frontend. Platform `/api/v1/workspace/capabilities`
cần trả `monitoring: true`; khởi động lại platform sau khi cập nhật backend.
`VITE_PLATFORM_HTTP_URL` độc lập với `VITE_INFERENCE_HTTP_URL`. Script giữ
nguyên dịch vụ đang chạy và lưu report/screenshot tại `VSIGN_SMOKE_OUTPUT`
(mặc định `/tmp/vsign-workspace-runtime-20261015`). Độ trễ trên trang là thời
gian gọi health, không phải latency nhận dạng; latency/tỷ lệ lỗi inference
vẫn chưa có nguồn tổng hợp. Screenshot/fixture không chứng minh chất lượng
webcam hoặc hiệu năng inference.

## Dev/Test thủ công

`manual_dev_test.mjs` dùng camera replay và backend/model thật với database
riêng để kiểm tra nhiều lượt test liên tiếp, giữ nhãn khi thu, video đã lưu,
kiểm định/loại clip mà không đổi dự đoán gốc, lỗi thu quá ngắn, mất reply rồi
retry cùng UUID, thống kê riêng lỗi kỹ thuật/negative và xuất CSV/JSON.
Kiểm tra DOM ở 320/390/768/1365 px và pixel camera không trắng; screenshot
được lưu. Hướng dẫn tại
[MANUAL_DEV_TEST_LOCAL.md](../../docs/MANUAL_DEV_TEST_LOCAL.md).
Không chạy smoke với database test thật; replay không chứng minh độ chính xác
webcam, người ký mới hoặc tốc độ realtime.

## Câu dự thảo tự động

`automatic_sentence.mjs` dùng camera replay, raw tracking/prediction fixture
và API ghép câu thật. Nó kiểm tra từ `Rẻ` đang chờ không bị bỏ, uncertainty
không biến thành câu đầy đủ, 16 frame RGB, không lỗi JS và layout
320/390/768/1365 px. Nhân viên cấu hình một lần; các lượt khách ký không bấm
web. Đây là bằng chứng workflow, không phải chất lượng webcam/model hay
nghiệm thu B2B. Lệnh chạy và giới hạn nằm trong
[AUTOMATIC_SENTENCE_LOCAL.md](../../docs/AUTOMATIC_SENTENCE_LOCAL.md).

## Tracking hiển thị ổn định

`tracking_display.mjs` kiểm tra lớp vẽ trên Chrome bằng camera replay: giữ màu
khi detector đảo thứ tự/hai tay bắt chéo, làm mờ rồi bỏ điểm mất dấu, hết hạn
ngay cả khi video tạm dừng, xóa canvas khi tắt camera và không tràn ngang ở
320/390/768/1365 px. Canvas-pixel checks xác nhận hình được vẽ. Một context khác
dùng MediaPipe thật trên replay để kiểm tra tích hợp; không dùng webcam thật.
Không gửi inference hoặc lưu mẫu trong các tình huống fixture.

Chuẩn bị replay riêng, không sửa clip nguồn:

```bash
ffmpeg -n -i ml/data/collected/sales30_seated_remaining21/clips/May-giat/HA_rep01.mp4 \
  -vf 'scale=640:360,setsar=1,fps=20,tpad=start_mode=clone:start_duration=2:stop_mode=clone:stop_duration=4' \
  -pix_fmt yuv420p -f yuv4mpegpipe /tmp/vsign-tracking-display.y4m
```

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_FAKE_CAMERA_FILE=/tmp/vsign-tracking-display.y4m \
node tests/e2e/tracking_display.mjs
```

`VSIGN_SMOKE_OUTPUT` mặc định `/tmp/vsign-tracking-display-smoke`, chứa report
và screenshot. Fixture/replay chứng minh hành vi kỹ thuật, không chứng minh
độ chính xác tracking ngón bị che hay chất lượng với người ký mới. Điểm làm
mượt/giữ tạm chỉ dùng hiển thị; raw landmark, presence mask, crop và timestamp
đưa vào nhận dạng/thu mẫu vẫn giữ nguyên.

### Evidence tracking ngày 2026-10-09

- 253 frontend tests trong 32 file đã qua; ESLint và TypeScript/Vite build
  đã qua. Trong đó có 25 test filter/overlay cho rung nhẹ, chuyển động nhanh,
  đổi thứ tự/bắt chéo tay, mất dấu ngắn/dài, raw presence mask, crop thích ứng,
  timestamp capture, fallback animation-frame và hủy callback khi tháo overlay.
- Smoke tracking đã qua tại
  `/tmp/vsign-tracking-display-smoke-20261009-resume/report.json`: fixture giữ
  màu, làm mờ/hết hạn, xóa canvas khi tắt camera, không gửi inference/lưu mẫu;
  MediaPipe thật vẽ được trên video replay. DOM và canvas-pixel checks đã qua
  ở 320/390/768/1365 px. Screenshot được lưu nhưng chưa kiểm tra trực quan do
  công cụ xem ảnh không khả dụng trong phiên này.
- Smoke hồi quy hàng đợi với backend PyTorch seated-v3 thật đã qua tại
  `/tmp/vsign-tracking-live-queue-regression-20261009/report.json`; vẫn thu
  lượt tiếp theo khi chờ AI, gửi FIFO và đúng 16 ảnh 224x224.
- Smoke transcript dùng prediction fixture đã qua tại
  `/tmp/vsign-tracking-transcript-regression-20261009/report.json`; xác nhận
  thủ công/tự động, loại phản hồi cũ/trùng và hoàn tác/xóa vẫn hoạt động.
- Không dùng webcam thật, train model hoặc sửa dữ liệu thu cũ. Replay và
  fixture không thay thế nghiệm thu camera thật, chất lượng ngón bị che hay
  đánh giá người ký mới. Timing smoke không phải benchmark inference.

## Video mẫu trên màn hình Thu dữ liệu AI

`collection_reference_videos.mjs` kiểm tra phát 30 MP4 Sales30 thật trên Chrome,
đổi từ đúng video, giữ hướng dẫn `Không ký hiệu`, không thêm video ở màn hình
nhận dạng và không tràn ngang ở 320/390/768/1365 px. Metadata/tiến độ là fixture;
không bật webcam, không gửi inference, không ghi thêm mẫu vào dữ liệu thật.

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_SMOKE_URL=http://localhost:5173 \
node tests/e2e/collection_reference_videos.mjs
```

`VSIGN_SMOKE_OUTPUT` mặc định `/tmp/vsign-collection-reference-videos`, chứa
`report.json` và screenshot. Script tự đóng Chrome test, giữ nguyên Vite/backend.

## Personal 100 collection smoke

`personal_collection.mjs` dùng Chrome và camera replay, lưu MP4 thật qua backend
thu local riêng với `COLLECTION_DIR` bắt buộc nằm trong `/tmp/vsign-*`.
Không chạy script với thư mục dữ liệu thật. Smoke kiểm tra tự thu nhiều lượt,
tạm dừng/tiếp tục/dừng, đọc lại tiến độ sau reload, lỗi lưu không tự retry,
retry chủ động giữ cùng `sample_key`, quota tổng 100 và bảo toàn dữ liệu legacy.
99 file quota là fixture, không phải 99 lượt thu thật. WebSocket inference bị
chặn để xác minh thu không phụ thuộc model. Bố cục kiểm tra ở 320/390/768/1365 px.

Chạy backend smoke ở một port trống, ví dụ:

```bash
PYTHONPATH=services/inference:. INFERENCE_BACKEND=mock COLLECTION_ENABLED=true \
COLLECTION_DIR=/tmp/vsign-personal100-smoke/data \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Trong terminal khác, với web mới đang chạy và camera replay đã chuẩn bị:

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_FAKE_CAMERA_FILE=/tmp/vsign-live-camera.y4m \
VSIGN_COLLECTION_SMOKE_DATA=/tmp/vsign-personal100-smoke/data \
VSIGN_COLLECTION_SMOKE_BACKEND=http://127.0.0.1:8002 \
VSIGN_SMOKE_URL=http://127.0.0.1:5174 \
node tests/e2e/personal_collection.mjs
```

Dùng thư mục smoke mới mỗi lần chạy. Script tự đóng Chrome, không dừng dịch vụ
của người dùng. Kết quả chỉ chứng minh luồng kỹ thuật, không chứng minh chất lượng
ký hiệu hoặc kết quả fine-tune.

### Evidence personal-100 ngày 2026-10-09

- 195 frontend tests trong 29 file và 29 backend tests tập trung đã qua.
- TypeScript/Vite build, ESLint và `git diff --check` đã qua.
- Smoke Chrome đã qua tại `/tmp/vsign-personal100-smoke-20261009-r2/report.json`:
  clip nguồn 28-29 ảnh 224x224, lưu MP4 thật vào thư mục tạm; không có request
  inference, page error hoặc tràn ngang ở 320/390/768/1365 px.
- Kiểm tra tạm dừng/tiếp tục/dừng, reload tiến độ, lỗi lưu không auto retry,
  retry chủ động giữ mã lượt, dừng ở tổng quota 100 và bảo toàn sentinel legacy.
  Quota test có 99 cặp fixture seed, không phải 99 mẫu ký hiệu hợp lệ.
- Test hồi quy bao phủ ghi dở video thiếu metadata, hai upload tranh lượt thứ
  100, lỗi camera/encode, tổng hai tay thay đổi từ cửa sổ khác và upload trả lỗi
  sau khi Dừng. Không train, không thay model hoặc dữ liệu cũ.

## Live capture queue smoke

`live_capture_queue.mjs` dùng Chrome với camera replay; không truy cập webcam thật.
Backend/frontend local cần đang chạy, Chrome và Playwright cần có sẵn. Test giữ
reply của backend trong trình duyệt để chứng minh camera vẫn thu 2 clip chờ,
không gửi request chồng, báo đầy, gửi FIFO khi trả reply và hủy clip chờ khi tắt
camera. Test cũng kiểm tra 16 ảnh 224x224, luồng Space thủ công, transcript không
tự thêm và bố cục 320/390/768/1365 px.

Tạo replay từ clip local (FFmpeg đã có sẵn):

```bash
ffmpeg -y -i ml/data/collected/sales30_seated_remaining21/clips/May-giat/HA_rep01.mp4 \
  -vf 'scale=640:360,setsar=1,fps=20,tpad=start_mode=clone:start_duration=2:stop_mode=clone:stop_duration=4' \
  -pix_fmt yuv420p -f yuv4mpegpipe /tmp/vsign-live-camera.y4m
```

Chạy từ root repo trên máy hiện tại bằng Playwright bundled của Codex:

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_FAKE_CAMERA_FILE=/tmp/vsign-live-camera.y4m \
node tests/e2e/live_capture_queue.mjs
```

Nếu Playwright được cài tại project thì không cần `VSIGN_PLAYWRIGHT_FROM`.
`VSIGN_SMOKE_URL` mặc định `http://localhost:5173`; `VSIGN_SMOKE_OUTPUT` mặc định
`/tmp/vsign-live-queue-smoke`, chứa `report.json` và screenshot. Script không dừng
backend/Vite và luôn đóng Chrome test. Timing trong smoke có độ trễ giả lập, không
được dùng làm benchmark; replay clip cũ không chứng minh chất lượng với người ký
mới. Camera thật vẫn cần một đợt nghiệm thu của người dùng.

## Automatic transcript smoke

`auto_transcript.mjs` dùng cùng camera replay nhưng thay metadata/prediction bằng
fixture xác định ngay trong Chrome; không cần backend và không chạy model thật.
Test kiểm tra mặc định thủ công, click xác nhận, thêm tự động với cả hai cách thu,
không nhận lại reply cũ/trùng sau đổi lựa chọn, hoàn tác/xóa, đúng 16 ảnh 224x224
và bố cục 320/390/768/1365 px. Fixture này chỉ xác minh hành vi ứng dụng, không
chứng minh độ chính xác nhận dạng hoặc tốc độ inference.

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_FAKE_CAMERA_FILE=/tmp/vsign-live-camera.y4m \
VSIGN_SMOKE_OUTPUT=/tmp/vsign-auto-transcript-smoke \
node tests/e2e/auto_transcript.mjs
```

Frontend đang chạy được dùng lại; script luôn đóng Chrome test và không dừng
Vite/backend. `report.json` và screenshot được ghi vào `VSIGN_SMOKE_OUTPUT`.

### Kết quả ngày 2026-10-08

- 175 frontend test trong 28 file đã qua; TypeScript/Vite build, ESLint và
  `git diff --check` đã qua. Test bổ sung bao phủ FIFO server/local, opt-in từ
  lúc bắt đầu thu, cooldown, đổi lựa chọn, phản hồi cũ/trùng, nhãn/phiên bản
  không hợp lệ, hoàn tác/xóa và không thêm từ trong luồng thu dữ liệu.
- Smoke thêm từ với fixture đã qua, evidence tại
  `/tmp/vsign-auto-transcript-smoke-20261008/report.json` và screenshot cạnh đó.
- Smoke hồi quy hàng đợi với backend PyTorch seated-v3 thật đã qua, evidence tại
  `/tmp/vsign-live-queue-regression-20261008/report.json` và screenshot cạnh đó.
- Hai smoke xác nhận payload 16 ảnh 224x224, không có page error và không đo
  được tràn ngang ở 320/390/768/1365 px. Camera dùng replay, không phải webcam
  thật; số đo có reply fixture/giữ nhân tạo nên không là benchmark latency.
- Rà soát độc lập phạm vi thêm từ không có finding cần sửa. Thời điểm native
  camera interruption trước khi React commit và chất lượng nhận dạng camera
  thật vẫn cần nghiệm thu; chưa được chứng minh bởi các smoke này.
- Không đổi model, ngưỡng nhận dạng hay dữ liệu; không commit/push và không dừng
  frontend/backend của người dùng. Frontend vẫn ở `http://localhost:5173`.
## Hoạt động

`workspace_activity.mjs` chạy màn hình Hoạt động với platform và cơ sở dữ liệu tạm riêng. Xem `docs/WORKSPACE_ACTIVITY_LOCAL.md` để biết điều kiện chạy, phạm vi và giới hạn bằng chứng.

## Local Default Admin

`workspace_local_admin.mjs` reads the already-running local frontend/platform.
It verifies enterprise admin identity and zero model mutation permissions without
a login form or session cookie, checks five workspace views at four responsive
widths, and blocks all
browser mutations. It does not start/stop servers, open a camera or deploy a
model. Requires Chrome and a local-admin backend.

```sh
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
node tests/e2e/workspace_local_admin.mjs
```

Optional `VSIGN_WEB_URL`, `VSIGN_PLATFORM_URL` and `VSIGN_E2E_OUTPUT` override
the default 5174 frontend, 8000 platform and `tmp/enterprise-admin-browser-20261015`
report/screenshot directory. Do not run against a publicly accessible server.

## Enterprise Models And Internal Lifecycle

`workspace_models.mjs` creates isolated platform/frontend processes, a temporary
database and tiny native ONNX artifacts on free ports. Its fixture explicitly
provisions an internal membership; no real workspace account is promoted.
The internal API exercises candidate-only registration, validation, separate
approval, deployment, idempotency and rollback. WebSocket predictions verify
the served model changes and restores. The customer workspace stays read-only
with populated update history at 320/390/768/1365 px.

```sh
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
node tests/e2e/workspace_models.mjs
```

The script prints the temporary report/screenshot directory and stops its test
browser and servers. It does not train, modify real artifacts or prove camera
quality, real evaluation quality or production release acceptance. Both browser
scripts check nonblank pixels and document overflow, not every possible text
overlap or clipping condition.

## Enterprise Workspace Data

`workspace_data.mjs` starts isolated mock inference/platform and Vite on free
ports with a temporary database/media directory and passwordless enterprise
admin. The browser creates labels and a draft, sets quota, records a synthetic
camera clip through the real capture/MP4 path, completes its session and seals
an immutable snapshot. It verifies copied bytes and manifest SHA256, reload
persistence, server audit and four Data tabs at 320/390/768/1365 px.

```sh
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
node tests/e2e/workspace_data.mjs
```

Requires Chrome, Playwright, sharp and the existing `.venv` inference dependencies.
Run separately from CPU-heavy frontend tests; the workspace loader has an
8-second timeout. Output includes report, network diagnostics, screenshots and
server logs. Disposable servers/browser are stopped even on failure. Existing
5174/8000/8002/8003 listeners and real media are not used or changed.

Platform writes must all belong to the data API: no legacy collection writes,
client collection-audit duplicates or model mutations. Existing MediaPipe SDK
telemetry can still make external requests. Pixel/DOM checks establish nonblank
rendering and measured clipping/overflow, not manual visual approval or real-camera
recognition quality. See `docs/WORKSPACE_DATA_LOCAL.md` for API and recovery limits.

## Enterprise Workspace Integrations

`workspace_integrations.mjs` starts disposable mock inference/platform and Vite
on free ports with an isolated database and encryption key. Chrome exercises
one-time API key creation, scoped reads, persisted rate limits, admin isolation,
encrypted webhook creation, explicit test enqueueing and key revocation. It
checks all three populated tabs at 1440/1024/768/390 px for nonblank pixels and
document overflow. It never starts a webhook dispatcher or sends to the saved
external URL; the test delivery remains queued.

```sh
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
node tests/e2e/workspace_integrations.mjs
```

Requires Chrome, Playwright, sharp and the existing `.venv` dependencies.
The script prints a temporary report/screenshot directory and stops its own
browser and servers. It does not modify the real workspace or active model.
Backend tests in `tests/test_workspace_integrations.py` separately check real
local TLS/signatures, certificate hostname rejection, SSRF, subprocess deadlines
and retry fencing. None of these checks establish delivery to customer
infrastructure, PostgreSQL behavior, production load or manual visual approval.
See `docs/WORKSPACE_INTEGRATIONS_LOCAL.md` for API and operator-key recovery.

## Enterprise Workspace Team

`workspace_team.mjs` starts isolated SQLite/mock platform and Vite on free
ports in session-auth mode. Chrome signs in as fixture owner, creates manual
invitations, accepts as a new account and an existing account, checks current
password protection/no implicit login, role changes, scoped session revocation,
restore/removal/reinvite and private Activity filtering. No emails or shared
workspace writes. All processes are stopped in cleanup.

```sh
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
  node tests/e2e/workspace_team.mjs
```

Requires Chrome, Playwright, sharp and `.venv` dependencies. Four populated
tabs, including the expanded searchable audit member picker, are checked at
1440/1024/768/390/320 px; acceptance is also checked on mobile. Reports include
screenshots, nonblank pixel statistics and document overflow, not manual visual
approval. Backend tests separately cover concurrent accept/revoke, persisted
limits, actor/session revalidation, pagination, stale revisions, migrations and
secret-safe validation. PostgreSQL/public load/SMTP remain unverified.
See `docs/WORKSPACE_TEAM_LOCAL.md` for API, security boundaries and recovery.

## Enterprise Workspace Settings

`workspace_settings.mjs` starts isolated SQLite/mock platform and Vite on free
ports with session authentication. It saves all five groups, verifies reload,
dirty-draft conflicts, exact request retry after a lost successful ACK, personal
preferences, role denial, session revocation, runtime defaults and opt-in consent.
No camera is started and no shared DB or real media is written. Own servers and
browser are cleaned up. `--serve` keeps only the fixture running for manual
verification; stop it with Ctrl+C.

```sh
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
  node tests/e2e/workspace_settings.mjs
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
  node tests/e2e/workspace_settings_live.mjs
```

Requires Chrome, Playwright, sharp and `.venv` dependencies. Five tabs are checked
at 1440/1024/768/390/320 px for nonblank pixels, document overflow and control
bounds. The live script requires an existing loopback local-admin workspace,
blocks every browser API write, and checks settings/metadata remain unchanged.
Optional `VSIGN_API`, `VSIGN_WEB`, `VSIGN_EVIDENCE_DIR` override its default
8000 API, 5174 frontend and evidence directory. Fixture writes are not live
acceptance. Retention is preview-only; email/push, PostgreSQL, load and real
camera quality are not established. See `docs/WORKSPACE_SETTINGS_LOCAL.md`.
