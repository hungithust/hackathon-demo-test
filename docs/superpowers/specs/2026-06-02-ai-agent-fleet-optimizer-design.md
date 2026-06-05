# AI Agent Tối Ưu Đội Xe Giao Hàng Realtime — Thiết kế (Spec)

> Phiên bản: 1.0 · Ngày: 2026-06-02
> Trạng thái: Đã brainstorm & thống nhất hướng. Đây là source of truth cho thiết kế
> & demo. Tài liệu nghiệp vụ gốc: `docs/PROBLEM_STATEMENT.md` (lưu ý: spec này đã
> **đính chính** mô hình bài toán — xem mục 1).

---

## 1. Đính chính & phát biểu lại bài toán

**Thay đổi lớn so với PROBLEM_STATEMENT.md:** Khách hàng của hệ thống là **một nhà
cung cấp sở hữu đội xe riêng**. Hệ thống tối ưu cho **chính đội xe đó**, không phải
toàn chuỗi nhiều tầng.

Mô hình rút gọn thành **hub-and-spoke một depot**:

```
                    ┌──────────────────┐
                    │   1 KHO (depot)  │  ← nhà cung cấp, có tồn kho theo SKU
                    └─────────┬────────┘
          ┌────────┬──────────┼──────────┬────────┐
          ▼        ▼          ▼          ▼        ▼
      [Siêu thị] [Chợ]  [Cửa hàng]   [Siêu thị] [Điểm bán]   ← N điểm giao hàng
          ▲ đội xe của nhà cung cấp xuất phát từ kho, giao hàng rồi quay về
```

Đây là bài toán **Vehicle Routing Problem with Time Windows (VRPTW)** một depot,
kết hợp **ra quyết định realtime dưới biến động** bằng AI Agent.

**Đã loại khỏi phạm vi** (so với tài liệu gốc): chuỗi nhiều tầng
NCC→kho→DC→retail; tool "đổi nhà cung cấp dự phòng" (vì khách hàng *chính là* nhà
cung cấp). Vẫn chỉ vận tải **đường bộ**.

### Mục tiêu cốt lõi (giữ nguyên tinh thần tài liệu gốc)

1. Tự phát hiện biến động trong vài giây.
2. Tự suy luận & đề xuất phương án tối ưu cho đội xe.
3. Tự thực thi việc nhỏ; xin con người phê duyệt việc lớn; rồi phát lệnh điều phối.

---

## 2. Ràng buộc & quyết định nền tảng (đã chốt)

| Hạng mục            | Quyết định                                                                                                                                                                                                                           |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Thời gian / team     | 1-2 tuần, team mạnh → làm thật được vài thuật toán lõi                                                                                                                                                                      |
| Nguồn data           | **Simulator là "thế giới"** — engine mô phỏng sinh stream realtime VÀ nhận lệnh ngược từ agent. Không dùng dataset tĩnh. (Có thể cắm 1-2 API thật như topping, nhưng lõi chạy offline để demo an toàn.) |
| Quy mô mạng         | Nhỏ-gọn có chủ đích: ~6-8 điểm giao, ~3-5 xe, 5-10 SKU, 1 depot                                                                                                                                                                 |
| Vai trò LLM          | **Claude điều phối (ReAct + tool-calling)**; thuật toán/tool lo tính toán chính xác                                                                                                                                      |
| Bài toán lịch giao | **VRPTW**: có khung giờ nhận hàng + ràng buộc tải trọng xe                                                                                                                                                                |
| Stack                 | **Python full-stack**: Streamlit + Plotly cho UI; backend Python cho sim/agent/Claude SDK                                                                                                                                         |

---

## 3. Kiến trúc tổng thể

Ba thành phần quay quanh một **World State** chung (in-memory), theo vòng lặp giám sát.

```
        ┌──────────────────────────────────────────────┐
        │           WORLD STATE (in-memory)            │
        │  depot, customers, vehicles, road_graph,     │
        │  plan, events, decisions                     │
        └──────────────────────────────────────────────┘
            ▲ (3) áp lệnh        │ (1) snapshot
            │                    ▼
   ┌─────────────────┐   ┌─────────────────────────────┐
   │   SIMULATOR     │   │      AGENT CORE (Claude)     │
   │  tick engine    │   │  Detect → Reason(ReAct) →    │
   │  sinh stream &  │   │  Tool-call → Propose →       │
   │  diễn tiến TG   │   │  (Approve?) → Dispatch       │
   └─────────────────┘   └─────────────────────────────┘
            │                    │
            └────────┬───────────┘
                     ▼
        ┌──────────────────────────────┐
        │   DASHBOARD (Streamlit)       │
        │  bản đồ mạng · KPI · approval │
        │  · log quyết định · nút "tiêm │
        │  biến động"                   │
        └──────────────────────────────┘
```

**Một vòng lặp (vd mỗi 2-3 giây thực = X phút mô phỏng):**

1. **Simulator tick**: xe di chuyển dọc tuyến, kho tiêu thụ, điểm giao phát sinh
   nhu cầu → cập nhật State.
2. **Detect**: rule/threshold + z-score quét State → gắn cờ biến động + mức nghiêm
   trọng.
3. **Agent (Claude)**: nếu có biến động → nhận context, ReAct, gọi tool để tính
   phương án + ước tính tác động + cờ "cần duyệt?".
4. **Approval gate**: tác động thấp → tự thực thi; tác động cao → đẩy vào hàng đợi
   phê duyệt trên dashboard.
5. **Dispatch**: áp lệnh ngược vào State (đổi tuyến, xếp lại lịch, ưu tiên đơn) →
   ghi audit log → đưa vào context vòng sau.

**Module tách bạch (interface rõ ràng):**

- `simulator/` — thế giới: tick engine, sinh data, `inject_event()`.
- `detection/` — phát hiện biến động (rule + z-score).
- `agent/` — não (Claude orchestrator) + 4 tool.
- `ui/` — Streamlit dashboard.
- `state.py` — schema World State, là **contract** chung mọi module đọc/ghi.

---

## 4. World State — schema

```python
WorldState:
  clock: sim_time                                          # datetime mô phỏng
  depot:      {location, inventory{sku: qty}}              # 1 kho duy nhất
  customers[]:{id, type, location, orders{sku: qty},
               time_window(start, end), priority, sla_deadline}
  vehicles[]: {id, capacity, pos(lat,lng), route[stops],
               load, status, shift_hours, eta_per_stop}
  road_graph: {nodes, edges{from, to, distance_km,
               base_time, traffic_factor, status}}         # tuyến đường bộ
  plan:       {vehicle_id -> [stop sequence + ETA mỗi điểm]}  # lịch giao hôm nay
  events[]:   {id, type, target, severity, started_at}     # biến động đang diễn ra
  decisions[]:{ts, event, action, impact_estimate,
               approved_by, engine}                        # audit log
```

State là **một dataclass Python duy nhất**, giữ in-memory. Có thể snapshot ra JSON
để debug/replay. Không dùng DB.

---

## 5. Simulator — cách sinh data & tiêm biến động

### 5.1. Sinh data mỗi tick (luật đơn giản, có cấu trúc giống thật)

- **Nhu cầu/đơn tại điểm giao**: mỗi customer phát sinh nhu cầu theo **mùa vụ
  (sin theo giờ) + nhiễu (Poisson/Gaussian)**. Lịch sử này cũng là dữ liệu cho model
  dự báo học.
- **Xe**: tiến dọc `route` theo `base_time × traffic_factor`; cập nhật `pos`, ETA.
- **Kho**: trừ tồn khi xe xuất hàng; nhập bổ sung theo lịch.
- Nhiễu **seed được** → demo có thể replay y hệt (an toàn) hoặc bật random cho sống.

### 5.2. `inject_event(type, target, severity)` — input on-demand

Panel "Tiêm biến động" trên dashboard cho phép MC/giám khảo bấm tạo biến động:

| Loại        | Tiêm vào State                               | Agent phản ứng                    |
| ------------ | ---------------------------------------------- | ----------------------------------- |
| Vận chuyển | `edge.status=blocked` / `traffic_factor=5` | `reroute` + xếp lại ETA         |
| Nhu cầu     | thêm đơn khẩn vào `customer.orders`     | chèn vào lịch (`plan_routes`)  |
| Tồn kho     | `depot.inventory[sku]` thiếu hụt           | `check_inventory` ưu tiên đơn |
| Đội xe     | `vehicle.status=broken`                      | phân bổ lại điểm sang xe khác |

Bổ sung: cơ chế **sinh biến động ngẫu nhiên theo thời gian** (tùy chọn bật/tắt) để
demo "sống" mà không cần bấm tay liên tục.

---

## 6. Agent Core — Claude orchestrator + 4 tool

**Claude (ReAct + tool-calling)** nhận context biến động → chọn & gọi tool → diễn
giải kết quả → đưa ra **đề xuất + ước tính tác động** (phút trễ giảm, km tiết kiệm,
đơn cứu được) + **cờ duyệt** + **chuỗi giải thích** đọc được.

| Tool                | Engine                                                                     | Dùng khi                                                |
| ------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------- |
| `plan_routes`     | **OR-Tools VRPTW** (depot, xe + tải trọng, đơn + khung giờ)     | Lập lịch đầu ngày & xếp lại khi biến động lớn |
| `reroute`         | Dijkstra/A* trên `road_graph` (cập nhật ma trận thời gian khi tắc) | Đường tắc/ngập                                      |
| `check_inventory` | Heuristic ưu tiên đơn theo SLA/priority khi kho thiếu SKU             | Thiếu hàng tại kho                                    |
| `forecast_demand` | Mô hình nhẹ (Prophet hoặc EWMA + mùa vụ) trên lịch sử sim         | Cảnh báo chủ động 24h trước                       |

**Fallback an toàn**: nếu Claude/API lỗi, hệ thống vẫn ra được quyết định hợp lý
bằng heuristic mặc định (vd gọi thẳng `plan_routes`), để demo không bao giờ chết.

---

## 7. Human-in-the-loop

- **Tự thực thi (tác động thấp)**: chèn 1 điểm vào tuyến còn chỗ; reroute không lỡ
  khung giờ.
- **Cần phê duyệt (tác động cao)**: xếp lại lịch toàn đội; lùi/từ chối đơn; điều
  thêm xe. → Đẩy vào hàng đợi approval trên dashboard, cho duyệt/từ chối/override.

---

## 8. Kịch bản demo (≥4, trải toàn vận hành)

1. **Đường tắc/ngập** → `reroute` + xếp lại ETA các điểm bị ảnh hưởng. (tự thực thi)
2. **Đơn khẩn mới giữa ngày** (1 siêu thị) → chèn vào lịch, kiểm tra khung giờ còn
   kịp. (tự thực thi nếu nhỏ)
3. **Kho thiếu 1 SKU** → ưu tiên đơn SLA-critical, lùi đơn thấp. (cần duyệt)
4. **Xe hỏng** → phân bổ lại các điểm của xe đó sang xe khác. (cần duyệt)
5. **Proactive**: `forecast_demand` báo mai nhu cầu điểm X tăng mạnh → đề xuất thêm
   chuyến sáng sớm *trước khi* thiếu. (đề xuất chủ động)

Mỗi kịch bản thể hiện trọn vòng: *phát hiện → suy luận → quyết định → (duyệt) →
điều phối → ghi log*, với phần quyết định bằng **LLM thật**.

---

## 9. UI / Dashboard (Streamlit + Plotly)

- **Bản đồ mạng**: depot + điểm giao + vị trí xe realtime; tuyến đường; nút đổi màu
  khi bất thường.
- **Bảng KPI**: tỷ lệ giao đúng khung giờ, km/chi phí, số đơn trễ, đơn đang xử lý.
- **Hàng đợi phê duyệt**: thẻ quyết định tác động cao + nút duyệt/từ chối/override.
- **Log quyết định**: dòng thời gian các quyết định + giải thích của agent.
- **Panel "Tiêm biến động"**: dropdown loại + target + severity + nút kích hoạt.

---

## 10. Cấu trúc thư mục đề xuất

```
/
├── state.py              # dataclass WorldState — contract chung
├── simulator/            # tick engine, sinh data, inject_event
├── detection/            # rule + z-score
├── agent/
│   ├── orchestrator.py   # Claude ReAct loop (Anthropic SDK)
│   └── tools/            # plan_routes(OR-Tools), reroute, check_inventory, forecast_demand
├── ui/                   # Streamlit app + Plotly components
└── docs/                 # spec, problem statement
```

---

## 11. Tiêu chí thành công (MVP)

- Chạy trọn vòng lặp tự động trên ≥4/5 kịch bản, quyết định bằng Claude thật.
- `plan_routes` cho lời giải VRPTW hợp lệ (tôn trọng khung giờ + tải trọng).
- Dashboard thể hiện realtime: bản đồ + KPI + approval + log.
- Có fallback để demo không lỗi.

---

## 12. Ngoài phạm vi (giai đoạn sau)

- Tích hợp ERP/TMS thật, GPS thật, API Maps/Weather thật ở mức production.
- VRP nâng cao (multi-depot, pickup-delivery, dynamic re-optimization liên tục).
- Mô hình dự báo huấn luyện nặng (LSTM/Transformer).
- Bộ nhớ dài hạn + RAG lịch sử quyết định.
- RL tự tối ưu chính sách định tuyến/tồn kho.
