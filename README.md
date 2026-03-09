# RentSignal

RentSignal의 동네 추천 시스템 코드  
* 사용자가 선호하는 편의시설 우선순위에 따라 법정동을 추천합니다.

## 파일 설명

### data_loader.py
* 공동 모듈을 보관하는 곳
    * 매핑
    * 데이터 로딩
    * 정규화
    * 점수 계산

### recommend.py
* 편의시설 기반 동네 추천
    * 점수만 반영

### recommend_with_price.py
* 전월세 가격을 고려한 가성비 동네 추천
    * (점수/가격)으로 가성비 순위 결정 

### api.py
* recommend.py + recommend_with_price.py를 통합한 API 서버
    * JSON으로 요청받고 JSON으로 응답

## 카테고리별 데이터 처리

### 1. 편의점, 카페, 병원, 약국, 음식점, 대형마트


**처리 방법**

* CSV에서 제공된 카테고리 코드와 법정동 코드를 통해 COUNT 집계

| 코드 | 카테고리 |
|---|---|
| CS2 | 편의점 |
| CE7 | 카페 |
| HP8 | 병원 |
| PM9 | 약국 |
| FD6 | 음식점 |
| MT1 | 대형마트 |

### 2. 교통 (버스정류장 + 지하철역)

* 좌표(위도/경도)만 제공

**처리 방법**


### 3. 치안 (CCTV + 범죄율)

* 구(자치구) 단위로만 제공, 법정동 단위 데이터 없음

**처리 방법**

* CCTV: 구별 CCTV 총 수량 집계
* 범죄: 구별 2024년 범죄 발생건수 → 역수(1/건수)
* 총 치안점수 = CCTV_정규화 × 0.5 + 범죄역수_정규화 × 0.5
* 같은 구의 모든 법정동에 동일한 치안점수 부여


### 4. 전월세 가격

**원룸 정의**
- `multi_family_housing_info.csv` 데이터는 연립다세대 전체를 포함하는 데이터
- 주택유형이 "원룸"으로 분류되어 있지 않아 **전용면적 33㎡ 이하**를 원룸으로 간주하고 필터링 진행 (33㎡ = 약 10평, 일반적인 원룸의 최대 평수)
- 오피스텔은 평균 전용면적 28.1㎡로 대부분이 원룸급이라 별도 필터 없이 전체 사용

**처리 방법**
1. 주소 매핑
    * 주소를 법정동으로
2. 4가지 유형으로 분류:
   * 오피스텔/전세, 오피스텔/월세 (전체)
3. 가격 기준 (전세/월세 분리 비교):
   * 전세: 평균 보증금 기준으로 비교
   * 월세: 월 환산 비용으로 통일 비교
        * 월환산비용 = 월세 + (보증금 × 전월세전환율 / 12)
        * 전환율 = 연 5%
4. 법정동별 평균 가격 계산


## 가중치 체계

| 순위 | 가중치
|---|---
| 1순위 | 1.2 
| 2순위 | 0.8 
| 3순위 | 0.5 
| 4순위 | 0.3 
| 5순위 | 0.2 


## 실행 방법

```bash
# 추천 시스템 실행 (편의시설 기반)
uv run python src/recommend.py

# 가성비 추천 시스템 실행 (편의시설 + 전월세 가격)
uv run python src/recommend_with_price.py

# API 서버 실행
uv run uvicorn api:app --app-dir src --reload
```

### API 사용법

서버 실행 후 `http://127.0.0.1:8000` 에서 요청 받음  
`http://127.0.0.1:8000/docs` 에서 API 문서 확인 및 브라우저 테스트 가능

**1) 법정동 입력 (자동완성)**

`GET /dongs?q={검색어}&limit={개수}`

```bash
# "강"이 포함된 법정동 목록 조회
curl "http://127.0.0.1:8000/dongs?q=강&limit=20"
```

- `q`가 빈 문자열이면 전체 법정동 목록 반환

**2) 추천 요청 (POST /recommend)**

```bash
# 위치 기준 반경 추천
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "priorities": {"편의점": 1, "카페": 1, "교통": 2, "병원": 3},
    "sort_by": "score",
    "housing_type": 1,
    "user_dong": "강남구 역삼동",
    "radius_km": 2.5
  }'
```

```bash
# user_dong을 비우면 전체 법정동 기준으로 추천
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "priorities": {"편의점": 1, "카페": 1, "교통": 2, "병원": 3},
    "sort_by": "value",
    "housing_type": 2,
    "user_dong": "",
    "radius_km": null
  }'
```

| 필드 | 설명 |
|---|---|
| priorities | 카테고리별 순위 (1~5). 미지정 카테고리는 5순위 자동 배정. 공동 순위 가능 |
| sort_by | "score" = 편의시설 점수순, "value" = 가성비순 |
| housing_type | 1 = 오피스텔/전세, 2 = 오피스텔/월세, 3 = 원룸/전세, 4 = 원룸/월세 |
| user_dong | 기준 법정동명. 빈 문자열이면 전체 동 기준 |
| radius_km | 반경(km). `user_dong` 입력 시 필수 |

**응답 주요 필드**

| 필드 | 설명 |
|---|---|
| `location_filter.enabled` | 위치 필터 사용 여부 |
| `location_filter.user_dong` | 기준 법정동 (위치 필터 사용 시) |
| `location_filter.radius_km` | 적용 반경 (위치 필터 사용 시) |
| `location_filter.candidate_count` | 반경 필터 적용 후 후보 동 개수 |
| `distance_km` | 기준 법정동 중심점으로부터 거리(km, 위치 필터 사용 시) |
| `score` | 편의시설 종합 점수 |
| `value_score` | 가성비 점수 (sort_by=value일 때만 포함) |
| `count` | 카테고리별 개수 (편의점, 카페, 병원, 약국, 음식점, 대형마트) |
| `normalized` | 카테고리별 정규화 점수 (0~1) |
| `bus` / `subway` | 교통 카테고리 세부 (버스정류장 수, 지하철역 수) |
| `cctv` / `crime` | 치안 카테고리 세부 (CCTV 수량, 범죄 발생건수). 구 단위 |
| `avg_deposit` | 평균 보증금 |
| `avg_monthly` | 평균 월세, 월세일 때만 포함 |
| `monthly_cost` | 월 환산 비용, 월세일 때만 포함 |
| `deals` | 거래건수 |

**응답 예시**

```json
{
  "housing": "오피스텔",
  "rent_type": "월세",
  "sort_by": "score",
  "location_filter": {
    "enabled": true,
    "user_dong": "서울특별시 강남구 역삼동",
    "radius_km": 2.5,
    "candidate_count": 31
  },
  "results": [
    {
      "rank": 1,
      "dong_name": "서울특별시 강남구 역삼동",
      "distance_km": 0.0,
      "score": 0.85,
      "categories": {
        "편의점": {"count": 12, "normalized": 0.85},
        "카페": {"count": 45, "normalized": 0.92},
        "교통": {"bus": 35, "subway": 1, "normalized": 0.72},
        "치안": {"cctv": 3204, "crime": 15234, "normalized": 0.65}
      },
      "price": {
        "avg_deposit": 1000,
        "avg_monthly": 60,
        "monthly_cost": 64,
        "deals": 45
      }
    }
  ]
}
```
