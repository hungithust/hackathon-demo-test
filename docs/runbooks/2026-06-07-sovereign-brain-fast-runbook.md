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

Lưu ý trước khi chạy:

- Không commit `.env`.
- Nếu log được chia sẻ ra ngoài, không in `ANTHROPIC_API_KEY`.
- Nên tạo venv mới để tránh lệch dependency giữa máy dev và máy ban tổ chức.

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

Lưu ý trước khi set env:

- `CONSEQUENTIAL_DISRUPTIONS=1` là mặc định vận hành mới cho dataset/train.
- `DECISION_ENGINE=nim` chỉ set khi endpoint NIM đã sống.
- `ROUTING_ENGINE=cuopt` chỉ set khi endpoint cuOpt đã sống; nếu endpoint lỗi mà vẫn ép `cuopt`, runtime có thể fail.

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

Lưu ý trước khi smoke:

- Chạy smoke trước khi sinh dataset hoặc train.
- Nếu smoke fail, không đi tiếp sang dataset/train.
- Nên tạo `logs\` trước để không mất output chẩn đoán.

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

Lưu ý trước khi sinh dataset:

- Không dùng path baseline cho train chính thức.
- Kết quả probe nhỏ đã tốt, nhưng vẫn phải kiểm gate trên dataset thực tế vừa sinh.
- Nếu định train DPO, vẫn phải sinh lại bằng `--consequential --dpo`.

```powershell
python -m scripts.gen_dataset --seeds 20 --out data/sovereign-brain --consequential 2>&1 | Tee-Object -FilePath logs\gen-dataset.log
```

## 8. Gate tự động trước train

Lưu ý trước khi chạy gate:

- Gate fail thì dừng train ngay.
- Không “đọc cảm tính” report; dùng exit code của lệnh gate.
- Gate này cũng chặn trường hợp dùng nhầm baseline dataset.

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

Lưu ý trước khi train LoRA:

- Chỉ train sau khi gate pass.
- Dataset train chuẩn phải đến từ `--consequential`.
- Nếu chạy trên máy GPU chung, luôn lưu log qua `Tee-Object`.

```powershell
python -m scripts.train_lora --train data/sovereign-brain/train.jsonl --out data/adapters/sovereign-brain 2>&1 | Tee-Object -FilePath logs\train-lora.log
```

Tuỳ chọn DPO:

Lưu ý trước khi chạy DPO:

- DPO chỉ có ý nghĩa nếu SFT dataset đã pass gate.
- `prefs.jsonl` phải được sinh lại bằng `--consequential --dpo`, không dùng file cũ.

```powershell
python -m scripts.gen_dataset --seeds 20 --out data/sovereign-brain --consequential --dpo 2>&1 | Tee-Object -FilePath logs\gen-dataset-dpo.log
python -m scripts.train_dpo --prefs data/sovereign-brain/prefs.jsonl --adapter data/adapters/sovereign-brain --out data/adapters/sovereign-brain-dpo 2>&1 | Tee-Object -FilePath logs\train-dpo.log
```

## 11. Eval nhanh

Lưu ý trước khi eval:

- Eval chỉ đáng tin nếu `test.jsonl` đến từ consequential dataset.
- Nếu NIM endpoint lỗi, eval NIM có thể rơi về fallback hoặc fail transport.
- Baseline eval chỉ để đối chiếu, không phải bằng chứng duy nhất cho chất lượng fine-tune.

Offline + online baseline:

```powershell
python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl --ticks 24 2>&1 | Tee-Object -FilePath logs\eval-baseline.log
```

Nếu có NIM endpoint:

```powershell
python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl --ticks 24 --nim-endpoint $env:NIM_ENDPOINT 2>&1 | Tee-Object -FilePath logs\eval-nim.log
```

## 11b. Voice intake demo (tùy chọn, mặc định TẮT)

Báo cáo sự cố bằng giọng nói/văn bản → tiêm `Event` vào world đang chạy. Chi tiết
đầy đủ ở runbook kỹ thuật **Mục 16**.

Lưu ý trước khi bật:

- Mặc định TẮT: không set `ASR_ENGINE`/`NIM_ENDPOINT` thì panel chỉ dùng ô gõ text.
- Suite test không import `streamlit/torch/whisper/openai/riva`; chỉ cần khi chạy live.
- Extractor `nim` tái dùng đúng `NIM_ENDPOINT` ở mục 5.

Smoke không cần model:

```powershell
pytest tests/test_intake_resolver.py tests/test_intake_extractor.py tests/test_intake_asr.py tests/test_intake_controller.py -q
```

Chạy live text-only (an toàn nhất):

```powershell
$env:DECISION_ENGINE="nim"
$env:NIM_ENDPOINT="http://host:8000/v1"
python -m streamlit run fleet/ui/app.py --server.port 8501
```

Có giọng nói (Whisper self-host):

```powershell
$env:ASR_ENGINE="whisper"
$env:WHISPER_MODEL="large-v3"
python -m streamlit run fleet/ui/app.py --server.port 8501
```

Panel "Báo cáo sự cố": gõ `kho C001 het hang` → **Bóc tách & xử lý** → thấy report
được tiêm + thẻ quyết định. Không có transport thì panel báo lỗi rõ ràng (degrade OK).

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
