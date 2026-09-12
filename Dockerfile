FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 (캐시 활용을 위해 먼저 복사)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 데이터 적재 (빌드 시 수행)
RUN python scripts/ingest.py

# FastAPI 서버 포트
EXPOSE 8000

# Streamlit 포트
EXPOSE 8501

# 기본 명령: FastAPI 서버 실행
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
