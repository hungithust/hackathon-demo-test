# AI Agent Tối Ưu Chuỗi Cung Ứng Realtime — Tài Liệu Bài Toán

> Phiên bản: 1.0 · Ngày: 2026-06-02
> Mục đích: Mô tả bài toán một cách chi tiết, chính xác và thống nhất cho cả
> nhóm (kỹ thuật + nghiệp vụ + người trình bày). Đây là tài liệu nguồn (source of
> truth) để mọi quyết định thiết kế và demo bám theo.

---

## 0. Tóm tắt một câu

Xây dựng một **AI Agent tự hành** giám sát toàn bộ chuỗi cung ứng theo thời gian
thực, **tự phát hiện biến động**, **tự suy luận và đề xuất phương án tái cấu trúc**,
rồi **tự thực thi** (việc nhỏ) hoặc **xin con người phê duyệt** (việc lớn) — tập
trung vào **luồng vận hành xe đường bộ** trong logistics.

---

## 1. Bối cảnh & Động lực

Chuỗi cung ứng hiện đại gồm nhiều nút (nhà cung cấp, kho, trung tâm phân phối,
điểm bán lẻ) nối với nhau bằng **đội xe vận tải đường bộ**. Khi xảy ra biến động —
nhà cung cấp giao trễ, nhu cầu tăng đột biến, tuyến đường tắc/ngập, cửa hàng hết
hàng — doanh nghiệp thường phản ứng **thủ công**: con người phát hiện muộn, họp
bàn, rồi mới điều chỉnh. Quá trình này chậm (hàng giờ đến hàng ngày), dễ sai, và
tốn chi phí (giao trễ, mất doanh số, chạy xe rỗng).

Phần lớn giải pháp trên thị trường chỉ dừng ở **dashboard cảnh báo** để con người
tự ra quyết định. **Khoảng trống**: chưa có hệ thống **tự ra quyết định và hành
động** ở quy mô toàn chuỗi, với con người chỉ tham gia ở các quyết định tác động
lớn.

---

## 2. Phát biểu bài toán (Problem Statement)

> Cho một mạng lưới chuỗi cung ứng vận hành bằng đội xe đường bộ, hãy xây dựng một
> AI Agent có khả năng:
>
> 1. **Quan sát liên tục** trạng thái mọi nút và mọi chuyến xe theo thời gian thực.
> 2. **Phát hiện biến động bất thường** trong vài giây kể từ khi tín hiệu xuất hiện.
> 3. **Suy luận** ra nguyên nhân/tác động và **đề xuất phương án tái cấu trúc** tối ưu.
> 4. **Thực thi** phương án: tự động với việc tác động thấp; xin **phê duyệt của con
>    người** với việc tác động cao; sau đó **phát lệnh điều phối cụ thể** xuống từng
>    nút và từng tài xế.
> 5. **Ghi nhật ký** mọi quyết định để truy vết/kiểm toán, và **học** từ vòng trước.

Bài toán cốt lõi mang tính **ra quyết định dưới bất định, theo thời gian thực, trên
một đồ thị mạng lưới động**, kết hợp **tối ưu tổ hợp** (định tuyến, phân bổ) với
**suy luận ngôn ngữ** (LLM điều phối, giải thích, quyết định tổng hợp).

---

## 3. Phạm vi (Scope)

### 3.1. TRONG phạm vi (In-scope)

- **Phương thức vận tải: CHỈ xe đường bộ** (xe tải/xe giao hàng). Toàn bộ tối ưu
  lộ trình, đội xe, tài xế, nhiên liệu, giao thông đều xoay quanh xe đường bộ.
- Toàn bộ các nút chuỗi: **Nhà cung cấp → Kho → Trung tâm phân phối → Điểm bán lẻ
  → Khách hàng**.
- Bốn nhóm biến động: **nguồn cung, nhu cầu, vận chuyển (đường bộ), bán lẻ**.
- Vòng lặp vận hành tự động: thu thập → phát hiện → quyết định → thực thi.
- Con người trong vòng lặp (human-in-the-loop) cho quyết định tác động cao.

### 3.2. NGOÀI phạm vi (Out-of-scope) — chốt rõ

- **KHÔNG xử lý vận tải đường sắt (tàu hỏa), đường thủy (tàu thủy/sà lan), hàng
  không (máy bay).** Các phương thức này không nằm trong bài toán. Nếu một tuyến
  thực tế có chặng tàu/thủy/bay, hệ thống coi đó là "đầu vào bên ngoài" và chỉ tối
  ưu phần **đường bộ** kết nối với nó.
- Không làm hệ thống ERP/WMS/TMS đầy đủ — chỉ tích hợp dữ liệu từ chúng.
- Không bao gồm bảo trì phương tiện (OBD-II), đào tạo tài xế — đây là hướng khác
  đã loại khỏi đề tài.
- Không xử lý thanh toán/tài chính/hợp đồng pháp lý.

### 3.3. Lý do giới hạn vào xe đường bộ

Đường bộ là phương thức **biến động nhất và điều khiển được nhất theo thời gian
thực** (tái định tuyến tức thời, đổi tài xế, ưu tiên đơn). Đây là nơi AI Agent tạo
giá trị rõ nhất và là phần khả thi để demo trong khuôn khổ hackathon.

---

## 4. Đối tượng người dùng

| Nhóm                            | Là ai                                                                                                                          | Tương tác với hệ thống                                                                                                                                                                                 |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Nhóm 1 — Trực tiếp** | Bộ phận quản lý chuỗi cung ứng / điều hành (ops)                                                                       | Nhận đề xuất tái cấu trúc của AI,**phê duyệt/từ chối** các quyết định tác động lớn (đổi NCC lớn, tái định tuyến toàn mạng…).                                             |
| **Nhóm 2 — Gián tiếp** | Nhân sự tại các nút: NCC, thủ kho, nhân viên trung tâm phân phối,**tài xế**, nhân viên cửa hàng bán lẻ | **Nhận lệnh điều phối tự động** do AI phát ra sau khi tái cấu trúc: lộ trình mới cho tài xế, lệnh xuất/nhập kho, đơn đặt hàng thay thế, lệnh bổ sung hàng cho cửa hàng. |

---

## 5. Mục tiêu & Nguyên tắc vận hành

### 5.1. Ba mục tiêu cốt lõi

1. **Tự phát hiện biến động trong vài giây.**
2. **Tự suy luận và đề xuất cách xử lý.**
3. **Tự thực thi nếu việc nhỏ; phê duyệt con người nếu việc lớn.**

### 5.2. Nguyên tắc thiết kế

- **Autonomy có kiểm soát**: agent hành động mặc định, con người là "phanh an toàn"
  cho quyết định lớn — không phải ngược lại.
- **Proactive hơn reactive**: dùng dự báo để hành động *trước* khi gián đoạn xảy ra
  khi có thể (dự báo điểm nghẽn 24–72h trước).
- **Giải thích được (explainable)**: mọi quyết định kèm chuỗi suy luận + ước tính
  tác động, ghi nhật ký đầy đủ cho kiểm toán.
- **An toàn khi vận hành**: có cơ chế fallback (nếu LLM/dịch vụ lỗi vẫn ra được
  quyết định hợp lý).

---

## 6. Luồng vận hành bị can thiệp (Operational Workflow)

Hệ thống chạy theo **vòng lặp giám sát** (ví dụ 5 phút/lần, hoặc kích hoạt theo sự
kiện). Bốn bước AI can thiệp:

1. **Tiếp nhận dữ liệu (Ingest)** — thu thập luồng dữ liệu realtime từ mọi nguồn
   (GPS đội xe, thời tiết, giao thông, ERP, API nhà cung cấp, POS bán lẻ).
2. **Phân tích & phát hiện sự cố (Detect)** — kết hợp ngưỡng theo luật (rule-based
   threshold) + phát hiện bất thường bằng ML để xác định biến động và mức nghiêm
   trọng.
3. **Ra quyết định & đề xuất (Decide & Propose)** — agent (LLM) nhận context, suy
   luận từng bước (ReAct), gọi công cụ tối ưu (định tuyến, tồn kho), đưa ra phương
   án cụ thể + ước tính tác động + cờ "cần phê duyệt hay không".
4. **Thực thi kế hoạch (Execute & Dispatch)** — nếu tác động cao → chờ con người
   duyệt; sau đó **phát lệnh điều phối cụ thể** xuống từng nút/tài xế, cập nhật
   trạng thái mạng, ghi nhật ký, đưa kết quả vào context vòng sau (bộ nhớ ngắn hạn).

---

## 7. Cấu trúc mạng lưới chuỗi cung ứng

Đồ thị có hướng gồm các loại nút và cung (cạnh) = **tuyến vận tải đường bộ**:

```
Nhà cung cấp ──▶ Kho ──▶ Trung tâm phân phối ──▶ Điểm bán lẻ ──▶ Khách hàng
(Supplier)     (WH)     (Distribution Center)   (Retail)       (Customer)
```

- **Nhà cung cấp (Supplier)**: nguồn nguyên liệu/hàng hóa; có năng lực, lead-time,
  chi phí, độ tin cậy.
- **Kho (Warehouse)**: lưu trữ; có tồn kho theo SKU, năng lực, điểm đặt hàng lại.
- **Trung tâm phân phối (Distribution Center)**: gom & chia hàng tới bán lẻ.
- **Điểm bán lẻ (Retail)**: bán cho khách cuối; có dữ liệu POS, tồn kho kệ.
- **Tuyến vận tải (đường bộ)**: cạnh nối các nút, do **đội xe** chạy; có khoảng
  cách, thời gian, tình trạng giao thông, ràng buộc SLA.

---

## 8. Các loại biến động cần xử lý

| # | Loại (tầng)                         | Ví dụ                                          | Hướng xử lý của agent                                                       |
| - | ------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------- |
| 1 | **Nguồn cung**                 | NCC chính báo trễ hàng 3 ngày               | Chuyển một phần đơn sang NCC dự phòng; phát PO thay thế                 |
| 2 | **Nhu cầu (kho)**              | SKU tại kho tăng nhu cầu +180%                | Điều hàng giữa kho (rebalance); tính lại EOQ/safety stock; đặt thêm     |
| 3 | **Vận chuyển (đường bộ)** | Quốc lộ ngập, nhiều chuyến xe nguy cơ trễ | Tái định tuyến đội xe qua đường thay thế; ưu tiên đơn SLA-critical |
| 4 | **Bán lẻ**                    | Cửa hàng hết hàng đột ngột (POS)          | Điều hàng từ trung tâm phân phối xuống cửa hàng trong SLA              |

> Lưu ý: biến động vận chuyển **chỉ liên quan đến xe đường bộ** (tắc đường, ngập,
> tai nạn, đóng đường, kẹt cửa khẩu đường bộ). Không xét chậm tàu/chuyến bay/tàu
> thủy.

---

## 9. Yêu cầu chức năng (Functional Requirements)

- **FR1 — Giám sát realtime**: hiển thị trạng thái mọi nút + đội xe + KPI, cập nhật
  liên tục; trực quan hóa mạng lưới (nút đổi màu khi bất thường).
- **FR2 — Phát hiện bất thường**: Isolation Forest / Z-score / DBSCAN + ngưỡng luật;
  phát hiện trong vài giây, kèm tín hiệu/độ nghiêm trọng.
- **FR3 — Suy luận & quyết định**: agent LLM (ReAct / Plan-Execute) tạo phương án
  + ước tính tác động + phân loại mức tác động.
- **FR4 — Tối ưu lộ trình xe**: giải VRP/shortest-path để tái định tuyến đội xe khi
  biến động (OR-Tools, Dijkstra/A*).
- **FR5 — Tối ưu tồn kho**: EOQ, safety stock, rebalance giữa kho.
- **FR6 — Tối ưu nguồn cung**: chọn/đổi NCC dự phòng dựa trên năng lực/chi phí/rủi ro.
- **FR7 — Human-in-the-loop**: hàng đợi phê duyệt cho quyết định tác động cao; cho
  phép duyệt/từ chối/override.
- **FR8 — Phát lệnh điều phối (Dispatch)**: sinh lệnh cụ thể xuống NCC/kho/tài
  xế/cửa hàng (lộ trình mới, lệnh xuất kho, PO thay thế, lệnh bổ sung hàng).
- **FR9 — Dự báo (Predictive)**: dự báo nhu cầu 7–14 ngày; cảnh báo điểm nghẽn
  24–72h trước để hành động chủ động.
- **FR10 — Nhật ký & kiểm toán**: log đầy đủ mọi quyết định (thời gian, sự kiện,
  hành động, người duyệt, engine) cho auditability.

### Yêu cầu phi chức năng (Non-functional)

- **Độ trễ phát hiện**: vài giây.
- **Độ tin cậy demo**: có fallback để không bao giờ lỗi khi trình diễn.
- **Khả năng giải thích**: mỗi quyết định có chuỗi lý luận đọc được.
- **Khả năng mở rộng**: kiến trúc tầng rõ ràng để cắm mô-đun thật ở giai đoạn sau.

---

## 10. Kiến trúc hệ thống (5 tầng)

1. **Tầng 1 — Nguồn dữ liệu**: GPS/IoT đội xe, thời tiết, giao thông (đường bộ),
   ERP (tồn kho/đơn), API nhà cung cấp, POS bán lẻ.
2. **Tầng 2 — Xử lý sự kiện & phát hiện bất thường**: Event Bus (Kafka/Redis
   Streams), Anomaly Detection (Isolation Forest, Z-score, DBSCAN), RAG (lịch sử).
3. **Tầng 3 — Agent Core (não)**: LangGraph điều phối workflow (ReAct/Plan-Execute);
   **Claude (Anthropic API)** ra quyết định; mô hình dự báo (Prophet, XGBoost) đưa
   kết quả vào context.
4. **Tầng 4 — Hành động tự động & điều phối**: tái định tuyến (VRP/OR-Tools), tối ưu
   tồn kho (EOQ/RL), đổi NCC (graph risk), **phát lệnh xuống node staff**, audit log.
5. **Tầng 5 — Giám sát & phê duyệt con người**: dashboard (monitor + override),
   human approval cho quyết định tác động cao, monitoring (AgentOps/Prometheus).

---

## 11. Thuật toán cốt lõi

- **Suy luận agent**: ReAct (suy luận + hành động), Plan-and-Execute.
- **Tối ưu lộ trình xe (đường bộ)**: Dijkstra/A* (đường ngắn nhất), VRP bằng Google
  OR-Tools (tối ưu đội xe), Greedy + Local Search (điều chỉnh lịch giao động).
- **Dự báo nhu cầu**: Prophet (mùa vụ), XGBoost; (mở rộng: LSTM/Transformer, ARIMA).
- **Phát hiện bất thường**: Isolation Forest, Z-Score/IQR, DBSCAN (theo không gian).
- **Tối ưu tồn kho**: EOQ, Safety Stock, Reinforcement Learning (Q-Learning/PPO).
- **Xử lý đồ thị chuỗi cung ứng**: GNN (rủi ro lan truyền), PageRank (nút quan
  trọng), Shortest Path (tuyến thay thế đường bộ).

---

## 12. Nguồn dữ liệu

- **Nội bộ**: ERP qua REST API — tồn kho realtime, lịch sử đơn, năng lực kho, thông
  tin NCC; dữ liệu POS bán lẻ.
- **Ngoại cảnh**: OpenWeatherMap (thời tiết), giá nhiên liệu (Petrolimex feed),
  Google Maps Platform (giao thông **đường bộ**, định tuyến).
- **Đội xe**: GPS/IoT (vị trí, tốc độ, tình trạng chuyến).
- **Hiện trạng**: prototype dùng **synthetic data** mô phỏng cấu trúc SAP/Oracle,
  sẵn sàng nối ERP thật ở giai đoạn pilot.

---

## 13. Tiêu chí thành công & Tác động kinh doanh

| Chỉ số                                       | Mục tiêu                                               |
| ---------------------------------------------- | -------------------------------------------------------- |
| Thời gian phản ứng gián đoạn             | Giảm 30–40%                                            |
| Chi phí logistics (tối ưu route & tồn kho) | Giảm 15–25%                                            |
| Tỷ lệ giao hàng đúng hạn                 | Cải thiện đáng kể (quản lý exception chủ động) |
| So với thủ công                             | Phản ứng nhanh hơn ~10–20 lần                       |

**Tiêu chí thành công của demo/MVP**: thể hiện trọn vòng *phát hiện → suy luận →
quyết định → (duyệt) → điều phối → ghi log* trên ≥4 kịch bản trải đều toàn chuỗi,
với phần ra quyết định bằng LLM thật.

---

## 14. Điểm khác biệt cạnh tranh

- So với app điều hướng/đội xe (Sygic/Garmin/Vietmap): chúng quản lý **xe & tài
  xế**; hệ thống này quản lý **toàn bộ chuỗi cung ứng**.
- So với ERP/dashboard truyền thống: chúng **hỗ trợ con người ra quyết định**; hệ
  thống này **thay con người ra quyết định** và hành động, chỉ escalate khi tác
  động lớn.
- Phát hiện bất thường ở **mọi nút** (NCC, kho, phân phối, bán lẻ) — không chỉ tắc
  đường/thời tiết.

---

## 15. Giả định & Ràng buộc

- **Giả định**: dữ liệu các nút có thể truy cập qua API; biến động có thể biểu diễn
  thành tín hiệu số; phương án tái cấu trúc có thể thực thi qua lệnh xuống nút.
- **Ràng buộc**: chỉ tối ưu vận tải **đường bộ**; tài nguyên/thời gian hackathon
  giới hạn → một số mô-đun ở mức mô phỏng; cần fallback an toàn cho demo.

---

## 16. Ngoài phạm vi & Hướng tương lai

- Tích hợp ERP/WMS/TMS thật; dữ liệu realtime thật.
- Mô hình dự báo huấn luyện thật (Prophet/XGBoost/LSTM).
- Bộ nhớ dài hạn + RAG lịch sử quyết định.
- Mở rộng đa phương thức vận tải (tàu hỏa/thủy/bay) — **chỉ khi cần ở giai đoạn
  sau**, ngoài phạm vi hiện tại.
- Học tăng cường để tự tối ưu chính sách tồn kho/định tuyến theo thời gian.

---

## 17. Thuật ngữ (Glossary)

- **Agent tự hành**: phần mềm AI tự quan sát–suy luận–hành động theo vòng lặp.
- **ReAct**: mẫu suy luận "Reasoning + Acting" — suy luận, gọi công cụ, quan sát,
  quyết định bước tiếp.
- **VRP**: Vehicle Routing Problem — bài toán tối ưu lộ trình đội xe.
- **EOQ**: Economic Order Quantity — lượng đặt hàng kinh tế.
- **SLA**: cam kết mức dịch vụ (vd thời gian giao tối đa).
- **Human-in-the-loop**: con người tham gia phê duyệt trong vòng lặp tự động.
- **Dispatch**: lệnh điều phối cụ thể phát xuống nút/tài xế để thực thi.
- **SKU**: đơn vị hàng hóa lưu kho.
- **Node staff**: nhân sự tại các nút mạng lưới (kho, tài xế, NCC, cửa hàng).
