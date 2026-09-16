FROM python:3.12-slim

WORKDIR /app

# 파이썬 의존성 설치
# 1) PyTorch CPU 전용 버전을 우선 설치하여 4.5GB 이상의 불필요한 CUDA/NVIDIA 패키지 차단
# 2) requirements.txt 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# 소스 코드 및 데이터 복사
COPY . .

# 임베딩 모델 사전 다운로드/캐싱 (서버 첫 요청 시 딜레이 방지)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('jhgan/ko-sroberta-multitask')"

# FastAPI 서버 포트
EXPOSE 8000

# 기본 명령: FastAPI 서버 실행
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
