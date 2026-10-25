## CI artifact 저장과 실행 환경 정책

- GitHub Actions artifact를 산출물의 저장·전달 수단으로 사용하지 않는다. `actions/upload-artifact`, `actions/download-artifact`와 외부 action이 간접 생성하는 artifact도 대상이다.
- GitHub-hosted runner 사용을 금지한다. 승인된 프로젝트의 self-hosted 실행 환경과 기존 자원 점유·검증 절차를 따른다. 이 지침을 Mac 또는 Oracle에서 전체 테스트를 임의 실행하거나 실행 환경을 대체하는 승인으로 해석하지 않는다.
- artifact 저장·전달이 필요하면 비공개 Cloudflare R2를 권장한다. 예상 파일 목록, source SHA, 크기·SHA256, 완료 표식과 엄격한 누락 검증을 유지하고 신뢰하지 않는 PR 코드에 장기 쓰기 자격증명을 전달하지 않는다.
- GitHub 저장소·PR·checks·로그와 self-hosted runner는 계속 사용할 수 있다. Actions cache, 컨테이너 이미지와 운영 배포 저장소는 이 artifact 정책의 이전 대상과 구분한다.

### 기존 자료와 CI의 전환 절차

- 기존 artifact는 R2 이관·전체 다운로드 복원 검증과 원본 삭제의 별도 구체적 승인이 완료될 때까지 보존한다. 정책 추가만으로 원본을 삭제하거나 실행 중 CI를 중단하지 않는다.
- 생산자와 소비자를 함께 변경하고 동일 최종 후보의 실제 CI로 검증한다. 기존 hosted workflow는 전환 대상이며, 이 정책을 근거로 새로 실행하거나 hosted fallback을 추가하지 않는다. 실행 환경 변경은 현재 사용자·프로젝트의 명시된 환경과 승인 경계를 따른다.
- 새 자격증명·지속 CI 접근·권한 확대·공개 접근·유료 약정은 대상과 범위를 제시한 별도 승인이 필요하다. PR merge와 운영 전환도 기존 승인 절차를 따른다.
