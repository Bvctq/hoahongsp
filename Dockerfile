FROM python:3.10-slim

WORKDIR /app

# Copy file danh sách thư viện vào trước để tận dụng cache của Docker
COPY requirements.txt .

# Tiến hành cài đặt các thư viện cần thiết
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code vào trong container
COPY . .

# Chạy FastAPI bằng Uvicorn, Render sẽ tự cấp cổng qua biến $PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
