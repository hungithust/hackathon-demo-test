# Hướng dẫn chạy — Fleet Optimizer (bản checkpoint)

Bản đóng gói tạm để **test giao diện, test luồng, và bản đồ tích hợp**.
Phần lõi mô hình LLM/ASR/GPU (cuOpt, NIM, Whisper/Riva) **chỉ chạy trên node-07
của ban tổ chức** — không bắt buộc cho checkpoint này. Hệ thống luôn chạy được
với cấu hình mặc định (rule-based + OR-Tools CPU + transcriber rỗng).

---

## 0. Kết quả kiểm tra toàn diện (đã chạy trên repo này)

| Hạng mục | Lệnh | Kết quả |
|---|---|---|
| Bộ test | `pytest -q` | ✅ **290 passed** (~1.6s) |
| Luồng headless | `python -m fleet.loop` | ✅ chạy 10 tick, auto-apply quyết định reroute |
| Bản đồ thực (WORLD=real) | dựng `SimulationController` | ✅ 18 khách hàng · 38 tuyến · 3 xe |
| Đồ thị OSM | `data/hcm_drive.graphml` | ✅ đã có sẵn (73 MB) |
| UI Streamlit | `fleet/ui/app.py` | ✅ parse/import OK |
| Python | `.venv` | 3.12.3 |

> Tất cả phụ thuộc lõi cần cho checkpoint **đã được cài trong `.venv`**
> (streamlit, pydeck, osmnx, networkx, geopandas, ortools, pandas, numpy, pytest).
> Các phụ thuộc node-07 (anthropic, openai, faster-whisper, riva, cuopt) **không
> cần** ở bước này — chúng được lazy-import và mặc định TẮT.

---

## 1. Yêu cầu hệ thống

- Python **3.10+** (đã test với 3.12).
- ~1 GB đĩa trống (đồ thị OSM HCM ~73 MB + thư viện).
- Internet **chỉ cần một lần** nếu bạn muốn tự tải lại đồ thị OSM
  (`scripts/fetch_osm.py`). File `data/hcm_drive.graphml` đã kèm sẵn nên thường
  không cần.

---

## 2. Cài đặt (dùng venv)

### Windows — PowerShell
```powershell
cd d:\hackathon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# Bản đầy đủ cho checkpoint (gồm cả bản đồ: osmnx/networkx/pydeck/geopandas)
pip install -r requirements.lock.txt
```

### Linux / macOS — bash
```bash
cd /đường/dẫn/hackathon
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.lock.txt
```

> **Vì sao `requirements.lock.txt`?** File `requirements.txt` để các deps bản đồ
> (osmnx/networkx/pydeck) ở dạng *tùy chọn, comment*. Bản `.lock` là ảnh chụp đầy
> đủ của venv đã chạy được — dùng nó để tái lập **chính xác** môi trường checkpoint
> (đủ cả phần bản đồ tích hợp). Nếu chỉ muốn chạy lõi headless + test, có thể dùng
> `pip install -r requirements.txt`.

**Quan trọng:** sau khi tạo venv, **mọi lệnh phải chạy trong venv đã activate**.
Nếu không activate, gọi trực tiếp:
- Windows: `.\.venv\Scripts\python.exe -m pytest`
- Linux/macOS: `./.venv/bin/python -m pytest`

---

## 3. Chạy

> Các lệnh dưới giả định **đã activate venv** (thấy `(.venv)` ở đầu dòng lệnh).

### 3.1. Chạy test (kiểm tra luồng)
```powershell
pytest -q            # nhanh, kỳ vọng: 290 passed
pytest -v            # chi tiết từng test
```

### 3.2. Chạy luồng headless (không UI)
```powershell
python -m fleet.loop
```
In ra mỗi tick: sự kiện đang hoạt động, quyết định được auto-apply/đưa vào hàng
đợi duyệt.

### 3.3. Chạy UI Streamlit — bản đồ mẫu (sample)
```powershell
streamlit run fleet/ui/app.py
```
Mở trình duyệt ở địa chỉ Streamlit in ra (mặc định http://localhost:8501).
Có: nút Step/Reset, bản đồ, hàng đợi duyệt quyết định, panel báo cáo sự cố.

### 3.4. Chạy UI với **bản đồ thực HCM** (WORLD=real)
```powershell
# PowerShell
$env:WORLD = "real"
streamlit run fleet/ui/app.py
```
```bash
# bash
WORLD=real streamlit run fleet/ui/app.py
```
Dùng đồ thị OSM thật trong `data/hcm_drive.graphml` (depot + ~18 khách hàng HCM,
tuyến đường định tuyến thật). Nếu thiếu file đồ thị hoặc osmnx, hệ thống **tự
fallback về bản đồ mẫu** (không crash).

---

## 4. Cấu hình (biến môi trường)

Mặc định chạy **không cần GPU, không cần API key**. Các biến thường dùng:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `WORLD` | `sample` | `sample` \| `real` (bản đồ OSM thật) |
| `ROUTING_ENGINE` | `cpu` | `cpu` (OR-Tools) \| `cuopt` (GPU, node-07) |
| `DECISION_ENGINE` | `rule` | `rule` \| `scoring` \| `claude` \| `nim` |
| `DETECTOR_ENGINE` | `rule` | `rule` \| `zscore` \| `residual` \| `cusum` \| `layered` |
| `FORECASTER_ENGINE` | `ewma` | `ewma` \| `holt` |
| `SEED` | `42` | seed mô phỏng |
| `TICK_MINUTES` | `5` | phút/tick |

Đặt biến (PowerShell): `$env:DECISION_ENGINE = "scoring"`.
Danh sách đầy đủ: xem [config/settings.py](config/settings.py).

---

## 5. Phần node-07 (KHÔNG chạy ở checkpoint — chỉ để tham khảo)

Các tính năng cần máy ban tổ chức (GPU / model phục vụ). Mặc định đều TẮT và được
lazy-import nên **không cài cũng không ảnh hưởng** việc test hiện tại.

| Tính năng | Bật khi | Cần cài thêm |
|---|---|---|
| Solver GPU cuOpt | `ROUTING_ENGINE=cuopt` + `CUOPT_ENDPOINT` | `cuopt-sh-client` |
| Quyết định LLM Claude | `DECISION_ENGINE=claude` + `ANTHROPIC_API_KEY` | `anthropic` |
| Quyết định LLM NIM | `DECISION_ENGINE=nim` + `NIM_ENDPOINT` | `openai` |
| ASR giọng nói (báo sự cố) | `ASR_ENGINE=whisper`/`riva` | `faster-whisper` / `nvidia-riva-client` |

Khi tới node-07, cài bổ sung vào venv, ví dụ:
```powershell
pip install anthropic openai faster-whisper
```
Sinh dataset/train trên node-07 nên gọi Python trong venv trực tiếp, ví dụ:
```bash
./.venv/bin/python -m scripts.gen_dataset --seeds 500 --out data/sovereign-brain --consequential --workers 4 --dataset-routing-engine cpu --consequential-horizon-min 60
```
Chi tiết vận hành node-07: xem
[docs/superpowers/runbooks/2026-06-08-real-map-world-runbook.md](docs/superpowers/runbooks/2026-06-08-real-map-world-runbook.md)
và [docs/runbooks/](docs/runbooks/).

---

## 6. (Tùy chọn) Tải lại đồ thị OSM

Chỉ cần khi muốn dựng lại `data/hcm_drive.graphml` (đã kèm sẵn). Bước **duy nhất
cần internet**:
```powershell
python scripts/fetch_osm.py
```

---

## 7. Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `ModuleNotFoundError` | Chưa activate venv hoặc chưa `pip install -r requirements.lock.txt` |
| `streamlit` không nhận lệnh | Chạy `python -m streamlit run fleet/ui/app.py` trong venv |
| Activate.ps1 bị chặn (Windows) | `Set-ExecutionPolicy -Scope Process RemoteSigned` rồi activate lại |
| WORLD=real ra bản đồ mẫu | Thiếu/ hỏng `data/hcm_drive.graphml` → chạy `scripts/fetch_osm.py` |
| Test fail vì cache cũ | Xóa `.pytest_cache/`, `.mypy_cache/` rồi chạy lại |

---

## 8. Lưu ý bảo mật

- File `.env` chứa `ANTHROPIC_API_KEY` và **đã được `.gitignore`** (không commit).
  Khi chia sẻ code cho mọi người, **đừng gửi kèm `.env`**; mỗi người tự tạo key
  riêng nếu cần phần Claude (không cần cho checkpoint).
- `data/*.graphml` và `cache/` cũng nằm trong `.gitignore` (tái tạo được).
