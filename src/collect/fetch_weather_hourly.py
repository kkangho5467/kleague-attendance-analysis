"""
기상청 ASOS 시간자료 수집 스크립트 (공공데이터포털 API) (1단계: 경기 시간대 날씨)

사용법
------
1) 공공데이터포털에서 '기상청_지상(종관, ASOS) 시간자료 조회서비스'를 활용신청한다.
   (일자료와 같은 키를 쓴다. .env의 KMA_API_KEY)
2) 관중·일정 데이터를 정리한 뒤 실행한다.
       python src/collect/kleague_attendance_merge.py
       python src/collect/fetch_weather_hourly.py

입력
- data/processed/attendance_clean.csv : 경기 날짜와 경기장
- data/external/stadium_station.csv   : 경기장 → 관측소 (본 분석 stn_id, 민감도 분석 alt_stn_id)

출력
- data/raw/weather/asos_hourly.csv : 관측소·시각별 기온(ta)·강수량(rn)·습도(hm)·풍속(ws)

경기 날짜마다 11시~23시 자료만 받는다 (킥오프 13:00~20:00 전후를 모두 덮는다).
이미 받은 (관측소, 날짜)는 다시 요청하지 않고, 중간에 끊겨도 다시 실행하면 이어서 받는다.
"""

from pathlib import Path
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_weather import get_key  # noqa: E402  (.env 키 읽기를 같이 쓴다)

ROOT = Path(__file__).resolve().parents[2]
MATCHES = ROOT / "data" / "processed" / "attendance_clean.csv"
STATIONS = ROOT / "data" / "external" / "stadium_station.csv"
OUT_FILE = ROOT / "data" / "raw" / "weather" / "asos_hourly.csv"

URL = "http://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"
FIELDS = {"stnId": "stn_id", "tm": "tm", "ta": "ta", "rn": "rn", "hm": "hm", "ws": "ws"}
HOUR_FROM, HOUR_TO = 11, 23
SAVE_EVERY = 50


def fetch_day(key: str, stn: int, date: pd.Timestamp) -> pd.DataFrame:
    params = dict(serviceKey=key, pageNo=1, numOfRows=999, dataType="JSON", dataCd="ASOS", dateCd="HR",
                  stnIds=stn, startDt=f"{date:%Y%m%d}", startHh=f"{HOUR_FROM:02d}",
                  endDt=f"{date:%Y%m%d}", endHh=f"{HOUR_TO:02d}")
    for attempt in range(4):
        try:
            body = requests.get(URL, params=params, timeout=30).json()["response"]
            break
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"관측소 {stn} {date:%Y-%m-%d} 요청 실패")
    code = body["header"]["resultCode"]
    if code == "03":   # 자료 없음 (아직 제공 전)
        return pd.DataFrame(columns=list(FIELDS.values()))
    if code != "00":
        raise RuntimeError(f"API 오류 {code}: {body['header']['resultMsg']}")
    return pd.DataFrame(body["body"]["items"]["item"])[list(FIELDS)].rename(columns=FIELDS)


def save(frames: list, have: pd.DataFrame) -> pd.DataFrame:
    allw = pd.concat([have] + frames, ignore_index=True)
    allw["stn_id"] = allw["stn_id"].astype(int)
    allw = allw.drop_duplicates(["stn_id", "tm"], keep="last").sort_values(["stn_id", "tm"])
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    allw.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
    return allw


def main() -> None:
    matches = pd.read_csv(MATCHES, encoding="utf-8-sig", usecols=["date", "stadium"], parse_dates=["date"])
    stations = pd.read_csv(STATIONS, encoding="utf-8-sig")
    unknown = sorted(set(matches["stadium"]) - set(stations["stadium"]))
    if unknown:
        sys.exit(f"stadium_station.csv에 없는 경기장: {unknown}")

    pairs = pd.concat([
        stations[["stadium", "stn_id"]],
        stations[["stadium", "alt_stn_id"]].rename(columns={"alt_stn_id": "stn_id"}),
    ]).drop_duplicates()
    need = matches.merge(pairs, on="stadium")[["stn_id", "date"]].drop_duplicates()
    need = need[need["date"] < pd.Timestamp.today().normalize()]

    if OUT_FILE.exists():
        have = pd.read_csv(OUT_FILE, encoding="utf-8-sig")
    else:
        have = pd.DataFrame(columns=list(FIELDS.values()))
    done = set(zip(have["stn_id"].astype(int), pd.to_datetime(have["tm"]).dt.normalize()))
    todo = need[[(s, d) not in done for s, d in zip(need["stn_id"], need["date"])]].sort_values(["stn_id", "date"])

    print(f"필요한 (관측소, 날짜) {len(need)}개 중 새로 받을 것 {len(todo)}개")
    if todo.empty:
        return

    key = get_key()
    frames, empty = [], 0
    for i, (stn, date) in enumerate(zip(todo["stn_id"], todo["date"]), 1):
        df = fetch_day(key, int(stn), date)
        if df.empty:
            empty += 1
        frames.append(df)
        if i % SAVE_EVERY == 0:
            have = save(frames, have)
            frames = []
            print(f"  {i}/{len(todo)} 저장")
        time.sleep(0.1)
    have = save(frames, have)
    print(f"\n저장 완료: {OUT_FILE.relative_to(ROOT)}  (총 {len(have)}행)")
    if empty:
        print(f"  자료가 없던 날짜 {empty}개는 다음 실행 때 다시 받습니다.")


if __name__ == "__main__":
    main()
