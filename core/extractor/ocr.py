"""
로컬 Tesseract 기반 한국어/영어 이미지 OCR 모듈.

파일 내용(바이트) 해시와 추출 설정(언어, psm 등)을 기준으로
OCR 결과를 캐싱하여 고비용 서브프로세스 재실행을 방지한다.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)

OCR_CACHE_DIR = Path("data/cache/ocr")

# Tesseract 바이너리 경로 검색
TESSERACT_CANDIDATES = [
    os.getenv("TESSERACT_PATH"),
    shutil.which("tesseract"),
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]


def get_tesseract_binary() -> str | None:
    """사용 가능한 Tesseract 실행 파일 경로를 반환한다."""
    for candidate in TESSERACT_CANDIDATES:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def extract_image_text(
    image_path: Path | str,
    lang: str = "kor+eng",
    psm: int = 3,
    timeout_sec: int = 30,
    use_cache: bool = True,
    cache_dir: Path | str | None = None,
) -> tuple[str, str, str | None]:
    """
    이미지 파일에서 텍스트를 추출한다.

    파일 내용의 SHA-256 해시와 추출 설정(lang, psm)을 기준으로 결과를 캐싱/재사용한다.

    Args:
        image_path: 로컬 이미지 파일 경로
        lang: Tesseract 언어 (기본: kor+eng)
        psm: Page segmentation mode (기본: 3)
        timeout_sec: OCR 실행 타임아웃(초)
        use_cache: 파일 내용 해시 기반 캐시 사용 여부
        cache_dir: 사용자 정의 캐시 디렉터리 (테스트 격리 지원)

    Returns:
        (extracted_text, status, error_message)
        status: "success", "empty", "ocr_tool_missing", "failed"
    """
    path = Path(image_path)
    if not path.exists() or path.stat().st_size == 0:
        return "", "failed", f"파일이 존재하지 않거나 비어있습니다: {path}"

    # 1. 파일 내용 해시 및 추출 설정 기반 캐시 확인
    cache_file = None
    cache_root = Path(cache_dir) if cache_dir is not None else OCR_CACHE_DIR
    if use_cache:
        try:
            cache_root.mkdir(parents=True, exist_ok=True)
            with open(path, "rb") as f:
                content_sha256 = hashlib.sha256(f.read()).hexdigest()
            config_sig = f"{content_sha256}_{lang}_psm{psm}"
            cache_key = hashlib.sha256(config_sig.encode("utf-8")).hexdigest()
            cache_file = cache_root / f"{cache_key}.json"

            if cache_file.exists():
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                cached_status = data.get("status")
                # 일시적 실패 상태(failed, ocr_tool_missing 등)는 캐시로 신뢰하지 않고 재시도
                if cached_status in ("success", "empty"):
                    logger.debug("OCR 캐시 재사용: %s (hash=%s)", path.name, content_sha256[:8])
                    return data["text"], data["status"], data.get("error")
                else:
                    logger.info("실패한 이전 OCR 캐시 무시 및 제거 후 재시도: %s (status=%s)", path.name, cached_status)
                    try:
                        cache_file.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("OCR 캐시 확인 실패 (%s): %s", path, e)

    tess_bin = get_tesseract_binary()
    if not tess_bin:
        msg = "Tesseract 실행 도구를 찾을 수 없습니다. brew install tesseract 또는 apt-get install tesseract-ocr 필요"
        logger.warning(msg)
        return "", "ocr_tool_missing", msg

    try:
        # PIL을 통한 이미지 무결성 검증 및 전처리
        with Image.open(path) as img:
            img.verify()

        # RGB 변환 (RGBA 투명도 배경 및 CMYK 처리)
        with Image.open(path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
                proc_path = path.with_suffix(".proc.png")
                img.save(proc_path, "PNG")
                target_path = proc_path
            else:
                target_path = path

    except Exception as e:
        logger.warning("이미지 파일 열기/전처리 실패 (%s): %s", path, e)
        return "", "failed", f"이미지 열기 실패: {e}"

    try:
        cmd = [
            tess_bin,
            str(target_path),
            "stdout",
            "-l",
            lang,
            "--psm",
            str(psm),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )

        if proc.returncode != 0:
            err = proc.stderr.strip() or f"Tesseract 종료 코드: {proc.returncode}"
            logger.warning("Tesseract OCR 실행 실패 (%s): %s", path, err)
            result = ("", "failed", err)
        else:
            text = proc.stdout.strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            cleaned_text = "\n".join(lines)

            if not cleaned_text:
                result = ("", "empty", None)
            else:
                result = (cleaned_text, "success", None)

        # 성공/완료된 결과(success, empty)만 캐싱! failed, ocr_tool_missing 등 일시적 실패는 캐시하지 않음
        if use_cache and cache_file and result[1] in ("success", "empty"):
            try:
                cache_data = {
                    "text": result[0],
                    "status": result[1],
                    "error": result[2],
                }
                cache_file.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning("OCR 결과 캐시 저장 실패: %s", e)

        return result

    except subprocess.TimeoutExpired:
        logger.warning("Tesseract 실행 시간 초과 (%s): %d초", path, timeout_sec)
        return "", "failed", f"OCR 타임아웃 ({timeout_sec}초 초과)"
    except Exception as e:
        logger.error("OCR 처리 중 오류 (%s): %s", path, e)
        return "", "failed", str(e)
    finally:
        # 전처리 임시 파일 정리
        proc_path = path.with_suffix(".proc.png")
        if proc_path.exists() and proc_path != path:
            try:
                proc_path.unlink()
            except Exception:
                pass
