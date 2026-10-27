# K리그 관중 결정요인 분석

K리그 홈경기 관중 수를 움직이는 요인을 공개 데이터로 분석하고, 구단 마케팅에 쓸 수 있는 시사점을 도출하는 프로젝트입니다.

## 프로젝트 구성

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | 관중 결정요인 분석 (경기 단위 회귀분석) | 진행 중 |
| 2 | 예측 모델 비교 (회귀 vs 트리 모델 vs MLP) | 예정 |
| 3 | 팬 텍스트 감성분석 | 예정 |
| 4 | 자동 갱신 대시보드 (수집 → 재학습 → 배포) | 예정 |

연구 질문과 가설, 변수 정의는 [docs/research_design.md](docs/research_design.md)에 있습니다.

## 폴더 구조

```
kleague-attendance-analysis/
├── data/
│   ├── raw/attendance/      # K리그 관중 현황에서 복사한 원본 표 (Git 제외)
│   ├── external/            # 직접 정하는 목록: 더비, 제외 경기, 공휴일
│   └── processed/           # 스크립트가 만든 정리 데이터 (Git 제외)
├── src/
│   └── collect/             # 수집·정리 스크립트
├── notebooks/               # 탐색·분석 노트북
├── reports/figures/         # 결과 그림
├── docs/                    # 연구 설계서
└── requirements.txt
```

## 실행 방법

```bash
pip install -r requirements.txt
python src/collect/kleague_attendance_merge.py
```

1. [K리그 관중 현황](https://www.kleague.com/record/audienceDetail.do)에서 시즌·리그별로 '경기별 / 300건 보기'를 조회합니다.
2. 표를 열 이름까지 포함해 복사하고, `data/raw/attendance/`에 `.txt`, `.csv`, `.xlsx` 중 하나로 저장합니다.
3. 위 명령을 실행하면 `data/processed/attendance_clean.csv`가 만들어집니다.

## 데이터 출처

- 경기별 관중 수: [K리그 관중 현황](https://www.kleague.com/record/audienceDetail.do)
- 경기 일정·결과: [K리그 일정/결과](https://www.kleague.com/schedule.do)
- 날씨: [기상자료개방포털](https://data.kma.go.kr) 종관기상관측(ASOS) 일자료

K리그 사이트는 robots.txt로 자동 수집을 제한하고 있어, 원본 표는 직접 복사하고 정리만 코드로 자동화합니다. 원본·가공 데이터는 저장소에 올리지 않습니다.
