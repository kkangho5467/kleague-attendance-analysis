"""
분석용 데이터셋 만들기: 일정·특별 경기 변수를 붙인다 (1단계)

사용법
------
프로젝트 최상위 폴더에서 아래 순서로 실행한다.
    python src/collect/kleague_attendance_merge.py
    python src/collect/build_excluded_matches.py
    python src/features/team_form.py
    python src/features/build_features.py

입력
- data/processed/attendance_clean.csv : 정리된 경기 데이터
- data/processed/team_form.csv        : 경기 직전 순위·form
- data/external/holidays.csv          : 공휴일
- data/external/derby_list.csv        : 더비 (tier 1만 사용)
- data/external/excluded_matches.csv  : 제외 경기

출력
- data/processed/features.csv : 1경기 = 1행 분석용 데이터 (제외 경기도 excluded=1로 남겨 둔다)

새로 만드는 변수
- ln_attendance      log(관중 수). 종속변수
- holiday            공휴일이면 1 (요일 무관)
- day_type           평일 / 평일공휴일 / 주말  (주말에 겹친 공휴일은 '주말')
- derby              tier 1 더비면 1
- home_opener        홈팀의 그 시즌 첫 홈경기면 1
- last_home          홈팀의 그 시즌 마지막 홈경기면 1 (진행 중인 시즌은 아직 0)
- home_first_game, away_first_game
                     그 팀의 시즌 첫 경기면 1. 이때 순위·form은 0으로 채운다.
                     0은 실제 값이 아니므로 반드시 이 더미와 함께 모형에 넣는다.
- excluded           제외 경기 목록에 있으면 1
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
EXT = ROOT / "data" / "external"
OUT_FILE = PROC / "features.csv"

# 아직 끝나지 않은 시즌: 마지막 홈경기를 알 수 없다. 시즌이 끝나면 여기서 지운다.
INCOMPLETE_SEASONS = {2026}


def read(path: Path, **kw) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: 인코딩을 알 수 없음")


def main() -> None:
    df = read(PROC / "attendance_clean.csv", parse_dates=["date"])
    form = read(PROC / "team_form.csv")
    holidays = read(EXT / "holidays.csv", parse_dates=["date"])
    derbies = read(EXT / "derby_list.csv")
    excluded = read(EXT / "excluded_matches.csv")

    df = df.merge(form, on="match_id", how="left", validate="one_to_one")
    df["ln_attendance"] = np.log(df["attendance"])

    # 공휴일·요일 유형
    df["holiday"] = df["date"].isin(holidays["date"]).astype(int)
    df["day_type"] = np.select(
        [df["weekend"] == 1, df["holiday"] == 1], ["주말", "평일공휴일"], default="평일")

    # 더비: 홈·원정 순서와 상관없이 매치업으로 찾는다
    tier1 = derbies[derbies["tier"] == 1]
    pairs = {frozenset(p) for p in zip(tier1["home_team"], tier1["away_team"])}
    df["derby"] = [int(frozenset((h, a)) in pairs) for h, a in zip(df["home_team"], df["away_team"])]

    # 첫 홈경기·마지막 홈경기 (홈팀 기준, 시즌별)
    order = df.groupby(["season", "home_team"])["date"]
    df["home_opener"] = (df["date"] == order.transform("min")).astype(int)
    df["last_home"] = (df["date"] == order.transform("max")).astype(int)
    df.loc[df["season"].isin(INCOMPLETE_SEASONS), "last_home"] = 0

    # 시즌 첫 경기 표시 + 결측 채우기
    for side in ["home", "away"]:
        first = df[f"{side}_games_pre"] == 0
        df[f"{side}_first_game"] = first.astype(int)
        df.loc[first, [f"{side}_rank_pre", f"{side}_form5"]] = 0

    df["excluded"] = df["match_id"].isin(excluded["match_id"]).astype(int)

    cols = [
        "match_id", "season", "league", "date", "month", "weekday", "weekend", "holiday", "day_type",
        "home_team", "away_team", "stadium",
        "attendance", "ln_attendance",
        "home_rank_pre", "away_rank_pre", "home_form5", "away_form5",
        "home_first_game", "away_first_game", "home_games_pre", "away_games_pre",
        "derby", "home_opener", "last_home", "final_round", "excluded",
    ]
    out = df[cols]
    out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(out)}경기, 제외 {out['excluded'].sum()}경기)")
    print("\n[변수별 해당 경기 수]")
    for c in ["holiday", "derby", "home_opener", "last_home", "final_round", "home_first_game", "away_first_game"]:
        print(f"  {c:<16} {out[c].sum():>4}")
    print("\n[요일 유형]")
    print(out["day_type"].value_counts().to_string())
    if INCOMPLETE_SEASONS:
        print(f"\n참고: {sorted(INCOMPLETE_SEASONS)}시즌은 진행 중이라 last_home을 모두 0으로 두었습니다.")


if __name__ == "__main__":
    main()
