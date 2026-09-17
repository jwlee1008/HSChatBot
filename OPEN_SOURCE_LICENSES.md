# Open Source Licenses and Third-Party Attributions

본 문서는 **CampusRAG (한성대학교 학내 공지사항 통합 RAG 챗봇 시스템)** 프로젝트에서 사용된 오픈소스 소프트웨어, 사전학습 AI 모델, 외부 시스템 엔진, 웹 폰트, 서드파티 라이브러리 및 데이터의 저작권과 라이선스 고지 사항을 담고 있습니다.

---

## 1. Project License

CampusRAG의 자체 소스 코드는 **MIT License**에 따라 배포됩니다.

```text
MIT License

Copyright (c) 2026 CampusRAG Team (Hansung University Capstone Project)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. Pre-trained AI Models (사전학습 인공지능 모델)

### 2.1 ko-sroberta-multitask (한국어 특화 임베딩 모델)
- **Author / Publisher**: Jeonghoon Gan (jhgan / 정훈 간)
- **Base Architecture**: KLUE RoBERTa (`klue/roberta-base`)
- **Repositories**:
  - Hugging Face: [jhgan/ko-sroberta-multitask](https://huggingface.co/jhgan/ko-sroberta-multitask)
  - GitHub: [jhgan00/ko-sentence-transformers](https://github.com/jhgan00/ko-sentence-transformers)
- **License**: **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**
  - *Attribution*: 본 프로젝트는 정훈 간(jhgan) 님의 `ko-sroberta-multitask` 모델을 학사 공지 유사도 검색 임베딩 엔진으로 사용합니다.

### 2.2 Qwen2.5-1.5B-Instruct (로컬 경량 생성 LLM)
- **Author / Publisher**: Alibaba Cloud (Qwen Team)
- **Repository**: [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
- **License**: **Apache License 2.0**
  - Copyright (c) Alibaba Cloud. Licensed under the Apache License, Version 2.0.

### 2.3 Gemma 2 (google/gemma-2-2b-it)
- **Author / Publisher**: Google LLC
- **Repository**: [google/gemma-2-2b-it](https://huggingface.co/google/gemma-2-2b-it)
- **License**: **Gemma Terms of Use**
  - Google Gemma의 사용 및 배포는 [Gemma Terms of Use](https://ai.google.dev/gemma/terms) 및 [Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy)를 준수합니다.

---

## 3. Typography & Fonts (웹 폰트)

### Pretendard
- **Author**: Kil Hyung-jin (길형진, orioncactus)
- **Repository**: [orioncactus/pretendard](https://github.com/orioncactus/pretendard)
- **License**: **SIL Open Font License 1.1 (OFL-1.1)**
  - Copyright (c) 2021 Kil Hyung-jin (https://github.com/orioncactus/pretendard) with Reserved Font Name 'Pretendard'.
  - 본 폰트는 SIL Open Font License 1.1에 따라 배포 및 웹 폰트로 사용되고 있습니다.

---

## 4. System Tools & Engines (시스템 엔진 및 바이너리)

### 4.1 Tesseract OCR
- **Copyright**:
  - Copyright (c) 1985-1995, Hewlett-Packard Co.
  - Copyright (c) 2006-present, Google LLC and Tesseract contributors
- **License**: **Apache License 2.0**
- **Note**: 공지사항 내 이미지 포스터 및 스캔 PDF 문서의 한국어/영어 텍스트 추출에 사용됩니다.

### 4.2 PDFium (via pypdfium2)
- **Copyright**: Copyright 2014 The PDFium Authors
- **License**: **BSD 3-Clause License**
- **Note**: 스캔 PDF 문서를 OCR하기 위한 페이지 렌더링에 사용됩니다.

---

## 5. Major Third-Party Packages (소프트웨어 의존성)

### 5.1 Python Backend & RAG Stack

| Package | Version | License | Copyright / Authors |
| :--- | :--- | :--- | :--- |
| **langchain** | >=0.3.0 | MIT | Copyright (c) Harrison Chase / LangChain, Inc. |
| **langchain-community** | >=0.3.0 | MIT | Copyright (c) LangChain, Inc. |
| **langchain-chroma** | >=0.2.0 | MIT | Copyright (c) LangChain, Inc. |
| **langchain-huggingface** | >=0.1.0 | MIT | Copyright (c) LangChain, Inc. |
| **langchain-google-genai** | >=2.0.0 | MIT | Copyright (c) LangChain, Inc. |
| **chromadb** | >=0.5.0 | Apache-2.0 | Copyright (c) Chroma Inc. |
| **sentence-transformers** | >=3.0.0 | Apache-2.0 | Copyright (c) UKP Lab, TU Darmstadt (NOTICE 포함) |
| **transformers** | >=4.44.0 | Apache-2.0 | Copyright (c) Hugging Face, Inc. |
| **torch (PyTorch)** | >=2.5.0 | Modified BSD | Copyright (c) Meta Platforms, Inc. / PyTorch contributors |
| **fastapi** | >=0.115.0 | MIT | Copyright (c) Sebastián Ramírez (tiangolo) |
| **uvicorn** | >=0.30.0 | BSD-3-Clause | Copyright (c) Encode OSS Ltd. |
| **requests** | >=2.32.0 | Apache-2.0 | Copyright (c) Kenneth Reitz / PSF (NOTICE 포함) |
| **beautifulsoup4** | >=4.12.0 | MIT | Copyright (c) Leonard Richardson |
| **pypdf** | >=5.0.0 | BSD-3-Clause | Copyright (c) Mathieu Fenniak, Martin Thoma |
| **pypdfium2** | >=4.30.0 | BSD-3-Clause / Apache-2.0 | Copyright (c) pypdfium2-team |
| **olefile** | >=0.47 | BSD-like | Copyright (c) Philippe Lagadec |
| **pillow** | >=10.0.0 | HPND / MIT-CMU | Copyright (c) Jeffrey A. Clark and contributors |
| **python-dotenv** | >=1.0.0 | BSD-3-Clause | Copyright (c) Saurabh Kumar |
| **lxml** | >=5.0.0 | BSD-3-Clause | Copyright (c) Martijn Faassen, Ian Bicking |
| **streamlit** | >=1.40.0 | Apache-2.0 | Copyright (c) Snowflake Inc. / Streamlit Inc. |
| **playwright** | >=1.40.0 | Apache-2.0 | Copyright (c) Microsoft Corporation |

### 5.2 Frontend Web Stack

| Package | Version | License | Copyright / Authors |
| :--- | :--- | :--- | :--- |
| **react** | ^18.3.1 | MIT | Copyright (c) Meta Platforms, Inc. |
| **react-dom** | ^18.3.1 | MIT | Copyright (c) Meta Platforms, Inc. |
| **tailwindcss** | ^4.0.9 | MIT | Copyright (c) Tailwind Labs, Inc. |
| **vite** | ^6.2.0 | MIT | Copyright (c) Yuxi (Evan) You and Vite contributors |
| **typescript** | ^5.7.3 | Apache-2.0 | Copyright (c) Microsoft Corporation |

---

## 6. Notice Files from Apache 2.0 Dependencies

### 6.1 Sentence-Transformers Notice
```text
Sentence-Transformers
Copyright 2019-2023 UKP Lab, TU Darmstadt

This product includes software developed by UKP Lab, TU Darmstadt (https://www.ukp.tu-darmstadt.de/).
```

### 6.2 Requests Notice
```text
Requests
Copyright 2019 Kenneth Reitz

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0
```

---

## 7. Data Attribution & Academic Disclaimer (데이터 출처 및 면책 조항)

1. **데이터 출처 (Source of Data)**:
   - 본 시스템에서 색인 및 검색하는 학내 공지사항 텍스트와 첨부파일(PDF, HWP, HWPX 등)의 모든 원저작권은 **한성대학교(Hansung University)**에 있습니다.
   - Copyright © Hansung University. All Rights Reserved.

2. **비공식 연구 프로젝트 안내 (Academic Project Disclaimer)**:
   - CampusRAG는 한성대학교 캡스톤디자인 비영리 학술 연구 목적으로 개발된 프로젝트이며, 한성대학교 공식 서비스나 보증 기관이 아닙니다.
   - 본 시스템의 AI 생성 답변은 최신 공지 변동 사항이나 오답(Hallucination)이 포함될 수 있으므로, 학사·장학·졸업 등 중요한 일정은 각 답변 하단에 제공되는 **공식 공지 원문 링크**를 반드시 직접 확인하시기 바랍니다.
