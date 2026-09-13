"""
HWP 및 HWPX 문서 텍스트 추출 모듈.

- HWPX: KS X 6101 개방형 문서 포맷 (ZIP + XML) 파싱
- HWP: 한글 5.0 OLE CFBF 형식 파싱 (zlib 압축 해제 및 태그 레코드 파싱)
- 미지원/암호화/배포용 문서에 대한 명확한 상태 및 사유 보고
"""

import logging
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_hwpx_text(file_path: Path | str) -> tuple[str, str, str | None, dict]:
    """
    HWPX 파일에서 텍스트를 추출한다 (ZIP/XML 파싱).

    Returns:
        (extracted_text, status, error, details)
    """
    path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        return "", "failed", f"파일이 없거나 비어있습니다: {path}", {"format": "hwpx"}

    if not zipfile.is_zipfile(str(path)):
        return "", "failed", "유효한 ZIP/HWPX 파일이 아닙니다.", {"format": "hwpx"}

    try:
        sections_text = []
        with zipfile.ZipFile(str(path), "r") as z:
            # section 파일 목록 찾기 (Contents/section0.xml 등)
            section_files = sorted(
                [name for name in z.namelist() if name.startswith("Contents/section") and name.endswith(".xml")]
            )

            if not section_files:
                # 대소문자 차이나 경로 변형 대응
                section_files = sorted(
                    [name for name in z.namelist() if "section" in name.lower() and name.endswith(".xml")]
                )

            if not section_files:
                return "", "failed", "HWPX 내부 section XML을 찾을 수 없습니다.", {"format": "hwpx"}

            for sec_name in section_files:
                with z.open(sec_name) as f:
                    xml_content = f.read()
                    root = ET.fromstring(xml_content)

                    # 모든 <...:t> 태그의 텍스트 수집 (단락 내 텍스트)
                    paras = []
                    # <hp:p> 단락 단위로 순회하여 줄바꿈 보존
                    for elem in root.iter():
                        tag_name = elem.tag.split("}")[-1]
                        if tag_name == "p":
                            p_texts = [
                                child.text
                                for child in elem.iter()
                                if child.tag.split("}")[-1] == "t" and child.text
                            ]
                            if p_texts:
                                paras.append("".join(p_texts).strip())

                    if paras:
                        sections_text.append("\n".join(paras))

        full_text = "\n\n".join(sections_text).strip()
        if not full_text:
            return "", "empty", None, {"format": "hwpx", "sections": len(section_files)}

        return full_text, "success", None, {
            "format": "hwpx",
            "sections": len(section_files),
        }

    except ET.ParseError as e:
        logger.warning("HWPX XML 파싱 오류 (%s): %s", path, e)
        return "", "failed", f"HWPX XML 파싱 오류: {e}", {"format": "hwpx"}
    except Exception as e:
        logger.error("HWPX 파싱 예외 (%s): %s", path, e)
        return "", "failed", str(e), {"format": "hwpx"}


def extract_hwp_text(file_path: Path | str) -> tuple[str, str, str | None, dict]:
    """
    한글 5.0 (HWP) 파일에서 텍스트를 추출한다 (OLE / zlib / 태그 레코드 파싱).

    Returns:
        (extracted_text, status, error, details)
    """
    path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        return "", "failed", f"파일이 없거나 비어있습니다: {path}", {"format": "hwp"}

    try:
        import olefile
    except ImportError:
        return "", "missing_dependency", "olefile 패키지가 필요합니다 (pip install olefile)", {"format": "hwp"}

    if not olefile.isOleFile(str(path)):
        # HWPX 확장자인데 hwp로 저장된 경우 또는 손상 파일
        if zipfile.is_zipfile(str(path)):
            logger.info("HWP 파일이 ZIP 기반이므로 HWPX로 파싱 시도: %s", path)
            return extract_hwpx_text(path)
        return "", "unsupported_format", "표준 HWP 5.0 OLE 포맷이 아닙니다 (구버전 HWP 3.0 또는 일반 텍스트).", {"format": "hwp"}

    try:
        ole = olefile.OleFileIO(str(path))
    except Exception as e:
        return "", "failed", f"OLE 파일 열기 실패: {e}", {"format": "hwp"}

    try:
        # 1. FileHeader 검사
        if not ole.exists("FileHeader"):
            return "", "unsupported_format", "FileHeader 스트림이 없는 비표준 문서입니다.", {"format": "hwp"}

        header_data = ole.openstream("FileHeader").read()
        if len(header_data) < 40:
            return "", "unsupported_format", "FileHeader 크기가 너무 작습니다.", {"format": "hwp"}

        flags = struct.unpack("<I", header_data[36:40])[0]
        is_compressed = bool(flags & 0x01)
        is_encrypted = bool(flags & 0x02)
        is_viewonly = bool(flags & 0x04)

        if is_encrypted:
            msg = "암호화(보안)가 설정된 HWP 문서는 비밀번호 없이 텍스트 추출이 불가능합니다."
            logger.info("%s (%s)", msg, path)
            return "", "unsupported_encrypted", msg, {
                "format": "hwp",
                "encrypted": True,
                "viewonly": is_viewonly,
            }

        # 2. BodyText 섹션 탐색
        sections = [
            e for e in ole.listdir()
            if len(e) >= 2 and e[0] == "BodyText" and e[1].startswith("Section")
        ]
        sections.sort()

        if not sections:
            return "", "unsupported_format", "BodyText 섹션이 없는 문서입니다.", {"format": "hwp"}

        full_sections_text = []

        for sec in sections:
            stream_data = ole.openstream(sec).read()
            if is_compressed:
                try:
                    data = zlib.decompress(stream_data, -15)
                except Exception as e:
                    logger.warning("HWP 섹션 zlib 압축 해제 실패: %s", e)
                    continue
            else:
                data = stream_data

            offset = 0
            sec_text = []
            while offset + 4 <= len(data):
                h = struct.unpack("<I", data[offset:offset+4])[0]
                offset += 4
                tag_id = h & 0x3FF
                size = (h >> 20) & 0xFFF
                if size == 0xFFF:
                    if offset + 4 > len(data):
                        break
                    size = struct.unpack("<I", data[offset:offset+4])[0]
                    offset += 4

                if offset + size > len(data):
                    break
                record_data = data[offset:offset+size]
                offset += size

                # HWPTAG_PARA_TEXT (67)
                if tag_id == 67:
                    chars = []
                    idx = 0
                    while idx + 2 <= len(record_data):
                        code = struct.unpack("<H", record_data[idx:idx+2])[0]
                        idx += 2

                        # 확장 컨트롤 문자: 뒤에 14바이트(총 16바이트) 추가 정보 건너뛰기
                        if code in (1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23):
                            idx += 14
                        # 인라인 컨트롤 문자: 스킵
                        elif code in (4, 5, 6, 7, 8, 9, 19, 20):
                            pass
                        elif code in (10, 13, 31):  # 줄바꿈
                            chars.append("\n")
                        elif code == 30:  # 필드 구분자
                            pass
                        elif 32 <= code < 0xFFFE:
                            chars.append(chr(code))

                    para_text = "".join(chars).strip()
                    if para_text:
                        sec_text.append(para_text)

            if sec_text:
                full_sections_text.append("\n".join(sec_text))

        full_text = "\n\n".join(full_sections_text).strip()
        if not full_text:
            return "", "empty", None, {
                "format": "hwp",
                "sections": len(sections),
                "viewonly": is_viewonly,
            }

        return full_text, "success", None, {
            "format": "hwp",
            "sections": len(sections),
            "viewonly": is_viewonly,
        }

    except Exception as e:
        logger.error("HWP 추출 중 오류 (%s): %s", path, e)
        return "", "failed", str(e), {"format": "hwp"}
    finally:
        try:
            ole.close()
        except Exception:
            pass


def extract_document_text(file_path: Path | str, filename_hint: str | None = None) -> tuple[str, str, str | None, dict]:
    """
    확장자 또는 힌트에 따라 적절한 문서 파서를 호출한다.
    """
    path = Path(file_path)
    name = (filename_hint or path.name).lower()

    if name.endswith(".hwpx"):
        return extract_hwpx_text(path)
    elif name.endswith(".hwp"):
        return extract_hwp_text(path)
    elif name.endswith(".pdf"):
        from core.extractor.pdf import extract_pdf_text
        return extract_pdf_text(path)
    else:
        return "", "unsupported_format", f"지원하지 않는 첨부파일 형식입니다: {name}", {}
