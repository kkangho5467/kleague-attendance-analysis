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
- rain_mm            경기장 근처 ASOS 관측소 일강수량 (빈칸 = 비 안 옴 = 0)
- rain               일강수량 1mm 이상이면 1
- max_ta, min_ta     일 최고·최저기온
- hot                일 최고기온 33℃ 이상이면 1 (기상청 폭염 기준)
- cold               일 최저기온 0℃ 이하면 1 (영하)
- rain_alt, hot_alt, cold_alt
                     대체 관측소(alt_stn_id) 기준 같은 변수. 모형 3 민감도 분석용
- ln_away_fans_pre   log(1 + 원정팀의 직전 5번 원정경기 평균 원정 관중). 상대팀 인기도
- away_fans_missing  원정팀의 데이터상 첫 원정경기면 1. 이때 ln_away_fans_pre는 0으로 채운다.
                     (first_game 더미처럼 반드시 함께 모형에 넣는다)
  날씨 입력: data/raw/weather/asos_daily.csv (src/collect/fetch_weather.py가 만듦),
            data/external/stadium_station.csv
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
    stations = read(EXT / "stadium_station.csv")
    weather = read(ROOT / "data" / "raw" / "weather" / "asos_daily.csv", parse_dates=["date"])

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

    # 날씨: 경기장 → 관측소 → 그날 자료. 아직 받지 못한 날은 결측으로 남는다.
    df = df.merge(stations[["stadium", "stn_id"]], on="stadium", how="left", validate="many_to_one")
    df = df.merge(weather[["stn_id", "date", "sum_rn", "max_ta", "min_ta"]],
                  on=["stn_id", "date"], how="left", validate="many_to_one")
    has_weather = df["max_ta"].notna()
    df["rain_mm"] = df["sum_rn"].where(~has_weather, df["sum_rn"].fillna(0))
    df["rain"] = (df["rain_mm"] >= 1).astype("Int64").where(has_weather)
    df["hot"] = (df["max_ta"] >= 33).astype("Int64").where(has_weather)
    df["cold"] = (df["min_ta"] <= 0).astype("Int64").where(has_weather)

    # 민감도 분석용: 대체 관측소 기준 날씨
    alt = weather[["stn_id", "date", "sum_rn", "max_ta", "min_ta"]].rename(
        columns={"stn_id": "alt_stn_id", "sum_rn": "sum_rn_alt", "max_ta": "max_ta_alt", "min_ta": "min_ta_alt"})
    df = df.merge(stations[["stadium", "alt_stn_id"]], on="stadium", how="left", validate="many_to_one")
    df = df.merge(alt, on=["alt_stn_id", "date"], how="left", validate="many_to_one")
    has_alt = df["max_ta_alt"].notna()
    df["rain_alt"] = (df["sum_rn_alt"].fillna(0) >= 1).astype("Int64").where(has_alt)
    df["hot_alt"] = (df["max_ta_alt"] >= 33).astype("Int64").where(has_alt)
    df["cold_alt"] = (df["min_ta_alt"] <= 0).astype("Int64").where(has_alt)

    # 상대팀 인기도: 원정팀이 지난 원정경기들에서 데려온 관중 (경기 전에 알 수 있는 값)
    df["away_fans_missing"] = df["away_fans_pre"].isna().astype(int)
    df["ln_away_fans_pre"] = np.log1p(df["away_fans_pre"]).fillna(0).round(4)

    cols = [
        "match_id", "season", "league", "date", "month", "weekday", "weekend", "holiday", "day_type",
        "home_team", "away_team", "stadium",
        "attendance", "ln_attendance",
        "home_rank_pre", "away_rank_pre", "home_form5", "away_form5",
        "home_first_game", "away_first_game", "home_games_pre", "away_games_pre",
        "derby", "home_opener", "last_home", "final_round",
        "away_fans_pre", "ln_away_fans_pre", "away_fans_missing",
        "rain_mm", "rain", "max_ta", "min_ta", "hot", "cold", "rain_alt", "hot_alt", "cold_alt",
        "excluded",
    ]
    out = df[cols]
    out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(out)}경기, 제외 {out['excluded'].sum()}경기)")
    print("\n[변수별 해당 경기 수]")
    for c in ["holiday", "derby", "home_opener", "last_home", "final_round", "home_first_game", "away_first_game",
              "rain", "hot", "cold", "rain_alt", "hot_alt", "cold_alt", "away_fans_missing"]:
        print(f"  {c:<16} {out[c].sum():>4}")
    n_missing = out["max_ta"].isna().sum()
    if n_missing:
        print(f"  날씨 결측 {n_missing}경기 -> python src/collect/fetch_weather.py를 다시 실행하세요")
    print("\n[요일 유형]")
    print(out["day_type"].value_counts().to_string())
    if INCOMPLETE_SEASONS:
        print(f"\n참고: {sorted(INCOMPLETE_SEASONS)}시즌은 진행 중이라 last_home을 모두 0으로 두었습니다.")


if __name__ == "__main__":
    main()
