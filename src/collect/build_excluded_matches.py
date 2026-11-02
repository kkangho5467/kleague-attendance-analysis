"""
정규 홈구장이 아닌 곳에서 열린 홈경기를 제외 목록으로 만드는 스크립트 (1단계)

사용법
------
프로젝트 최상위 폴더에서 정리 스크립트를 먼저 실행한 뒤 실행한다.
    python src/collect/kleague_attendance_merge.py
    python src/collect/build_excluded_matches.py

입력
- data/processed/attendance_clean.csv : 정리된 경기 데이터
- data/external/home_stadiums.csv     : 구단·시즌별 정규 홈구장 (직접 확정한 목록)

출력
- data/external/excluded_matches.csv  : 제외할 경기 (match_id, reason, source)

기준은 data/external/README.md '제외 경기 기준'에 있다.
관중 수는 읽지 않는다. 결과를 보고 기준을 바꾸지 않기 위해서다.
"""

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MATCHES = ROOT / "data" / "processed" / "attendance_clean.csv"
HOME_STADIUMS = ROOT / "data" / "external" / "home_stadiums.csv"
OUT_FILE = ROOT / "data" / "external" / "excluded_matches.csv"


def read_csv(path: Path, **kw) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    sys.exit(f"{path.name}: 인코딩을 알 수 없음")


def main() -> None:
    matches = read_csv(MATCHES, usecols=["match_id", "season", "home_team", "stadium"])
    regular = read_csv(HOME_STADIUMS).rename(columns={"team": "home_team"})
    regular["is_regular"] = True

    m = matches.merge(regular, on=["home_team", "season", "stadium"], how="left")

    # 정규 홈구장 목록에 구단·시즌 자체가 없으면 새 데이터가 들어온 것이므로 먼저 목록을 채워야 한다
    known = set(zip(regular["home_team"], regular["season"]))
    unknown = m[[(t, s) not in known for t, s in zip(m["home_team"], m["season"])]]
    if len(unknown):
        print("[확인 필요] home_stadiums.csv에 없는 구단·시즌:")
        print(unknown[["home_team", "season", "stadium"]].drop_duplicates().to_string(index=False))
        sys.exit("home_stadiums.csv를 먼저 채워 주세요.")

    out = m[m["is_regular"].isna()].copy()
    out["reason"] = "비정규 홈구장: " + out["stadium"]
    out["source"] = "data/external/README.md 제외 경기 기준"
    out = out.sort_values("match_id")[["match_id", "reason", "source"]]
    out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"제외 경기 {len(out)}개 저장: {OUT_FILE.relative_to(ROOT)}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
