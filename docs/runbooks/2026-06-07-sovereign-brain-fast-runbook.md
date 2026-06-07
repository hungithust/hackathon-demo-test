# Sovereign Brain v2 — Runbook nhanh

## 1. Mục tiêu

Runbook này ưu tiên **chạy được, nhìn được, dừng đúng chỗ**. Nó không giả định có AI hỗ trợ debug trên máy ban tổ chức.

## 2. Trạng thái thực tế cần biết trước

- `M-A`, `M-B`, `M-C`, `M-D`, `M-E` đã có code khung.
- Spec M-F ở `docs/superpowers/specs/2026-06-07-sbf-consequential-disruptions-design.md` đã được vá vào code.
- Dataset/train path chuẩn mới là **consequential path**: `scripts.gen_dataset --consequential`.
- Không dùng path cũ làm mặc định nữa. Path cũ chỉ để đối chiếu baseline.
- Vẫn phải chặn bằng gate coverage trước train.

## 3. Chuẩn bị môi trường

```powershell
cd d:\hackathon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Nếu cần NIM / OpenAI SDK / training stack:

```powershell
pip install openai datasets transformers peft trl accelerate torch
```

Nếu cần cuOpt self-hosted client:

```powershell
pip install cuopt-sh-client
```

## 4. File config cần kiểm soát

- App config: `config/settings.py`
- Env local: `.env`
- Dataset output: `data/sovereign-brain/`
- Runtime loop: `fleet/loop.py`
- Oracle grading: `fleet/agent/oracle.py`
- Dataset factory: `fleet/agent/dataset.py`
- NIM agent: `fleet/agent/nim_agent.py`
- cuOpt adapter: `fleet/routing/cuopt_adapter.py`

## 5. Thiết lập env tối thiểu

PowerShell:

```powershell
$env:ROUTING_ENGINE="cpu"
$env:DECISION_ENGINE="rule"
$env:ORACLE_HORIZON_TICKS="12"
$env:ORACLE_MIN_GAP="1.0"
$env:CONSEQUENTIAL_DISRUPTIONS="1"
```

Nếu có cuOpt:

```powershell
$env:ROUTING_ENGINE="cuopt"
$env:CUOPT_ENDPOINT="host:5000"
```

Nếu có NIM:

```powershell
$env:DECISION_ENGINE="nim"
$env:NIM_ENDPOINT="http://host:8000/v1"
$env:NIM_MODEL="nvidia/llama-3.1-nemotron-nano-8b-v1"
```

## 6. Smoke test bắt buộc

```powershell
pytest tests/test_config.py tests/test_oracle.py tests/test_dataset.py tests/test_nim_agent.py tests/test_cuopt_adapter.py -q
```

Nếu chỉ cần chạy headless loop:

```powershell
python -m fleet.loop 2>&1 | Tee-Object -FilePath logs\loop-smoke.log
```

Nếu thư mục `logs` chưa có:

```powershell
mkdir logs -Force
```

## 7. Sinh dataset — mặc định dùng consequential path

```powershell
python -m scripts.gen_dataset --seeds 20 --out data/sovereign-brain --consequential 2>&1 | Tee-Object -FilePath logs\gen-dataset.log
```

## 8. Gate tự động trước train

Lệnh kiểm gate:

```powershell
python -c "import json, pathlib, sys; p=pathlib.Path('logs/gen-dataset.log'); txt=p.read_text(encoding='utf-8'); i=txt.rfind('{'); report=json.loads(txt[i:]); ok=(report.get('consequential') is True and report.get('informative_fraction',0)>=0.60 and len(report.get('event_types',{}))>=4 and report.get('n_train',0)>0 and report.get('n_test',0)>0); print(json.dumps(report, indent=2)); print('GATE=PASS' if ok else 'GATE=FAIL'); sys.exit(0 if ok else 1)"
```

Chỉ đi tiếp nếu:

- `informative_fraction >= 0.60`
- `event_types` có ít nhất `4` loại disruption
- `consequential = true`
- `n_train > 0`
- `n_test > 0`

## 9. Quyết định vận hành sau gate dataset

- Nếu gate **fail**: dừng train; demo runtime bằng `rule`, `scoring`, hoặc `nim` base model; không claim “outcome-verified multi-class”.
- Nếu gate **pass**: mới chạy train/eval.

## 10. Train nhanh

```powershell
python -m scripts.train_lora --train data/sovereign-brain/train.jsonl --out data/adapters/sovereign-brain 2>&1 | Tee-Object -FilePath logs\train-lora.log
```

Tuỳ chọn DPO:

```powershell
python -m scripts.gen_dataset --seeds 20 --out data/sovereign-brain --consequential --dpo 2>&1 | Tee-Object -FilePath logs\gen-dataset-dpo.log
python -m scripts.train_dpo --prefs data/sovereign-brain/prefs.jsonl --adapter data/adapters/sovereign-brain --out data/adapters/sovereign-brain-dpo 2>&1 | Tee-Object -FilePath logs\train-dpo.log
```

## 11. Eval nhanh

Offline + online baseline:

```powershell
python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl --ticks 24 2>&1 | Tee-Object -FilePath logs\eval-baseline.log
```

Nếu có NIM endpoint:

```powershell
python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl --ticks 24 --nim-endpoint $env:NIM_ENDPOINT 2>&1 | Tee-Object -FilePath logs\eval-nim.log
```

## 12. Kiểm soát log

- Loop log: `logs\loop-smoke.log`
- Dataset log: `logs\gen-dataset.log`
- Dataset DPO log: `logs\gen-dataset-dpo.log`
- LoRA log: `logs\train-lora.log`
- DPO log: `logs\train-dpo.log`
- Eval log: `logs\eval-baseline.log`, `logs\eval-nim.log`

Tất cả lệnh vận hành nên chạy qua `Tee-Object` để vừa xem console vừa lưu file.

## 13. Gate cứng cho demo

- `python -m fleet.loop` chạy hết mà không crash
- Nếu dùng `ROUTING_ENGINE=cuopt`, endpoint cuOpt phải reachable
- Nếu dùng `DECISION_ENGINE=nim`, endpoint NIM phải trả JSON hợp lệ
- Dataset gate phải pass thì mới được nói tới train/eval oracle đa lớp
- Dataset dùng cho train phải được sinh bằng `--consequential`

## 14. Flow chuẩn đã chuẩn hóa

- Runtime smoke
- `gen_dataset --consequential`
- gate tự động
- train LoRA
- sinh `prefs.jsonl` bằng `--consequential --dpo`
- train DPO nếu cần
- eval
