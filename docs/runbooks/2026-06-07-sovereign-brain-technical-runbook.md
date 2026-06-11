# Sovereign Brain v2 — Runbook kỹ thuật chi tiết

## 1. Mục tiêu vận hành

Runbook này dành cho người trực máy cần kiểm soát:

- config thực dùng
- log đầu ra từng pha
- endpoint cuOpt / NIM
- điều kiện dừng trước khi train
- tác động thực tế của lỗi oracle M-F

## 2. Snapshot kiến trúc đang có trong repo

### 2.1 Runtime path

- `fleet/factory.py`: chọn optimizer + decision engine theo env
- `fleet/loop.py`: orchestration tick/detect/decide/approve/apply/reroute
- `fleet/routing/cuopt_adapter.py`: cuOpt transport
- `fleet/agent/nim_agent.py`: NIM transport + fallback rule-based

### 2.2 Offline path cho Sovereign Brain v2

- `fleet/agent/oracle.py`: `roll_forward()`, `realized_cost()`, `best_action()`
- `fleet/agent/dataset.py`: `make_example()`, `iter_examples()`, `grade_full()`, `make_disrupted_example()`, `iter_disrupted_examples()`, `grade_disrupted()`
- `scripts/gen_dataset.py`: JSONL train/test/prefs
- `scripts/train_lora.py`: SFT LoRA
- `scripts/train_dpo.py`: DPO từ prefs
- `scripts/eval_brain.py`: offline + online eval

### 2.3 Trạng thái M-F hiện tại

Spec `docs/superpowers/specs/2026-06-07-sbf-consequential-disruptions-design.md` đã được wired vào repo với:

- `enable_travel_time`
- `WorldSimulator.advance_only`
- `roll_forward(..., freeze_world=True)`
- `make_disrupted_example()`
- `grade_disrupted()`
- path `--consequential` trong `gen_dataset`

Trace triển khai và số đo hiện tại nằm ở `docs/superpowers/notes/2026-06-07-m-f-implementation-trace.md`.

## 3. Config map

### 3.1 Config hiện hữu trong `Settings`

Các biến đang có và thực sự được code đọc:

- `ROUTING_ENGINE=cpu|cuopt`
- `DECISION_ENGINE=rule|claude|scoring|nim`
- `CUOPT_ENDPOINT`
- `ANTHROPIC_API_KEY`
- `NIM_ENDPOINT`
- `NIM_MODEL`
- `ORACLE_HORIZON_TICKS`
- `CONSEQUENTIAL_MIN_HORIZON_TICKS`
- `ORACLE_MIN_GAP`
- `ENABLE_TRAVEL_TIME`

### 3.2 Config vận hành chuẩn

- `ENABLE_TRAVEL_TIME` không cần bật tay khi chạy `--consequential`; grading path tự bật trên clone.
- `CONSEQUENTIAL_DISRUPTIONS=1` có thể dùng để ép `scripts.gen_dataset` chạy path mới ngay cả khi quên cờ CLI.
- `advance_only` là cờ nội bộ grading, không phải env public.
- `CONSEQUENTIAL_MIN_HORIZON_TICKS` là knob mới cho consequential grading; mặc định `60`.
- `scripts.gen_dataset` có CLI mới: `--workers`, `--dataset-routing-engine`, `--consequential-horizon-min`.

## 4. Root cause kỹ thuật của lỗi oracle cũ

### 4.1 Movement hiện tại không phụ thuộc road disruption

`fleet/simulator/engine.py` dùng `_advance_vehicles()` theo `planned_arrival <= state.clock`. Nó không replay theo live graph. Vì vậy:

- edge blocked/flooded/congested có thể đổi matrix khi replan
- nhưng nếu không re-solve đúng cách hoặc stop đã schedule sẵn, actual movement vẫn rất “cứng”

### 4.2 `inject_event()` chỉ thêm event, không làm thế giới bị thương

`make_example()` trong `fleet/agent/dataset.py` gọi `sim.inject_event(...)`. Hàm này chỉ append `Event` vào `state.events`. Nó **không**:

- block edge
- break vehicle
- spike demand
- siết time window

Do đó phần lớn examples không tạo trade-off thật.

### 4.3 Oracle grading chưa freeze ngoại sinh

`roll_forward()` trong `fleet/agent/oracle.py` tick simulator bình thường. Mỗi tick vẫn:

- generate demand mới
- restock
- update shortage
- update weather nếu bật

Nên realized cost có thể bị order churn chi phối, thay vì phản ánh khác biệt hành động.

### 4.4 Dataset path cũ là M-B baseline

`scripts/gen_dataset.py` đang dùng:

- `iter_examples()`
- `grade_full()`
- `is_informative()`

Nhánh này vẫn còn để đối chiếu baseline, nhưng **không còn là path train chuẩn**.

## 5. Trạng thái sau khi vá

- Oracle consequential path đã usable cho training signal.
- Probe nhỏ hiện đạt `6/6` event types informative trong trace ngày `2026-06-07`.
- Path baseline vẫn tồn tại nhưng chỉ để so sánh, không dùng làm dataset train chuẩn.

## 6. Checklist trước khi chạy

### 6.1 Môi trường

Lưu ý trước khi chuẩn bị môi trường:

- Không commit `.env`.
- Không in `ANTHROPIC_API_KEY` vào log hoặc screenshot.
- Nếu máy đã dùng chung nhiều project Python, ưu tiên venv sạch.

```powershell
cd d:\hackathon
.\.venv\Scripts\Activate.ps1
python --version
pip show ortools
```

Linux / node-07:

```bash
cd /raid/team/hackathon-demo-test
source .venv/bin/activate
python --version
pip show ortools
```

Nếu không activate, dùng trực tiếp `./.venv/bin/python`.

Nếu dùng NIM:

```powershell
pip show openai
```

Nếu dùng cuOpt:

```powershell
pip show cuopt-sh-client
```

Nếu train:

```powershell
pip show torch transformers datasets peft trl accelerate
```

### 6.2 Tạo thư mục log

Lưu ý trước khi tạo log/output:

- Toàn bộ lệnh vận hành nên ghi log bằng `Tee-Object`.
- Tách riêng log dataset, train, DPO, eval để dễ đối chiếu sau sự cố.

```powershell
mkdir logs -Force
mkdir data\sovereign-brain -Force
mkdir data\adapters -Force
```

## 7. Runtime smoke path

### 7.1 CPU + rule path an toàn nhất

Lưu ý:

- Đây là smoke path an toàn nhất khi cần xác nhận loop còn sống.
- Nếu path này fail, không nên thử cuOpt/NIM trước khi sửa.

```powershell
$env:ROUTING_ENGINE="cpu"
$env:DECISION_ENGINE="rule"
python -m fleet.loop 2>&1 | Tee-Object -FilePath logs\runtime-cpu-rule.log
```

Kỳ vọng:

- có log `AUTO-APPLIED` hoặc `QUEUED(approval)`
- không crash import

### 7.2 cuOpt path

Lưu ý:

- Chỉ chuyển sang path này khi `cpu + rule` đã chạy ổn.
- Nếu `CUOPT_ENDPOINT` có giá trị nhưng endpoint chết, runtime có thể văng exception.
- Test cuOpt sớm trước demo, không để tới phút cuối.

```powershell
$env:ROUTING_ENGINE="cuopt"
$env:CUOPT_ENDPOINT="host:5000"
python -m fleet.loop 2>&1 | Tee-Object -FilePath logs\runtime-cuopt.log
```

Nếu endpoint sai, `build_components()` sẽ fallback CPU **chỉ khi** `CUOPT_ENDPOINT` rỗng. Nếu endpoint có giá trị nhưng cuOpt transport fail khi solve, runtime có thể văng exception. Vì vậy cần test riêng trước demo.

### 7.3 NIM path

Lưu ý:

- Chỉ chuyển sang path này khi `cpu + rule` đã chạy ổn.
- `NIM_ENDPOINT` và `NIM_MODEL` phải khớp server thật.
- Nếu transport/parse fail, agent có thể fallback rule-based; cần đọc log để xác nhận.

```powershell
$env:DECISION_ENGINE="nim"
$env:NIM_ENDPOINT="http://host:8000/v1"
$env:NIM_MODEL="nvidia/llama-3.1-nemotron-nano-8b-v1"
python -m fleet.loop 2>&1 | Tee-Object -FilePath logs\runtime-nim.log
```

Nếu NIM hỏng:

- per-event fallback sang rule-based
- log loop vẫn tiếp tục
- nhưng cần đọc decision output để xác nhận đang fallback

## 8. Dataset generation path chuẩn

### 8.1 Env chuẩn

Lưu ý:

- `CONSEQUENTIAL_DISRUPTIONS=1` là mặc định chuẩn cho dataset/train.
- `ENABLE_TRAVEL_TIME` không cần bật tay cho path này.

```powershell
$env:ORACLE_HORIZON_TICKS="12"
$env:CONSEQUENTIAL_MIN_HORIZON_TICKS="60"
$env:ORACLE_MIN_GAP="1.0"
$env:CONSEQUENTIAL_DISRUPTIONS="1"
```

### 8.2 Lệnh sinh dataset chuẩn

Lưu ý:

- Không dùng baseline path để sinh dataset train chính thức.
- `--consequential` là bắt buộc cho train/eval oracle đa lớp.
- Nếu chạy lại nhiều lần, nên đổi thư mục output hoặc xoá có chủ đích để tránh đọc nhầm file cũ.
- Sau bản vá tăng tốc, ưu tiên chạy dataset offline bằng CPU: `--dataset-routing-engine cpu`.
- `1 seed = 6 examples`; muốn ~`3000` samples thì dùng `--seeds 500`.

```powershell
.\.venv\Scripts\python.exe -m scripts.gen_dataset --seeds 500 --out data/sovereign-brain --consequential --workers 4 --dataset-routing-engine cpu --consequential-horizon-min 60 2>&1 | Tee-Object -FilePath logs\gen-dataset.log
```

```bash
./.venv/bin/python -m scripts.gen_dataset --seeds 500 --out data/sovereign-brain --consequential --workers 4 --dataset-routing-engine cpu --consequential-horizon-min 60 2>&1 | tee logs/gen-dataset.log
```

### 8.2b Benchmark / regression check trên node-07

Lưu ý:

- Chạy benchmark sau khi pull code mới nếu nghi dataset lại chậm bất thường.
- Luôn kiểm tra `routing_engine` ở cuối report; nếu hiện `cuopt`, nghĩa là đang benchmark sai path.
- `workers=1` dùng để đo baseline; `workers=4` là cấu hình thực tế đã đo tốt.

```bash
mkdir -p logs
/usr/bin/time -f '%E real' ./.venv/bin/python -m scripts.gen_dataset --seeds 100 --out data/bench-100 --consequential --workers 1 --dataset-routing-engine cpu --consequential-horizon-min 60 2>&1 | tee logs/gen-100.log
/usr/bin/time -f '%E real' ./.venv/bin/python -m scripts.gen_dataset --seeds 500 --out data/bench-500-w4 --consequential --workers 4 --dataset-routing-engine cpu --consequential-horizon-min 60 2>&1 | tee logs/gen-500-w4.log
```

Tham chiếu đã đo trên `node-07` sau bản vá:

- `100` seeds → `600` samples trong khoảng `8.58s`
- `500` seeds + `workers=4` → `3000` samples trong khoảng `13.00s`

### 8.3 Gate bắt buộc

Lưu ý:

- Gate fail thì dừng ngay, không sửa bằng cách hạ ngưỡng.
- Dùng lệnh gate thay vì đọc tay report để tránh bỏ sót `consequential=true`.
- Gate này là hàng rào cuối trước khi đốt thời gian GPU.

Lệnh gate tự động:

```powershell
.\.venv\Scripts\python.exe -c "import json, pathlib, sys; p=pathlib.Path('logs/gen-dataset.log'); txt=p.read_text(encoding='utf-8'); i=txt.rfind('{'); report=json.loads(txt[i:]); checks={'consequential': report.get('consequential') is True, 'informative_fraction': report.get('informative_fraction',0)>=0.60, 'event_types': len(report.get('event_types',{}))>=4, 'n_train': report.get('n_train',0)>0, 'n_test': report.get('n_test',0)>0}; print(json.dumps({'report':report,'checks':checks}, indent=2)); ok=all(checks.values()); print('GATE=PASS' if ok else 'GATE=FAIL'); sys.exit(0 if ok else 1)"
```

```bash
./.venv/bin/python -c "import json, pathlib, sys; p=pathlib.Path('logs/gen-dataset.log'); txt=p.read_text(encoding='utf-8'); i=txt.rfind('{'); report=json.loads(txt[i:]); checks={'consequential': report.get('consequential') is True, 'informative_fraction': report.get('informative_fraction',0)>=0.60, 'event_types': len(report.get('event_types',{}))>=4, 'n_train': report.get('n_train',0)>0, 'n_test': report.get('n_test',0)>0}; print(json.dumps({'report':report,'checks':checks}, indent=2)); ok=all(checks.values()); print('GATE=PASS' if ok else 'GATE=FAIL'); sys.exit(0 if ok else 1)"
```

Đi tiếp chỉ khi:

- `informative_fraction >= 0.60`
- `event_types` có ít nhất `4` event types
- `consequential = true`
- `n_train > 0`
- `n_test > 0`

Nếu không đạt, **không chạy train**.

## 9. Train path

### 9.1 LoRA

Lưu ý:

- Chỉ train sau khi gate pass.
- Fine-tune đã “đủ tốt để bắt đầu”, nhưng vẫn phụ thuộc dataset thực tế vừa sinh chứ không phải probe nhỏ.
- Nếu máy GPU dùng chung, theo dõi dung lượng và checkpoint output ngay từ đầu.

```powershell
.\.venv\Scripts\python.exe -m scripts.train_lora --train data/sovereign-brain/train.jsonl --out data/adapters/sovereign-brain 2>&1 | Tee-Object -FilePath logs\train-lora.log
```

Theo dõi:

- log step/loss trong console
- artifact output trong `data/adapters/sovereign-brain`

### 9.2 DPO

Lưu ý:

- DPO không cứu được một dataset SFT kém; chỉ chạy sau khi gate pass.
- `prefs.jsonl` phải được regen từ consequential path cùng cấu hình hiện hành.

```powershell
.\.venv\Scripts\python.exe -m scripts.gen_dataset --seeds 500 --out data/sovereign-brain --consequential --dpo --workers 4 --dataset-routing-engine cpu --consequential-horizon-min 60 2>&1 | Tee-Object -FilePath logs\gen-dataset-dpo.log
.\.venv\Scripts\python.exe -m scripts.train_dpo --prefs data/sovereign-brain/prefs.jsonl --adapter data/adapters/sovereign-brain --out data/adapters/sovereign-brain-dpo 2>&1 | Tee-Object -FilePath logs\train-dpo.log
```

Chỉ chạy DPO nếu dataset gate đã pass. Nếu không, preference pairs sẽ vô nghĩa.

## 10. Eval path

### 10.1 Baseline eval

Lưu ý:

- Eval baseline chỉ để đối chiếu.
- Không dùng baseline eval một mình để kết luận chất lượng oracle multi-class.

```powershell
python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl --ticks 24 2>&1 | Tee-Object -FilePath logs\eval-baseline.log
```

### 10.2 Eval với NIM

Lưu ý:

- Eval NIM chỉ có ý nghĩa khi model endpoint đúng và không fallback âm thầm.
- Nếu nghi ngờ fallback, kiểm tra log decision engine trước khi đọc metric.

```powershell
python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl --ticks 24 --nim-endpoint $env:NIM_ENDPOINT 2>&1 | Tee-Object -FilePath logs\eval-nim.log
```

Đọc report để kiểm:

- `offline_rule_baseline`
- `offline_nim`
- `online.rule`
- `online.scoring`
- `online.nim`

Nếu lỡ dùng nhầm baseline dataset thay vì consequential dataset, các số này **không chứng minh** multi-class oracle learning.

## 11. API control points

### 11.1 cuOpt

- Config: `CUOPT_ENDPOINT`
- Adapter: `fleet/routing/cuopt_adapter.py`
- Expected format: `host:port`
- Failure mode: transport exception tại `solve()`

Khuyến nghị test sớm:

```powershell
python -c "from config.settings import load_settings; from fleet.factory import build_components; s=load_settings(); print(type(build_components(s).optimizer).__name__)"
```

### 11.2 NIM

- Config: `NIM_ENDPOINT`, `NIM_MODEL`
- Agent: `fleet/agent/nim_agent.py`
- Protocol: OpenAI-compatible `chat.completions.create`
- Structured output: `guided_json` theo `_DECISION_SCHEMA`
- Failure mode: parse fail hoặc transport fail, sau đó fallback rule-based

Khuyến nghị test sớm:

```powershell
python -c "from config.settings import load_settings; from fleet.factory import build_components; s=load_settings(); print(type(build_components(s).decision_engine).__name__)"
```

## 12. Quản lý secret

`.env` hiện có Anthropic key. Điều này cần lưu ý:

- không in key ra log
- không commit lại
- nếu đã chia sẻ máy hoặc log, nên rotate key sau sự kiện

Lưu ý thực thi:

- Các bước đọc log, chụp ảnh màn hình, hoặc gửi file log phải kiểm tra xem có lộ secret không.
- Nếu key đã xuất hiện trong lịch sử chia sẻ, coi như đã lộ và nên rotate.

## 13. Ghi chú chất lượng sau khi vá

- Consequential path hiện đã đủ để sinh dataset train đa lớp.
- Baseline path vẫn cho `1/6` nếu dùng nhầm, nên gate `consequential=true` là bắt buộc.
- Nếu muốn đối chiếu số đo, dùng trace `docs/superpowers/notes/2026-06-07-m-f-implementation-trace.md`.

## 14. Quy tắc dừng

Dừng ngay và không train nếu một trong các điều kiện sau xảy ra:

- `gen_dataset` ra `informative_fraction < 0.60`
- `event_types` dưới `4` loại
- `consequential != true`
- `test.jsonl` trống hoặc quá ít
- NIM chỉ toàn fallback rule-based
- cuOpt endpoint không ổn định

## 15. Kết luận vận hành

- Repo hiện tại đủ cho runtime path và consequential oracle training path.
- Flow chuẩn cần tuân thủ là:
  1. smoke runtime
  2. kiểm endpoint cuOpt/NIM
  3. `gen_dataset --consequential`
  4. chạy gate tự động
  5. train LoRA
  6. sinh `prefs.jsonl` bằng `--consequential --dpo` nếu cần DPO
  7. eval

## 16. Voice Disruption Intake — vận hành trên node-07

Tính năng intake (`fleet/intake/`) biến một báo cáo sự cố **nói hoặc gõ** thành
`Event` được tiêm vào world đang chạy, để pipeline detect→decide→reroute phản ứng
ngay trên màn hình. Phần này dành cho người trực node-07 chạy bản **live**.

### 16.1 Nguyên tắc bất biến

- Tính năng **mặc định TẮT**: không có `ASR_ENGINE`/`NIM_ENDPOINT` thì hệ chạy y
  như cũ, `build_transcriber` trả `NullTranscriber` (chỉ ô gõ text dùng được).
- Suite test **không** import `streamlit/torch/whisper/openai/riva`; mọi transport
  (ASR + extractor) đều lazy-import, chỉ nạp khi thực sự bật.
- Không đổi chữ ký `inject_event` / `disrupt_edge` / `run_loop`.
- Edge event (`traffic`, `flooded_area`) đi qua `disrupt_edge` (đổi ma trận
  routing thật); node/vehicle event đi qua `inject_event`.

### 16.2 Kiểm tra tài nguyên trước khi chạy live (non-blocking cho text path)

- Riva ASR NIM: xác nhận có thể pull được image; nếu không, giữ `ASR_ENGINE=whisper`.
- `faster-whisper` kéo được `large-v3` về `/raid` (cache model).
- Mở được một web port để demo Streamlit.
- Toàn bộ suite và path **text-only** không cần bất kỳ thứ nào ở trên.

### 16.3 Cài optional deps (chỉ khi bật live)

```bash
# extractor transport (NIM OpenAI-compatible) — thường đã có sẵn từ NIM path
pip install openai
# ASR self-host (khuyến nghị, tiếng Việt khỏe, không cần entitlement NGC)
pip install faster-whisper
# ASR premium qua Riva NIM (tùy chọn)
pip install nvidia-riva-client
```

### 16.4 Env vars

| Var | Giá trị | Ý nghĩa |
|-----|---------|---------|
| `ASR_ENGINE` | `none` (mặc định) \| `whisper` \| `riva` | chọn engine audio→text |
| `WHISPER_MODEL` | `large-v3` (mặc định) | model id cho faster-whisper |
| `RIVA_ENDPOINT` | vd `localhost:50051` | endpoint Riva ASR NIM |
| `INTAKE_EXTRACTOR` | `nim` (mặc định) \| `claude` | transport bóc tách event |
| `NIM_ENDPOINT` | vd `http://localhost:8000/v1` | tái dùng cho extractor khi `nim` |
| `NIM_MODEL` | `nvidia/llama-3.1-nemotron-nano-8b-v1` | model NIM phục vụ |

Extractor `nim` tái dùng đúng endpoint Nemotron NIM đã deploy ở mục 7.3 — không
cần dựng thêm dịch vụ.

### 16.5 Chạy live (text-only — an toàn nhất, không cần ASR)

```bash
DECISION_ENGINE=nim \
NIM_ENDPOINT=http://localhost:8000/v1 \
python -m streamlit run fleet/ui/app.py --server.port 8501
```

Trong panel "Báo cáo sự cố", gõ `kho C001 het hang` → bấm **Bóc tách & xử lý**:
phải thấy transcript/echo, report được tiêm, và một thẻ quyết định
(`action` + mô tả + phút trễ). Nếu chưa cấu hình transport, panel báo lỗi rõ
ràng — đây là degrade-gracefully đúng thiết kế.

### 16.6 Chạy live có giọng nói (Whisper self-host)

```bash
ASR_ENGINE=whisper \
WHISPER_MODEL=large-v3 \
DECISION_ENGINE=nim \
NIM_ENDPOINT=http://localhost:8000/v1 \
python -m streamlit run fleet/ui/app.py --server.port 8501
```

Dùng mic (`st.audio_input`) hoặc upload file `wav/mp3/m4a`. Lần đầu sẽ tải model
`large-v3` về cache (chậm); các lần sau nhanh. Nếu muốn ASR premium:
`ASR_ENGINE=riva RIVA_ENDPOINT=localhost:50051`.

### 16.7 Smoke không cần model (xác nhận code path trước khi bật live)

```bash
python -m pytest -q tests/test_intake_resolver.py tests/test_intake_extractor.py \
  tests/test_intake_asr.py tests/test_intake_controller.py tests/test_factory.py
```

Phải xanh và **không** kéo theo `streamlit/torch/whisper/openai/riva`.

### 16.8 Quy tắc dừng cho intake

Dừng và quay lại text-only path nếu:

- Whisper không tải được `large-v3` hoặc OOM GPU → `ASR_ENGINE=whisper` thất bại.
- Riva NIM không pull/khởi động được → bỏ `riva`, dùng `whisper` hoặc text.
- Extractor toàn trả rỗng/`reports=[]` → kiểm `NIM_ENDPOINT`/`NIM_MODEL` khớp
  server, vì parse fail bị nuốt và trả `IntakeResult` rỗng (không crash).
