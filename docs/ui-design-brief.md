# Design Brief — UI cho "AI Điều phối Đội xe Giao hàng Thời gian thực"

> Prompt để đưa cho Claude (hoặc công cụ thiết kế) dựng giao diện. Mô tả sát hệ thống
> đang chạy. Mục tiêu: thay UI Streamlit thô hiện tại bằng một giao diện điều hành
> (control-room / dispatch dashboard) chuyên nghiệp.

---

## 1. Bối cảnh sản phẩm

Đây là một hệ thống AI điều phối chuỗi cung ứng / đội xe giao hàng **theo thời gian
thực**. Hệ thống chạy một "thế giới mô phỏng sống" (một thành phố — bản đồ thật TP.HCM
hoặc bản đồ mẫu) gồm: 1 kho (depot), nhiều khách hàng, nhiều xe tải, và mạng lưới đường.
Theo từng nhịp thời gian (tick = 5 phút mô phỏng), thế giới biến động: nhu cầu tăng/giảm
theo mùa và giờ cao điểm, kẹt xe, ngập đường do mưa, xe hỏng, thiếu hàng trong kho…

Vòng lặp cốt lõi của hệ thống chạy đúng **4 bước**, và UI phải phản ánh được mạch này:

1. **Tiếp nhận dữ liệu** — thế giới tick một nhịp, cập nhật vị trí xe, đơn hàng, đường.
2. **Phát hiện sự cố** — bộ dò (rule / thống kê) phát hiện biến động và tạo *Event*.
3. **Ra quyết định & đề xuất** — "bộ não" (luật → chấm điểm → mô hình ngôn ngữ) đề xuất
   hành động xử lý cho mỗi sự cố, kèm ước lượng tác động (số phút trễ thêm).
4. **Thực thi** — việc nhỏ thì **tự động duyệt & thực thi**; việc lớn thì **đẩy vào hàng
   chờ phê duyệt của con người**. Sau khi áp dụng, lộ trình xe được tính lại (reroute).

Điểm nhấn công nghệ: chạy trên hạ tầng NVIDIA (cuOpt tối ưu lộ trình trên GPU, NIM phục
vụ mô hình ngôn ngữ, Riva/Whisper nhận dạng giọng nói). Nhưng UI **không cần** thể hiện
hạ tầng — chỉ thể hiện nghiệp vụ điều phối.

## 2. Người dùng (personas)

- **Chính — Quản lý chuỗi cung ứng / điều phối viên (dispatcher):** ngồi trước màn hình
  như phòng điều hành. Họ theo dõi bản đồ, nhận đề xuất từ AI, **phê duyệt hoặc từ chối**
  các thay đổi lớn, và báo cáo sự cố hiện trường. Đây là người dùng UI chính.
- **Gián tiếp — nhân sự tại các nút (kho, tài xế, điểm bán):** nhận lệnh điều phối mới
  (lộ trình mới, đổi ưu tiên). Không thao tác trực tiếp trên UI này.

Giọng điệu thiết kế: **phòng điều hành nghiêm túc, mật độ thông tin cao, đáng tin cậy,
realtime** — không phải landing page marketing. Ưu tiên rõ ràng dưới áp lực thời gian.

## 3. Dữ liệu thật mà UI hiển thị (sát code)

Tất cả màn hình lấy từ một "snapshot" JSON của thế giới. Các thực thể và trạng thái:

### Thanh chỉ số (KPI, luôn nhìn thấy)
- `sim_tick` — số nhịp đã chạy.
- `clock` — đồng hồ mô phỏng (ISO datetime).
- `pending_orders` — tổng số đơn còn chờ giao.
- `pending_decisions` — số quyết định đang chờ người duyệt (cần nổi bật khi > 0).

### Bản đồ (trung tâm màn hình)
- **Depot** (kho) — 1 điểm, màu vàng, có tên.
- **Khách hàng** — nhiều điểm xanh dương; mỗi điểm có `priority` 1–4 (1 = khẩn nhất,
  4 = ít khẩn nhất). Nên phân biệt độ ưu tiên bằng kích thước/sắc độ.
- **Xe** — nhiều điểm đỏ; mỗi xe có `status`: `at_depot | in_transit | on_route |
  broken | maintenance`. Trạng thái nên có màu/biểu tượng riêng (vd: xe hỏng = đỏ cảnh báo).
- **Lộ trình (routes)** — các đường nối thể hiện tuyến xe đang chạy (vẽ polyline trên
  đường thật). Khi reroute, tuyến đổi.

### Sự cố đang hoạt động (Active Events)
Mỗi sự cố gồm: `event_type`, `target` (đối tượng bị ảnh hưởng: id khách/xe/cạnh đường),
`severity`. 6 **loại sự cố**:
- `traffic` — kẹt xe trên một đoạn đường.
- `demand_surge` — nhu cầu tăng đột biến tại khách hàng.
- `inventory_shortage` — thiếu hàng trong kho.
- `vehicle_breakdown` — xe hỏng.
- `urgent_order` — đơn gấp.
- `flooded_area` — đoạn đường ngập (xe lội được hay không tùy độ sâu).

4 **mức nghiêm trọng** (`severity`): `low | medium | high | critical`. Cần thang màu rõ
(vd: low xám/xanh → critical đỏ). Đây là tín hiệu thị giác quan trọng nhất.

### Hàng chờ phê duyệt (Decisions awaiting approval) — màn hình quan trọng nhất
Mỗi quyết định gồm:
- `action` — 1 trong 7 hành động: `reroute` (đổi tuyến), `reschedule` (đổi lịch),
  `reprioritize` (đổi ưu tiên), `reallocate` (phân bổ lại), `defer` (hoãn),
  `cancel` (hủy), `accelerate` (đẩy nhanh).
- `description` — mô tả người-đọc-được về việc sẽ làm.
- `added_delay_min` — ước lượng số phút trễ thêm (tác động). Là con số then chốt để
  con người quyết định duyệt/từ chối.
- (ngầm) gắn với một `event_id` đã gây ra nó, và `engine` ra quyết định
  (`rule_based | claude | local_nim | human`) — có thể hiện badge "do AI/luật/người đề xuất".
- Trạng thái duyệt: `pending | approved | rejected | override`.

Mỗi dòng cần 2 nút **Approve** / **Reject**. Quy tắc nghiệp vụ: việc nhỏ (trễ thêm dưới
ngưỡng, mặc định 15 phút) hệ thống **tự duyệt**; việc lớn mới vào hàng chờ này. UI nên
phân biệt rõ "AI đã tự xử lý" vs "đang chờ bạn duyệt".

### Bảng xe (vehicle table)
Danh sách xe với id, status, vị trí, chỉ số stop hiện tại.

## 4. Tính năng điểm nhấn — Báo cáo sự cố bằng giọng nói/văn bản

Một panel cho phép điều phối viên báo sự cố hiện trường bằng **3 cách**: nói qua mic,
tải file âm thanh (.wav/.mp3/.m4a), hoặc gõ chữ (vd: *"đường vào C001 ngập, xe 3 hỏng"*).
Luồng: âm thanh → nhận dạng giọng nói → mô hình ngôn ngữ bóc tách thành sự cố có cấu trúc
→ tiêm vào thế giới → hệ thống lập tức đề xuất xử lý ngay trước mắt.

UI cần hiển thị: (a) văn bản đã nghe/đọc được, (b) (các) sự cố bóc tách được dưới dạng
chip "loại · đối tượng · mức độ", (c) các quyết định phát sinh ngay sau đó. Đây là khoảnh
khắc "wow" của demo — nên được thiết kế nổi bật, mạch lạc.

## 5. Điều khiển mô phỏng

- Nút **Step 1 tick** / **Step 5 ticks** — tua thế giới tới.
- Nút **Reset** — dựng lại thế giới.
- (Tùy chọn nâng cao cho bản mới: nút Play/Pause auto-tick, tốc độ tua.)

## 6. UI hiện tại & hạn chế (cái cần thay)

Bản hiện tại là một trang Streamlit dọc, thô: tiêu đề → 3 nút → 4 metric → bản đồ pydeck
→ bảng xe → bảng sự cố → danh sách duyệt → panel giọng nói, xếp chồng nhau. Hạn chế:
- Không có bố cục phòng điều hành; mọi thứ trôi dọc, phải cuộn nhiều.
- Bản đồ nhỏ, không phải trung tâm; sự cố/quyết định nằm tách rời khỏi bản đồ.
- Không có thang màu mức độ nghiêm trọng, không có dòng thời gian sự cố, không có
  trạng thái realtime rõ ràng.
- Hàng chờ phê duyệt — phần quan trọng nhất — chỉ là text + 2 nút.

## 7. Yêu cầu thiết kế (đề bài cho designer)

Hãy thiết kế giao diện web **dashboard điều phối thời gian thực** với:

1. **Bố cục phòng điều hành**: bản đồ lớn làm trung tâm, các panel thông tin bao quanh
   (thanh KPI trên cùng; sự cố + hàng chờ duyệt ở sidebar; điều khiển + báo cáo giọng nói
   dễ với tới).
2. **Hàng chờ phê duyệt nổi bật**: mỗi quyết định là một thẻ rõ ràng — hành động, mô tả,
   tác động (phút trễ), nguồn đề xuất (AI/luật/người), 2 nút Approve/Reject lớn. Khi có
   việc chờ duyệt phải gây chú ý ngay.
3. **Hệ thống tín hiệu thị giác** cho 4 mức severity và 5 trạng thái xe — nhất quán, dễ
   quét bằng mắt dưới áp lực.
4. **Dòng/khoảnh khắc realtime**: cảm giác thế giới đang sống — sự cố mới xuất hiện, AI
   đề xuất, con người duyệt, lộ trình đổi.
5. **Panel báo cáo giọng nói** liền mạch, thể hiện rõ chuỗi nghe → bóc tách → đề xuất.
6. **Trạng thái rỗng & tải**: "Chưa có sự cố", "Không có việc chờ duyệt", v.v.

Đề xuất giao gồm: sơ đồ bố cục (layout) tổng, hệ màu + thang severity, mockup các thành
phần chính (thẻ quyết định, danh sách sự cố, thanh KPI, panel giọng nói), và trạng thái
tương tác. Có thể là hệ thống tối (dark dispatch theme) — phù hợp phòng điều hành.

---

### Phụ lục — bảng tra nhanh (enum để gắn nhãn/màu)

| Nhóm | Giá trị |
|---|---|
| Loại sự cố | traffic · demand_surge · inventory_shortage · vehicle_breakdown · urgent_order · flooded_area |
| Mức độ | low · medium · high · critical |
| Hành động | reroute · reschedule · reprioritize · reallocate · defer · cancel · accelerate |
| Trạng thái xe | at_depot · in_transit · on_route · broken · maintenance |
| Trạng thái duyệt | pending · approved · rejected · override |
| Nguồn quyết định | rule_based · claude · local_nim · human |
| Ưu tiên khách | 1 (khẩn nhất) … 4 (ít khẩn nhất) |
