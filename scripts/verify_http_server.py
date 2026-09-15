# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import subprocess
import requests

env = os.environ.copy()
env["CHROMA_PERSIST_DIR"] = "data/integrated_eval_chroma_db"
env["CHROMA_COLLECTION_NAME"] = "campus_knowledge"
port = 8018

print("1. uvicorn 서버 시작 중 (port: %d)..." % port)
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--host", "127.0.0.1"],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

results = {}
try:
    # 1. 헬스체크 폴링
    healthy = False
    for _ in range(40):
        try:
            r = requests.get("http://127.0.0.1:%d/health" % port, timeout=1)
            if r.status_code == 200:
                healthy = True
                results["health"] = r.json()
                print("   -> 헬스체크 성공: %s" % r.json())
                break
        except Exception:
            time.sleep(0.5)

    if not healthy:
        raise RuntimeError("서버 시작 실패")

    # 2. Retrieve 테스트
    r_ret = requests.post(
        "http://127.0.0.1:%d/api/retrieve" % port,
        json={"question": "2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간", "top_k": 3},
        timeout=10,
    )
    ret_data = r_ret.json()
    results["retrieve_test"] = {
        "status_code": r_ret.status_code,
        "results_count": len(ret_data.get("results", [])),
        "top_source": ret_data.get("results", [{}])[0] if ret_data.get("results") else None
    }
    print("   -> Retrieve 성공: %d건 검색됨" % results["retrieve_test"]["results_count"])

    # 3. Query 테스트: 무관 질문 (근거 부족 유보)
    r_irrel = requests.post(
        "http://127.0.0.1:%d/api/query" % port,
        json={"question": "파이썬으로 이진 탐색 트리 구현하는 코드 짜줘", "top_k": 3},
        timeout=25,
    )
    results["query_irrelevant"] = {
        "status_code": r_irrel.status_code,
        "response": r_irrel.json()
    }
    print("   -> Query (무관 질문) 응답 (status %d): %s" % (r_irrel.status_code, r_irrel.json().get("answer", "")[:80]))

    # 4. Query 테스트: 실제 질문 (정상 답변 또는 장애 시 안내문)
    r_q = requests.post(
        "http://127.0.0.1:%d/api/query" % port,
        json={"question": "2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간이 언제야?", "top_k": 3},
        timeout=30,
    )
    results["query_mentoring"] = {
        "status_code": r_q.status_code,
        "response": r_q.json()
    }
    print("   -> Query (멘토링 질문) 응답 (status %d): %s" % (r_q.status_code, r_q.json().get("answer", "")[:80]))

finally:
    print("5. uvicorn 서버 종료 중...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    print("   -> 서버 정상 종료 완료")

with open("data/http_backend_verification.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("결과 저장: data/http_backend_verification.json")
