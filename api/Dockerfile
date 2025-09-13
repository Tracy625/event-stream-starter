# api/Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Hugging Face 本地缓存，避免每次冷启动都下模型
    HF_HOME=/opt/hf \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONPATH=/app

WORKDIR /app

# 系统依赖：基础网络工具 + （可选）git（某些HF权重需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements 以利用 Docker 层缓存
# 把你的运行依赖都放进 requirements.txt（见下方示例）
COPY api/requirements.txt /app/requirements.txt

# 先装 torch（CPU 轮子），再装其余，减少解析冲突
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
    "torch>=2.3,<3" \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/requirements.txt

# 仅在依赖安装成功后再复制源代码，避免无谓重建
COPY api /app/api
COPY scripts /app/scripts
COPY data /app/data


# 为了让 Uvicorn 在容器里更稳（不必须）
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]