# 설치와 연결

**선택형 고급 설정 문서다.** 내일의 기본 흐름은 [README의 시작 요청](../README.md#2-ai-입력란에-이것만-보내세요)으로 필요한 지침 파일을 직접 읽는 방식이며 설치·MCP 등록이 필요하지 않다. 스킬 이름 호출 또는 로컬 검사 도구가 실제로 필요할 때 아래 항목을 사용한다.

## 1. 오늘 개인 PC에서 확인

저장소 폴더에서 PowerShell로 실행합니다.

```powershell
python scripts/cofa.py doctor
python -m unittest discover -s tests -v
python scripts/cofa.py profile examples/defects.csv
```

Python 3.10 이상이 필요합니다. 프로젝트를 열고 `skills/`의 필요한 `SKILL.md`를 읽도록 요청하는 방식은 Python 없이도 가능합니다. 오늘의 로컬 환경 성공이 Cofa 환경의 도구 허용이나 연결 성공을 증명하지는 않습니다.

## 2. 내일 Cofa 작업 공간에 가져오기

먼저 과제 README, 기존 파일, 현재 경로를 확인합니다. 아래는 직접 설치를 선택했고 제공 터미널이 Bash 계열이며 `.cofa-kit`이 아직 없을 때의 예시입니다. 이미 있으면 [기존 폴더 처리](MANUAL.md#4-3-cofa-kit이-이미-있는-경우)를 먼저 따릅니다.

```bash
pwd
ls -la
git clone --depth 1 https://github.com/ripplelover/cofa-ready-kit.git .cofa-kit
python3 .cofa-kit/scripts/install.py --workspace . --dry-run
python3 .cofa-kit/scripts/install.py --workspace .
python3 .cofa-kit/scripts/cofa.py doctor
```

`--dry-run`은 복사 예정만 표시합니다. 동일한 스킬이면 두 번째 설치는 건너뛰고, 다른 내용이 이미 있으면 중단합니다. 기존 스킬을 덮어쓰거나 삭제하지 않습니다. 설치된 위치는 `.agents/skills/cofa-*/SKILL.md`입니다.

`python3`이 없다면 `python --version`을 확인합니다. 둘 다 없다면 환경을 무리하게 재설정하지 말고 제공 Codex에 `.cofa-kit/skills/…/SKILL.md`를 직접 읽게 하세요. 핵심은 스킬의 작업 방식이며 CLI 설치는 필수가 아닙니다.

Clone이 차단되면 다른 도메인·프록시·터널로 우회하지 않습니다. Cofa Helper로 사용법을 확인하고 반복 오류는 문제 신고로 접수합니다. 키트가 없어도 README, 제공 Codex, 기본 셸로 과제를 진행할 수 있습니다.

## 3. 제공 Codex에서 스킬 쓰기

```text
codex
/status
/model
```

`codex`는 터미널 명령이고, 나머지는 Codex 입력란 명령입니다. `/model`에서 **실제 제공 목록의 허용 모델**을 고릅니다. PDF 표기상 권장은 Sol 6.1, Terra 5.6, Luna 6, Sol 6.0입니다. 공개 OpenAI 모델명과 대회 표기를 임의로 바꾸거나 인터넷의 모델 ID를 강제로 입력하지 마세요.

기본 운영 제안은 Sol 6.1이 제공된다면 주 작업에 사용하고, 짧은 분류·요약처럼 범위가 작은 일은 환경에서 허용하는 가벼운 모델을 고려하는 것입니다. 대회 환경별 성능·지연을 측정한 결과는 아닙니다. 첫 요청의 실제 지연과 오류를 보고 판단하세요. 고난도 검토에만 더 많은 추론 시간을 쓰고, 모델을 자주 갈아타며 문맥을 잃지 마세요.

Codex CLI에서는 `$cofa-triage`처럼 명시적으로 호출할 수 있습니다. 이미 열린 세션에 스킬 목록이 즉시 반영되는지는 제공 버전에 따라 확인합니다. 목록에 없으면 **파일 경로로 읽게 하는 방식이 가장 간단한 대안**입니다. 인증 재설정·개인 로그인·개인 API 키를 추가할 필요가 없습니다.

공식 참고: [스킬 형식과 호출](https://learn.chatgpt.com/docs/build-skills). 대회 환경의 적용 방법은 제공 환경의 안내를 우선합니다.

## 4. 선택형 로컬 MCP

Skill은 작업 지침이고, MCP는 AI가 호출할 수 있는 도구 연결입니다. 이 키트의 MCP는 같은 작업 환경에서 Python 프로세스로 실행됩니다. HTTP 서버, 포트 공개, 외부 계정, API 키가 없습니다. 버전 1.2.1의 제공 도구는 다섯 가지입니다.

| 도구 | 읽는 것 | 결과 |
|---|---|---|
| `workspace_check` | 지정 작업 폴더의 요구사항 파일 | 미완료 선언·누락 파일·근거 경로 확인 |
| `profile_csv` | 지정 작업 폴더 안의 CSV | 제한된 행의 결측·중복·숫자 요약 |
| `semiconductor_yield` | 같은 검사 모집단의 집계 CSV | 그룹별 합격 수 / 검사 수, 중복 키·잘못된 수량 검사 |
| `spc_monitor` | 한 공정 조건의 시간순 계측 CSV | 고정된 과거 기준의 I-MR 관리 한계와 이후 신호 |
| `csv_join_audit` | 결합하려는 두 CSV와 각각의 키 | 키 유일성·미매칭·예상 결합 행 수. 실제 조인·합계 보존은 별도 검사 |

반도체 도구의 열 이름·분모·기준 구간은 실제 과제를 읽고 지정해야 합니다. 정확한 예제와 해석은 [반도체 실행 실습](SEMICONDUCTOR-WALKTHROUGH.md)을 보세요. MCP의 최대 행 수는 10,000이며 전체 결과가 너무 크면 CLI를 사용합니다.

여러 CSV를 결합할 때는 [조인 검사 실습](DATA-JOIN.md)을 참고하세요. 새 기능도 같은 `cofa_local` 서버에 있으므로 별도 MCP 서버를 추가하지 않습니다. 현재 세션의 도구 목록 갱신은 제공 환경 안내를 따르고, 새 도구가 보이지 않으면 같은 검사의 CLI를 사용합니다. 업데이트된 반도체 스킬과 기존 설치본이 달라 설치가 멈추면 기존 파일을 보존하고 최신 `.cofa-kit/skills/cofa-semiconductor/SKILL.md`를 직접 읽게 하세요.

실행 명령이나 임의 코드, 파일 쓰기, 원격 요청 도구를 MCP로 노출하지 않습니다. 결과는 연결된 제공 Codex로 돌아갑니다. 서술형 단계에서는 사용하지 않습니다.

### Cofa MCP 탭을 사용할 때

```bash
python3 .cofa-kit/scripts/install.py --workspace . --mcp-json
```

현재 환경의 **실제 Python 경로와 실제 작업 경로**가 들어간 JSON을 출력합니다. 출력에는 `mcpServers.cofa_local.command`와 `args`가 들어갑니다. PDF는 MCP 탭의 JSON 편집·저장을 지원한다고 설명하지만 정확한 JSON 스키마를 명시하지는 않습니다. 탭 예시와 구조가 같을 때 기존 서버를 보존하며 `cofa_local` 항목을 추가하세요. 구조가 다르면 Cofa Helper로 확인하고 그동안 CLI를 사용합니다. 전체 설정을 지우고 교체하지 마세요.

### 일반 Codex CLI에서 사용하는 표준 명령

제공 환경이 이 CLI 등록 방식을 안내하거나 허용할 때만 사용할 수 있는 대안입니다.

```bash
codex mcp add cofa_local -- python3 -u "$PWD/.cofa-kit/scripts/mcp_server.py" --workspace "$PWD"
codex mcp list
```

Codex 입력란에서는 `/mcp`로 상태를 확인합니다. 일반 Codex의 표준 방법을 확인한 것이며, Cofa가 이 경로를 지원한다고 보장하지 않습니다. 등록을 위해 관리자 설정이나 연결 프로세스를 수정하지 않습니다. 참고: [OpenAI MCP 설정 문서](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

연결 확인용 요청:

```text
cofa_local의 profile_csv로 .cofa-kit/examples/defects.csv를 요약해 줘.
샘플 행 수와 전체 행 수를 구분하고, 이 결과가 과제 정확성을 검증한 것은 아님을 밝혀 줘.
```

### MCP를 꼭 연결해야 하나?

아니요. 다음 CLI가 동일한 핵심 검사를 합니다.

```bash
python3 .cofa-kit/scripts/cofa.py profile .cofa-kit/examples/defects.csv
python3 .cofa-kit/scripts/cofa.py check --workspace .
```

설정에 2–3분 이상 막히면 CLI로 진행하는 것이 운영상 유리하다는 제안입니다. 연결 성공 자체가 평가 목표라는 근거는 없습니다. 원격 MCP를 무더기로 연결하면 문제나 코드가 요청에 실릴 수 있으므로, 이 키트의 시험 기본 구성에는 원격 MCP를 넣지 않았습니다.

## 5. Browser 확인

실제 과제가 웹 서비스를 요구할 때만 서버를 실행합니다. 플랫폼 내 Browser에서 포트와 경로를 지정하고 사람이 직접 기능을 확인합니다. 서버는 `0.0.0.0`에 바인딩해야 합니다. 예를 들어 기존 프로젝트가 Vite라면 프로젝트 스크립트를 확인한 뒤 `npm run dev -- --host 0.0.0.0`을 고려할 수 있습니다. 포트는 터미널이 출력한 실제 값을 사용합니다.

서버 터미널을 유지하고, 연결이 안 되면 **오류 로그 → 프로세스 생존 → 포트 → 바인딩 → 경로** 순서로 봅니다. 외부 터널·배포가 필요하지 않습니다. Browser 자동 조작을 추가하지 마세요. Computer Use 금지와 브라우저 테스트 도구의 구체적 경계가 별도 안내되지 않은 상황에서는 UI 수동 검증과 함수·API 테스트를 사용합니다.

## 6. 공개 저장소 게시와 시험 중 동작을 구분

준비 키트의 공개 게시는 **시험 전 개인 PC에서** 진행합니다. `docs/PUBLISH.md`를 보세요. 시험 중에는 공개본을 가져오기만 하고 시험 작업을 GitHub로 보내지 않습니다. 제출은 플랫폼의 제출 절차로 진행합니다.
