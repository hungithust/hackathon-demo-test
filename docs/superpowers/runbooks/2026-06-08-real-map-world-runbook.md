# Runbook — Real-Map World (bản đồ HCM thật + lộ trình thật)

**Cập nhật:** 2026-06-08 · **Trạng thái:** code đã merge trên `feat/base-project`, 290 test xanh, đã verify end-to-end trên máy dev.

Tính năng này thay các cạnh đường "gõ tay" bằng **khoảng cách/thời gian/lộ trình thật** lấy từ OpenStreetMap (offline qua `osmnx`), mở rộng lên **~18 khách HCM thật**, và vẽ depot/khách/xe + **polyline lộ trình** lên bản đồ pydeck trong Streamlit.

> **Độc lập hoàn toàn** với phần Voice Intake và phần train Sovereign Brain trên node-07. Không sửa contracts/simulator/matrix/detector. Mặc định **TẮT** (`WORLD=sample`) → mọi thứ cũ chạy y hệt.

---

## TL;DR — Executor cần làm gì?

- **Chạy test / dùng hệ thống mặc định:** **KHÔNG cần làm gì.** `WORLD=sample` là mặc định; không cần osmnx, không cần internet, không cần graphml.
- **Muốn demo bản đồ thật:** chạy **1 lệnh fetch** (cần internet 1 lần) rồi bật `WORLD=real`. Xem §3.

---

## 1. Đã làm xong (không phải làm lại)

- `fleet/geo/router.py` — định tuyến thuần trên networkx (nearest-node + shortest-path + fallback đường thẳng). Không phụ thuộc osmnx.
- `fleet/geo/roster.py` — 18 khách HCM thật.
- `fleet/geo/osm_graph.py` — nạp graphml đã cache (lazy-import osmnx; thiếu file → báo lỗi rõ, trỏ về script fetch).
- `fleet/scenarios.py::build_real_state(graph, ...)` — dựng world thật, trả `(WorldState, geometry)`. `build_sample_state` **giữ nguyên** làm fallback.
- `config/settings.py` — `WORLD` / `OSM_GRAPHML_PATH` / `URBAN_SPEED_KMH`.
- `fleet/ui/controller.py` — nhánh `WORLD=real`, **tự fallback về sample** nếu thiếu graph/osmnx; `snapshot()` thêm `depot`/`customers`/`routes`.
- `fleet/ui/app.py` — bản đồ pydeck (chỉ import pydeck ở đây).
- `scripts/fetch_osm.py` — tải OSM 1 lần, **clamp tốc độ về đô thị** rồi lưu graphml.
- `data/*.graphml` và `cache/` đã **gitignore** — không commit file lớn.

---

## 2. Tài nguyên cần

| Thứ | Ghi chú |
|---|---|
| `osmnx>=2.0`, `networkx>=3.0` | pip, $0. Chỉ cần khi `WORLD=real` (lazy-import). Test không cần. |
| `pydeck>=0.8` | Đi kèm Streamlit. Chỉ import trong `app.py`. |
| Internet (1 lần) | `fetch_osm.py` gọi OpenStreetMap/Overpass. **Sau khi có graphml thì offline hoàn toàn.** |
| ~73 MB đĩa | Kích thước `data/hcm_drive.graphml` (đo thực tế). Không commit. |
| GPU / API key / node-07 | **Không cần.** |

Cài (nếu máy chưa có — venv dev đã có sẵn):
```bash
.venv/Scripts/python.exe -m pip install osmnx pydeck
```

---

## 3. Bật bản đồ thật (cho demo)

**Bước 1 — tải graph (1 lần, cần internet).** Chạy dạng **module** (không chạy `python scripts/fetch_osm.py` trực tiếp — sẽ lỗi `No module named 'fleet'`):
```bash
# Windows (venv dev)
.venv/Scripts/python.exe -m scripts.fetch_osm
# Linux / node-07
python -m scripts.fetch_osm
```
Kỳ vọng: `Saved data/hcm_drive.graphml: ~59k nodes, ~136k edges, ~73 MB`.

> **Nếu timeout `overpass-api.de`:** đây là sự cố mạng tạm thời của OSM, **không phải lỗi code** — chạy lại lệnh 1–2 lần (đã gặp & retry thành công khi verify).

**Bước 2 — chạy app với world thật:**
```bash
# PowerShell
$env:WORLD="real"; .venv/Scripts/python.exe -m streamlit run fleet/ui/app.py
# bash
WORLD=real python -m streamlit run fleet/ui/app.py
```
Kỳ vọng: panel **"Bản đồ"** vẽ polyline lộ trình thật giữa depot và ~18 khách rải nhiều quận; depot vàng, khách xanh, xe đỏ.

**Tinh chỉnh tốc độ (tùy chọn).** OSM maxspeed cho thời gian quá nhanh, nên ta clamp về `URBAN_SPEED_KMH` (mặc định 25). Đổi rồi **fetch lại**:
```bash
URBAN_SPEED_KMH=20 python -m scripts.fetch_osm
```

---

## 4. Verify nhanh (không cần internet sau khi đã có graphml)

```bash
# 1) Suite vẫn xanh, không import osmnx/pydeck
.venv/Scripts/python.exe -m pytest -q          # 290 passed

# 2) World thật dựng được + ra routes
.venv/Scripts/python.exe -c "from config.settings import load_settings; \
from fleet.ui.controller import SimulationController; \
c=SimulationController(settings=load_settings({'WORLD':'real'})); \
s=c.snapshot(); print('customers',len(s['customers']),'routes',len(s['routes']))"
# kỳ vọng: customers 18 routes 38
```
Số liệu tham chiếu đã verify: `DEPOT->C002` ≈ **10.18 km / 24.4 phút** (clamp 25 km/h), cạnh ngập `DEPOT->C001#2` có mặt.

---

## 5. Điều KHÔNG được làm / cần tránh

- **Đừng commit `data/hcm_drive.graphml`** (73 MB) — đã gitignore; tái tạo bằng `fetch_osm` thay vì commit.
- **Đừng đổi mặc định sang `WORLD=real`** trong settings — giữ `sample` để CI/test và đường tối thiểu luôn chạy.
- **Đừng import osmnx/pydeck ở module khác** ngoài `osm_graph.py` (lazy) và `app.py` — sẽ làm test phụ thuộc nặng.
- **Đừng nhét đường OSM thành `RoadEdge`** — model chỉ giữ cạnh logic depot↔khách; OSM chỉ điền số + polyline bên lề.

---

## 6. Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| App vẫn ra chấm điểm, **không có polyline** | Chưa có graphml hoặc đang `WORLD=sample`. Controller tự fallback về sample (đúng thiết kế). Chạy §3 để bật world thật. |
| `FileNotFoundError ... fetch_osm` | Chưa tải graph. Chạy `python -m scripts.fetch_osm`. |
| `ConnectTimeout overpass-api.de` | Mạng OSM tạm thời. Chạy lại lệnh fetch 1–2 lần. |
| `No module named 'fleet'` khi fetch | Chạy trực tiếp file. Dùng `-m scripts.fetch_osm` từ thư mục gốc repo. |
| Thời gian đi quá nhanh/chậm | Chỉnh `URBAN_SPEED_KMH` rồi fetch lại (clamp áp lúc fetch, không phải lúc chạy). |

---

## 7. Gợi ý tiếp theo (không bắt buộc)

- Lớp **KPI counterfactual + decision card** (hướng B đã có spec riêng) vẽ **đè lên chính bản đồ này** → một màn hình demo vừa đẹp vừa có số.
- Trên node-07: chạy `fetch_osm` một lần, mở port web cho demo; nếu node-07 chặn outbound thì **copy `data/hcm_drive.graphml` từ máy dev sang** (offline được sau khi đã có file).
