from data_loader import (
    CATEGORIES, HOUSING_TYPES, CONVERSION_RATE,
    load_and_prepare_data, load_rental_data, normalize_data,
    get_user_priorities, calculate_scores,
)


def get_housing_type():
    """주거 유형 선택"""
    print("\n" + "=" * 50)
    print("주거 유형 선택")
    print("=" * 50)

    for num, (housing, rent_type) in HOUSING_TYPES.items():
        print(f"  {num}. {housing} / {rent_type}")

    while True:
        try:
            choice = int(input("\n선택 (1-4): ").strip())
            if choice in HOUSING_TYPES:
                housing, rent_type = HOUSING_TYPES[choice]
                print(f"\n {housing} / {rent_type}를 선택하셨습니다.")
                return choice
            print("1~4 사이의 숫자를 입력하세요.")
        except ValueError:
            print("숫자를 입력하세요.")


def calculate_value_scores(scores, price_info, is_jeonse):
    """가성비 점수 = 편의시설 점수 ÷ 가격 (정규화)"""
    common_dongs = scores.index.intersection(price_info.index)

    # 전세: 보증금 기준, 월세: 월환산비용 기준
    if is_jeonse:
        price = price_info.loc[common_dongs, '평균보증금']
    else:
        price = price_info.loc[common_dongs, '월환산비용']

    valid = price > 0
    common_dongs = common_dongs[valid]
    price = price[valid]

    facility_scores = scores.loc[common_dongs]

    value_scores = facility_scores / price

    v_min = value_scores.min()
    v_max = value_scores.max()
    if v_max > v_min:
        value_normalized = (value_scores - v_min) / (v_max - v_min)
    else:
        value_normalized = value_scores * 0

    return value_normalized, price


def display_results(pivot, normalized, value_scores, price,
                    price_info, dong_names, housing_choice, top_n=10):
    """가성비 추천 결과 출력"""
    housing, rent_type = HOUSING_TYPES[housing_choice]
    is_jeonse = rent_type == '전세'
    top_dongs = value_scores.nlargest(top_n)

    print("\n" + "=" * 70)
    print(f"가성비 추천 TOP {top_n} ({housing} / {rent_type})")
    if not is_jeonse:
        print(f"전월세전환율: {CONVERSION_RATE*100:.0f}%")
    print("=" * 70)

    for rank, (dong_code, v_score) in enumerate(top_dongs.items(), 1):
        dong_name = dong_names[dong_code]
        p_info = price_info.loc[dong_code]
        deals = int(p_info['거래건수'])

        print(f"\n{rank}위: {dong_name}")
        print(f"    가성비 점수: {v_score:.3f}")

        avg_deposit = p_info['평균보증금']
        avg_monthly = p_info['평균월세']

        if is_jeonse:
            print(f"    평균 전세금: {avg_deposit:,.0f}만원")
        else:
            monthly_cost = p_info['월환산비용']
            print(f"    평균 보증금/월세: {avg_deposit:,.0f}만원 / {avg_monthly:,.0f}만원 (월 환산: {monthly_cost:,.0f}만원)")

        print(f"    거래건수: {deals}건 (최근 1년)")

        print(f"    편의시설 현황:")
        for cat in CATEGORIES:
            raw = pivot.loc[dong_code, cat]
            norm_score = normalized.loc[dong_code, cat]
            bar = "█" * int(norm_score * 10)

            if cat == '치안':
                print(f"      {cat:6}: {raw:.2f} [{bar:<10}] ({norm_score:.2f})")
            else:
                print(f"      {cat:6}: {int(raw):3}개 [{bar:<10}] ({norm_score:.2f})")

    print("\n" + "=" * 70)


def main():
    print("=" * 50)
    print("서울시 법정동 가성비 추천 시스템")
    print("=" * 50)

    print("\n데이터 로딩 중...")
    pivot, dong_names = load_and_prepare_data()
    normalized = normalize_data(pivot)

    print("전월세 데이터 로딩 중...")
    price_data = load_rental_data(dong_names)

    print(f"분석 대상: {len(pivot)}개 법정동")
    print(f"카테고리: {CATEGORIES}")

    while True:
        housing_choice = get_housing_type()
        priorities = get_user_priorities()

        facility_scores = calculate_scores(normalized, priorities)

        price_info = price_data[housing_choice]
        housing, rent_type = HOUSING_TYPES[housing_choice]
        is_jeonse = rent_type == '전세'
        value_scores, price = calculate_value_scores(facility_scores, price_info, is_jeonse)

        available = len(value_scores)
        print(f"\n{housing}/{rent_type} 거래 데이터가 있는 법정동: {available}개")

        display_results(pivot, normalized, value_scores, price,
                        price_info, dong_names, housing_choice)

        again = input("\n다른 조건으로 다시 검색하시겠습니까? (y/n): ").strip().lower()
        if again != 'y':
            break


if __name__ == "__main__":
    main()
