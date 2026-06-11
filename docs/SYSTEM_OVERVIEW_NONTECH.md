# Tổng quan hệ thống — bản dành cho người không chuyên kỹ thuật

> Tài liệu này dành cho người cần hiểu hệ thống **đang làm gì**, **có những phần nào**, và **vì sao nó hữu ích**.
> Không cần biết code để đọc tài liệu này.

---

## 1. Hệ thống này là gì?

Đây là một hệ thống hỗ trợ điều phối giao hàng theo thời gian thực.

Nó giúp trả lời các câu hỏi như:

- xe nào nên đi giao trước?
- khi đường bị tắc hoặc ngập thì nên đổi tuyến thế nào?
- khi nhu cầu tăng đột biến thì nên ưu tiên đơn nào?
- khi xe hỏng hoặc kho thiếu hàng thì nên xử lý ra sao?

Nói đơn giản, hệ thống theo dõi một mạng lưới giao hàng nhỏ gồm:

- **1 kho**
- **nhiều xe giao hàng**
- **nhiều điểm giao**
- **các sự cố có thể xảy ra**

Rồi từ đó:

1. phát hiện vấn đề
2. đề xuất cách xử lý
3. cho phép tự động xử lý việc nhỏ
4. giữ quyền phê duyệt của con người cho việc lớn

---

## 2. Bài toán mà hệ thống giải

Trong thực tế vận hành giao hàng, khó nhất không phải chỉ là “tìm đường ngắn nhất”.

Khó ở chỗ:

- mỗi xe có giới hạn tải
- mỗi khách có khung giờ nhận hàng
- kho có thể thiếu hàng
- đường có thể tắc, ngập, bị chặn
- xe có thể hỏng
- nhu cầu có thể tăng đột biến

Vì vậy, hệ thống không chỉ là bản đồ hay GPS.

Nó là một **bộ não điều phối** giúp xem toàn cục và ra quyết định trong tình huống thay đổi liên tục.

---

## 3. Hệ thống vận hành như thế nào?

Hệ thống chạy theo một vòng lặp đơn giản:

1. **quan sát thế giới hiện tại**
2. **phát hiện có gì bất thường**
3. **đề xuất hành động**
4. **quyết định tự làm hay chờ người duyệt**
5. **cập nhật kế hoạch giao hàng**

Có thể hình dung như sau:

```text
Thế giới giao hàng
   ↓
Phát hiện sự cố
   ↓
Đề xuất quyết định
   ↓
Tự duyệt hoặc chờ người duyệt
   ↓
Áp dụng thay đổi
   ↓
Tính lại tuyến xe nếu cần
```

---

## 4. Những khối chính của hệ thống

## 4.1 Khối mô phỏng thế giới

Đây là phần đóng vai trò “mô hình thế giới thật”.

Nó quản lý:

- thời gian hiện tại
- tồn kho trong kho
- đơn hàng đang chờ
- trạng thái xe
- trạng thái đường
- kế hoạch giao hàng hiện tại

Nó cũng mô phỏng các thay đổi như:

- phát sinh thêm nhu cầu
- nhập thêm hàng vào kho
- xe giao xong đơn
- sự cố trên đường

Ý nghĩa của khối này:

- cho phép cả hệ thống “thấy” bức tranh chung
- giúp kiểm thử và huấn luyện AI mà không cần dữ liệu thật từ doanh nghiệp

## 4.2 Khối phát hiện sự cố

Khối này trả lời câu hỏi:

> “Hiện tại có vấn đề gì đang xảy ra không?”

Ví dụ:

- một cung đường bị ngập
- một xe bị hỏng
- nhu cầu ở một khách tăng bất thường
- kho đang thiếu hàng cho một mặt hàng nào đó

Ý nghĩa:

- tách rõ phần “nhận biết sự cố” khỏi phần “ra quyết định xử lý”
- giúp hệ thống có thể thay đổi cách phát hiện mà không phải viết lại toàn bộ

## 4.3 Khối ra quyết định

Khối này trả lời câu hỏi:

> “Khi có sự cố, nên làm gì?”

Các hành động chính có thể là:

- đổi tuyến
- dời lịch
- ưu tiên lại khách hàng
- chuyển việc sang xe khác
- hoãn đơn
- hủy đơn
- đẩy nhanh đơn gấp

Hiện hệ thống có nhiều kiểu ra quyết định:

- kiểu đơn giản theo luật có sẵn
- kiểu chấm điểm theo mức ảnh hưởng
- kiểu dùng mô hình AI ngoài
- kiểu dùng mô hình AI nội bộ tự host

Ý nghĩa:

- cùng một hệ thống nhưng có thể thay “bộ não quyết định” theo nhu cầu

## 4.4 Khối phê duyệt

Không phải quyết định nào cũng nên tự động thực thi.

Vì vậy hệ thống có một lớp kiểm soát:

- việc nhỏ, ít rủi ro → có thể tự làm
- việc lớn, nhạy cảm → chờ con người duyệt

Ví dụ:

- đổi tuyến nhẹ có thể tự duyệt
- hủy đơn hoặc thay đổi lớn thì nên chờ người quản lý

Ý nghĩa:

- giữ được cân bằng giữa tự động hóa và kiểm soát

## 4.5 Khối thực thi

Sau khi quyết định được duyệt, hệ thống phải biến nó thành thay đổi thật trong kế hoạch.

Ví dụ:

- bỏ một điểm giao khỏi tuyến
- chuyển đơn sang xe khác
- cập nhật mức ưu tiên khách hàng
- tính lại tuyến sau khi đường bị chặn

Ý nghĩa:

- quyết định không chỉ nằm trên giấy
- thế giới mô phỏng thay đổi thật sau mỗi quyết định

## 4.6 Khối tối ưu tuyến đường

Đây là phần giải bài toán tuyến xe.

Nó nhận dữ liệu như:

- các xe còn khả dụng
- các khách cần giao
- khung giờ giao hàng
- giới hạn tải
- thời gian di chuyển

Rồi tạo ra kế hoạch xe nào đi đâu trước, đi theo thứ tự nào.

Hệ thống có thể chạy:

- bằng CPU thông thường
- hoặc qua NVIDIA cuOpt nếu có hạ tầng GPU

---

## 5. AI trong hệ thống nằm ở đâu?

AI trong repo này không chỉ là một chatbot trả lời câu hỏi.

Nó được dùng như một **bộ máy ra quyết định**.

Vai trò của AI gồm 2 phần:

## 5.1 AI dùng trong runtime

Khi hệ thống đang chạy, AI có thể được dùng để:

- đọc tình huống hiện tại
- chọn hành động phù hợp
- giải thích ngắn gọn vì sao chọn như vậy

## 5.2 AI dùng để huấn luyện offline

Ngoài runtime, repo còn có một pipeline riêng để:

- tự sinh dữ liệu huấn luyện từ mô phỏng
- thử nhiều hành động khác nhau
- chọn hành động nào cho kết quả tốt nhất
- dùng dữ liệu đó để fine-tune model nội bộ

Điều này quan trọng vì:

- không phụ thuộc hoàn toàn vào dịch vụ AI bên ngoài
- có thể xây được “bộ não quyết định” riêng
- dễ kể câu chuyện data sovereignty và self-hosted AI

---

## 6. “Oracle” là gì trong hệ thống này?

Trong bối cảnh repo này, “oracle” không phải cơ sở dữ liệu Oracle.

Ở đây, oracle nghĩa là:

> một cơ chế dùng mô phỏng để thử nhiều phương án và xem phương án nào thật sự tốt hơn

Ví dụ:

- cùng một sự cố giao thông
- thử 3 cách xử lý khác nhau
- cho mô phỏng chạy tiếp
- xem cách nào làm ít trễ hơn, ít mất đơn hơn

Sau đó hệ thống giữ lại phương án tốt nhất làm “đáp án chuẩn”.

Ý nghĩa:

- AI không chỉ bắt chước quyết định cũ
- mà học từ phương án đã được mô phỏng và kiểm chứng

---

## 7. Tại sao repo này có cả “runtime” và “train”?

Vì đây là hai nhu cầu khác nhau:

## 7.1 Runtime

Phục vụ cho việc:

- chạy demo
- mô phỏng vận hành
- đưa ra quyết định trực tiếp

## 7.2 Train / offline

Phục vụ cho việc:

- tạo dữ liệu
- đánh giá chất lượng quyết định
- fine-tune model
- thay thế dần decision engine bên ngoài

Nói dễ hiểu:

- runtime là **xe đang chạy**
- offline pipeline là **xưởng chế tạo và huấn luyện bộ não cho xe**

---

## 8. Hệ thống có những chế độ chạy nào?

Ở mức vận hành, có vài chế độ quan trọng:

## 8.1 Chế độ an toàn, dễ demo

Hệ thống dùng luật đơn giản hoặc heuristic.

Ưu điểm:

- ổn định
- ít phụ thuộc ngoài
- dễ giải thích

## 8.2 Chế độ dùng AI bên ngoài

Hệ thống gọi model ngoài để đề xuất quyết định.

Ưu điểm:

- nhanh thử nghiệm
- chất lượng reasoning tốt

Nhược điểm:

- phụ thuộc API
- phụ thuộc mạng
- có rủi ro chi phí và data governance

## 8.3 Chế độ dùng AI nội bộ tự host

Hệ thống gọi model chạy trên hạ tầng của chính mình.

Ưu điểm:

- phù hợp câu chuyện self-hosted
- không phụ thuộc hoàn toàn vào bên thứ ba
- tốt cho demo hackathon hoặc hệ thống nội bộ

---

## 9. Người vận hành cần quan tâm điều gì?

Người không chuyên kỹ thuật không cần đọc code, nhưng nên biết vài điểm:

## 9.1 Hệ thống rất phụ thuộc cấu hình

Nhiều hành vi được đổi bằng config:

- có dùng cuOpt hay không
- có dùng NIM hay không
- có dùng AI ngoài hay không
- ngưỡng auto-approve là bao nhiêu

## 9.2 Dataset train phải đúng đường chạy

Đối với phần AI nội bộ, chất lượng dữ liệu rất quan trọng.

Hệ thống đã có path chuẩn để sinh dataset huấn luyện từ mô phỏng.

Nếu sinh dataset sai cách thì:

- command vẫn có thể chạy xong
- nhưng dữ liệu huấn luyện sẽ không tốt

## 9.3 Không phải cứ có AI là tự động tốt hơn

Trong repo này, rule engine và scoring engine vẫn rất quan trọng vì:

- chúng là baseline
- chúng là fallback
- chúng giúp demo ổn định khi endpoint AI gặp sự cố

---

## 10. Hệ thống này mạnh ở đâu?

Những điểm mạnh chính:

- tách module rõ ràng
- dễ đổi engine qua config
- có cả runtime và training pipeline
- có thể demo theo nhiều mức độ
- có đường đi rõ ràng từ rule-based → AI ngoài → AI self-hosted

---

## 11. Hệ thống này chưa phải cái gì?

Đây chưa phải là:

- một sản phẩm production hoàn chỉnh tích hợp ERP/WMS/TMS thật
- một nền tảng đã tối ưu đầy đủ cho mọi bài toán logistics ngoài đời
- một hệ thống “có AI là tự giải được mọi lỗi”

Nó là:

- một nền tảng mô phỏng và điều phối khá đầy đủ
- một bộ khung tốt để demo, nghiên cứu, và tiếp tục phát triển

---

## 12. Nếu chỉ nhớ 5 ý thì nhớ gì?

1. Hệ thống này giúp điều phối giao hàng khi thế giới thay đổi liên tục.
2. Nó có 5 khối chính: mô phỏng, phát hiện sự cố, ra quyết định, phê duyệt, thực thi.
3. Nó có cả đường chạy vận hành và đường chạy huấn luyện AI nội bộ.
4. AI trong hệ thống được dùng để ra quyết định, không chỉ để “chat”.
5. Chất lượng dữ liệu huấn luyện quan trọng không kém chất lượng model.

---

## 13. Nên đọc tiếp gì?

- Muốn hiểu kiến trúc kỹ thuật hơn: `docs/ARCHITECTURE.md`
- Muốn hiểu từng module sâu hơn: `docs/MODULES.md`
- Muốn biết cách chạy thật: `docs/runbooks/2026-06-07-sovereign-brain-fast-runbook.md`
- Muốn quy trình kỹ thuật đầy đủ: `docs/runbooks/2026-06-07-sovereign-brain-technical-runbook.md`
