FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS web-build
WORKDIR /web
COPY frontend-web/package*.json ./
RUN npm ci
COPY frontend-web/ ./
RUN npm run build

FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

WORKDIR /app

# 파이썬 의존성 설치 (재현성을 위해 잠금 파일 사용)
COPY requirements-lock.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

# 애플리케이션과 공개 지식 seed만 복사 (개인 DB/.env 제외)
COPY config.py ./
COPY backend/ backend/
COPY core/ core/
COPY scripts/sqlite_snapshot.py scripts/sqlite_snapshot.py
COPY data/unified_campus_knowledge.json data/unified_campus_knowledge.json
COPY data/integrated_eval_chroma_db/ data/integrated_eval_chroma_db/
COPY --from=web-build /web/dist frontend-web/dist/

# Model downloads happen only when RAG is explicitly initialized at runtime.
ENV AUTH_DB_PATH=/var/lib/campusmate/campusmate.db \
    PREWARM_RAG_ON_STARTUP=false \
    PYTHONUNBUFFERED=1

# FastAPI 서버 포트
EXPOSE 8000

# 기본 명령: FastAPI 서버 실행
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
