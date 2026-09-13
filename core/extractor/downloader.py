"""
보안 다운로더 및 캐시 모듈.

외부 리소스 다운로드 시 SSRF 방어, 타임아웃, 파일 크기 상한, 재시도 제어 및
ETag/Last-Modified 기반 조건부 재검증 파일 캐시를 제공한다.
"""

import hashlib
import ipaddress
import json
import logging
import os
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/cache/downloads")
DEFAULT_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
DEFAULT_TIMEOUT = (3.0, 10.0)  # (connect timeout, read timeout)
DEFAULT_MAX_RETRIES = 2
MAX_REDIRECTS = 5


def is_ip_private_or_restricted(ip_str: str) -> bool:
    """IP 주소가 사설망, 루프백, 링크로컬, 예약 주소 등 접근 제한 대상인지 확인한다."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return True


def is_safe_url(url: str) -> tuple[bool, str]:
    """
    URL의 스킴과 목적지 IP가 안전한 공인 네트워크 주소인지 검증한다 (SSRF 방어).

    Returns:
        (is_safe, reason)
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"URL 파싱 실패: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"허용되지 않은 스킴: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "호스트명이 누락되었습니다."

    # localhost 문자열 직접 차단
    if hostname.lower() in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
        return False, "로컬호스트 접근 차단"

    # DNS 해석 및 IP 검사
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"호스트명 해석 실패 ({hostname}): {e}"
    except Exception as e:
        return False, f"호스트명 검증 오류 ({hostname}): {e}"

    if not addr_infos:
        return False, "해석된 IP 주소가 없습니다."

    for family, socktype, proto, canonname, sockaddr in addr_infos:
        ip = sockaddr[0]
        if is_ip_private_or_restricted(ip):
            return False, f"비공개/제한된 IP 주소 접근 차단: {hostname} -> {ip}"

    return True, "ok"


class SafeDownloader:
    """SSRF 방지, 파일 크기 제한 및 ETag 재검증 캐싱을 지원하는 파일 다운로더."""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = max_file_size
        self.timeout = timeout
        self.max_retries = max_retries

    def _get_cache_path(self, url: str, filename_hint: str | None = None) -> Path:
        """URL 해시 기반 캐시 파일 경로를 생성한다."""
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        ext = ""
        if filename_hint:
            ext = Path(filename_hint).suffix.lower()
        elif "." in url.split("/")[-1].split("?")[0]:
            ext = Path(url.split("/")[-1].split("?")[0]).suffix.lower()

        clean_ext = ext if len(ext) <= 10 and ext.isalnum() or ext.startswith(".") else ""
        return self.cache_dir / f"{url_hash}{clean_ext}"

    def _get_meta_path(self, cache_path: Path) -> Path:
        return cache_path.with_name(f"{cache_path.name}.meta.json")

    def download_file(
        self,
        url: str,
        filename_hint: str | None = None,
        force_refresh: bool = False,
        validate_cache: bool = False,
    ) -> tuple[Path | None, str, dict]:
        """
        URL에서 파일을 안전하게 다운로드하여 로컬 경로를 반환한다.

        Args:
            url: 대상 URL
            filename_hint: 파일명 힌트
            force_refresh: 캐시 무시하고 강제 재다운로드
            validate_cache: ETag/Last-Modified 조건부 요청으로 서버 변경 여부 재검증

        Returns:
            (cached_file_path, status, metadata)
            status: "cached", "downloaded", "not_modified", "ssrf_blocked", "size_exceeded", "download_failed"
        """
        cache_path = self._get_cache_path(url, filename_hint)
        meta_path = self._get_meta_path(cache_path)

        cached_meta = {}
        if meta_path.exists():
            try:
                cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 1. 재검증 없이 캐시 즉시 사용
        if not force_refresh and not validate_cache and cache_path.exists() and cache_path.stat().st_size > 0:
            logger.debug("캐시된 파일 사용 (재검증 없음): %s (%s)", cache_path, url)
            return cache_path, "cached", {
                "url": url,
                "size_bytes": cache_path.stat().st_size,
                "cached": True,
                "sha256": cached_meta.get("sha256", ""),
            }

        # 2. SSRF 검증
        safe, reason = is_safe_url(url)
        if not safe:
            # 오프라인 환경 또는 일시적 DNS 해석 실패 시, 이미 받아둔 유효 캐시가 있다면 폴백 사용
            # (사설망/루프백 등 실제 SSRF 차단 건은 엄격히 차단 유지)
            if (
                validate_cache
                and not force_refresh
                and cache_path.exists()
                and cache_path.stat().st_size > 0
                and "호스트명 해석 실패" in reason
            ):
                logger.warning("DNS 해석 실패로 기존 캐시 폴백 사용 (%s): %s", url, reason)
                return cache_path, "cached", {
                    "url": url,
                    "size_bytes": cache_path.stat().st_size,
                    "cached": True,
                    "sha256": cached_meta.get("sha256", ""),
                }
            logger.warning("다운로드 차단 (SSRF 방어): %s - %s", url, reason)
            return None, "ssrf_blocked", {"url": url, "error": reason}

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        # 조건부 재검증 헤더 추가
        if validate_cache and cache_path.exists() and cache_path.stat().st_size > 0:
            if cached_meta.get("etag"):
                headers["If-None-Match"] = cached_meta["etag"]
            if cached_meta.get("last_modified"):
                headers["If-Modified-Since"] = cached_meta["last_modified"]

        current_url = url
        last_error = ""

        for attempt in range(self.max_retries + 1):
            try:
                redirect_count = 0
                while redirect_count < MAX_REDIRECTS:
                    safe, reason = is_safe_url(current_url)
                    if not safe:
                        return None, "ssrf_blocked", {
                            "url": current_url,
                            "error": f"리다이렉트 차단: {reason}",
                        }

                    resp = requests.get(
                        current_url,
                        headers=headers,
                        timeout=self.timeout,
                        stream=True,
                        allow_redirects=False,
                    )

                    # 304 Not Modified 처리 (서버 변경 없음 -> 캐시 유지)
                    if resp.status_code == 304:
                        if cache_path.exists() and cache_path.stat().st_size > 0:
                            logger.info("캐시 재검증 완료 (304 Not Modified): %s", url)
                            return cache_path, "cached", {
                                "url": url,
                                "size_bytes": cache_path.stat().st_size,
                                "cached": True,
                                "revalidated": True,
                                "sha256": cached_meta.get("sha256", ""),
                            }

                    # 3xx 리다이렉트 처리 (301, 302, 303, 307, 308)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location")
                        if not location:
                            break
                        current_url = urljoin(current_url, location)
                        redirect_count += 1
                        continue

                    resp.raise_for_status()
                    break

                if redirect_count >= MAX_REDIRECTS:
                    return None, "download_failed", {"url": url, "error": "최대 리다이렉트 횟수 초과"}

                # 파일 크기 헤더 확인
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_file_size:
                    logger.warning("파일 크기 상한 초과 (헤더): %s bytes > %s bytes", content_length, self.max_file_size)
                    return None, "size_exceeded", {
                        "url": url,
                        "error": f"크기 초과 ({content_length} bytes > {self.max_file_size} bytes)",
                    }

                # 청크 스트리밍 다운로드 및 해시 계산
                temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
                downloaded_bytes = 0
                hasher = hashlib.sha256()

                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        downloaded_bytes += len(chunk)
                        if downloaded_bytes > self.max_file_size:
                            f.close()
                            if temp_path.exists():
                                temp_path.unlink()
                            logger.warning("다운로드 중 크기 상한 초과: %s bytes", downloaded_bytes)
                            return None, "size_exceeded", {
                                "url": url,
                                "error": f"다운로드 중 크기 초과 ({downloaded_bytes} bytes)",
                            }
                        f.write(chunk)
                        hasher.update(chunk)

                # 원자적 이동
                temp_path.replace(cache_path)
                file_sha256 = hasher.hexdigest()

                # 캐시 메타데이터 저장
                new_meta = {
                    "url": url,
                    "etag": resp.headers.get("ETag", ""),
                    "last_modified": resp.headers.get("Last-Modified", ""),
                    "size_bytes": downloaded_bytes,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "sha256": file_sha256,
                    "cached_at": time.time(),
                }
                try:
                    meta_path.write_text(json.dumps(new_meta, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass

                logger.info("다운로드 성공: %s (%d bytes, sha256=%s) -> %s", url, downloaded_bytes, file_sha256[:8], cache_path)
                return cache_path, "downloaded", {
                    "url": url,
                    "size_bytes": downloaded_bytes,
                    "cached": False,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "sha256": file_sha256,
                }

            except requests.RequestException as e:
                last_error = str(e)
                logger.warning("다운로드 재시도 (%d/%d) [%s]: %s", attempt + 1, self.max_retries + 1, url, e)
                time.sleep(0.5 * (attempt + 1))
            except Exception as e:
                last_error = str(e)
                logger.error("다운로드 예상치 못한 오류 [%s]: %s", url, e)
                break

        return None, "download_failed", {"url": url, "error": last_error}
