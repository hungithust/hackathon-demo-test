Dưới đây là bản Markdown được parse và chuẩn hóa từ PDF. Mình đã giữ nguyên nội dung, cấu trúc lại tiêu đề, bảng và code block để dễ đọc hơn.

> Nguồn: NVIDIA Hackathon 2026 — Hướng dẫn cho đội thi 

---

# NVIDIA Open Hackathon 2026

## Tổng quan

Mỗi đội thi được cấp một server H200 dùng riêng trong suốt cuộc thi — nguyên cả máy, không chia sẻ với đội khác.

Đội toàn quyền sử dụng 8 GPU, storage và môi trường của máy mình.

| Tài nguyên | Thông số                |
| ---------- | ----------------------- |
| GPU        | 8× NVIDIA H200 (Hopper) |
| GPU Memory | ~1.1 TB (8×141 GB)      |
| RAM        | ~2 TB                   |
| CPU        | 192 cores               |
| Storage    | ~28 TB NVMe             |

---

# Hướng dẫn cho đội thi — Tài nguyên & cách truy cập

**Cập nhật:** 2026-05-30

---

## COMPUTE

### 8× H200 + NVSwitch Full Mesh

* 8 GPU NVIDIA H200 (mỗi GPU 141 GB HBM3e)
* Kết nối NVSwitch/NVLink giữa các GPU
* Hỗ trợ training và inference multi-GPU hiệu quả
* CPU Intel Xeon Platinum 8558
* 192 CPU cores
* ~2 TB RAM
* Driver: 580.159.03
* CUDA: 13.0
* NVIDIA Container Toolkit đã cài sẵn

---

## STORAGE

### ~28 TB NVMe local tại `/raid`

Ổ NVMe RAID0 ext4 khoảng 28 TB được mount tại:

```bash
/raid
```

Dùng cho:

* Dataset
* Checkpoint
* Model cache
* Output

Trong JupyterLab:

```bash
/workspace
```

chính là:

```bash
/raid/team
```

Dữ liệu vẫn được giữ lại sau khi restart container.

---

## SOFTWARE

### Stack NVIDIA + NGC sẵn sàng

Máy đã cài:

* Docker với `default-runtime: nvidia`
* JupyterLab
* Image:

```text
nvcr.io/nvidia/pytorch:24.10-py3
```

Đã cấu hình sẵn:

* 8 GPU khả dụng
* Đăng nhập sẵn vào `nvcr.io`

Có thể pull trực tiếp:

```text
nvcr.io/nvidia/*
nvcr.io/nim/*
```

không cần tự cấu hình credentials.

---

## ACCESS

### 2 đường truy cập, không cần VPN

#### 1. JupyterLab

* Truy cập bằng trình duyệt
* Viết và chạy notebook
* Có terminal tích hợp

#### 2. SSH

* Chạy Docker
* Chạy NIM
* Thao tác hệ thống

Không cần VPN.

---

# Cách truy cập

VTS sẽ cấp cho mỗi đội:

| Thông tin               | Mục đích                   |
| ----------------------- | -------------------------- |
| IP máy đội              | Truy cập JupyterLab và SSH |
| JupyterLab password     | Đăng nhập JupyterLab       |
| SSH user + password/key | SSH vào máy                |

---

# 1. JupyterLab (trình duyệt)

Mở:

```text
http://<IP-máy-đội>:8888/lab
```

Nhập password được VTS cung cấp.

Notebook chạy trong container PyTorch với đủ 8 GPU.

Thư mục:

```bash
/workspace
```

được lưu trên ổ `/raid`.

---

# 2. SSH vào máy

```bash
ssh <user>@<IP-máy-đội>
```

Kiểm tra nhanh:

```bash
nvidia-smi
```

```bash
docker ps
```

```bash
df -h /raid
```

Kết quả mong đợi:

* 8× H200
* Driver 580.159.03
* CUDA 13.0
* ~28 TB storage

Máy của đội là máy riêng.

Mọi thay đổi:

* Cài package
* Chạy container
* Ghi file

chỉ ảnh hưởng máy của đội mình.

---

# Sanity Check

## Check 1 — JupyterLab + GPU

```python
import torch

print("CUDA available:", torch.cuda.is_available())
print("GPU count :", torch.cuda.device_count())
print("GPU 0 :", torch.cuda.get_device_name(0))
```

Mong đợi:

```text
CUDA available: True
GPU count: 8
GPU 0: NVIDIA H200
```

---

## Check 2 — GPU hoạt động

```bash
nvidia-smi
```

Mong đợi:

```text
8× NVIDIA H200
Driver 580.159.03
CUDA 13.0
```

---

## Check 3 — Ghi đọc storage

```bash
echo "hello from $(hostname)" > /workspace/hello.txt
cat /workspace/hello.txt
```

SSH dùng:

```bash
/raid/team
```

Kiểm tra:

```bash
df -h /raid
```

Mong đợi:

```text
~27 TB còn trống
```

Nếu cả 3 check pass thì môi trường đã sẵn sàng.

---

# Dùng GPU trong JupyterLab

JupyterLab sử dụng image:

```text
nvcr.io/nvidia/pytorch:24.10-py3
```

Đã có sẵn:

* PyTorch CUDA 13
* Transformer Engine
* Apex
* Triton

---

## Ví dụ DataParallel

```python
import torch
import torch.nn as nn

print("Số GPU:", torch.cuda.device_count())

model = nn.Linear(4096, 4096).cuda()
model = nn.DataParallel(model)

x = torch.randn(2048, 4096, device="cuda")
y = model(x)

print("Output:", y.shape, "trên", torch.cuda.device_count(), "GPU")
```

---

## Tải và chạy LLM từ Hugging Face

```python
!pip install -q transformers accelerate
```

```python
from transformers import pipeline

pipe = pipeline(
    "text-generation",
    model="meta-llama/Llama-3.2-1B",
    device_map="auto",
    torch_dtype="auto"
)

print(
    pipe(
        "Xin chào,",
        max_new_tokens=30
    )[0]["generated_text"]
)
```

---

## Mẹo

Notebook và file trong:

```bash
/workspace
```

được lưu trên:

```bash
/raid
```

nên không mất khi restart container.

Với job dài:

```bash
nohup
```

hoặc

```bash
tmux
```

---

# Theo dõi GPU

```bash
watch -n1 nvidia-smi
```

Hiển thị realtime:

* GPU utilization
* Memory
* Temperature

---

# Chạy Container & NIM bằng Docker

Máy đã cài Docker:

```text
default-runtime: nvidia
```

và đăng nhập sẵn:

```text
nvcr.io
```

---

## Chạy container bất kỳ

```bash
docker run --rm --gpus all \
nvcr.io/nvidia/pytorch:24.10-py3 \
python -c "import torch; print(torch.cuda.device_count(), 'GPU')"
```

Mount storage:

```bash
docker run --rm --gpus all \
-v /raid/team:/workspace \
nvcr.io/nvidia/pytorch:24.10-py3 bash
```

---

# Deploy NIM

Ví dụ:

```text
Llama-3.1-Nemotron-Nano-8B
```

## Bước 1

```bash
export NGC_API_KEY=<key-VTS-cấp>
```

```bash
docker run -d \
--name nim-llama \
--gpus all \
--shm-size=16g \
-e NGC_API_KEY \
-v /raid/nim-cache:/opt/nim/.cache \
-p 8000:8000 \
nvcr.io/nim/nvidia/llama-3.1-nemotron-nano-8b-v1:latest
```

---

## Bước 2

```bash
docker logs -f nim-llama
```

Đợi:

```text
Application startup complete
```

---

## Bước 3

```bash
curl http://localhost:8000/v1/models
```

```bash
curl http://localhost:8000/v1/chat/completions \
-H 'Content-Type: application/json' \
-d '{
  "model":"nvidia/llama-3.1-nemotron-nano-8b-v1",
  "messages":[
    {
      "role":"user",
      "content":"Xin chào!"
    }
  ],
  "max_tokens":50
}'
```

---

## Giới hạn GPU

Mặc định:

```bash
--gpus all
```

Chỉ dùng GPU 0 và 1:

```bash
--gpus '"device=0,1"'
```

---

# Storage

| Đường dẫn         | Ý nghĩa                |
| ----------------- | ---------------------- |
| `/raid/team`      | Thư mục làm việc chính |
| `/workspace`      | Alias của `/raid/team` |
| `/raid/nim-cache` | Cache model NIM        |
| `/raid/docker`    | Docker images/layers   |

---

# Upload dữ liệu

Qua SCP:

```bash
scp ./dataset.tar \
<user>@<IP-máy-đội>:/raid/team/
```

Hoặc:

```bash
wget -P /raid/team https://example.com/dataset.tar
```

Trong JupyterLab có nút Upload cho file nhỏ.

---

# Software có sẵn

## GPU Stack

* Driver 580.159.03
* CUDA 13.0
* NVIDIA Container Toolkit
* NVSwitch Fabric Manager

---

## AI Frameworks

Có sẵn trong image:

```text
pytorch:24.10-py3
```

* PyTorch CUDA 13
* NeMo
* TensorRT
* Transformer Engine
* Triton

Có thể:

```bash
pip install
```

thêm thư viện.

---

## Container & NGC

Đã đăng nhập:

```text
nvcr.io
```

Riêng NIM cần:

```bash
NGC_API_KEY
```

---

# Quy tắc & cô lập

Mỗi đội có:

* Máy H200 riêng
* Credentials riêng
* Mạng riêng

---

## Được phép

* Chạy notebook
* Chạy container
* Chạy NIM
* Cài package
* Ghi dữ liệu vào `/raid`
* Dùng đủ 8 GPU
* Pull mọi container từ NGC
* Mở cổng dịch vụ demo

---

## Không được

* Truy cập máy đội khác
* Truy cập dữ liệu đội khác
* Thay đổi driver
* Thay đổi CUDA
* Thay đổi Docker data-root
* Thay đổi container JupyterLab hệ thống

---

# Trình diễn Demo

## Cách 1 — Mở cổng

Ví dụ Gradio:

```python
demo.launch(
    server_name="0.0.0.0",
    server_port=7860
)
```

Truy cập:

```text
http://<IP-máy-đội>:7860
```

---

## Cách 2 — SSH Port Forward

```bash
ssh -L 7860:localhost:7860 \
<user>@<IP-máy-đội>
```

Sau đó:

```text
http://localhost:7860
```

---

# FAQ

## JupyterLab sai password?

Dùng password do VTS cấp.

---

## Notebook chỉ thấy 1 GPU?

Kiểm tra:

```python
torch.cuda.device_count()
```

Kết quả phải là:

```text
8
```

---

## NIM không tải được model?

Đảm bảo:

```bash
export NGC_API_KEY=<key>
```

và:

```bash
-e NGC_API_KEY
```

---

## Hết GPU Memory (OOM)?

Mỗi H200 có:

```text
141 GB
```

Giải pháp:

* Giảm batch size
* Kiểm tra bằng `nvidia-smi`
* Điều chỉnh `NIM_MAX_MODEL_LEN`

---

## Chạy nhiều NIM song song?

Được.

Ví dụ:

```bash
--gpus '"device=2,3"'
```

và dùng cổng khác nhau.

---

## Job dừng khi đóng trình duyệt?

Dùng:

```bash
tmux
```

hoặc:

```bash
nohup
```

---

## Dữ liệu có mất khi restart?

Không.

Mọi dữ liệu trong:

```bash
/raid
```

và

```bash
/workspace
```

được giữ lại.

---

## Dataset lớn upload thế nào?

```bash
scp
```

hoặc

```bash
wget
```

```bash
/raid/team
```

Còn khoảng:

```text
~27 TB
```

trống.

---

**NVIDIA Open Hackathon 2026**
**Hướng dẫn cho đội thi**
**Cập nhật: 2026-05-30**

**Viettel Solutions × NVIDIA Vietnam Partnership**
