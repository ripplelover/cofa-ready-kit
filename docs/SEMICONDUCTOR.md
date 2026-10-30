# 반도체 과제를 받았을 때 사용하는 준비 자료

이 자료는 **반도체 데이터 과제가 실제로 주어졌을 때** 쓰는 분석 지침이다. 실제 대회 문제나 예상 정답은 아니다. 특정 수율·Cpk·불량률 기준을 합격선으로 제시하지 않는다. 먼저 [시험 규칙](RULES.md)과 실제 과제 README를 확인한다.

## 1. 어떤 자료를 읽을지 고르기

| 받은 자료·요구 | 첫 확인 | 다음 결과물 |
| --- | --- | --- |
| `tested`, `passed`, 검사 집계 | 같은 검사 단계·모집단인가? 재검사가 섞였는가? | 분자·분모를 표시한 통과율과 소량 손계산 대조 |
| die 좌표·test bin·attempt | 한 행이 die인가 검사 시도인가? 최종 판정은 어떻게 고르는가? | 정책이 명시된 고유 개체 분석 테이블 |
| defect type·좌표·건수 | 결함 사건인가 불량 개체인가? 다중 label은 가능한가? | 분모·미분류가 보이는 Pareto와 조사 우선순위 |
| tool·chamber·시각·센서 | 하나의 비교 가능한 시계열인가? 기준기간은 어디인가? | I-MR 계산·변화 신호·해석 한계 |
| 여러 CSV를 연결해야 함 | 조인 키와 1:1/다:1 관계가 맞는가? | 결합 전후 행·개체·수량 보존 검사 |
| 불량 예측 요구 | 예측 시점에 알 수 있는 정보인가? | 그룹·시간 누수를 검사한 기준 모델과 평가 |
| 공정 개선 설명 요구 | 관찰과 원인 후보가 구분되는가? | 근거·대안 설명·추가 확인 목록 |

Codex에서 다음처럼 필요한 분석을 시작한다.

```text
$cofa-semiconductor
실제 과제 README와 데이터 사전을 먼저 읽어줘.
한 행의 의미, 키, 검사 단계, 시간·단위, 분자·분모를 확인해줘.
확정된 사실과 결과를 바꿀 미확정 조건을 나누고,
가장 중요한 집계 하나를 구현·손계산 대조까지 이어가줘.
불필요한 모델이나 화면을 추가하지 말고 실제 확인한 한계를 남겨줘.
```

Skill 자동 탐색이 안 되면 `.cofa-kit/skills/cofa-semiconductor/SKILL.md`를 직접 읽게 한다. 상세 자료는 Skill 폴더 안에 있어 설치 시 함께 복사된다.

- [행 단위·수율·재검사·조인](../skills/cofa-semiconductor/references/data-contract.md)
- [I-MR·관리한계·규격·공정능력](../skills/cofa-semiconductor/references/spc.md)
- [Pareto·원인 후보·예측 누수](../skills/cofa-semiconductor/references/investigation.md)

## 2. 업무를 이해하는 데 필요한 최소 용어

웨이퍼는 반도체 회로를 만드는 얇은 원판이다. 그 위의 개별 회로 단위인 die와, 여러 die가 들어갈 수도 있는 package를 같은 개수로 세면 안 된다. lot는 이 자료에서 생산·추적 묶음을 가리키는 업무 용어로 쓰되, 구성 수량·ID 유일성·분할/재작업 규칙은 제공 데이터에서 확인한다. [Samsung Wafer](https://semiconductor.samsung.com/support/tools-resources/dictionary/semiconductor-glossary-wafer/), [SK hynix 패키징 설명](https://news.skhynix.com/en/semiconductor-back-end-process-episode-4-packages-part-2/)

| 용어 | 파일을 읽을 때의 의미 |
| --- | --- |
| deposition·증착 | 막을 형성하는 공정. 측정값이 두께인지, 균일도인지 단위와 위치를 확인 |
| lithography·노광 | 빛을 이용해 resist에 패턴을 옮기는 단계. 검사 대상 layer·정렬 기준을 확인 |
| etch·식각 | 필요한 패턴을 남기도록 재료를 제거하는 단계. 깊이·치수와 해당 공정 구간을 확인 |
| ion implantation·이온 주입 | 전기적 특성을 조절하는 공정. recipe의 항목과 결과 측정량을 구분 |
| metrology·inspection | 수치 측정과 결함 검출 자료의 의미가 다를 수 있음. 단위와 판정 기준 확인 |
| test·EDS·final test | 검사 단계가 다르면 모집단과 통과 기준도 다를 수 있으므로 단계명을 보존 |

공정 설명의 배경은 [ASML 제조 단계 소개](https://www.asml.com/en/company/stories/2021/semiconductor-manufacturing-process-steps)를 짧게 재정리했고, 오른쪽 분석 질문은 이 키트의 적용 제안이다. 제조 흐름은 이 표 순서를 한 번 지나가는 단순 직선으로 가정하지 않는다. 검사 단계의 배경은 [Samsung EDS](https://semiconductor.samsung.com/support/tools-resources/fabrication-process/eight-essential-semiconductor-fabrication-processes-part-8-eds-electrical-die-sorting-for-the-perfect-chips/)를 참고한다.

## 3. 처음 10분에 실무자에게 물을 질문

이미 README에 답이 있으면 반복하지 않는다. 먼저 데이터 구조를 보고 결과를 바꾸는 질문을 선택한다.

1. “이 결과로 누가 무엇을 결정하나요? 어느 제품·공정·검사 단계가 대상인가요?”
2. “한 행은 하나의 die, 검사 시도, wafer 집계, 결함 사건 중 무엇인가요? 유일 키는 무엇인가요?”
3. “분모에서 미검사·대기·중단 항목은 어떻게 처리하나요? 수량 결측을 임의로 보완해도 되나요?”
4. “최초 검사와 재검사 중 어떤 통과율이 필요한가요? 최종 판정을 고르는 상태값이 있나요?”
5. “비교 대상 장비들의 제품·recipe·검사량이 같은가요? 알려진 정비·교정·변경 시점이 있나요?”
6. “규격·업무 임계값·비용 기준은 어느 문서에 있나요? 없다면 조사 후보를 제시하는 수준으로 충분한가요?”

질문을 기다리는 동안 키 중복·결측·단위·기간을 확인한다. 답변이 없으면 영향이 큰 규칙을 임의 확정하지 않고 조건별 결과나 미산출 항목을 구분한다. 예를 들어 검사 수가 없는 wafer를 0%로 기록하는 것은 결측을 불량으로 바꾸는 선택이므로 조용히 수행하지 않는다.

## 4. 바로 적용하는 구현 순서

**입력 계약 한 개 → 중요한 계산 한 개 → 손계산 사례 → 예외 입력 → 해석** 순으로 만든다. 기준 문서는 실제 과제가 요구하는 계획·결과 문서 한 곳에 둔다.

| 단계 | 수행 | 완료 확인 |
| --- | --- | --- |
| 입력 계약 | 행 단위·키·분자·분모·단위·재검사 정책 기록 | 실제 컬럼과 값으로 설명할 수 있음 |
| 작은 구현 | 하나의 그룹이나 한 시계열을 처리 | 입력 한 묶음에서 의미 있는 결과가 나옴 |
| 검증 | 손계산과 대조, 결측·0분모·중복·상충값 확인 | 맞는 숫자뿐 아니라 잘못된 입력 처리가 확인됨 |
| 확대 | 같은 계약을 전체 자료에 적용 | 제외 수·기간·그룹별 표본 수가 함께 출력됨 |
| 설명 | 관찰·업무 해석·한계 구분 | 실제 계산보다 큰 결론을 쓰지 않음 |

수율 계산은 **합계의 비율과 비율의 평균**을 먼저 구별한다. 설비 비교는 생산량과 제품 구성 차이부터 본다. 예측 모델은 실제로 요청된 경우에만 만들고, 예측 순간 이후 정보가 들어가지 않았는지 확인한다. 자세한 손계산과 검증 기준은 위 Skill 참고 자료에 있다.

## 5. 키트 계산 도구를 쓸 때

CLI의 `semi yield`는 이미 집계된 `tested`·`passed` 수량을 다룬다. 개별 die 재검사 이력을 자동 판정하거나 결함 건수를 양품 수로 변환하는 도구가 아니다. 먼저 업무 정책에 맞는 입력을 만들고 고유 키를 선택한다.

```bash
python3 .cofa-kit/scripts/cofa.py semi yield --help
python3 .cofa-kit/scripts/cofa.py semi spc --help
```

일반적인 호출 형태는 다음과 같다. `analysis/wafer_counts.csv`와 `analysis/one_series.csv`는 **실제 과제 안에서 작성할 분석 파일의 예시 경로**이며 기본 배포 파일이 아니다. 컬럼과 키는 실제 자료에 맞춘다.

```bash
python3 .cofa-kit/scripts/cofa.py semi yield analysis/wafer_counts.csv --group-by tool_id --key lot_id,wafer_id --tested-col tested --passed-col passed
python3 .cofa-kit/scripts/cofa.py semi spc analysis/one_series.csv --value-col value --time-col timestamp --baseline-count 25
```

`lot_id,wafer_id`는 해당 파일이 wafer별 확정 집계 한 행일 때만 키 예시로 쓴다. 여러 검사 단계·시도가 남아 있으면 이 키가 충분하지 않다. 그룹별 `sum(passed)/sum(tested)`는 같은 단위의 겹치지 않는 모집단일 때 의미가 있다. 원자료에 없는 검사 대상을 추정해서 채우지 않는다.

`semi spc`는 하나의 계열을 받아 앞의 지정된 관측으로 I-MR 한계를 계산하고 이후 관측을 비교한다. 기본적으로 존재하는 알려진 계열 식별 열이 일정한지 확인한다. `25`는 호출 예시일 뿐 정상 기준기간의 보증이나 과학적 최소 표본 기준이 아니다. 기준기간은 업무 근거로 선택한다. 혼합 장비·recipe를 억지로 통과시키려고 계열 식별 열을 빼지 않는다.

자세한 옵션·샘플 실행·반환값은 [반도체 실행 실습](SEMICONDUCTOR-WALKTHROUGH.md)을 사용한다. 선택형 MCP의 `semiconductor_yield`, `spc_monitor`도 같은 종류의 로컬 분석을 위한 것이며, 수율 목표나 공정 안정성을 승인하는 기능이 아니다.

## 6. 보고서에 붙일 해석 제한

- `passed/tested`는 선택한 검사 모집단의 통과율이다. 전체 wafer·출하 수율로 해석하려면 검사 범위가 그 정의와 같아야 한다.
- defects가 결함 사건 수라면 검사 수보다 클 수 있다. 불량 개체 수와 구분한다.
- 관리한계 이탈은 조사 신호다. 규격 불합격이나 특정 공정의 원인 확정이 아니다.
- 이탈이 없다는 결과는 사용한 규칙의 결과이며, 독립성·정규성·안정성 확인을 대신하지 않는다.
- Cpk는 규격과 통계적 조건을 확인한 뒤 다룬다. 키트는 Cpk·합격선 자동 판정을 제공하지 않는다.
- Pareto·상관계수·모델 중요도는 추가 조사 방향을 정하는 자료이며 그 자체가 인과 증거가 아니다.
- 실제 설비 제어·recipe 변경·MES 승인·lot 해제는 이 준비 키트의 범위가 아니다.

통계 근거와 제한은 [SPC 참고](../skills/cofa-semiconductor/references/spc.md), 인과·모델 검증 근거는 [조사 참고](../skills/cofa-semiconductor/references/investigation.md)에 연결했다. 후속 서술형 단계에서는 이 Skill이나 AI 도구를 사용하지 않고 실제로 수행한 판단과 검증을 본인이 설명한다.

자료 확인일: 2026-10-30. 공식 제조사·NIST·라이브러리 문서를 짧게 참고했으며, 원문·이미지·실제 생산 데이터는 포함하지 않았다. 공식 출처의 설명과 키트의 가상 사례·작업 제안은 구분한다.
