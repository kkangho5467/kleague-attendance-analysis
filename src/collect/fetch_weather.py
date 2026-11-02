"""
기상청 ASOS 일자료 수집 스크립트 (공공데이터포털 API) (1단계)

사용법
------
1) 공공데이터포털에서 '기상청_지상(종관, ASOS) 일자료 조회서비스'를 활용신청한다.
2) 프로젝트 최상위 폴더의 .env 파일에 키를 넣는다. (Encoding·Decoding 키 모두 가능)
       KMA_API_KEY=발급받은키
3) 관중 데이터를 정리한 뒤 실행한다.
       python src/collect/kleague_attendance_merge.py
       python src/collect/fetch_weather.py

입력
- data/processed/attendance_clean.csv : 경기 날짜와 경기장
- data/external/stadium_station.csv   : 경기장 → ASOS 관측소 대응표 (본 분석 stn_id, 민감도 분석 alt_stn_id)

출력
- data/raw/weather/asos_daily.csv : 관측소·날짜별 기온·강수량 (받은 자료를 쌓아 두는 파일)

이미 받은 날짜는 다시 요청하지 않는다. 새 경기가 생긴 날짜만 받는다.
일자료는 보통 '어제'까지 제공되므로, 오늘 경기의 날씨는 내일 다시 실행하면 채워진다.
"""

from pathlib import Path
from urllib.parse import unquote
import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
MATCHES = ROOT / "data" / "processed" / "attendance_clean.csv"
STATIONS = ROOT / "data" / "external" / "stadium_station.csv"
OUT_DIR = ROOT / "data" / "raw" / "weather"
OUT_FILE = OUT_DIR / "asos_daily.csv"

URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
FIELDS = {"stnId": "stn_id", "stnNm": "stn_name", "tm": "date",
          "avgTa": "avg_ta", "minTa": "min_ta", "maxTa": "max_ta", "sumRn": "sum_rn"}


def get_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.getenv("KMA_API_KEY")
    if not key:
        sys.exit(".env 파일에 KMA_API_KEY가 없습니다.")
    # Encoding 키(%가 들어 있음)를 넣어도 되도록 한 번 풀어 둔다. requests가 다시 인코딩한다.
    return unquote(key)


def fetch(key: str, stn_id: int, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """한 관측소의 기간 자료를 받는다. 1년 이내로 나눠서 요청한다."""
    params = dict(serviceKey=key, pageNo=1, numOfRows=999, dataType="JSON",
                  dataCd="ASOS", dateCd="DAY", stnIds=stn_id,
                  startDt=f"{start:%Y%m%d}", endDt=f"{end:%Y%m%d}")
    for attempt in range(3):
        try:
            r = requests.get(URL, params=params, timeout=30)
            body = r.json()["response"]
            break
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"관측소 {stn_id} {start:%Y-%m-%d}~{end:%Y-%m-%d} 요청 실패: {r.text[:200]}")

    code = body["header"]["resultCode"]
    if code == "03":   # 자료 없음 (아직 제공 전인 날짜 등)
        return pd.DataFrame(columns=list(FIELDS.values()))
    if code != "00":
        raise RuntimeError(f"API 오류 {code}: {body['header']['resultMsg']}")
    items = body["body"]["items"]["item"]
    return pd.DataFrame(items)[list(FIELDS)].rename(columns=FIELDS)


def main() -> None:
    matches = pd.read_csv(MATCHES, encoding="utf-8-sig", usecols=["date", "stadium"], parse_dates=["date"])
    stations = pd.read_csv(STATIONS, encoding="utf-8-sig")

    unknown = sorted(set(matches["stadium"]) - set(stations["stadium"]))
    if unknown:
        sys.exit(f"stadium_station.csv에 없는 경기장: {unknown}\n대응표에 관측소를 먼저 추가해 주세요.")

    # 본 분석 관측소(stn_id)와 민감도 분석용 대체 관측소(alt_stn_id)를 모두 받는다
    pairs = pd.concat([
        stations[["stadium", "stn_id"]],
        stations[["stadium", "alt_stn_id"]].rename(columns={"alt_stn_id": "stn_id"}),
    ]).drop_duplicates()
    need = matches.merge(pairs, on="stadium")[["stn_id", "date"]].drop_duplicates()
    yesterday = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    need = need[need["date"] <= yesterday]

    if OUT_FILE.exists():
        have = pd.read_csv(OUT_FILE, encoding="utf-8-sig", parse_dates=["date"])
    else:
        have = pd.DataFrame(columns=list(FIELDS.values()))
    have_keys = set(zip(have["stn_id"].astype(int), have["date"]))
    missing = need[[(s, d) not in have_keys for s, d in zip(need["stn_id"], need["date"])]]

    if missing.empty:
        print("새로 받을 날씨가 없습니다.")
        return

    key = get_key()
    frames = []
    # 관측소·연도별로 묶어서 요청 횟수를 줄인다
    for (stn, year), g in missing.groupby([missing["stn_id"], missing["date"].dt.year]):
        start, end = g["date"].min(), g["date"].max()
        df = fetch(key, stn, start, end)
        print(f"  관측소 {stn:>3} {year}: {len(df):>3}일 받음 (필요한 날 {len(g)}일)")
        frames.append(df)
        time.sleep(0.2)

    new = pd.concat(frames, ignore_index=True)
    new["stn_id"] = new["stn_id"].astype(int)
    new["date"] = pd.to_datetime(new["date"])
    for c in ["avg_ta", "min_ta", "max_ta", "sum_rn"]:
        new[c] = pd.to_numeric(new[c], errors="coerce")   # 빈칸 = 비 안 옴 또는 결측

    # 대응표의 관측소 이름과 API가 돌려준 이름이 같은지 확인 (관측소 번호 오타 방지)
    expect = pd.concat([
        stations[["stn_id", "stn_name"]],
        stations[["alt_stn_id", "alt_stn_name"]].set_axis(["stn_id", "stn_name"], axis=1),
    ]).drop_duplicates("stn_id").set_index("stn_id")["stn_name"]
    got = new.drop_duplicates("stn_id").set_index("stn_id")["stn_name"]
    wrong = [(i, expect[i], got[i]) for i in got.index if expect.get(i) != got[i]]
    if wrong:
        print(f"[확인 필요] 관측소 이름이 다릅니다 (번호, 대응표, API): {wrong}")

    allw = pd.concat([have, new], ignore_index=True)
    allw["stn_id"] = allw["stn_id"].astype(int)
    allw["date"] = pd.to_datetime(allw["date"])
    allw = allw.drop_duplicates(["stn_id", "date"], keep="last").sort_values(["stn_id", "date"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    allw.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    still = len(missing) - len(set(zip(new["stn_id"], new["date"])) & set(zip(missing["stn_id"], missing["date"])))
    print(f"\n저장 완료: {OUT_FILE.relative_to(ROOT)}  (총 {len(allw)}행)")
    if still:
        print(f"  아직 제공되지 않은 날짜 {still}개는 다음 실행 때 다시 받습니다.")


if __name__ == "__main__":
    main()
