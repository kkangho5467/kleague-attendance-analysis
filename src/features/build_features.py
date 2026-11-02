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
- sellout_proxy      매진으로 보이는 경기면 1 (민감도 분석 1에서 뺀다)
                     경기장·시즌별 최다 관중의 95% 이상인 경기가 5번 이상 나오면 그 경기장·시즌에
                     관중 상한(매진)이 있다고 보고, 그 경기들을 표시한다. 경기마다 여는 구역이 달라
                     실제 판매 좌석 수를 알 수 없어서 쓰는 대체 기준이다. 관중 수로 만든 기준이므로
                     본 분석에는 쓰지 않는다.
- kickoff, kickoff_hour  킥오프 시각 (일정 페이지)
- night              18시 이후 시작이면 1. 평일 경기는 모두 저녁이라, night 계수는 사실상
                     '주말·공휴일 저녁 경기 vs 낮 경기' 차이를 보여 준다
- round, tv_terrestrial  라운드, 지상파(KBS·MBC·SBS) 중계면 1
  일정 입력: data/processed/schedule_clean.csv (src/collect/kleague_schedule_merge.py가 만듦)
[경기 시간대 날씨 = 본 분석] 시간자료, 킥오프 1시간 전 ~ 2시간 후 (예: 19:30 킥오프 -> 18~21시)
- rain_match_mm      그 4시간 강수량 합 (빈칸 = 비 안 옴 = 0)
- ta_kickoff         킥오프 시각(정시 기준, 19:30이면 19시)의 기온
- rain               rain_match_mm 1mm 이상이면 1
- hot                ta_kickoff 30℃ 이상이면 1
- cold               ta_kickoff 5℃ 이하면 1
- rain_alt, hot_alt, cold_alt
                     대체 관측소(alt_stn_id) 기준 같은 변수. 모형 3 민감도 분석용
[하루 전체 날씨 = 기술통계용] 일자료
- rain_mm, max_ta, min_ta  일강수량, 일 최고·최저기온
- rain_day, hot_day, cold_day  일강수량 1mm 이상 / 최고 33℃ 이상 / 최저 0℃ 이하
- ln_away_fans_pre   log(1 + 원정팀의 직전 5번 원정경기 평균 원정 관중). 상대팀 인기도
- away_fans_missing  원정팀의 데이터상 첫 원정경기면 1. 이때 ln_away_fans_pre는 0으로 채운다.
                     (first_game 더미처럼 반드시 함께 모형에 넣는다)
  날씨 입력: data/raw/weather/asos_daily.csv (src/collect/fetch_weather.py가 만듦),
            data/raw/weather/asos_hourly.csv (src/collect/fetch_weather_hourly.py가 만듦),
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
NIGHT_FROM = 18   # 이 시각(시) 이후 킥오프면 야간 경기
# 경기 시간대 날씨 기준 (2026-11-02 확정)
WINDOW_BEFORE, WINDOW_AFTER = 1, 2   # 킥오프 몇 시간 전 ~ 몇 시간 후
RAIN_MM = 1.0                        # 그 시간 강수량 합이 이 값 이상이면 비
HOT_TA = 30.0                        # 킥오프 기온이 이 값 이상이면 더위
COLD_TA = 5.0                        # 킥오프 기온이 이 값 이하면 추위
# 매진 대체 기준 (2026-11-02 확정)
SELLOUT_RATIO = 0.95                 # 경기장·시즌 최다 관중의 몇 % 이상이면 꽉 찼다고 볼지
SELLOUT_MIN_GAMES = 5                # 그런 경기가 몇 번 이상이어야 상한이 있다고 볼지


def match_weather(m: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    """경기마다 킥오프 전후 시간대의 강수량 합과 킥오프 기온을 구한다.
    m: match_id, stn, date, kickoff_hour / 반환: match_id, rain_match_mm, ta_kickoff"""
    h = hourly.assign(date=hourly["tm"].dt.normalize(), hour=hourly["tm"].dt.hour)[["stn_id", "date", "hour", "ta", "rn"]]
    rows = []
    for off in range(-WINDOW_BEFORE, WINDOW_AFTER + 1):
        x = m.assign(hour=m["kickoff_hour"] + off, offset=off)
        rows.append(x.merge(h, left_on=["stn", "date", "hour"], right_on=["stn_id", "date", "hour"], how="left"))
    x = pd.concat(rows)
    g = x.groupby("match_id")
    out = pd.DataFrame({
        # 시간자료가 한 시간이라도 있으면 빈칸 강수량은 0으로 본다
        "rain_match_mm": g["rn"].apply(lambda s: s.fillna(0).sum()).where(g["ta"].count() > 0),
        "ta_kickoff": x[x["offset"] == 0].set_index("match_id")["ta"],
    }).reset_index().rename(columns={"index": "match_id"})
    return out


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
    schedule = read(PROC / "schedule_clean.csv")
    stations = read(EXT / "stadium_station.csv")
    weather = read(ROOT / "data" / "raw" / "weather" / "asos_daily.csv", parse_dates=["date"])
    hourly = read(ROOT / "data" / "raw" / "weather" / "asos_hourly.csv", parse_dates=["tm"])

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

    # 매진 대체 기준: 관중 수가 같은 상한 근처에서 반복해서 멈추는 경기장·시즌
    stadium_season = df.groupby(["stadium", "season"])["attendance"]
    near_max = df["attendance"] >= SELLOUT_RATIO * stadium_season.transform("max")
    has_cap = near_max.groupby([df["stadium"], df["season"]]).transform("sum") >= SELLOUT_MIN_GAMES
    df["sellout_proxy"] = (near_max & has_cap).astype(int)

    # 킥오프 시간·야간 경기·중계 (일정 페이지). 일정이 없는 경기는 결측
    df = df.merge(schedule[["match_id", "kickoff", "kickoff_hour", "round", "tv_terrestrial"]],
                  on="match_id", how="left", validate="one_to_one")
    df["night"] = (df["kickoff_hour"] >= NIGHT_FROM).astype("Int64").where(df["kickoff_hour"].notna())

    # 하루 전체 날씨 (일자료, 기술통계용). 아직 받지 못한 날은 결측으로 남는다.
    df = df.merge(stations[["stadium", "stn_id", "alt_stn_id"]], on="stadium", how="left", validate="many_to_one")
    df = df.merge(weather[["stn_id", "date", "sum_rn", "max_ta", "min_ta"]],
                  on=["stn_id", "date"], how="left", validate="many_to_one")
    has_day = df["max_ta"].notna()
    df["rain_mm"] = df["sum_rn"].where(~has_day, df["sum_rn"].fillna(0))
    df["rain_day"] = (df["rain_mm"] >= 1).astype("Int64").where(has_day)
    df["hot_day"] = (df["max_ta"] >= 33).astype("Int64").where(has_day)
    df["cold_day"] = (df["min_ta"] <= 0).astype("Int64").where(has_day)

    # 경기 시간대 날씨 (시간자료, 본 분석): 본 관측소와 대체 관측소 각각
    for stn_col, suffix in [("stn_id", ""), ("alt_stn_id", "_alt")]:
        w = match_weather(df[["match_id", stn_col, "date", "kickoff_hour"]].rename(columns={stn_col: "stn"}), hourly)
        df = df.merge(w.add_suffix(suffix).rename(columns={f"match_id{suffix}": "match_id"}),
                      on="match_id", how="left", validate="one_to_one")
        ok = df[f"ta_kickoff{suffix}"].notna()
        df[f"rain{suffix}"] = (df[f"rain_match_mm{suffix}"] >= RAIN_MM).astype("Int64").where(ok)
        df[f"hot{suffix}"] = (df[f"ta_kickoff{suffix}"] >= HOT_TA).astype("Int64").where(ok)
        df[f"cold{suffix}"] = (df[f"ta_kickoff{suffix}"] <= COLD_TA).astype("Int64").where(ok)

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
        "kickoff", "kickoff_hour", "night", "round", "tv_terrestrial",
        "rain_match_mm", "ta_kickoff", "rain", "hot", "cold", "rain_alt", "hot_alt", "cold_alt",
        "rain_mm", "max_ta", "min_ta", "rain_day", "hot_day", "cold_day",
        "sellout_proxy", "excluded",
    ]
    out = df[cols]
    out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(out)}경기, 제외 {out['excluded'].sum()}경기)")
    print("\n[변수별 해당 경기 수]")
    for c in ["sellout_proxy", "night", "tv_terrestrial", "holiday", "derby", "home_opener", "last_home", "final_round", "home_first_game", "away_first_game",
              "rain", "hot", "cold", "rain_alt", "hot_alt", "cold_alt", "rain_day", "hot_day", "cold_day",
              "away_fans_missing"]:
        print(f"  {c:<16} {out[c].sum():>4}")
    n_kick = out["kickoff"].isna().sum()
    if n_kick:
        print(f"  킥오프 결측 {n_kick}경기 -> python src/collect/kleague_schedule_merge.py 결과를 확인하세요")
    n_missing = out["max_ta"].isna().sum()
    if n_missing:
        print(f"  일자료 날씨 결측 {n_missing}경기 -> python src/collect/fetch_weather.py를 다시 실행하세요")
    n_missing = out["ta_kickoff"].isna().sum()
    if n_missing:
        print(f"  경기 시간대 날씨 결측 {n_missing}경기 -> python src/collect/fetch_weather_hourly.py를 다시 실행하세요")
    print("\n[요일 유형]")
    print(out["day_type"].value_counts().to_string())
    if INCOMPLETE_SEASONS:
        print(f"\n참고: {sorted(INCOMPLETE_SEASONS)}시즌은 진행 중이라 last_home을 모두 0으로 두었습니다.")


if __name__ == "__main__":
    main()
