# CLI 사용 예제

아래는 저장소 루트에서 사용하는 예제입니다. Cofa 작업 공간에서는 `python scripts/cofa.py`를 `python3 .cofa-kit/scripts/cofa.py`로 바꾸세요. 모든 결과는 로컬 파일·터미널에만 남습니다. 도구 이름이나 출력은 공식 채점 기준이 아닙니다.

## 요구사항을 먼저 적기

```bash
python scripts/cofa.py init --workspace work/practice
```

새 폴더에 `requirements.json`, `decision-log.jsonl`을 만듭니다. 기존 파일이 있으면 덮어쓰지 않습니다. 생성한 요구사항은 의도적으로 `todo`이므로 검사에 실패해야 정상입니다. 실제 과제에서는 다음처럼 **README의 요구사항으로 교체**합니다.

```json
{
  "required_files": ["README.md", "analysis.csv"],
  "criteria": [
    {
      "id": "R1",
      "requirement": "실제 과제가 요구한 계산과 예외 처리 조건",
      "priority": "must",
      "status": "todo",
      "evidence": []
    }
  ]
}
```

위 파일명과 요구사항은 예시일 뿐입니다. 기준마다 사용자가 볼 수 있는 행동 또는 값으로 완료 조건을 적으세요. 예: '대시보드 완성'보다 '필터 적용 시 전체 건수와 표의 행 수가 같고 결과 0건 메시지가 보인다'가 검증하기 쉽습니다.

`priority`는 `must/should/could`, `status`는 `todo/in_progress/verified/blocked` 중 하나입니다. 실제 확인을 마친 뒤에만 `verified`로 바꾸고, 구현 파일과 검증 기록 경로를 `evidence`에 연결하세요. 검증을 안 했거나 실패했다면 상태를 맞게 유지합니다.

## 데이터의 모양 확인

```bash
python scripts/cofa.py profile examples/defects.csv
python scripts/cofa.py profile examples/requests.json --format json
python scripts/cofa.py profile examples/defects.csv --max-rows 3 --output work/profile-sample.json
```

출력 경로의 부모 폴더는 먼저 만들어야 합니다. `--output`은 기존 파일을 덮어쓰지 않습니다. 한글 Windows CSV가 UTF-8로 열리지 않으면 파일 인코딩을 확인한 뒤 `--encoding cp949`를 명시합니다.

요약은 데이터 이해의 출발점입니다. 숫자처럼 보이는 ID·우편번호를 실제 수치로 해석할지는 따로 판단합니다. 기본 최대 10,000행이고, 표본을 읽은 경우 그 범위를 밝힙니다. JSON은 최대 20MiB이며 전체 파일을 파싱한 뒤 레코드 표본을 요약합니다. 큰 파일은 제공 환경에서 목적에 맞는 스트리밍 도구를 선택하세요.

## 판단과 검증을 남기기

```bash
python scripts/cofa.py log --workspace work/practice --kind assumption --summary "빈 값의 처리 규칙이 미확정. 실무자에게 확인할 예정."
python scripts/cofa.py log --workspace work/practice --kind decision --summary "실무자 확인 후 빈 수량은 합산에서 제외하고 누락 건수를 별도 표시한다."
```

실제로 확인하지 않은 답변·테스트를 기록하지 마세요. 직접 입력한 `test` 기록은 사용자의 진술이며 도구가 실행했다는 뜻이 아닙니다. 실제 명령의 실행 결과를 남기려면 `run`을 사용합니다.

```bash
python scripts/cofa.py run --workspace work/practice --id R1 --timeout 30 -- python -m unittest discover -s tests -v
```

위 명령의 `tests`는 **work/practice 안의 실제 과제 테스트**여야 합니다. 증거 폴더에 실행 명령, 종료코드, 소요시간, 제한된 stdout/stderr가 기록됩니다. 일회성 테스트·빌드·분석 명령에 사용하고 개발 서버처럼 계속 실행되는 명령에는 쓰지 마세요. 임의 명령의 네트워크 행동을 차단하는 보안 샌드박스는 아닙니다. 허용된 로컬 검사만 실행하세요.

`run`의 `--id`는 해당 작업 폴더의 `requirements.json`에 존재하는 ID여야 합니다. 결과는 `evidence/<UTC시각-고유값>/result.json`, `stdout.txt`, `stderr.txt`에 저장되고 `decision-log.jsonl`에 연결됩니다. 출력은 기본적으로 스트림마다 앞부분 65,536바이트까지 보존하며 `--max-output-bytes`로 1,024~1,048,576바이트 사이에서 조정합니다. 원래 출력 바이트를 보존하므로 프로그램에 따라 텍스트 인코딩이 UTF-8이 아닐 수 있습니다.

`run`은 요구사항을 자동으로 `verified`로 바꾸지 않습니다. 종료코드 0만으로 올바른 요구사항을 테스트했다고 판단할 수 없기 때문입니다. 일반적인 unittest/pytest 요약에서 테스트 0개·전부 skip·실패를 발견하면 하위 명령이 0으로 끝나도 성공으로 취급하지 않습니다. 이 감지는 텍스트 형식에 의존합니다. 여러 테스트 실행 결과를 한 명령에 섞거나 출력이 잘렸다면 저장된 결과를 직접 검토하세요. timeout은 실행한 자식 프로세스를 종료하지만 자손 프로세스 전체 종료를 보장하지 않습니다.

## 제출 전 구조 검사

```bash
python scripts/cofa.py check --workspace work/practice
python scripts/cofa.py report --workspace work/practice --output work/practice/evidence-summary.md
```

`check`는 필수 파일이 존재하고 비어 있지 않은지, `must` 요구사항이 `verified`로 선언됐는지, 근거 파일이 실제 작업 폴더 안에 존재하고 비어 있지 않은지 확인합니다. 완료로 선언한 필수 요구사항에 근거 경로가 하나도 없어도 실패합니다. `should/could`의 미완료·근거 누락은 `warnings`에 표시되며 그것만으로 종료코드가 1이 되지는 않습니다. 파일 내용의 진실성이나 테스트 품질을 판정하지 않습니다. 빈 요구사항 목록, 필수 파일 누락, 미완료 필수 항목을 정상 통과로 취급하지 않습니다.

`evidence`에는 실행 정보를 담은 `result.json`과 필요한 구현·검증 파일을 연결하세요. 아무것도 출력하지 않은 명령의 `stdout.txt`나 `stderr.txt`는 정상적으로 빈 파일일 수 있으므로 무조건 근거 목록에 넣을 필요는 없습니다. 각 경로는 `--workspace` 폴더 기준 상대 경로이며, 상위 폴더 이동이나 작업 폴더 밖으로 향하는 심볼릭 링크는 허용하지 않습니다. MCP 검사에서 오류가 나오면 같은 `check` 명령을 터미널에서 실행해 `issues`와 입력 오류를 구분할 수 있습니다.

`report`는 현재 요구사항과 실제 기록을 Markdown으로 정리합니다. 자동 생성된 문서를 공식 제출 문서로 그대로 삼지 말고, 과제가 지정한 형식에 맞게 검토·정리하세요. 계획과 실제 구현이 다르면 이유와 현재 상태를 분명히 적습니다.

| 종료코드 | `check` | 의미 |
|---|---|---|
| 0 | 구조 검사 통과 | 기능 정확성은 별도 확인 |
| 1 | 누락·미완료 | 출력의 issues를 해결 |
| 2 | 입력 오류 | 경로·JSON 형식·사용법 확인 |

`run`의 종료코드는 0이면 실행 관찰상 성공, 1이면 실행 실패·시간 초과·인식된 무효 테스트 결과, 2이면 입력·파일 처리 오류입니다. 0도 요구사항 충족을 보증하지 않습니다. `report --output` 역시 기존 파일을 덮어쓰지 않으므로 새 경로를 지정하세요.

정확한 전체 옵션은 `python scripts/cofa.py --help`와 하위 명령의 `--help`를 사용합니다.

## 반도체 검사 집계·계측 데이터

버전 1.1.0부터 다음 두 명령을 제공합니다. 먼저 열의 의미, 검사 모집단, 개체 키, 공정 조건을 확인하세요.

```bash
python scripts/cofa.py semi yield examples/semiconductor/yield_clean.csv --group-by tool_id --key lot_id,wafer_id
python scripts/cofa.py semi spc examples/semiconductor/measurements.csv --value-col value --time-col timestamp --baseline-count 25
```

`semi yield`는 검사 수로 가중한 통과율을 계산하고 복합키 중복·잘못된 수량을 거부합니다. `semi spc`는 한 계열의 앞부분으로 I-MR 기준을 계산하고 이후 관측만 비교합니다. 두 명령 모두 행 수 한도를 넘으면 부분 결과를 전체 집계처럼 반환하지 않고 오류를 냅니다. CLI 최대 행 수는 100,000, MCP는 10,000입니다.

실습의 예상 출력, 실제 데이터의 열 이름 매핑, 오류 대응, MCP 호출 예시는 [반도체 실행 실습](SEMICONDUCTOR-WALKTHROUGH.md)에 있습니다. 결과의 업무 의미와 통계적 한계는 [반도체 안내](SEMICONDUCTOR.md)를 함께 읽으세요. `--output`은 다른 도구와 마찬가지로 새로운 파일에만 씁니다.
