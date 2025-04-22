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
 
* **`auto-add-to-project.yml`:**

    * 실행 시점: 다른 워크플로우에서 호출 시 (workflow_call).
    * 기능: 이슈 또는 풀 리퀘스트가 생성될 때, 지정된 Organization 프로젝트에 자동으로 추가합니다. 프로젝트 URL은 입력 파라미터로 설정 가능하며, 기본값은 https://github.com/orgs/uitiorg/projects/2 입니다.
    * 목적: 새로운 이슈나 풀 리퀘스트를 프로젝트 보드에 수동으로 추가하는 번거로움을 줄여 개발 및 관리 프로세스를 효율화합니다.
    * 사용 방법: 워크플로우를 호출하는 YAML 파일의 jobs.<job_id>.steps.uses 아래 with 구문을 사용하여 project-url을 필요에 따라 설정할 수 있습니다. Organization 프로젝트에 접근하기 위한 ADD_TO_PROJECT_PAT 시크릿 토큰이 필요할 수 있습니다.
 
* **`sync-main-to-develop.yml`:**

    * 실행 시점: 다른 워크플로우에서 호출 시 (workflow_call).
    * 기능: main 브랜치의 변경 사항을 자동으로 develop 브랜치에 동기화합니다. main_branch와 develop_branch 인풋을 통해 동기화할 브랜치 이름을 유연하게 설정할 수 있습니다.
    * 목적: main 브랜치에 병합된 최신 코드를 개발 브랜치에 자동으로 반영하여 개발 환경을 최신 상태로 유지하고 브랜치 간의 격차를 줄입니다.
    * 사용 방법: 워크플로우를 호출할 때 필요한 경우 main_branch와 develop_branch 인풋 값을 설정할 수 있습니다. API 호출을 위해 GITHUB_TOKEN 시크릿이 필요합니다. 충돌이 발생할 경우 풀 리퀘스트를 생성하고 코멘트를 남기지만, 자동으로 병합하지는 않습니다.
 
* **`org-deploy.yml`:**

    * 실행 시점:
         - workflow_dispatch: 수동 트리거 (target_branch 입력, 기본: main).
         - pull_request: main 병합 시 (release/, hotfix/ 접두사 브랜치).
         - workflow_call: 다른 워크플로우에서 호출 (deploy-script 필수, target-branch 선택).
    * 기능: 빌드, Docker 이미지 빌드 & ECR 푸시, 원격 서버 배포 스크립트 실행 (macOS 러너).
    * 목적: 2.0 서비스를 위한 자동 빌드 및 배포 파이프라인.
    * 필수 시크릿: REPO_NAME, ACCESS_KEY, SECRET_KEY, INSTANCE_IP, INSTANCE_USERNAME, INSTANCE_KEY, SSH_PORT.
    * 사용 방법:
         - 수동: workflow_dispatch 시 target_branch 설정.
         - 자동: release/ 또는 hotfix/ 브랜치 main 병합 시.
         - 호출: workflow_call 시 deploy-script 경로 입력.
    * 주의사항: 대상 서버 aws CLI, docker 필요. macOS ss 명령어 관련 문제 해결 (스크립트 내 자동 수정).
