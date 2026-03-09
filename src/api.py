import math
import pandas as pd
from contextlib import asynccontextmanager
from enum import Enum
from fastapi import FastAPI, Query
from pydantic import BaseModel

from data_loader import (
    CATEGORIES, HOUSING_TYPES, PRIORITY_WEIGHTS,
    load_and_prepare_data, load_rental_data, normalize_data,
)


# ========== 데이터 저장소 ==========

app_data = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    pivot, dong_names, detail = load_and_prepare_data()
    normalized = normalize_data(pivot)
    price_data = load_rental_data(dong_names)

    app_data["pivot"] = pivot
    app_data["dong_names"] = dong_names
    app_data["normalized"] = normalized
    app_data["price_data"] = price_data
    app_data["detail"] = detail
    yield


# ========== 요청/응답 모델 ==========

class SortBy(str, Enum):
    score = "score"
    value = "value"


class RecommendRequest(BaseModel):
    priorities: dict[str, int]
    sort_by: SortBy
    housing_type: int
    user_dong: str = ""
    radius_km: float | None = None


# ========== API ==========

app = FastAPI(lifespan=lifespan)


# ========== 위치/거리 유틸 ==========

EARTH_RADIUS_KM = 6371.0088


def _normalize_text(text: str) -> str:
    return ''.join(str(text).split())


def _get_dong_aliases(dong_name: str):
    tokens = str(dong_name).split()
    aliases = [dong_name]
    if len(tokens) >= 2:
        aliases.append(' '.join(tokens[-2:]))  # 예: 강남구 역삼동
    if len(tokens) >= 1:
        aliases.append(tokens[-1])             # 예: 역삼동
    return aliases


def _search_dongs(query: str, dong_names):
    key = _normalize_text(query)
    matches = []

    for code, name in dong_names.items():
        aliases = _get_dong_aliases(name)
        if not key or any(key in _normalize_text(alias) for alias in aliases):
            matches.append({
                "dong_code": int(code),
                "dong_name": name,
            })

    matches.sort(key=lambda x: x["dong_name"])
    return matches


def _resolve_user_dong_code(user_dong: str, dong_lookup, dong_names):
    key = _normalize_text(user_dong)
    if not key:
        return None, None

    # 정확 매칭 우선, 없으면 부분 매칭으로 확장
    matched_codes = list(dong_lookup.get(key, []))
    if not matched_codes:
        partial = _search_dongs(user_dong, dong_names)
        matched_codes = [row["dong_code"] for row in partial]

    if len(matched_codes) == 1:
        return matched_codes[0], None
    if len(matched_codes) > 1:
        candidates = [
            {"dong_code": int(code), "dong_name": dong_names.get(code, str(code))}
            for code in matched_codes[:30]
        ]
        return None, {
            "error": "매칭 결과가 여러 개입니다. /dongs에서 선택해주세요.",
            "candidates": candidates,
        }

    return None, {"error": f"알 수 없는 법정동명: {user_dong}"}


def _distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def _filter_dongs_by_radius(dong_centers, user_dong_code: int, radius_km: float):
    valid_centers = dong_centers.dropna(subset=["center_lat", "center_lon"])
    if user_dong_code not in valid_centers.index:
        return pd.Series(dtype=float)

    user_center = valid_centers.loc[user_dong_code]
    distances = {}
    for dong_code, row in valid_centers.iterrows():
        distance = _distance_km(
            user_center["center_lat"], user_center["center_lon"],
            row["center_lat"], row["center_lon"],
        )
        if distance <= radius_km:
            distances[dong_code] = distance

    return pd.Series(distances, dtype=float).sort_values()


@app.get("/dongs")
def search_dongs(q: str = "", limit: int = Query(30, ge=1, le=500)):
    dong_names = app_data["dong_names"]
    matches = _search_dongs(q, dong_names)
    return {
        "query": q,
        "count": len(matches),
        "results": matches[:limit],
    }


@app.post("/recommend")
def recommend(req: RecommendRequest):
    pivot = app_data["pivot"]
    dong_names = app_data["dong_names"]
    normalized = app_data["normalized"]
    price_data = app_data["price_data"]
    detail = app_data["detail"]

    # 유효성 검사
    if req.housing_type not in HOUSING_TYPES:
        return {"error": "housing_type은 1~4 사이의 값이어야 합니다."}
    if req.radius_km is not None and req.radius_km <= 0:
        return {"error": "radius_km은 0보다 커야 합니다."}

    for cat, priority in req.priorities.items():
        if cat not in CATEGORIES:
            return {"error": f"알 수 없는 카테고리: {cat}"}
        if priority not in PRIORITY_WEIGHTS:
            return {"error": f"우선순위는 1~5만 가능합니다: {cat}={priority}"}

    # 사용자 법정동 해석 (비어 있으면 전체 동 기준)
    user_dong_code, location_error = _resolve_user_dong_code(
        req.user_dong,
        detail["dong_lookup"],
        dong_names,
    )
    if location_error:
        return location_error

    # 미지정 카테고리는 5순위 자동 배정
    priorities = {cat: req.priorities.get(cat, 5) for cat in CATEGORIES}

    # 편의시설 점수 계산
    scores = pd.Series(0.0, index=normalized.index)
    for cat, priority in priorities.items():
        weight = PRIORITY_WEIGHTS[priority]
        scores += normalized[cat] * weight

    # 위치가 지정되면 반경 필터 적용
    nearby_distances = None
    if user_dong_code is not None:
        if req.radius_km is None:
            return {"error": "user_dong을 입력한 경우 radius_km도 함께 입력해야 합니다."}

        nearby_distances = _filter_dongs_by_radius(
            detail["dong_centers"],
            user_dong_code,
            req.radius_km,
        )
        if nearby_distances.empty:
            return {"error": "선택한 위치 반경 내에 분석 가능한 법정동이 없습니다."}

        scores = scores.loc[scores.index.intersection(nearby_distances.index)]

    # 가격 정보
    housing, rent_type = HOUSING_TYPES[req.housing_type]
    is_jeonse = rent_type == "전세"
    price_info = price_data[req.housing_type]

    # 정렬 기준 결정
    if req.sort_by == SortBy.value:
        common_dongs = scores.index.intersection(price_info.index)
        price_col = "평균보증금" if is_jeonse else "월환산비용"
        price = price_info.loc[common_dongs, price_col]

        valid = price > 0
        common_dongs = common_dongs[valid]
        price = price[valid]

        value_scores = scores.loc[common_dongs] / price
        v_min, v_max = value_scores.min(), value_scores.max()
        if v_max > v_min:
            value_normalized = (value_scores - v_min) / (v_max - v_min)
        else:
            value_normalized = value_scores * 0

        ranking = value_normalized.nlargest(10)
    else:
        ranking = scores.nlargest(10)
        value_normalized = None

    if ranking.empty:
        return {"error": "조건에 맞는 추천 결과가 없습니다."}

    # 결과 생성
    results = []
    for rank, (dong_code, _) in enumerate(ranking.items(), 1):
        result = {
            "rank": rank,
            "dong_name": dong_names[dong_code],
            "score": round(float(scores[dong_code]), 3),
            "categories": {},
            "price": None,
        }

        if nearby_distances is not None:
            result["distance_km"] = round(float(nearby_distances[dong_code]), 2)

        if value_normalized is not None and dong_code in value_normalized.index:
            result["value_score"] = round(float(value_normalized[dong_code]), 3)

        for cat in CATEGORIES:
            raw = float(pivot.loc[dong_code, cat])
            norm = float(normalized.loc[dong_code, cat])
            cat_data = {"normalized": round(norm, 2)}

            if cat == "교통":
                bus = int(detail["bus_per_dong"].get(dong_code, 0))
                subway = int(detail["subway_per_dong"].get(dong_code, 0))
                cat_data["bus"] = bus
                cat_data["subway"] = subway
            elif cat == "치안":
                gu = detail["dong_to_gu"].get(dong_code, "")
                cctv = int(detail["cctv_per_gu"].get(gu, 0))
                crime = int(detail["crime_per_gu"].get(gu, 0))
                cat_data["cctv"] = cctv
                cat_data["crime"] = crime
            else:
                cat_data["count"] = int(raw)

            result["categories"][cat] = cat_data

        if dong_code in price_info.index:
            p = price_info.loc[dong_code]
            price_result = {
                "avg_deposit": round(float(p["평균보증금"])),
                "deals": int(p["거래건수"]),
            }
            if not is_jeonse:
                price_result["avg_monthly"] = round(float(p["평균월세"]))
                price_result["monthly_cost"] = round(float(p["월환산비용"]))
            result["price"] = price_result

        results.append(result)

    return {
        "housing": housing,
        "rent_type": rent_type,
        "sort_by": req.sort_by.value,
        "location_filter": {
            "enabled": user_dong_code is not None,
            "user_dong": dong_names[user_dong_code] if user_dong_code is not None else None,
            "radius_km": req.radius_km if user_dong_code is not None else None,
            "candidate_count": int(len(scores)),
        },
        "results": results,
    }
