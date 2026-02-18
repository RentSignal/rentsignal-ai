import pandas as pd
import numpy as np
from pathlib import Path

# ========== 매핑 ==========

CATEGORIES = ['편의점', '카페', '병원', '약국', '음식점', '대형마트', '교통', '치안']

POI_CATEGORY_NAMES = {
    'CS2': '편의점',
    'CE7': '카페',
    'HP8': '병원',
    'PM9': '약국',
    'FD6': '음식점',
    'MT1': '대형마트',
}

PRIORITY_WEIGHTS = {
    1: 1.2,
    2: 0.8,
    3: 0.5,
    4: 0.3,
    5: 0.2,
}

DISTRICT_CODES = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}

HOUSING_TYPES = {
    1: ('오피스텔', '전세'),
    2: ('오피스텔', '월세'),
    3: ('원룸', '전세'),
    4: ('원룸', '월세'),
}

CONVERSION_RATE = 0.05 # 보증금 월환산비율 (예: 5% 연이자 → 0.05 / 12)
ONEROOM_MAX_AREA = 33.0 # 원룸 최대 면적 설정 (33㎡ 이하)


# ========== 유틸리티 ==========

def get_data_path():
    return Path(__file__).parent.parent / "data"


# 추후 GEOJSON 활용 시 수정 필요
def _count_within_radius(centroids, points_lon, points_lat, radius_deg=0.005):
    """각 법정동 중심 반경 내 포인트 개수 (반경 기본 ~500m)"""
    dong_codes = centroids['LEGALDONG_CD'].values
    c_lon = centroids['center_lon'].values
    c_lat = centroids['center_lat'].values

    pts_lon = np.array(points_lon)
    pts_lat = np.array(points_lat)

    counts = {}
    for i, code in enumerate(dong_codes):
        dist = np.sqrt((pts_lon - c_lon[i]) ** 2 + (pts_lat - c_lat[i]) ** 2)
        counts[code] = int((dist <= radius_deg).sum())

    return pd.Series(counts)


# ========== 편의시설 데이터 로드 ==========

def _load_poi_data(data_path):
    df = pd.read_csv(data_path / 'collect_seoul_legal_dong.csv')
    df = df[df['CL_CD'].isin(POI_CATEGORY_NAMES.keys())]

    counts = df.groupby(['LEGALDONG_CD', 'CL_CD']).size().reset_index(name='count')
    pivot = counts.pivot(
        index='LEGALDONG_CD', columns='CL_CD', values='count'
    ).fillna(0)
    pivot = pivot.rename(columns=POI_CATEGORY_NAMES)

    dong_names = df.drop_duplicates('LEGALDONG_CD').set_index('LEGALDONG_CD')['LEGALDONG_ADDR'].to_dict()

    centroids = df.groupby('LEGALDONG_CD').agg(
        center_lon=('LC_LO', 'mean'),
        center_lat=('LC_LA', 'mean')
    ).reset_index()

    return pivot, dong_names, centroids


def _load_transport_data(data_path, centroids):
    bus = pd.read_csv(data_path / 'bus_stop_location.csv', encoding='cp949')
    bus_per_dong = _count_within_radius(
        centroids, bus['X좌표'].values, bus['Y좌표'].values
    )

    subway = pd.read_csv(data_path / 'subway_info.csv', encoding='cp949')
    subway_per_dong = _count_within_radius(
        centroids, subway['경도'].values, subway['위도'].values
    )

    # 지하철역 1개 = 버스정류장 10개 가중치
    return bus_per_dong.add(subway_per_dong * 10, fill_value=0)


def _load_safety_data(data_path):
    cctv = pd.read_csv(data_path / 'cctv_location.csv', encoding='cp949')
    cctv_per_gu = cctv.groupby('자치구')['CCTV 수량'].sum()

    crime = pd.read_csv(data_path / 'crime_rate.csv')
    crime_data = crime.iloc[4:29][['자치구별(2)', '2024']].copy()
    crime_data.columns = ['자치구', '범죄건수']
    crime_data['범죄건수'] = pd.to_numeric(crime_data['범죄건수'])
    crime_data = crime_data.set_index('자치구')['범죄건수']

    cctv_norm = (cctv_per_gu - cctv_per_gu.min()) / (cctv_per_gu.max() - cctv_per_gu.min())
    crime_inv = 1 / crime_data
    crime_norm = (crime_inv - crime_inv.min()) / (crime_inv.max() - crime_inv.min())

    return (cctv_norm * 0.5 + crime_norm * 0.5).fillna(0)


def load_and_prepare_data():
    """편의시설 데이터 로드 및 통합 (POI + 교통 + 치안)"""
    data_path = get_data_path()

    poi_pivot, dong_names, centroids = _load_poi_data(data_path)
    transport = _load_transport_data(data_path, centroids)
    poi_pivot['교통'] = transport.reindex(poi_pivot.index).fillna(0)

    safety_per_gu = _load_safety_data(data_path)
    dong_to_gu = {
        code: DISTRICT_CODES.get(str(code)[:5], "")
        for code in poi_pivot.index
    }
    poi_pivot['치안'] = poi_pivot.index.map(
        lambda code: safety_per_gu.get(dong_to_gu.get(code, ""), 0)
    )

    poi_pivot = poi_pivot[CATEGORIES]
    return poi_pivot, dong_names


# ========== 전월세 데이터 로드 ==========

def _parse_price(col):
    return pd.to_numeric(col.astype(str).str.replace(',', ''), errors='coerce')


def _calc_monthly_cost(deposit, monthly_rent):
    return monthly_rent + (deposit * CONVERSION_RATE / 12)


def load_rental_data(dong_names):
    """전월세 데이터 로드 → 법정동별 평균 가격 (4가지 유형)"""
    data_path = get_data_path()

    addr_to_code = {}
    for code, full_addr in dong_names.items():
        short_addr = ' '.join(full_addr.split()[:3])
        addr_to_code[short_addr] = code

    # 오피스텔
    off = pd.read_csv(data_path / 'officetel_info.csv', encoding='cp949',
                       low_memory=False)
    off['보증금'] = _parse_price(off['보증금(만원)'])
    off['월세'] = _parse_price(off['월세금(만원)'])
    off['법정동코드'] = off['시군구'].map(addr_to_code)
    off['월환산비용'] = _calc_monthly_cost(off['보증금'], off['월세'])

    # 연립다세대 (원룸: 33㎡ 이하)
    mf = pd.read_csv(data_path / 'multi_family_housing_info.csv', encoding='cp949',
                      low_memory=False)
    mf['보증금'] = _parse_price(mf['보증금(만원)'])
    mf['월세'] = _parse_price(mf['월세금(만원)'])
    mf['법정동코드'] = mf['시군구'].map(addr_to_code)
    mf['월환산비용'] = _calc_monthly_cost(mf['보증금'], mf['월세'])
    mf_oneroom = mf[mf['전용면적(㎡)'] <= ONEROOM_MAX_AREA]

    agg_cols = dict(
        평균보증금=('보증금', 'mean'),
        평균월세=('월세', 'mean'),
        월환산비용=('월환산비용', 'mean'),
        거래건수=('보증금', 'count'),
    )

    price_data = {
        1: off[off['전월세구분'] == '전세'].groupby('법정동코드').agg(**agg_cols),
        2: off[off['전월세구분'] == '월세'].groupby('법정동코드').agg(**agg_cols),
        3: mf_oneroom[mf_oneroom['전월세구분'] == '전세'].groupby('법정동코드').agg(**agg_cols),
        4: mf_oneroom[mf_oneroom['전월세구분'] == '월세'].groupby('법정동코드').agg(**agg_cols),
    }

    return price_data


# ========== 정규화 & 점수 계산 ==========

def normalize_data(pivot):
    """Min-Max 정규화"""
    normalized = pivot.copy()
    for col in pivot.columns:
        col_min = pivot[col].min()
        col_max = pivot[col].max()
        if col_max > col_min:
            normalized[col] = (pivot[col] - col_min) / (col_max - col_min)
        else:
            normalized[col] = 0
    return normalized


def get_user_priorities():
    """사용자로부터 우선순위 입력 받기"""
    categories = CATEGORIES.copy()
    selected = set()
    priorities = {}

    print("\n" + "=" * 50)
    print("우선순위 선택")
    print("=" * 50)
    print("각 순위에서 중요하게 생각하는 카테고리를 선택하세요.")
    print("복수 선택 가능 (쉼표로 구분)")
    print("=" * 50)

    for priority in range(1, 6):
        print(f"\n{'='*20} {priority}순위 선택 {'='*20}")

        available = [(i, cat) for i, cat in enumerate(categories, 1)
                     if cat not in selected]

        if not available:
            print("모든 카테고리가 선택되었습니다.")
            break

        print("\n선택 가능한 카테고리:")
        for i, cat in available:
            print(f"  {i}. {cat}")
        print(f"  0. 없음")

        while True:
            try:
                user_input = input(f"\n{priority}순위 선택 (예: 1,3,5 또는 0): ").strip()

                if user_input == '0':
                    break

                nums = [int(x.strip()) for x in user_input.split(',')]

                valid = True
                for num in nums:
                    if num < 1 or num > len(categories):
                        print(f"잘못된 번호: {num}")
                        valid = False
                        break
                    if categories[num - 1] in selected:
                        print(f"이미 선택됨: {categories[num - 1]}")
                        valid = False
                        break

                if valid:
                    for num in nums:
                        cat = categories[num - 1]
                        priorities[cat] = priority
                        selected.add(cat)
                        print(f"  ✓ {cat} → {priority}순위 (가중치: {PRIORITY_WEIGHTS[priority]})")
                    break

            except ValueError:
                print("숫자를 입력하세요.")

        if user_input == '0':
            for cat in categories:
                if cat not in selected:
                    priorities[cat] = priority
            break

    for cat in categories:
        if cat not in priorities:
            priorities[cat] = 5

    return priorities


def calculate_scores(normalized, priorities):
    """가중치 기반 편의시설 점수 계산"""
    scores = pd.Series(0.0, index=normalized.index)

    sorted_priorities = sorted(priorities.items(), key=lambda x: x[1])

    print("\n" + "=" * 40)
    print("적용된 가중치")
    print("=" * 40)

    current_priority = 0
    for category, priority in sorted_priorities:
        if priority != current_priority:
            current_priority = priority
            print(f"\n[{priority}순위] (가중치: {PRIORITY_WEIGHTS[priority]})")
        print(f"  - {category}")
        weight = PRIORITY_WEIGHTS[priority]
        scores += normalized[category] * weight

    print("=" * 40)

    return scores
