"""
K리그 경기별 관중 데이터 정리·병합 스크립트 (1단계)

사용법
------
1) K리그 홈페이지 > 기록 > 관중 현황에서
   시즌 / 리그 / 클럽 '전체' / 타입 '경기별' / '300건 보기'로 조회한다.
2) 표를 드래그해 복사한 뒤, 아래 중 편한 방식으로 data/raw/attendance/ 폴더에 저장한다.
   - 메모장에 붙여넣고 .txt로 저장 (예: data/raw/attendance/2026_K1.txt)
   - 엑셀에 붙여넣고 .xlsx 또는 .csv로 저장 (예: data/raw/attendance/2026_K1.xlsx)
   파일 이름은 자유. 한 시즌이 여러 페이지면 파일을 여러 개 만들어도 된다.
3) 프로젝트 최상위 폴더에서 실행:
       pip install -r requirements.txt
       python src/collect/kleague_attendance_merge.py
4) 결과
   - data/processed/attendance_clean.csv : 정리된 경기 단위 데이터 (1경기 = 1행)
   - 화면에 시즌·리그별 경기 수와 점검 결과 출력

이 스크립트는 사이트에 자동으로 접속하지 않는다.
(K리그 사이트는 robots.txt로 자동 수집을 막고 있어, 수집은 손으로 하고 정리만 자동화한다.)
"""

from pathlib import Path
import csv
import io
import re
import sys

import pandas as pd

# 어느 폴더에서 실행해도 프로젝트 최상위 기준으로 경로를 잡는다
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "attendance"
OUT_DIR = ROOT / "data" / "processed"
OUT_FILE = OUT_DIR / "attendance_clean.csv"

# 사이트 표의 원래 열 이름 -> 분석용 영문 열 이름
COLUMN_MAP = {
    "시즌": "season",
    "대회명": "competition",
    "일자": "date",
    "홈팀": "home_team",
    "상대": "away_team",
    "경기결과": "result",
    "경기장": "stadium",
    "관중수": "attendance",
    "원정팀": "away_fans_raw",  # 원정 관중 수로 보이나 연맹 확인 필요
    "비고": "note",
}
EXPECTED = list(COLUMN_MAP.keys())


# ---------------------------------------------------------------------------
# 1. 파일 읽기
# ---------------------------------------------------------------------------
def read_text_table(path: Path) -> pd.DataFrame:
    """브라우저에서 복사해 메모장에 붙여넣은 표(탭 구분)나 CSV를 읽는다."""
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path.name}: 인코딩을 알 수 없음 (UTF-8 또는 CP949로 저장해 주세요)")

    # 탭 구분(메모장 붙여넣기)이면 탭, 아니면 CSV 규칙("34,068" 같은 따옴표 처리 포함)
    sep = "\t" if "\t" in text else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=sep) if any(c.strip() for c in r)]
    return rows_to_frame(rows, path.name)


def read_excel_table(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, header=None, dtype=str)
    rows = df.fillna("").values.tolist()
    return rows_to_frame(rows, path.name)


def rows_to_frame(rows: list[list[str]], name: str) -> pd.DataFrame:
    """헤더 행을 찾아 그 아래를 데이터로 쓴다. 중간에 반복된 헤더나 빈 줄은 버린다."""
    rows = [[str(c).strip() for c in r] for r in rows]

    header_idx = next(
        (i for i, r in enumerate(rows) if "관중수" in r and "홈팀" in r), None
    )
    if header_idx is None:
        # 헤더 없이 데이터만 복사한 경우: 열이 10개이고 첫 칸이 연도면 순서대로 간주
        data = [r for r in rows if len(r) >= 10 and re.fullmatch(r"\d{4}", r[0])]
        if not data:
            raise ValueError(f"{name}: 관중 현황 표를 찾지 못함 (열 이름 행을 포함해 복사했는지 확인)")
        header = EXPECTED
    else:
        header = rows[header_idx]
        data = rows[header_idx + 1 :]

    width = len(header)
    clean = [
        r[:width]
        for r in data
        if len(r) >= width - 1           # 마지막 '비고' 칸이 비어 잘린 경우 허용
        and r[0] != header[0]            # 반복된 헤더 제거
        and "조회된 데이터" not in "".join(r)
    ]
    clean = [r + [""] * (width - len(r)) for r in clean]

    df = pd.DataFrame(clean, columns=header)
    missing = [c for c in EXPECTED if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: 다음 열이 없음 {missing}")
    df = df[EXPECTED].rename(columns=COLUMN_MAP)
    df["source_file"] = name
    return df


def load_all(raw_dir: Path) -> pd.DataFrame:
    files = sorted(
        p for p in raw_dir.glob("*")
        if p.suffix.lower() in {".txt", ".csv", ".tsv", ".xlsx", ".xls"}
    )
    if not files:
        sys.exit(f"'{raw_dir}' 폴더에 파일이 없습니다. 복사한 표를 저장해 주세요.")

    frames = []
    for p in files:
        try:
            df = read_excel_table(p) if p.suffix.lower() in {".xlsx", ".xls"} else read_text_table(p)
            print(f"  읽음  {p.name:<30} {len(df):>4}행")
            frames.append(df)
        except ValueError as e:
            print(f"  건너뜀 {e}")
    if not frames:
        sys.exit("읽을 수 있는 파일이 없습니다.")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 2. 정리
# ---------------------------------------------------------------------------
def to_int(s: pd.Series) -> pd.Series:
    """'35,729' 같은 문자열을 정수로. 숫자가 아니면 결측."""
    return pd.to_numeric(s.astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce").astype("Int64")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["season"] = to_int(out["season"])
    out["date"] = pd.to_datetime(out["date"].astype(str).str.strip(), errors="coerce")
    out["attendance"] = to_int(out["attendance"])
    out["away_fans_raw"] = to_int(out["away_fans_raw"])

    # 리그 구분: 대회명에 'K리그1' / 'K리그2'가 들어 있음
    out["league"] = out["competition"].str.extract(r"(K리그\s?[12])", expand=False).str.replace(" ", "")

    # 경기결과 '1 : 0' -> 홈 득점 / 원정 득점
    goals = out["result"].astype(str).str.extract(r"(\d+)\s*:\s*(\d+)")
    out["home_goals"] = pd.to_numeric(goals[0], errors="coerce").astype("Int64")
    out["away_goals"] = pd.to_numeric(goals[1], errors="coerce").astype("Int64")
    out["home_result"] = pd.NA
    out.loc[out["home_goals"] > out["away_goals"], "home_result"] = "W"
    out.loc[out["home_goals"] == out["away_goals"], "home_result"] = "D"
    out.loc[out["home_goals"] < out["away_goals"], "home_result"] = "L"

    # 요일·주말 (공휴일은 사이트 '비고'에 표시되지 않으므로 별도 목록으로 나중에 붙인다)
    out["weekday"] = out["date"].dt.dayofweek          # 0=월 ... 6=일
    out["weekend"] = (out["weekday"] >= 5).astype("Int64")
    out["month"] = out["date"].dt.month

    for col in ["home_team", "away_team", "stadium", "note"]:
        out[col] = out[col].astype(str).str.strip()

    # 같은 경기를 두 번 복사한 경우 제거 (날짜 + 홈팀 + 원정팀 기준)
    before = len(out)
    out = out.drop_duplicates(subset=["date", "home_team", "away_team"], keep="first")
    dup = before - len(out)

    out = out.sort_values(["season", "league", "date", "home_team"]).reset_index(drop=True)
    out.insert(0, "match_id", [
        f"{d:%Y%m%d}_{h}_{a}" if pd.notna(d) else f"NA_{h}_{a}"
        for d, h, a in zip(out["date"], out["home_team"], out["away_team"])
    ])

    cols = [
        "match_id", "season", "league", "date", "weekday", "weekend", "month",
        "home_team", "away_team", "stadium",
        "attendance", "away_fans_raw",
        "home_goals", "away_goals", "home_result",
        "note", "competition", "source_file",
    ]
    out = out[cols]
    out.attrs["duplicates_removed"] = dup
    return out


# ---------------------------------------------------------------------------
# 3. 점검
# ---------------------------------------------------------------------------
def report(df: pd.DataFrame) -> None:
    print("\n[시즌·리그별 경기 수]")
    summary = (
        df.groupby(["season", "league"])
        .agg(경기수=("match_id", "size"), 평균관중=("attendance", "mean"), 첫경기=("date", "min"), 마지막경기=("date", "max"))
    )
    summary["평균관중"] = summary["평균관중"].round(0).astype("Int64")
    print(summary.to_string())

    print("\n[점검]")
    print(f"  중복으로 제거한 행: {df.attrs.get('duplicates_removed', 0)}")
    for col, label in [("date", "날짜"), ("attendance", "관중 수"), ("home_goals", "경기 결과"), ("league", "리그")]:
        n = df[col].isna().sum()
        flag = "  <- 원본 확인 필요" if n else ""
        print(f"  {label} 결측: {n}{flag}")
        if n:
            print(df.loc[df[col].isna(), ["match_id", "source_file"]].head(5).to_string(index=False))

    zero = (df["attendance"] == 0).sum()
    if zero:
        print(f"  관중 0명 경기: {zero} (무관중·중립 경기인지 확인)")

    teams = sorted(set(df["home_team"]))
    print(f"\n  홈팀 이름 {len(teams)}개: {', '.join(teams)}")
    print("  (같은 구단이 다른 이름으로 나오면 이름 통일이 필요합니다)")


def main() -> None:
    print(f"'{RAW_DIR.relative_to(ROOT)}/' 폴더의 파일을 읽는 중...")
    raw = load_all(RAW_DIR)
    df = clean(raw)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")  # 엑셀에서 한글이 깨지지 않도록
    report(df)
    print(f"\n저장 완료: {OUT_FILE.relative_to(ROOT)}  ({len(df)}경기)")


if __name__ == "__main__":
    main()
