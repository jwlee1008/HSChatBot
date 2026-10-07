"""
마일스톤 PPTX 2번째 슬라이드 정밀 완성 스크립트 (이미지 깨짐 복구 및 레이아웃 정리)
"""

import copy
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

PPTX_PATH = Path("팀명_프로젝트 마일스톤_(vx.xx)_yyyymmdd.pptx")
BACKUP_PATH = Path("팀명_프로젝트 마일스톤_(vx.xx)_yyyymmdd.backup.pptx")

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

EPIC_BOXES = {
    "Google Shape;110;p2": ("[성과도출-1]", "공지 크롤러 & 전처리 MVP"),
    "Google Shape;106;p2": ("[성과도출-2]", "ChromaDB & 임베딩 검색 엔진"),
    "Google Shape;107;p2": ("[성과도출-3]", "FastAPI & 모바일 웹 프로토타입"),
    "Google Shape;108;p2": ("[성과도출-4]", "OCR 추출 & 상시안내·FAQ 통합"),
    "Google Shape;109;p2": ("[성과도출-5]", "Cloudtype 배포 & UT 10명 검증"),
}

TARGET_SHAPES_FROM_SLIDE1 = [
    "Google Shape;28;p1",  # 착 / 수
    "Google Shape;29;p1",  # 요 / 구 / 정 / 의
    "Google Shape;30;p1",  # 통합 테스트
    "Google Shape;31;p1",  # 유지보수
    "Google Shape;50;p1",  # Sprint 1 내부 (분석및설계, 구현, 단위테스트)
    "Google Shape;54;p1",  # Sprint 1 외곽 테두리 사각형
    "Google Shape;55;p1",  # Sprint 2 그룹
    "Google Shape;61;p1",  # Sprint 3 그룹
    "Google Shape;67;p1",  # Sprint 4 그룹
    "Google Shape;73;p1",  # Sprint 5 그룹
    "Google Shape;79;p1",  # Sprint 1 순환 루프 화살표 이미지 (rId3)
    "Google Shape;80;p1",  # Sprint 2 순환 루프 화살표 이미지 (rId3)
    "Google Shape;81;p1",  # Sprint 3 순환 루프 화살표 이미지 (rId3)
    "Google Shape;82;p1",  # Sprint 4 순환 루프 화살표 이미지 (rId3)
    "Google Shape;83;p1",  # Sprint 5 순환 루프 화살표 이미지 (rId3)
]


def update_presentation():
    # 원본 백업 파일로부터 시작하여 깨끗하게 재생성
    src_file = BACKUP_PATH if BACKUP_PATH.exists() else PPTX_PATH

    with zipfile.ZipFile(src_file, "r") as z_in:
        file_map = {name: z_in.read(name) for name in z_in.namelist()}

    tree1 = ET.fromstring(file_map["ppt/slides/slide1.xml"])
    tree2 = ET.fromstring(file_map["ppt/slides/slide2.xml"])

    spTree1 = tree1.find(".//p:spTree", NS)
    spTree2 = tree2.find(".//p:spTree", NS)

    # 1. 슬라이드 2의 상단 타이틀 갱신: "템플릿" -> "CampusRAG 프로젝트 마일스톤"
    for sp in spTree2.findall(".//p:sp", NS):
        cNvPr = sp.find(".//p:cNvPr", NS)
        if cNvPr is not None and cNvPr.get("name") == "Google Shape;97;p2":
            for t in sp.iter(f"{{{NS['a']}}}t"):
                if t.text:
                    t.text = "CampusRAG 프로젝트 마일스톤"

    # 2. 슬라이드 2의 작성일 갱신: 오타 수정 ("20265-09-15" -> "2026-09-22")
    for sp in spTree2.findall(".//p:sp", NS):
        cNvPr = sp.find(".//p:cNvPr", NS)
        if cNvPr is not None and cNvPr.get("name") == "Google Shape;100;p2":
            for t in sp.iter(f"{{{NS['a']}}}t"):
                if t.text and "작성일" in t.text:
                    t.text = "작성일: 2026-09-22"

    # 3. 성과목표 및 Epic 박스 내용 교체 (가독성 높은 2줄 구조: 태그 + 산출물)
    for sp in spTree2.findall(".//p:sp", NS):
        cNvPr = sp.find(".//p:cNvPr", NS)
        if cNvPr is not None and cNvPr.get("name") in EPIC_BOXES:
            header_txt, detail_txt = EPIC_BOXES[cNvPr.get("name")]
            txBody = sp.find(".//p:txBody", NS)
            if txBody is not None:
                for p in list(txBody.findall("a:p", NS)):
                    txBody.remove(p)

                # Line 1: [성과도출-N]
                p1 = ET.SubElement(txBody, f"{{{NS['a']}}}p")
                pPr1 = ET.SubElement(p1, f"{{{NS['a']}}}pPr")
                pPr1.set("algn", "ctr")
                r1 = ET.SubElement(p1, f"{{{NS['a']}}}r")
                rPr1 = ET.SubElement(r1, f"{{{NS['a']}}}rPr")
                rPr1.set("sz", "750")
                rPr1.set("b", "1")
                rPr1.set("lang", "ko-KR")
                solid1 = ET.SubElement(rPr1, f"{{{NS['a']}}}solidFill")
                srgb1 = ET.SubElement(solid1, f"{{{NS['a']}}}srgbClr")
                srgb1.set("val", "1F4E79")  # 짙은 네이비
                t1 = ET.SubElement(r1, f"{{{NS['a']}}}t")
                t1.text = header_txt

                # Line 2: 세부 내용
                p2 = ET.SubElement(txBody, f"{{{NS['a']}}}p")
                pPr2 = ET.SubElement(p2, f"{{{NS['a']}}}pPr")
                pPr2.set("algn", "ctr")
                r2 = ET.SubElement(p2, f"{{{NS['a']}}}r")
                rPr2 = ET.SubElement(r2, f"{{{NS['a']}}}rPr")
                rPr2.set("sz", "650")
                rPr2.set("b", "0")
                rPr2.set("lang", "ko-KR")
                solid2 = ET.SubElement(rPr2, f"{{{NS['a']}}}solidFill")
                srgb2 = ET.SubElement(solid2, f"{{{NS['a']}}}srgbClr")
                srgb2.set("val", "262626")  # 짙은 차콜
                t2 = ET.SubElement(r2, f"{{{NS['a']}}}t")
                t2.text = detail_txt

    # 4. 슬라이드 1의 프로세스 블록들을 슬라이드 2에 복제하여 추가 (외곽 박스 54 포함)
    target_names_set = set(TARGET_SHAPES_FROM_SLIDE1)
    s2_names = set()
    for el in spTree2:
        cNvPr = el.find(".//p:cNvPr", NS)
        if cNvPr is not None:
            s2_names.add(cNvPr.get("name"))

    for el1 in spTree1:
        cNvPr = el1.find(".//p:cNvPr", NS)
        if cNvPr is not None:
            name = cNvPr.get("name")
            if name in target_names_set:
                new_name = name.replace(";p1", ";p2_added")
                if new_name not in s2_names:
                    cloned_el = copy.deepcopy(el1)
                    # 재귀적으로 모든 p:cNvPr의 ID와 Name 갱신
                    for cnv in cloned_el.iter(f"{{{NS['p']}}}cNvPr"):
                        cname = cnv.get("name", "")
                        if ";p1" in cname:
                            cnv.set("name", cname.replace(";p1", ";p2_added"))
                        old_id = int(cnv.get("id", "100"))
                        cnv.set("id", str(old_id + 500))
                    spTree2.append(cloned_el)
                    s2_names.add(new_name)

    # 5. 테이블 셀(Row 4~9) 정리:
    # 예시 슬라이드(Slide 1)와 동일하게 표 셀 내부를 깨끗이 비워
    # 위에 배치된 프로세스 블록 뒤로 글자가 겹치거나 잘려 나오는 현상(clipping) 방지
    tbl = spTree2.find(".//a:tbl", NS)
    if tbl is not None:
        rows = tbl.findall("a:tr", NS)
        for r_idx in range(4, len(rows)):
            row = rows[r_idx]
            cells = row.findall("a:tc", NS)
            # Col 1~16 셀 내 텍스트 제거 (Col 0은 라벨 유지)
            for c_idx in range(1, len(cells)):
                cell = cells[c_idx]
                txBody = cell.find("a:txBody", NS)
                if txBody is not None:
                    for old_p in list(txBody.findall("a:p", NS)):
                        txBody.remove(old_p)
                    empty_p = ET.SubElement(txBody, f"{{{NS['a']}}}p")
                    empty_pPr = ET.SubElement(empty_p, f"{{{NS['a']}}}pPr")
                    empty_pPr.set("algn", "ctr")
                    endRPr = ET.SubElement(empty_p, f"{{{NS['a']}}}endParaRPr")
                    endRPr.set("lang", "ko-KR")

    # 6. 슬라이드 2의 Relationships 파일에 rId3 추가 (image3.png 스프린트 순환 화살표)
    # 이것이 누락되면 PowerPoint에서 "그림을 표시할 수 없습니다." 오류가 발생함!
    rels_key = "ppt/slides/_rels/slide2.xml.rels"
    rels_str = file_map[rels_key].decode("utf-8")
    rels_root = ET.fromstring(rels_str)

    has_rId3 = False
    for rel in rels_root:
        if rel.get("Id") == "rId3":
            has_rId3 = True
            break

    if not has_rId3:
        new_rel = ET.SubElement(rels_root, f"{{{REL_NS}}}Relationship")
        new_rel.set("Id", "rId3")
        new_rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image")
        new_rel.set("Target", "../media/image3.png")

    ET.register_namespace("", REL_NS)
    file_map[rels_key] = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)

    # 7. Slide 2 XML 직렬화 및 ZIP 저장
    file_map["ppt/slides/slide2.xml"] = ET.tostring(tree2, encoding="utf-8", xml_declaration=True)

    with zipfile.ZipFile(PPTX_PATH, "w", compression=zipfile.ZIP_DEFLATED) as z_out:
        for name, content in file_map.items():
            z_out.writestr(name, content)

    print("SUCCESS: Slide 2 successfully updated and all image relationships restored!")


if __name__ == "__main__":
    update_presentation()

