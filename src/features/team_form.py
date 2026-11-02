"""
경기 직전 순위와 최근 성적 변수 계산 스크립트 (1단계)

사용법
------
프로젝트 최상위 폴더에서 정리 스크립트를 먼저 실행한 뒤 실행한다.
    python src/collect/kleague_attendance_merge.py
    python src/features/team_form.py

입력
- data/processed/attendance_clean.csv : 정리된 경기 데이터 (모든 리그 경기의 점수가 들어 있음)

출력
- data/processed/team_form.csv : match_id별 경기 직전 변수
    home_rank_pre, away_rank_pre   경기 날짜 '전날까지' 결과로 매긴 리그 순위
    home_form5, away_form5         직전 최대 5경기의 경기당 평균 승점 (0~3)
    home_games_pre, away_games_pre 그 시즌 직전까지 치른 경기 수
    final_round                    K리그1 34~38라운드(파이널 라운드)면 1

규칙
- 같은 날 열린 다른 경기 결과는 쓰지 않는다. 관중이 경기장에 올 때 알 수 없던 정보이기 때문이다.
- 시즌이 바뀌면 처음부터 다시 센다. 시즌 첫 경기는 순위·form이 결측이다.
- 순위 기준(K리그 규정): 승점 → 다득점 → 득실차 → 다승. 그래도 같으면 같은 순위.
  (승자승·벌점은 반영하지 않는다)
- K리그1 파이널 라운드에서는 33라운드 순위로 파이널A(1~6위)와 B(7~12위)를 나누고,
  그룹 안에서만 순위를 매긴다. B그룹 팀은 승점이 높아도 7위 위로 올라갈 수 없기 때문이다.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
IN_FILE = ROOT / "data" / "processed" / "attendance_clean.csv"
OUT_FILE = ROOT / "data" / "processed" / "team_form.csv"

FORM_N = 5          # 최근 몇 경기를 볼지
SPLIT_AFTER = 33    # K리그1 스플릿 전 라운드 수
SPLIT_TOP = 6       # 파이널A 팀 수


def to_long(df: pd.DataFrame) -> pd.DataFrame:
    """1경기 = 1행을 1팀·1경기 = 1행으로 바꾼다 (홈·원정 모두)."""
    base = ["match_id", "season", "league", "date"]
    home = df[base + ["home_team", "home_goals", "away_goals"]].rename(
        columns={"home_team": "team", "home_goals": "gf", "away_goals": "ga"})
    away = df[base + ["away_team", "away_goals", "home_goals"]].rename(
        columns={"away_team": "team", "away_goals": "gf", "home_goals": "ga"})
    long = pd.concat([home, away], ignore_index=True)
    long["pts"] = (long["gf"] > long["ga"]) * 3 + (long["gf"] == long["ga"]) * 1
    long["win"] = (long["gf"] > long["ga"]).astype(int)
    return long.sort_values(["team", "season", "date"]).reset_index(drop=True)


def rank_table(played: pd.DataFrame, teams) -> pd.Series:
    """지금까지 치른 경기로 순위표를 만든다. 반환: team -> 순위
    teams: 순위표에 넣을 팀 전체. 아직 경기가 없는 팀(K리그2 휴식 팀 등)도 0점으로 넣는다."""
    t = played.groupby("team").agg(pts=("pts", "sum"), gf=("gf", "sum"), ga=("ga", "sum"), win=("win", "sum"))
    t = t.reindex(teams, fill_value=0)
    t["gd"] = t["gf"] - t["ga"]
    key = list(zip(t["pts"], t["gf"], t["gd"], t["win"]))
    return pd.Series(key, index=t.index).rank(method="min", ascending=False).astype(int)


def ranks_before_each_date(long: pd.DataFrame) -> pd.DataFrame:
    """시즌·리그별로, 각 경기 날짜 전날까지의 순위를 구한다."""
    out = []
    for (season, league), g in long.groupby(["season", "league"]):
        is_k1 = league == "K리그1"
        groups = None  # 파이널 라운드 그룹 (team -> 'A'/'B')
        teams = sorted(g["team"].unique())
        for date in sorted(g["date"].unique()):
            played = g[g["date"] < date]
            if played.empty:
                continue
            rank = rank_table(played, teams)

            # K리그1: 모든 팀이 33경기를 마쳤으면 그 시점 순위로 그룹을 고정한다
            if is_k1 and groups is None and played.groupby("team").size().min() >= SPLIT_AFTER:
                groups = (rank <= SPLIT_TOP).map({True: "A", False: "B"})
            if groups is not None:
                rank = pd.concat([
                    rank_table(played[played["team"].isin(groups[groups == grp].index)],
                               groups[groups == grp].index) + offset
                    for grp, offset in [("A", 0), ("B", SPLIT_TOP)]
                ])

            out.append(pd.DataFrame({"season": season, "league": league, "date": date,
                                     "team": rank.index, "rank_pre": rank.values}))
    return pd.concat(out, ignore_index=True)


def form_before_each_match(long: pd.DataFrame) -> pd.DataFrame:
    """팀별로 직전 최대 5경기의 경기당 승점과, 직전까지 치른 경기 수를 구한다."""
    g = long.groupby(["team", "season"])["pts"]
    long = long.copy()
    # shift(1): 그 경기 자신은 빼고 직전 경기까지만 본다
    long["form5"] = g.transform(lambda s: s.shift(1).rolling(FORM_N, min_periods=1).mean())
    long["games_pre"] = g.cumcount()
    return long[["match_id", "team", "form5", "games_pre"]]


def main() -> None:
    df = pd.read_csv(IN_FILE, encoding="utf-8-sig", parse_dates=["date"])
    long = to_long(df)

    ranks = ranks_before_each_date(long)
    form = form_before_each_match(long)

    out = df[["match_id", "season", "league", "date", "home_team", "away_team"]].copy()
    for side in ["home", "away"]:
        out = out.merge(
            ranks.rename(columns={"team": f"{side}_team", "rank_pre": f"{side}_rank_pre"}),
            on=["season", "league", "date", f"{side}_team"], how="left")
        out = out.merge(
            form.rename(columns={"team": f"{side}_team", "form5": f"{side}_form5", "games_pre": f"{side}_games_pre"}),
            on=["match_id", f"{side}_team"], how="left")

    # 그 팀의 시즌 첫 경기는 순위 결측 (0점 동률 순위는 의미가 없다)
    for side in ["home", "away"]:
        out.loc[out[f"{side}_games_pre"] == 0, f"{side}_rank_pre"] = pd.NA

    out["final_round"] =((out["league"] == "K리그1") & (out["home_games_pre"] >= SPLIT_AFTER)).astype(int)
    for c in ["home_rank_pre", "away_rank_pre"]:
        out[c] = out[c].astype("Int64")
    out["home_form5"] = out["home_form5"].round(3)
    out["away_form5"] = out["away_form5"].round(3)

    cols = ["match_id", "home_rank_pre", "away_rank_pre", "home_form5", "away_form5",
            "home_games_pre", "away_games_pre", "final_round"]
    out[cols].to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(out)}경기)")
    print(f"  순위 결측(시즌 첫 경기): {out['home_rank_pre'].isna().sum()}경기")
    print(f"  파이널 라운드 경기: {out['final_round'].sum()}경기")


if __name__ == "__main__":
    main()
