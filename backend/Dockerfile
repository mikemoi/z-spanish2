FROM python:3.12-slim

WORKDIR /app

# 依赖先装，利用层缓存
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 代码 + 前端
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 数据目录（挂载卷做持久化 + 备份）
ENV Z_SPANISH_DATA=/data
RUN mkdir -p /data

EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
