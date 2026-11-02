"""
K리그 일정/결과 페이지 복사본 정리 스크립트 (1단계: 킥오프 시간·라운드·중계)

사용법
------
1) K리그 홈페이지 > 일정/결과에서 시즌·리그·월을 골라 경기 목록을 드래그해 복사한다.
2) 미리 만들어 둔 빈 파일에 붙여넣고 저장한다.
       data/raw/schedule/K1/2026/05.txt   (리그/시즌/월.txt)
   - 비어 있는 파일은 건너뛴다. 복사한 달부터 채우면 된다.
   - 연도는 파일 안의 날짜(예: 2026.05.05)에서 읽는다. 맨 앞 날짜가 잘려도(예: 5.02) 괜찮다.
   - 파일 안 날짜가 폴더·파일 이름(시즌·월)과 다르거나, 다른 리그 경기가 들어 있으면 경고한다.
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
# 복사할 때 앞이 잘린 날짜 (예: 5.02, 023.04.01, .04.01): 월·일만 읽고 연도는 파일 안 다른 날짜에서 가져온다
PART_DATE = re.compile(r"^(?:\d{0,4}\.)?(\d{1,2})\.(\d{2})$")
ROUND = re.compile(r"^R(\d+)$")
MATCH = re.compile(r"^(\d{1,2}:\d{2})\t(.+?) (\d+):(\d+) (.+)$")
UPCOMING = re.compile(r"^\d{1,2}:\d{2}\t.+ VS .+$")         # 아직 안 열린 경기 (점수 대신 VS)
CROWD = re.compile(r"^\[관중수 ([\d,]+)\]")
STREAMING = {"COUPANGPLAY": "COUPANGPLAY", "쿠팡플레이": "COUPANGPLAY"}
TERRESTRIAL = {"KBS1", "KBS2", "MBC", "SBS"}


def channel_of(line: str):
    """중계 채널 줄이면 채널 이름, 아니면 None.
    채널 줄은 'JTBC SPORTS\\t캐스터:...'처럼 탭 뒤에 '캐스터'가 오거나, 쿠팡플레이 줄이다.
    이 규칙 덕분에 페이지 전체를 복사(Ctrl+A)해도 메뉴·하단 안내문이 채널로 잡히지 않는다."""
    left, _, right = line.partition("\t")
    name = left.strip()
    if name in STREAMING:
        return STREAMING[name]
    if "\t" in line and name and right.strip().startswith("캐스터"):
        return name
    return None


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


def expected_from_path(path: Path):
    """K1/2026/05.txt -> ('K리그1', 2026, 5). 이 구조가 아니면 None"""
    m = re.search(r"(K[12])[/\\](\d{4})[/\\](\d{1,2})\.txt$", path.as_posix())
    if not m:
        return None
    return {"K1": "K리그1", "K2": "K리그2"}[m.group(1)], int(m.group(2)), int(m.group(3))


def parse_file(path: Path) -> pd.DataFrame:
    lines = [l.rstrip() for l in read_text(path)]
    if not any(l.strip() for l in lines):
        return pd.DataFrame()   # 아직 붙여넣지 않은 빈 파일
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
                   "source_file": path.relative_to(RAW_DIR).as_posix()}
            rows.append(cur)
        elif cur is None:
            continue
        elif m := CROWD.match(s):
            cur["attendance_sched"] = int(m.group(1).replace(",", ""))
        elif s.startswith("해설:") and "\t" in line:
            cur["stadium_short"] = line.split("\t")[-1].strip()
        elif (ch := channel_of(line)) and ch not in cur["channels"]:
            cur["channels"].append(ch)

    upcoming = sum(bool(UPCOMING.match(l.strip(" "))) for l in lines)
    df = pd.DataFrame(rows)
    df.attrs["upcoming"] = upcoming
    if df.empty:
        if upcoming:
            return df   # 아직 열리지 않은 경기만 있는 파일
        raise ValueError(f"{path.name}: 경기 줄을 찾지 못함")
    if df["date"].isna().any():
        raise ValueError(f"{path.name}: 날짜 줄보다 먼저 나온 경기 {df['date'].isna().sum()}개 "
                         "(복사할 때 맨 앞 날짜가 빠졌는지 확인)")
    return df


def main() -> None:
    files = sorted(p for p in RAW_DIR.rglob("*") if p.is_file() and not p.name.startswith("."))
    if not files:
        sys.exit(f"'{RAW_DIR.relative_to(ROOT)}' 폴더에 파일이 없습니다.")

    frames, empty, upcoming, warnings = [], 0, 0, []
    for p in files:
        name = p.relative_to(RAW_DIR).as_posix()
        try:
            df = parse_file(p)
        except ValueError as e:
            print(f"  건너뜀 {name}: {e}")
            continue
        upcoming += df.attrs.get("upcoming", 0)
        if df.empty:
            if not df.attrs.get("upcoming"):
                empty += 1
            continue
        print(f"  읽음  {name:<16} {len(df):>3}경기  ({df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d})")
        exp = expected_from_path(p)
        if exp:
            df["league_expected"] = exp[0]
            wrong = df[(df["date"].dt.year != exp[1]) | (df["date"].dt.month != exp[2])]
            if len(wrong):
                warnings.append(f"{name}: {exp[1]}년 {exp[2]}월 파일인데 다른 달 경기 {len(wrong)}개 "
                                f"({wrong['date'].min():%Y-%m-%d} ~ {wrong['date'].max():%Y-%m-%d})")
        frames.append(df)
    print(f"  (빈 파일 {empty}개, 아직 열리지 않은 경기 {upcoming}개는 건너뜀)")
    if not frames:
        sys.exit("붙여넣은 파일이 없습니다.")
    sch = pd.concat(frames, ignore_index=True)

    sch["kickoff_hour"] = sch["kickoff"].str.split(":").str[0].astype(int)
    sch["broadcast"] = sch["channels"].map(" / ".join)
    sch["tv_terrestrial"] = sch["channels"].map(lambda c: int(any(x in TERRESTRIAL for x in c)))
    sch["match_id"] = [f"{d:%Y%m%d}_{h}_{a}" for d, h, a in zip(sch["date"], sch["home_team"], sch["away_team"])]
    att = pd.read_csv(ATTENDANCE, encoding="utf-8-sig", parse_dates=["date"],
                      usecols=["match_id", "date", "league", "attendance", "home_goals", "away_goals"])

    # 중복 제거 전에: 리그 폴더가 틀린 파일, 같은 경기가 두 파일에 있는 경우
    if "league_expected" in sch:
        chk = sch.merge(att[["match_id", "league"]], on="match_id", how="inner")
        other = chk[chk["league_expected"].notna() & (chk["league_expected"] != chk["league"])]
        for f, g in other.groupby("source_file"):
            warnings.append(f"{f}: {g['league_expected'].iat[0]} 폴더인데 {g['league'].iat[0]} 경기 {len(g)}개")
    dup = sch[sch.duplicated("match_id", keep=False)]
    for files_, g in dup.groupby("match_id")["source_file"].apply(lambda s: " , ".join(sorted(s))).value_counts().items():
        warnings.append(f"같은 경기가 여러 파일에 있음 ({g}경기): {files_}")

    before = len(sch)
    sch = sch.drop_duplicates("match_id")

    # 관중 데이터와 대조
    m = sch.merge(att, on="match_id", how="left", suffixes=("", "_att"), indicator=True)

    print(f"\n[대조] 일정 {len(sch)}경기 (중복 {before - len(sch)}개 제거)")
    nomatch = m[m["_merge"] == "left_only"]
    last_att = att["date"].max()
    later = nomatch[nomatch["date"] > last_att]
    other = nomatch[nomatch["date"] <= last_att]
    print(f"  관중 데이터에 없는 경기: {len(nomatch)}")
    if len(later):
        print(f"   - 관중 표 마지막 날({last_att:%Y-%m-%d}) 이후 경기 {len(later)}개 "
              "-> 관중 표를 다시 복사하면 해결")
    if len(other):
        print(f"   - 그 외 {len(other)}개 (승강 플레이오프·슈퍼컵 등 분석 범위 밖이면 정상)")
        print(other[["match_id", "source_file"]].to_string(index=False))
    ok = m[m["_merge"] == "both"]
    bad = ok[(ok["attendance_sched"] != ok["attendance"]) |
             (ok["home_goals"] != ok["home_goals_att"]) | (ok["away_goals"] != ok["away_goals_att"])]
    print(f"  관중 수·점수가 다른 경기: {len(bad)}")
    if len(bad):
        print(bad[["match_id", "attendance_sched", "attendance", "home_goals", "home_goals_att"]].to_string(index=False))

    # 관중 데이터에는 있는데 일정(킥오프 시간)이 없는 경기 -> 어느 파일을 채워야 하는지 리그·월별로
    missing = att[~att["match_id"].isin(sch["match_id"])]
    print(f"  킥오프 시간이 없는 경기: {len(missing)} / 관중 데이터 {len(att)}경기")
    if len(missing):
        lg = missing["league"].map({"K리그1": "K1", "K리그2": "K2"})
        where = (lg + "/" + missing["date"].dt.strftime("%Y/%m") + ".txt").value_counts().sort_index()
        for f, n in where.items():
            print(f"   - {f}: {n}경기")

    if warnings:
        print("\n[확인 필요] 파일 위치와 내용이 맞지 않습니다")
        for w in warnings:
            print("  " + w)

    cols = ["match_id", "date", "round", "kickoff", "kickoff_hour", "broadcast", "tv_terrestrial",
            "stadium_short", "attendance_sched", "source_file"]
    OUT_DIR = OUT_FILE.parent
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sch[cols].sort_values("match_id").to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(sch)}경기)")


if __name__ == "__main__":
    main()
