# Kiến trúc hệ thống — Fleet Optimizer + Sovereign Brain v2

> Tài liệu này mô tả **toàn bộ hệ thống ở mức kiến trúc và module** cho người đã biết một chút về tech.
> Mục tiêu là hiểu hệ thống gồm những khối nào, chúng nối với nhau ra sao, cấu hình ở đâu, và đường chạy nào dùng cho demo / train / eval.
> Tài liệu này **không** đi vào từng hàm hay từng dòng code; chỉ nhắc tới **class** và **script** ở những điểm quan trọng.

---

## 1. Hệ thống này làm gì?

Đây là một hệ thống tối ưu điều phối giao hàng thời gian thực cho mô hình:

- **1 kho trung tâm** (`Depot`)
- **nhiều xe** (`Vehicle`)
- **nhiều khách hàng** có đơn, khung giờ phục vụ và mức ưu tiên (`CustomerProfile`)
- **mạng lưới đường** có thể bị tắc, ngập, chặn (`RoadGraph`, `RoadEdge`)

Ở mức business, hệ thống làm 4 việc:

1. mô phỏng thế giới giao hàng đang vận hành
2. phát hiện biến động / disruption
3. ra quyết định điều phối
4. thực thi và đánh giá lại kết quả

Ngoài runtime path, repo còn có một offline pipeline tên **Sovereign Brain v2** để:

- sinh dataset từ mô phỏng
- gán nhãn bằng oracle
- fine-tune model nội bộ
- serve model qua NIM

Nói ngắn gọn:

- **runtime path** = hệ thống đang chạy để quyết định
- **offline path** = hệ thống tạo dữ liệu và train model để thay thế decision engine bên thứ ba

---

## 2. Hai đường chạy chính

## 2.1 Runtime path

Runtime path là đường dùng khi mô phỏng hoặc demo hệ thống end-to-end:

`WorldSimulator` → `Detector` → `DecisionEngine` → `Approval` → `Dispatcher` → `RouteOptimizer`

Mỗi tick thời gian:

1. simulator cập nhật thế giới
2. detector tìm sự kiện bất thường
3. decision engine sinh quyết định
4. approval gate quyết định tự duyệt hay chờ người duyệt
5. dispatcher áp dụng thay đổi vào state
6. nếu cần, route optimizer giải lại tuyến

File trung tâm của runtime:

- `fleet/loop.py`
- `fleet/factory.py`
- `fleet/contracts/state.py`

## 2.2 Offline Sovereign Brain path

Offline path dùng để tạo dữ liệu và train:

1. dựng nhiều tình huống mô phỏng
2. tạo disruption có hậu quả thật trong world
3. oracle grade các action candidate bằng roll-forward
4. giữ action tốt nhất làm ground truth
5. xuất `train.jsonl`, `test.jsonl`, `prefs.jsonl`
6. fine-tune LoRA / DPO
7. eval offline + online

File trung tâm của offline path:

- `fleet/agent/oracle.py`
- `fleet/agent/dataset.py`
- `scripts/gen_dataset.py`
- `scripts/train_lora.py`
- `scripts/train_dpo.py`
- `scripts/eval_brain.py`

---

## 3. Mô hình lõi của hệ thống

Toàn hệ thống xoay quanh một state duy nhất: `WorldState`.

`WorldState` là nguồn sự thật chung cho:

- simulator
- detector
- routing
- decision engine
- UI
- eval

Các thành phần không trao đổi trực tiếp với nhau bằng object riêng lẻ; chúng chủ yếu:

- đọc `WorldState`
- ghi ngược thay đổi vào `WorldState`

Class quan trọng trong `fleet/contracts/state.py`:

- `WorldState`: snapshot tổng
- `Depot`: kho và tồn kho
- `Vehicle`: xe, trạng thái, loại xe, khả năng lội nước
- `CustomerProfile`: khách hàng, đơn hàng, time window, priority
- `RoadGraph`, `RoadEdge`, `RoadNode`: đồ thị đường
- `Event`: disruption / anomaly
- `Decision`: quyết định điều phối
- `VehicleRoute`, `Stop`: tuyến đã giải

Điểm quan trọng về mặt kiến trúc:

- state model đủ giàu để dùng cho cả **simulation**, **routing**, **agent**, **UI**, và **dataset generation**
- các enum như `EventType`, `DecisionAction`, `VehicleStatus`, `EdgeStatus` tạo ra “ngôn ngữ chung” cho toàn repo

---

## 4. Composition root: nơi chọn engine thật

File `fleet/factory.py` là **composition root**.

Đây là nơi duy nhất chọn implementation thật cho từng interface, dựa trên `Settings`.

Class chính:

- `Components`
- `build_components(settings)`

Những gì `build_components` quyết định:

- chọn optimizer: `CpuSolver` hay `CuOptAdapter`
- chọn decision engine: `RuleBasedEngine`, `ScoringEngine`, `ClaudeAgent`, hay `NimAgent`
- chọn detector: `RuleDetector`, `ZScoreDetector`, `ForecastResidualDetector`, `CusumDetector`, `CompositeDetector`
- chọn forecaster: `EwmaForecaster` hay `HoltWintersForecaster`
- luôn dựng `WorldSimulator` và `Dispatcher`

Ý nghĩa:

- caller như `fleet/loop.py` hay `fleet/ui/controller.py` không cần biết engine cụ thể
- đổi CPU ↔ GPU, rule ↔ LLM, local ↔ hosted chỉ là **đổi config**

---

## 5. Runtime pipeline chi tiết

## 5.1 Simulator

Module: `fleet/simulator/engine.py`

Class chính:

- `WorldSimulator`

Vai trò:

- đẩy đồng hồ mô phỏng theo tick
- sinh thêm nhu cầu
- restock kho
- tạo / đóng shortage events
- cập nhật weather / traffic nếu bật
- di chuyển xe và giao hàng

Hiện simulator có hai mode logic quan trọng:

- **schedule-driven path**: hành vi mặc định
- **travel-time-aware path**: dùng khi grading consequential disruptions trong oracle

Các ý quan trọng:

- `advance_only` là cờ nội bộ dùng cho grading path để **freeze** các yếu tố ngoại sinh
- `enable_travel_time` cho phép movement phản ứng với live road graph thay vì chỉ bám lịch cứng

## 5.2 Detector

Modules:

- `fleet/detection/rules.py`
- `fleet/detection/zscore.py`
- `fleet/detection/forecast_residual.py`
- `fleet/detection/cusum.py`
- `fleet/detection/composite.py`

Các class chính:

- `RuleDetector`
- `ZScoreDetector`
- `ForecastResidualDetector`
- `CusumDetector`
- `CompositeDetector`

Vai trò:

- chuyển trạng thái của thế giới thành `Event`
- tách phần “thế giới đang có gì bất thường” khỏi phần “nên làm gì tiếp theo”

Thiết kế hiện tại có hai tầng:

- tầng rule-based đơn giản, dễ giải thích
- tầng statistical / layered để phát hiện tinh hơn

## 5.3 Decision engine

Modules:

- `fleet/agent/rule_based.py`
- `fleet/agent/scoring_engine.py`
- `fleet/agent/claude_agent.py`
- `fleet/agent/nim_agent.py`

Các class chính:

- `RuleBasedEngine`
- `ScoringEngine`
- `ClaudeAgent`
- `NimAgent`

Vai trò:

- nhận `state + events`
- trả về `List[Decision]`

Ý nghĩa từng engine:

- `RuleBasedEngine`: baseline đơn giản, deterministic
- `ScoringEngine`: policy heuristic có chấm điểm cost
- `ClaudeAgent`: dùng LLM ngoài
- `NimAgent`: dùng model self-hosted qua OpenAI-compatible endpoint

Với `NimAgent` và `ClaudeAgent`, code tách rõ:

- **prompt/build_messages**
- **structured output parsing**
- **transport gọi model**

Thiết kế này giúp test offline và thay transport dễ.

## 5.4 Approval + Dispatcher

Modules:

- `fleet/dispatch/approval.py`
- `fleet/dispatch/dispatcher.py`

Class chính:

- `Dispatcher`

Vai trò:

- quyết định nào được auto-approve
- quyết định nào phải đợi người duyệt
- khi đã duyệt thì áp dụng thay đổi thật vào world

Các action mà dispatcher phải xử lý:

- `reroute`
- `reschedule`
- `reprioritize`
- `reallocate`
- `defer`
- `cancel`
- `accelerate`

Điểm quan trọng:

- không phải action nào cũng tự giải lại tuyến
- `RESOLVE_ACTIONS` xác định action nào phải reroute sau khi apply

## 5.5 Route optimizer

Modules:

- `fleet/routing/matrix.py`
- `fleet/routing/cpu_solver.py`
- `fleet/routing/cuopt_adapter.py`
- `fleet/routing/planner.py`

Class / function chính:

- `CpuSolver`
- `CuOptAdapter`
- `plan_routes`
- `reroute`

Vai trò:

- chuyển `WorldState` thành bài toán routing
- giải VRPTW
- ghi solution trở lại `state.plan`

Hai mode chính:

- `CpuSolver`: local, deterministic, mặc định
- `CuOptAdapter`: GPU/self-hosted, dùng khi có endpoint

Ý nghĩa kiến trúc:

- solver thực nằm sau DTO và adapter
- loop không cần biết đang dùng OR-Tools hay cuOpt

---

## 6. Offline Sovereign Brain v2 pipeline

## 6.1 Oracle

Module: `fleet/agent/oracle.py`

Các thành phần chính:

- `realized_cost`
- `roll_forward`
- `grade_action`
- `best_action`

Vai trò:

- clone world
- áp action thử
- roll simulator tiến lên
- đo cost thực tế sau một horizon

Ý nghĩa:

- thay vì “đoán” action nào tốt bằng rule cứng
- hệ thống dùng chính simulator làm **oracle**

Cost hiện dùng cùng đơn vị với decision scoring:

- delay
- dropped demand
- SLA breach

## 6.2 Dataset factory

Module: `fleet/agent/dataset.py`

Các thành phần chính:

- `make_example` / `iter_examples`: baseline path cũ
- `make_disrupted_example` / `iter_disrupted_examples`: consequential path chuẩn
- `grade_full`
- `grade_disrupted`
- `build_record`
- `build_preference_record`

Vai trò:

- dựng tình huống train
- tạo event / injury
- grade tất cả candidate actions
- giữ action tốt nhất
- xuất JSONL cho SFT / DPO

Điểm kiến trúc quan trọng hiện nay:

- **consequential path** là path chuẩn cho training
- baseline path vẫn giữ lại để đối chiếu, không phải path train chính thức

## 6.3 Training scripts

Modules:

- `scripts/train_lora.py`
- `scripts/train_dpo.py`

Vai trò:

- `train_lora.py`: SFT trên `train.jsonl`
- `train_dpo.py`: preference tuning trên `prefs.jsonl`

Đặc điểm:

- heavy GPU import nằm trong `main()`
- formatter functions giữ độc lập để test dễ
- output của model bám đúng structured decision schema

## 6.4 Eval scripts

Module: `scripts/eval_brain.py`

Vai trò:

- offline eval: prediction vs oracle ground truth
- online eval: engine chạy qua full simulator loop

Các engine thường đem so:

- rule
- scoring
- nim

Ý nghĩa:

- tách “học được action đúng theo dataset chưa”
- khỏi “chạy trong thế giới mô phỏng có tốt không”

---

## 7. UI và lớp điều khiển

Modules:

- `fleet/ui/controller.py`
- `fleet/ui/app.py`

Class chính:

- `SimulationController`

Vai trò:

- đóng vai trò bridge giữa UI và runtime loop
- cung cấp `step`, `snapshot`, `approve`, `reject`

`app.py` là lớp Streamlit mỏng:

- render state
- hiển thị event / pending decisions
- cho người dùng duyệt hoặc từ chối quyết định

Ý nghĩa:

- logic vận hành nằm ở controller và loop
- UI chỉ là lớp hiển thị / tương tác

---

## 8. Các chế độ decision hiện có

Ở mức vận hành, decision layer hiện có 4 mode thực dụng:

- `rule`: đơn giản, ổn định, dễ demo
- `scoring`: heuristic tốt hơn rule
- `claude`: phụ thuộc API ngoài
- `nim`: self-hosted, dùng cho hướng sovereign brain

Trong thực tế:

- nếu cần demo chắc chắn, `rule` hoặc `scoring` an toàn nhất
- nếu cần story “self-hosted AI”, `nim` là mode quan trọng
- nếu cần teacher / labeler / đối chiếu, `claude` vẫn hữu ích ở offline path

---

## 9. Cấu hình hệ thống

Toàn bộ cấu hình tập trung ở `config/settings.py`.

Class chính:

- `Settings`
- `load_settings(env)`

Có thể chia config thành 8 nhóm:

## 9.1 Engine selection

- `ROUTING_ENGINE`
- `DECISION_ENGINE`
- `DETECTOR_ENGINE`
- `FORECASTER_ENGINE`

## 9.2 Core simulation

- `SEED`
- `TICK_MINUTES`
- `RESTOCK_INTERVAL_MIN`
- `DEMAND_NOISE`

## 9.3 Demand process

- `DEMAND_TREND_PER_DAY`
- `DEMAND_WEEKEND_FACTOR`
- `DEMAND_AR_RHO`
- `DEMAND_AR_SIGMA`
- `REGIME_PROB`
- `REGIME_FACTOR`
- `REGIME_DURATION_MIN`

## 9.4 Weather / road effects

- `ENABLE_WEATHER`
- `ENABLE_TRAVEL_TIME`
- `TRAFFIC_PEAK_FACTOR`
- `WEATHER_RHO`
- `WEATHER_FLOOD_THRESHOLD`
- `WEATHER_FLOOD_LEVEL`

## 9.5 Forecast / statistical detection

- `EWMA_ALPHA`
- `HW_ALPHA`
- `HW_BETA`
- `HW_GAMMA`
- `SEASON_LENGTH`
- `PI_Z`
- `CUSUM_K`
- `CUSUM_THRESHOLD`
- `DETECTOR_MIN_HISTORY`
- `ZSCORE_THRESHOLD`

## 9.6 Decision / approval

- `AUTO_APPROVE_DELAY_THRESHOLD_MIN`
- `SLA_CRITICAL_THRESHOLD_MIN`
- `SCORE_W_SLA`
- `SCORE_W_DELAY`
- `SCORE_W_DROP`
- `ENABLE_PROACTIVE`

## 9.7 Oracle / dataset

- `ORACLE_HORIZON_TICKS`
- `ORACLE_MIN_GAP`

## 9.8 External endpoints

- `ANTHROPIC_API_KEY`
- `CUOPT_ENDPOINT`
- `NIM_ENDPOINT`
- `NIM_MODEL`

Ý nghĩa kiến trúc:

- hệ thống được thiết kế để **đổi behavior chủ yếu qua config**
- không phải sửa caller để đổi engine

---

## 10. Cấu trúc thư mục nên hiểu như thế nào

## 10.1 `fleet/contracts/`

Lớp đáy:

- schema
- enums
- DTO
- interfaces

Đây là nền tảng mà mọi module khác dùng.

## 10.2 `fleet/simulator/`

Mô hình thế giới sống.

## 10.3 `fleet/detection/`

Phát hiện disruption và anomaly.

## 10.4 `fleet/routing/`

Chuyển state thành routing problem và giải route.

## 10.5 `fleet/forecast/`

Dự báo cho detector hoặc các policy về sau.

## 10.6 `fleet/agent/`

Các decision engines và offline oracle/dataset logic.

## 10.7 `fleet/dispatch/`

Approval policy + world mutation theo action.

## 10.8 `fleet/ui/`

Lớp điều khiển và Streamlit app.

## 10.9 `scripts/`

Entry points cho dataset / train / eval.

## 10.10 `tests/`

Regression protection cho cả runtime và offline path.

---

## 11. Những điểm “đáng biết” về kiến trúc hiện tại

## 11.1 Hệ thống thiên về deterministic-by-default

Phần runtime mặc định vẫn ưu tiên:

- CPU path
- rule/scoring path
- test offline được

Điều này giúp demo ít rủi ro hơn.

## 11.2 External AI/GPU là optional, không phải hard dependency

- cuOpt chỉ dùng khi endpoint có sẵn
- Claude chỉ dùng khi có key
- NIM chỉ dùng khi có endpoint

Nếu không có, hệ thống vẫn chạy.

## 11.3 Offline training path được tách khỏi runtime path

Điều này quan trọng vì:

- train có thể thay đổi, thử nghiệm nhiều
- runtime phải ổn định hơn

Chỉ một phần nhỏ của sovereign brain thực sự vào runtime:

- `NimAgent`
- config chọn engine

## 11.4 Oracle quality phụ thuộc dataset path, không chỉ model path

Điểm mấu chốt của repo hiện tại là:

- quality của fine-tune phụ thuộc mạnh vào `scripts.gen_dataset --consequential`
- nếu sinh dataset sai path, train script vẫn chạy nhưng signal học sẽ kém

---

## 12. Hệ thống phù hợp để demo như thế nào?

Repo hiện tại phù hợp cho 3 kiểu demo:

## 12.1 Demo vận hành runtime

Cho thấy:

- thế giới có disruption
- engine đưa ra quyết định
- approval gate hoạt động
- dispatcher áp dụng quyết định
- route được giải lại

## 12.2 Demo kiến trúc mở rộng

Cho thấy:

- cùng một loop
- nhưng đổi engine qua config
- CPU ↔ cuOpt
- rule/scoring ↔ LLM ↔ NIM

## 12.3 Demo sovereign brain

Cho thấy:

- dataset sinh từ mô phỏng
- oracle chọn action tốt nhất
- train LoRA / DPO
- serve model nội bộ

---

## 13. Giới hạn hiện tại cần nói thẳng

- đây vẫn là mô phỏng, không phải hệ thống production tích hợp ERP/WMS/TMS thật
- runtime path và training path đã usable, nhưng policy semantics vẫn có thể tinh chỉnh thêm
- một số engine cao cấp phụ thuộc endpoint ngoài repo
- dataset quality phải được kiểm bằng gate, không suy ra chỉ từ việc command chạy xong

---

## 14. Nên đọc tiếp gì?

- Nếu cần xem trách nhiệm từng module sâu hơn: `docs/MODULES.md`
- Nếu cần quy trình chạy thật: `docs/runbooks/2026-06-07-sovereign-brain-fast-runbook.md`
- Nếu cần quy trình kỹ thuật đầy đủ: `docs/runbooks/2026-06-07-sovereign-brain-technical-runbook.md`
- Nếu cần dấu vết vá oracle M-F: `docs/superpowers/notes/2026-06-07-m-f-implementation-trace.md`

---

## 15. Một câu tóm tắt

Đây là một nền tảng mô phỏng + tối ưu + ra quyết định cho delivery fleet, được thiết kế theo kiểu config-driven và module hóa, đồng thời có một offline AI pipeline đủ hoàn chỉnh để sinh dữ liệu, train model và đưa model self-hosted quay trở lại runtime qua NIM.
