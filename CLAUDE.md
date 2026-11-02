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
data/raw/schedule/     K리그 일정/결과 페이지 복사본 (시즌·리그별 한 파일, 여러 달 이어 붙임)
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
python src/collect/kleague_schedule_merge.py      # 일정 페이지 복사본 → data/processed/schedule_clean.csv (킥오프·라운드·중계)
python src/collect/build_excluded_matches.py     # home_stadiums.csv 기준 → data/external/excluded_matches.csv
python src/collect/fetch_weather.py              # 기상청 ASOS API → data/raw/weather/asos_daily.csv (새 날짜만)
python src/features/team_form.py                 # 경기 직전 순위·form → data/processed/team_form.csv
python src/features/build_features.py            # 모두 합친 분석용 데이터 → data/processed/features.csv
```

- 2026시즌이 끝나면 `build_features.py`의 `INCOMPLETE_SEASONS`에서 2026을 지운다. (그 전에는 `last_home`이 모두 0)

- 작업 환경은 Windows다. 경로는 `pathlib`로 다루고, 스크립트 경로는 `Path(__file__).resolve().parents[...]`로 프로젝트 최상위를 잡는다.
- 한글이 들어간 CSV는 엑셀에서 깨지지 않도록 `encoding="utf-8-sig"`로 저장한다. 읽을 때는 `utf-8-sig`와 `cp949`를 둘 다 시도한다.

## 반드시 지킬 규칙

### 데이터 수집
- **K리그 사이트(kleague.com)를 자동으로 크롤링하는 코드는 만들지 않는다.** robots.txt로 자동 접근을 막고 있다. 원본 표는 사용자가 직접 복사하고, 코드는 정리만 한다.
- 자동화가 필요한 외부 데이터는 공식 API가 있는 것만 쓴다. (예: 기상청 API, 공공데이터포털 특일 정보)
- API 키는 `.env`의 `KMA_API_KEY`에 둔다. `.env`는 커밋하지 않고, 키 값을 출력하거나 코드에 적지 않는다.
- `data/raw/`와 `data/processed/`의 데이터 파일은 커밋하지 않는다. `.gitignore`가 막고 있으니 우회하지 말 것.

### 분석 설계 (편향 방지)
- 순위와 최근 성적 변수는 **경기 직전 값**만 쓴다. 그 경기 결과가 반영된 값을 쓰면 관중이 알 수 없던 정보가 들어간다.
- 더비 목록(`derby_list.csv`)과 제외 경기 목록은 **결과를 보기 전에** 정한다. 분석 결과를 보고 이 파일들을 고치자고 제안하지 않는다.
  - 더비: `tier` 1(위키백과 단독 문서가 있는 더비 10쌍)만 `derby`로 쓴다. tier 2는 검토 기록일 뿐 분석에 쓰지 않는다.
  - 제외: 정규 홈구장이 아닌 곳(공사로 빌린 구장, 중립 구장)에서 열린 홈경기. 자세한 기준은 `data/external/README.md`
- 분석 범위는 2023~2026시즌, 정규 리그 경기다. K리그1 파이널 라운드(34~38R)는 포함하고 `final_round` 더미로 구분한다. 승강 플레이오프·컵대회는 뺀다.
- 순위·form은 시즌마다 새로 센다. 시즌 첫 경기는 결측이고, form은 직전 최대 5경기의 경기당 평균 승점이다. 2020~2022년은 코로나 영향으로 제외한다. 2017년 이전은 유료 관중 집계 전이라 비교하지 않는다.
- 측정의 한계는 `docs/limitations.md`에 모은다. 새 한계를 발견하면 여기에 추가한다.
- 결과는 인과가 아니라 연관성으로 표현한다. ("~일수록 관중이 많았다")

### 모형 (1단계)
- 종속변수는 `log(attendance)`다.
- 구단 고정효과와 시즌 고정효과를 넣은 OLS를 쓴다. (`statsmodels`)
- 표준오차는 구단별 군집 표준오차다.
- 모형은 단계적으로 쌓는다. 모형 1은 일정·날씨, 모형 2는 여기에 경기력, 모형 3은 여기에 상대팀·특별 경기를 더한다.
- 모형 1의 일정 변수에 `night`를 넣는다.
- 모형 3의 상대팀 인기도는 `ln_away_fans_pre`(+ `away_fans_missing`)로 넣는다.
- VIF로 다중공선성을 확인한다.
- 민감도 분석(결과가 기준에 따라 흔들리지 않는지 확인)은 미리 정한 두 가지만 한다.
  1. 매진으로 보이는 경기(`sellout_proxy`=1)를 뺀 모형 3. 경기마다 여는 구역이 달라 판매 좌석 수를 알 수 없으므로, 관중이 경기장·시즌 최다치의 95% 이상에서 5번 이상 멈춘 곳(대구 2023~2025, 포항 2024, 33경기)을 매진으로 본다
  2. 날씨를 대체 관측소 기준(`rain_alt`, `hot_alt`, `cold_alt`)으로 바꾼 모형 3
- 로그 종속변수에서 더미 계수 b는 `(e^b − 1) × 100%`로 해석해 설명한다.

## 데이터 사전 (`data/processed/attendance_clean.csv`)

| 열 | 뜻 |
| --- | --- |
| `match_id` | `YYYYMMDD_홈팀_원정팀` |
| `season`, `league` | 시즌, `K리그1` / `K리그2` |
| `date`, `weekday`, `weekend`, `month` | 날짜, 요일(0=월), 주말 여부, 월 |
| `home_team`, `away_team`, `stadium` | 관중 현황 표기 그대로 (예: 수원, 수원FC, 서울) |
| `attendance` | 관중 수 (종속변수) |
| `away_fans_raw` | 사이트 '원정팀' 열 = 원정 관중 수 (사용자 확인, 2026-11-02). 그 경기 관중의 일부이므로 **설명변수로 직접 쓰지 않는다**. 경기 전 값 `away_fans_pre`로만 쓴다 |
| `home_goals`, `away_goals`, `home_result` | 득점, 홈팀 기준 W/D/L |
| `note` | 사이트 '비고' 열. 주말만 표시하고 공휴일은 표시하지 않는다 |

## 데이터 사전 (`data/processed/team_form.csv`, `match_id`로 붙인다)

| 열 | 뜻 |
| --- | --- |
| `home_rank_pre`, `away_rank_pre` | 경기 전날까지 결과로 매긴 리그 순위. 승점 → 다득점 → 득실차 → 다승. 파이널 라운드는 A(1~6)·B(7~12) 그룹 안 순위 |
| `home_form5`, `away_form5` | 직전 최대 5경기 경기당 평균 승점 (0~3) |
| `home_games_pre`, `away_games_pre` | 그 시즌 직전까지 치른 경기 수 |
| `final_round` | K리그1 34~38라운드면 1 |

## 데이터 사전 (`data/processed/features.csv`, 분석용 최종 데이터)

위 두 표의 열에 아래를 더한다.

| 열 | 뜻 |
| --- | --- |
| `ln_attendance` | log(관중 수). 종속변수 |
| `holiday` | 공휴일이면 1 (요일 무관, 근로자의 날 포함) |
| `day_type` | 평일 / 평일공휴일 / 주말. 주말에 겹친 공휴일은 '주말' |
| `derby` | tier 1 더비면 1 |
| `home_opener`, `last_home` | 홈팀의 시즌 첫·마지막 홈경기 |
| `home_first_game`, `away_first_game` | 그 팀의 시즌 첫 경기면 1. 이때 순위·form은 0으로 채워져 있으니 **반드시 이 더미와 함께 모형에 넣는다** |
| `excluded` | 제외 경기면 1. 모형에서는 `excluded == 0`만 쓴다 |
| `sellout_proxy` | 매진으로 보이는 경기면 1. 관중 수로 만든 기준이라 **민감도 분석 1에서 빼는 용도로만** 쓴다 |
| `rain_mm`, `rain` | 경기장 근처 ASOS 관측소 일강수량, 1mm 이상이면 `rain`=1 (**모형에는 `rain`**) |
| `max_ta`, `min_ta`, `hot`, `cold` | 일 최고·최저기온. `hot`=최고 33℃ 이상(폭염 기준), `cold`=최저 0℃ 이하 |
| `kickoff`, `kickoff_hour`, `night` | 킥오프 시각, 18시 이후 시작이면 `night`=1. 평일 경기는 모두 저녁이라 `night`는 주말·공휴일 안에서의 저녁 vs 낮 차이를 잡는다 |
| `round`, `tv_terrestrial` | 라운드, 지상파(KBS·MBC·SBS) 중계면 1 (18경기뿐이라 기술통계용) |
| `rain_alt`, `hot_alt`, `cold_alt` | 대체 관측소(`stadium_station.csv`의 `alt_stn_id`) 기준 날씨. 민감도 분석에만 쓴다 |
| `away_fans_pre` | 원정팀의 직전 최대 5번 원정경기 평균 원정 관중. 시즌을 넘어 이어서 센다. 원정석이 꽉 찬 경기(`away_fans_capped`=1)는 평균에서 뺀다. 원정석 관중만 집계되는 한계는 `docs/limitations.md` |
| `ln_away_fans_pre`, `away_fans_missing` | log(1 + `away_fans_pre`). 데이터상 첫 원정경기는 0으로 채우고 `away_fans_missing`=1 (**반드시 함께 넣는다**) |

## 다음 할 일 (1단계)

1. ~~`home_rank_pre`, `home_form5`, `away_rank_pre` 계산~~ (완료: `src/features/team_form.py`)
2. ~~`holiday`, `derby`, `home_opener`, `last_home` 변수 생성~~ (완료: `src/features/build_features.py`)
3. ~~날씨 변수 `rain`, `hot`, `cold` 생성~~ (완료: `src/collect/fetch_weather.py`, 대응표 `data/external/stadium_station.csv`)
4. `notebooks/`에 기술통계와 모형 1~3 노트북 작성
5. 수원 삼성 사례 분석: `home_form5 × K리그2` 상호작용

## 작업 방식

- 코드 주석과 설명은 한국어로 쓴다. 변수명과 열 이름은 영어 snake_case를 쓴다.
- 사용자는 행정학 전공 학생이다. 통계 개념이 처음 나오면 한두 문장으로 짧게 설명해 준다.
- 새 스크립트를 만들면 맨 위 docstring에 사용법과 입력·출력 파일을 적는다.
- 커밋 메시지는 한국어로, 무엇을 했는지 한 줄로 쓴다.
