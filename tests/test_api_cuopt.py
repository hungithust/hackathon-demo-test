import requests
import time
import json
import math
import random

# ==========================================
# 1. TẠO DỮ LIỆU GIẢ LẬP BẰNG PYTHON THUẦN
# ==========================================
random.seed(42)

n_locations = 19  # 0: Depot, 1 -> 18: Điểm giao hàng
n_vehicles = 5  # Số lượng xe tải

# Giả lập tọa độ X, Y
coords = [(random.randint(0, 100), random.randint(0, 100)) for _ in range(n_locations)]

# Tính ma trận khoảng cách và thời gian (Làm tròn 2 chữ số thập phân cho nhẹ payload JSON)
matrix_data = []
for i in range(n_locations):
    row = []
    for j in range(n_locations):
        dist = round(math.hypot(coords[i][0] - coords[j][0], coords[i][1] - coords[j][1]), 2)
        row.append(dist)
    matrix_data.append(row)

# Tạo dữ liệu phụ trợ
demands = [0] + [random.randint(5, 20) for _ in range(18)]
vehicle_capacities = [40, 50, 50, 60, 70]

order_earliest = [0] + [random.randint(0, 120) for _ in range(18)]
order_latest = [500] + [random.randint(180, 400) for _ in range(18)]
service_times = [0] + [10] * 18

vehicle_earliest = [0] * n_vehicles
vehicle_latest = [500] * n_vehicles

# ==========================================
# 2. ĐÓNG GÓI JSON PAYLOAD THEO CHUẨN API
# ==========================================
# Lưu ý: Trong cuOpt API, 'task_data' chỉ chứa thông tin các điểm cần giao (từ 1 đến 18)
# Dữ liệu dạng danh sách đa chiều (mảng của mảng) để hỗ trợ nhiều dimension (ví dụ: vừa có khối lượng, vừa có thể tích)

# ==========================================
# 2. ĐÓNG GÓI JSON PAYLOAD THEO CHUẨN API
# ==========================================
payload = {
    "cost_matrix_data": {
        "data": {"0": matrix_data}
    },
    # ĐÃ XÓA transit_time_matrix_data Ở ĐÂY
    "task_data": {
        "task_locations": list(range(1, n_locations)),
        "demand": [demands[1:]],
        "task_time_windows": [[order_earliest[i], order_latest[i]] for i in range(1, n_locations)],
        "service_times": service_times[1:]
    },
    "fleet_data": {
        "vehicle_locations": [[0, 0]] * n_vehicles,
        "capacities": [vehicle_capacities],
        "vehicle_time_windows": [[vehicle_earliest[i], vehicle_latest[i]] for i in range(n_vehicles)]
    },
    "solver_config": {
        "time_limit": 2.0
    }
}

# ==========================================
# 3. GỌI API & CHỜ KẾT QUẢ (POLLING)
# ==========================================
REQUEST_URL = "http://localhost:8001/cuopt/request"
SOLUTION_URL = "http://localhost:8001/cuopt/solution"

print(f"1. Đang nộp bài toán ({n_locations - 1} đơn hàng, {n_vehicles} xe)...")
try:
    response = requests.post(REQUEST_URL, json=payload, timeout=5)
    response.raise_for_status()
    req_id = response.json().get("reqId")
except requests.exceptions.RequestException as e:
    print(f"Lỗi nộp bài: {e}")
    req_id = None

if req_id:
    print(f"-> Nộp thành công! Mã tiến trình (reqId): {req_id}")
    print("\n2. Đang chờ API giải quyết...")

    MAX_RETRIES = 10
    attempt = 0

    while attempt < MAX_RETRIES:
        try:
            sol_response = requests.get(f"{SOLUTION_URL}/{req_id}", timeout=5)
            sol_response.raise_for_status()
            sol_data = sol_response.json()

            if "response" in sol_data:
                # Trạng thái 0 = SUCCESS
                print(sol_data)
                break
            else:
                print(f"Vẫn đang tính... (Thử lại {attempt + 1}/{MAX_RETRIES})")

        except requests.exceptions.RequestException as e:
            print(f"Lỗi khi lấy kết quả: {e}")
            break

        time.sleep(2)
        attempt += 1

    if attempt == MAX_RETRIES:
        print("Hết thời gian chờ. Hệ thống có thể đang quá tải.")