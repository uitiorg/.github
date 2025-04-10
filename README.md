# .github 디렉토리 설명

이 레포지토리에는 Issue Template과 GitHub Actions 워크플로우 파일들이 저장되어 있으며, 코드 품질 관리 및 개발 프로세스 자동화를 위한 작업을 수행합니다. 다른 레포지토리에서 `uses: uitiorg/.github/.github/workflows/review-dog.yml@main` 와 같은 형태로 워크플로우를 불러 사용해 보세요. 현재 정의된 워크플로우는 다음과 같습니다:

## 정의된 워크플로우

*   **`code-review.yml`:**
    *   **실행 시점:** 다른 워크플로우에서 호출 시 (`workflow_call`).
    *   **기능:** Google Gemini AI를 활용하여 변경된 코드에 대한 자동 코드 리뷰를 수행하고 결과를 풀 리퀘스트에 코멘트로 게시합니다. Python 스크립트(`.github/scripts/code_review.py`)를 통해 실제 리뷰 로직을 실행합니다.
    *   **목적:** 자동화된 AI 기반 코드 리뷰를 통해 코드 품질을 개선하고 리뷰 프로세스를 효율화합니다.
    *   **예시:** [데이터팀 활용 사례](https://github.com/uitiorg/ubuntu-crawler/blob/main/.github/workflows/code-review.yml)
    *   **주의사항:** workflow를 사용하는 repo에서 [GEMINI_API_KEY](https://aistudio.google.com/apikey)를 발급받아야 합니다

*   **`jacoco-rule.yml`:**
    *   **실행 시점:** 다른 워크플로우에서 호출 시 (`workflow_call`).
    *   **기능:** Gradle 프로젝트에서 Jacoco를 사용하여 Java 코드 커버리지를 측정하고, 그 결과를 풀 리퀘스트에 코멘트로 게시합니다. 전체 및 변경된 파일에 대한 최소 커버리지 기준을 설정할 수 있지만, 현재는 기준 미달 시 실패 처리는 비활성화되어 있습니다.
    *   **목적:** 코드 커버리지 정보를 개발자에게 제공하여 테스트가 부족한 부분을 파악하고 코드 품질 관리를 돕는 재사용 가능한 워크플로우입니다.

*   **`review-dog.yml`:**
    *   **실행 시점:** 다른 워크플로우에서 호출 시 (`workflow_call`).
    *   **기능:** Gradle 프로젝트에서 Detekt를 사용하여 Kotlin 코드에 대한 정적 분석을 수행하고, Reviewdog을 통해 발견된 문제점들을 풀 리퀘스트에 리뷰 코멘트로 게시합니다.
    *   **목적:** Kotlin 코드의 잠재적 오류, 스타일 위반 등을 자동으로 검사하고 개발자가 풀 리퀘스트에서 바로 확인할 수 있도록 하여 코드 품질을 향상시키는 재사용 가능한 워크플로우입니다.
