import pandas as pd
from contextlib import asynccontextmanager
from enum import Enum
from fastapi import FastAPI
from pydantic import BaseModel

from data_loader import (
    CATEGORIES, HOUSING_TYPES, PRIORITY_WEIGHTS,
    load_and_prepare_data, load_rental_data, normalize_data,
)


# ========== 데이터 저장소 ==========

app_data = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    pivot, dong_names = load_and_prepare_data()
    normalized = normalize_data(pivot)
    price_data = load_rental_data(dong_names)

    app_data["pivot"] = pivot
    app_data["dong_names"] = dong_names
    app_data["normalized"] = normalized
    app_data["price_data"] = price_data
    yield


# ========== 요청/응답 모델 ==========

class SortBy(str, Enum):
    score = "score"
    value = "value"


class RecommendRequest(BaseModel):
    priorities: dict[str, int]
    sort_by: SortBy
    housing_type: int


# ========== API ==========

app = FastAPI(lifespan=lifespan)


@app.post("/recommend")
def recommend(req: RecommendRequest):
    pivot = app_data["pivot"]
    dong_names = app_data["dong_names"]
    normalized = app_data["normalized"]
    price_data = app_data["price_data"]

    # 유효성 검사
    if req.housing_type not in HOUSING_TYPES:
        return {"error": "housing_type은 1~4 사이의 값이어야 합니다."}

    for cat in req.priorities:
        if cat not in CATEGORIES:
            return {"error": f"알 수 없는 카테고리: {cat}"}

    # 미지정 카테고리는 5순위 자동 배정
    priorities = {cat: req.priorities.get(cat, 5) for cat in CATEGORIES}

    # 편의시설 점수 계산
    scores = pd.Series(0.0, index=normalized.index)
    for cat, priority in priorities.items():
        weight = PRIORITY_WEIGHTS[priority]
        scores += normalized[cat] * weight

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

        if value_normalized is not None and dong_code in value_normalized.index:
            result["value_score"] = round(float(value_normalized[dong_code]), 3)

        for cat in CATEGORIES:
            raw = float(pivot.loc[dong_code, cat])
            norm = float(normalized.loc[dong_code, cat])
            result["categories"][cat] = {
                "count": round(raw, 2) if cat == "치안" else int(raw),
                "normalized": round(norm, 2),
            }

        if dong_code in price_info.index:
            p = price_info.loc[dong_code]
            result["price"] = {
                "avg_deposit": round(float(p["평균보증금"])),
                "avg_monthly": round(float(p["평균월세"])),
                "monthly_cost": round(float(p["월환산비용"])),
                "deals": int(p["거래건수"]),
            }

        results.append(result)

    return {
        "housing": housing,
        "rent_type": rent_type,
        "sort_by": req.sort_by.value,
        "results": results,
    }
