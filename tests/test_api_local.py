import requests
import json

# URL hướng thẳng vào cổng 8002 ở máy bạn (đã được nối với server nhờ SSH Tunnel)
API_URL = "http://localhost:8002/v1/chat/completions"

# Đóng vai trò là hệ thống Sovereign Brain v2
system_prompt = """You are a logistics routing decision agent. Your job is to analyze real-time disruptions and output strict JSON with your decision.
The JSON must contain two keys:
1. "action": One of ["ignore", "divert", "reroute", "cancel", "delay"]
2. "reasoning": A brief explanation of why this action is optimal."""

# Tình huống hóc búa gửi cho con AI
user_prompt = """Event type: flooded_area
Location: Node C045 (District 7)
Severity: High
Details: A sudden heavy rain has completely flooded the main road leading to the depot. 
The water level is above 50cm. Delivery truck V-99 is currently 2km away from this node carrying temperature-sensitive goods."""

print("Đang cầu cứu LLaMA xử lý tình huống ngập lụt...")

payload = {
    "model": "sovereign-brain",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    "max_tokens": 500,
    "temperature": 0.0  # Bắt buộc là 0 để JSON chuẩn xác nhất
}

try:
    response = requests.post(API_URL, json=payload, timeout=30)

    if response.status_code == 200:
        result = response.json()
        answer = result["choices"][0]["message"]["content"]

        print("\n=== QUYẾT ĐỊNH CỦA ĐẠI CA LLaMA ===")
        print(answer)

    else:
        print("\n[LỖI TỪ MÁY CHỦ]:", response.status_code)
        print(response.text)

except requests.exceptions.ConnectionError:
    print("\n[LỖI KẾT NỐI] Không thể gọi được máy chủ. Bạn chắc chắn đã chạy lệnh SSH Tunnel ở Bước 1 chưa?")