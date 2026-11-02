"""
K리그 일정/결과 페이지 복사본 정리 스크립트 (1단계: 킥오프 시간·라운드·중계)

사용법
------
1) K리그 홈페이지 > 일정/결과에서 시즌·리그·월을 골라 경기 목록을 드래그해 복사한다.
2) 메모장에 붙여넣어 data/raw/schedule/ 폴더에 저장한다.
   - 시즌·리그별로 한 파일 (예: data/raw/schedule/2026_K1.txt)
   - 여러 달을 한 파일에 이어 붙여도 된다. 확장자가 없어도 읽는다.
   - 연도는 파일 안의 날짜(예: 2026.05.05)에서 읽는다. 맨 앞 날짜가 잘려도(예: 5.02) 괜찮다.
3) 프로젝트 최상위 폴더에서 실행:
       python src/collect/kleague_schedule_merge.py

입력
- data/raw/schedule/*            : 일정 페이지 복사본
- data/processed/attendance_clean.csv : 대조용 관중 데이터

출력
- data/processed/schedule_clean.csv : match_id별 kickoff, round, broadcast 등
- 화면에 관중 데이터와 대조한 결과 (맞지 않는 경기, 빠진 경기)

복사본 한 경기의 모양 (필요한 줄만 읽고 나머지는 버린다)
    2026.05.05                         <- 날짜
    R12                                <- 라운드
    14:00   전북 전북 4:0 광주 광주     <- 시간, 홈팀, 점수, 원정팀
    JTBC SPORTS   캐스터:...            <- TV 중계 채널
    해설:...       전주 월드컵           <- 경기장 (짧은 이름)
    [관중수 20,364]  매치센터            <- 관중 수 (대조용)
"""

from pathlib import Path
import re
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "schedule"
ATTENDANCE = ROOT / "data" / "processed" / "attendance_clean.csv"
OUT_FILE = ROOT / "data" / "processed" / "schedule_clean.csv"

FULL_DATE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$")
PART_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})$")          # 앞이 잘린 날짜 (예: 5.02)
ROUND = re.compile(r"^R(\d+)$")
MATCH = re.compile(r"^(\d{1,2}:\d{2})\t(.+?) (\d+):(\d+) (.+)$")
CROWD = re.compile(r"^\[관중수 ([\d,]+)\]")
CHANNEL = re.compile(r"^([A-Z0-9][A-Z0-9 &+]*?)\s*(\t|$)")    # 'JTBC SPORTS\t캐스터:...', 'COUPANGPLAY'
TERRESTRIAL = {"KBS1", "KBS2", "MBC", "SBS"}


def half(name: str) -> str:
    """'서울 서울'처럼 팀 이름이 두 번 붙어 복사된 것을 하나로 줄인다."""
    parts = name.split(" ")
    n = len(parts)
    if n % 2 == 0 and parts[: n // 2] == parts[n // 2 :]:
        return " ".join(parts[: n // 2])
    return name


def read_text(path: Path) -> list[str]:
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return path.read_text(encoding=enc).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: 인코딩을 알 수 없음")


def parse_file(path: Path) -> pd.DataFrame:
    lines = [l.rstrip() for l in read_text(path)]
    years = [int(m.group(1)) for l in lines if (m := FULL_DATE.match(l.strip()))]
    if not years:
        raise ValueError(f"{path.name}: '2026.05.05' 같은 날짜 줄이 없어 연도를 알 수 없음")
    year = years[0]

    rows, date, rnd, cur = [], None, None, None
    for line in lines:
        s = line.strip()
        if m := FULL_DATE.match(s):
            year = int(m.group(1))
            date = pd.Timestamp(year, int(m.group(2)), int(m.group(3)))
        elif m := PART_DATE.match(s):
            date = pd.Timestamp(year, int(m.group(1)), int(m.group(2)))
        elif m := ROUND.match(s):
            rnd = int(m.group(1))
        elif m := MATCH.match(line.strip(" ")):
            cur = {"date": date, "round": rnd, "kickoff": m.group(1),
                   "home_team": half(m.group(2)), "away_team": half(m.group(5)),
                   "home_goals": int(m.group(3)), "away_goals": int(m.group(4)),
                   "channels": [], "stadium_short": None, "attendance_sched": None,
                   "source_file": path.name}
            rows.append(cur)
        elif cur is None:
            continue
        elif m := CROWD.match(s):
            cur["attendance_sched"] = int(m.group(1).replace(",", ""))
        elif s.startswith("해설:") and "\t" in line:
            cur["stadium_short"] = line.split("\t")[-1].strip()
        elif (m := CHANNEL.match(line)) and m.group(1) not in cur["channels"]:
            cur["channels"].append(m.group(1).strip())

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{path.name}: 경기 줄을 찾지 못함")
    return df


def main() -> None:
    files = sorted(p for p in RAW_DIR.rglob("*") if p.is_file() and not p.name.startswith("."))
    if not files:
        sys.exit(f"'{RAW_DIR.relative_to(ROOT)}' 폴더에 파일이 없습니다.")

    frames = []
    for p in files:
        try:
            df = parse_file(p)
            print(f"  읽음  {p.name:<20} {len(df):>3}경기  ({df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d})")
            frames.append(df)
        except ValueError as e:
            print(f"  건너뜀 {e}")
    if not frames:
        sys.exit("읽을 수 있는 파일이 없습니다.")
    sch = pd.concat(frames, ignore_index=True)

    sch["kickoff_hour"] = sch["kickoff"].str.split(":").str[0].astype(int)
    sch["broadcast"] = sch["channels"].map(" / ".join)
    sch["tv_terrestrial"] = sch["channels"].map(lambda c: int(any(x in TERRESTRIAL for x in c)))
    sch["match_id"] = [f"{d:%Y%m%d}_{h}_{a}" for d, h, a in zip(sch["date"], sch["home_team"], sch["away_team"])]
    before = len(sch)
    sch = sch.drop_duplicates("match_id")

    # 관중 데이터와 대조
    att = pd.read_csv(ATTENDANCE, encoding="utf-8-sig", parse_dates=["date"],
                      usecols=["match_id", "date", "league", "attendance", "home_goals", "away_goals"])
    m = sch.merge(att, on="match_id", how="left", suffixes=("", "_att"), indicator=True)

    print(f"\n[대조] 일정 {len(sch)}경기 (중복 {before - len(sch)}개 제거)")
    nomatch = m[m["_merge"] == "left_only"]
    print(f"  관중 데이터에 없는 경기: {len(nomatch)}")
    if len(nomatch):
        print(nomatch[["match_id", "source_file"]].to_string(index=False))
    ok = m[m["_merge"] == "both"]
    bad = ok[(ok["attendance_sched"] != ok["attendance"]) |
             (ok["home_goals"] != ok["home_goals_att"]) | (ok["away_goals"] != ok["away_goals_att"])]
    print(f"  관중 수·점수가 다른 경기: {len(bad)}")
    if len(bad):
        print(bad[["match_id", "attendance_sched", "attendance", "home_goals", "home_goals_att"]].to_string(index=False))

    # 일정을 복사한 달 가운데 빠진 경기 (리그·월 단위)
    covered = ok.assign(month=ok["date"].dt.to_period("M"))[["league", "month"]].drop_duplicates()
    att["month"] = att["date"].dt.to_period("M")
    expect = att.merge(covered, on=["league", "month"])
    missing = expect[~expect["match_id"].isin(sch["match_id"])]
    print(f"  복사한 달인데 일정에 빠진 경기: {len(missing)}")
    if len(missing):
        print(missing[["match_id"]].to_string(index=False))

    cols = ["match_id", "date", "round", "kickoff", "kickoff_hour", "broadcast", "tv_terrestrial",
            "stadium_short", "attendance_sched", "source_file"]
    OUT_DIR = OUT_FILE.parent
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sch[cols].sort_values("match_id").to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(sch)}경기)")


if __name__ == "__main__":
    main()
