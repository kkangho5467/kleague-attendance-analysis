# CLAUDE.md

이 파일은 Claude Code가 이 프로젝트를 이해하고 작업하기 위한 안내서다.

## 프로젝트 개요

K리그 홈경기 관중 수를 움직이는 요인을 공개 데이터로 분석하는 프로젝트다.
목적은 **국내 프로구단 경영·마케팅 부서 데이터 분석가 취업용 포트폴리오**다.
그래서 결과는 항상 "구단 마케팅 담당자가 무엇을 할 수 있는가"로 이어져야 한다.

- 작성자: 한신대 공공인재빅데이터융합학부 학생 (행정학 전공, 데이터 분석 학습 중)
- 저장소: https://github.com/kkangho5467/kleague-attendance-analysis
- 연구 설계서: `docs/research_design.md` (전체 설계서 링크 포함)

## 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | 관중 결정요인 분석: 경기 단위 회귀분석 | 진행 중 |
| 2 | 예측 모델 비교: 회귀 vs 트리 모델(XGBoost 등) vs MLP, SHAP 해석 | 예정 |
| 3 | 팬 텍스트 감성분석: 유튜브 댓글 등, 한국어 사전학습 모델 파인튜닝 | 예정 |
| 4 | 자동 갱신 대시보드: 수집 → 재학습 → 배포 파이프라인 (MLOps) | 예정 |

지금은 1단계만 한다. 다른 단계 코드는 요청이 있을 때만 만든다.

## 폴더 구조

```
data/raw/attendance/   K리그 관중 현황에서 손으로 복사한 원본 표 (.txt/.csv/.xlsx)
data/external/         직접 정하는 목록: derby_list.csv, excluded_matches.csv, holidays.csv
data/processed/        스크립트 결과물 (attendance_clean.csv 등)
src/collect/           수집·정리 스크립트
notebooks/             탐색·분석 노트북
reports/figures/       결과 그림
docs/                  연구 설계 문서
```

## 실행

```bash
pip install -r requirements.txt
python src/collect/kleague_attendance_merge.py   # raw 표 → data/processed/attendance_clean.csv
```

- 작업 환경은 Windows다. 경로는 `pathlib`로 다루고, 스크립트 경로는 `Path(__file__).resolve().parents[...]`로 프로젝트 최상위를 잡는다.
- 한글이 들어간 CSV는 엑셀에서 깨지지 않도록 `encoding="utf-8-sig"`로 저장한다. 읽을 때는 `utf-8-sig`와 `cp949`를 둘 다 시도한다.

## 반드시 지킬 규칙

### 데이터 수집
- **K리그 사이트(kleague.com)를 자동으로 크롤링하는 코드는 만들지 않는다.** robots.txt로 자동 접근을 막고 있다. 원본 표는 사용자가 직접 복사하고, 코드는 정리만 한다.
- 자동화가 필요한 외부 데이터는 공식 API가 있는 것만 쓴다. (예: 기상청 API, 공공데이터포털 특일 정보)
- `data/raw/`와 `data/processed/`의 데이터 파일은 커밋하지 않는다. `.gitignore`가 막고 있으니 우회하지 말 것.

### 분석 설계 (편향 방지)
- 순위와 최근 성적 변수는 **경기 직전 값**만 쓴다. 그 경기 결과가 반영된 값을 쓰면 관중이 알 수 없던 정보가 들어간다.
- 더비 목록(`derby_list.csv`)과 제외 경기 목록은 **결과를 보기 전에** 정한다. 분석 결과를 보고 이 파일들을 고치자고 제안하지 않는다.
- 분석 범위는 2023~2026시즌, 정규 라운드다. 2020~2022년은 코로나 영향으로 제외한다. 2017년 이전은 유료 관중 집계 전이라 비교하지 않는다.
- 결과는 인과가 아니라 연관성으로 표현한다. ("~일수록 관중이 많았다")

### 모형 (1단계)
- 종속변수는 `log(attendance)`다.
- 구단 고정효과와 시즌 고정효과를 넣은 OLS를 쓴다. (`statsmodels`)
- 표준오차는 구단별 군집 표준오차다.
- 모형은 단계적으로 쌓는다. 모형 1은 일정·날씨, 모형 2는 여기에 경기력, 모형 3은 여기에 상대팀·특별 경기를 더한다.
- VIF로 다중공선성을 확인하고, 수용률 95% 이상인 매진 경기를 뺀 민감도 분석을 한다.
- 로그 종속변수에서 더미 계수 b는 `(e^b − 1) × 100%`로 해석해 설명한다.

## 데이터 사전 (`data/processed/attendance_clean.csv`)

| 열 | 뜻 |
| --- | --- |
| `match_id` | `YYYYMMDD_홈팀_원정팀` |
| `season`, `league` | 시즌, `K리그1` / `K리그2` |
| `date`, `weekday`, `weekend`, `month` | 날짜, 요일(0=월), 주말 여부, 월 |
| `home_team`, `away_team`, `stadium` | 관중 현황 표기 그대로 (예: 수원, 수원FC, 서울) |
| `attendance` | 관중 수 (종속변수) |
| `away_fans_raw` | 사이트 '원정팀' 열. 원정 관중 수로 보이나 **연맹 확인 전에는 분석에 쓰지 않는다** |
| `home_goals`, `away_goals`, `home_result` | 득점, 홈팀 기준 W/D/L |
| `note` | 사이트 '비고' 열. 주말만 표시하고 공휴일은 표시하지 않는다 |

## 다음 할 일 (1단계)

1. 경기 일정·결과 데이터로 `home_rank_pre`, `home_form5`, `away_rank_pre` 계산 코드 작성
2. `holidays.csv`, `derby_list.csv`를 붙여 `holiday`, `derby`, `home_opener`, `last_home` 변수 생성
3. 기상청 ASOS 일자료와 경기장-관측소 대응표로 `rain_mm`, `temp_extreme` 생성
4. `notebooks/`에 기술통계와 모형 1~3 노트북 작성
5. 수원 삼성 사례 분석: `home_form5 × K리그2` 상호작용

## 작업 방식

- 코드 주석과 설명은 한국어로 쓴다. 변수명과 열 이름은 영어 snake_case를 쓴다.
- 사용자는 행정학 전공 학생이다. 통계 개념이 처음 나오면 한두 문장으로 짧게 설명해 준다.
- 새 스크립트를 만들면 맨 위 docstring에 사용법과 입력·출력 파일을 적는다.
- 커밋 메시지는 한국어로, 무엇을 했는지 한 줄로 쓴다.
