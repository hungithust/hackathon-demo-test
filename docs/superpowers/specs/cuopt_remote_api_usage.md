# Hướng dẫn sử dụng NVIDIA cuOpt API (Remote to Local)

Tài liệu này hướng dẫn cách kết nối và gọi API giải thuật tối ưu hóa lộ trình của **NVIDIA cuOpt NIM** (phiên bản `25.12.0`) đang chạy trên máy chủ (Server có GPU) từ máy tính cá nhân (Local) thông qua bảo mật SSH Tunnel.

## 1. Thiết lập SSH Tunnel

Do API của Server (thường là cổng `8000` hoặc `8001`) không được mở công khai ra Internet để đảm bảo an toàn, chúng ta cần tạo một "đường ống" (Tunnel) từ máy Local đến Server.

Chạy lệnh sau trên **Terminal/CMD của máy Local**:
```bash
ssh -N -L 8001:localhost:8001 <user>@<server_ip>
```
*(Trong đó `8001` là cổng mà Docker container của cuOpt đang map trên Server).*

Sau khi chạy lệnh này, bạn có thể gọi thẳng API vào địa chỉ `http://localhost:8001` ngay trên máy Local như thể phần mềm đang chạy trên máy của bạn.

## 2. Đặc điểm Kiến trúc API cuOpt (Asynchronous Polling)

cuOpt NIM sử dụng cơ chế giải thuật bất đồng bộ. Vì các bài toán lớn có thể tốn nhiều giây đến nhiều phút để GPU tính toán, API không trả về kết quả ngay để tránh Timeout.

**Quy trình chuẩn gồm 2 bước:**
1. **Nộp bài (POST):** Gửi dữ liệu JSON lên `/cuopt/request`. Server ghi nhận và cấp ngay 1 mã số công việc là `reqId`.
2. **Hỏi kết quả (GET):** Nối mã `reqId` vào đuôi của đường dẫn `/cuopt/solution` (Ví dụ: `GET /cuopt/solution/<reqId>`) và liên tục hỏi (polling) cho đến khi server tính toán xong và trả về chuỗi JSON chứa đáp án.

> **Lưu ý quan trọng:** Tuyệt đối không dùng lệnh POST truyền `{reqId: ...}` vào `/cuopt/solution` vì API sẽ hiểu nhầm đó là lệnh nộp bài mới, gây treo vòng lặp vô tận.

## 3. Code Python mẫu (Chạy trên máy Local)

Dưới đây là ví dụ hoàn chỉnh mô phỏng lại cách gửi một bài toán VRP (Vehicle Routing Problem) cơ bản với 2 xe và 2 nhiệm vụ lên Server:

```python
import requests
import time
import json

# Cổng 8001 đã được kéo về Local qua SSH Tunnel
REQUEST_URL = "http://localhost:8001/cuopt/request"
SOLUTION_URL = "http://localhost:8001/cuopt/solution"

# Cấu trúc JSON bài toán VRP
data = {
    "cost_matrix_data": {
        "data": {
            "0": [
                [0, 10, 20],
                [10, 0, 15],
                [20, 15, 0]
            ]
        }
    },
    "task_data": {
        "task_locations": [1, 2]
    },
    "fleet_data": {
        "vehicle_locations": [
            [0, 0],  # Xe 1: Bắt đầu ở đỉnh 0, kết thúc ở đỉnh 0
            [0, 0]   # Xe 2: Bắt đầu ở đỉnh 0, kết thúc ở đỉnh 0
        ]
    }
}

print("1. Đang nộp bài toán...")
# BƯỚC 1: Nộp bài 1 LẦN DUY NHẤT để lấy reqId
response = requests.post(REQUEST_URL, json=data)
req_id = response.json().get("reqId")

if not req_id:
    print("❌ Lỗi nộp bài!")
else:
    print(f"-> Nộp thành công! Mã công việc: {req_id}")
    print("\n2. Đang chờ GPU giải...")
    
    # BƯỚC 2: Polling liên tục chờ kết quả
    while True:
        # Dùng lệnh GET, nối thẳng reqId vào đường dẫn
        sol_response = requests.get(f"{SOLUTION_URL}/{req_id}")
        
        if sol_response.status_code == 200:
            sol_data = sol_response.json()
            
            # API trả về key "response" khi đã giải xong
            if "response" in sol_data:
                print("\n✅ cuOpt ĐÃ GIẢI XONG! KẾT QUẢ:")
                print(json.dumps(sol_data["response"], indent=2))
                break
            else:
                print("⏳ Vẫn đang chờ GPU tính toán...")
        else:
            print(f"❌ Lỗi HTTP: {sol_response.status_code} - {sol_response.text}")
            break
            
        time.sleep(2)
```
