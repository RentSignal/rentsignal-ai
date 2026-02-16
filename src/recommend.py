from data_loader import (
    CATEGORIES, load_and_prepare_data, normalize_data,
    get_user_priorities, calculate_scores,
)


def display_results(pivot, normalized, scores, dong_names, top_n=10):
    """상위 N개 법정동 결과 출력"""
    top_dongs = scores.nlargest(top_n)

    print("\n" + "=" * 70)
    print(f"추천 법정동 TOP {top_n}")
    print("=" * 70)

    for rank, (dong_code, score) in enumerate(top_dongs.items(), 1):
        dong_name = dong_names[dong_code]

        print(f"\n{rank}위: {dong_name}")
        print(f"    종합 점수: {score:.3f}")
        print(f"    편의시설 현황:")

        for cat in CATEGORIES:
            raw = pivot.loc[dong_code, cat]
            norm_score = normalized.loc[dong_code, cat]
            bar = "█" * int(norm_score * 10)

            if cat == '치안':
                print(f"      {cat:6}: {raw:.2f} [{bar:<10}] ({norm_score:.2f})") # 치안은 점수로 표시 (예: 3.5점)
            else:
                print(f"      {cat:6}: {int(raw):3}개 [{bar:<10}] ({norm_score:.2f})")

    print("\n" + "=" * 70)


def main():
    print("=" * 50)
    print("서울시 법정동 추천 시스템")
    print("=" * 50)

    print("\n데이터 로딩 중...")
    pivot, dong_names = load_and_prepare_data()
    normalized = normalize_data(pivot)

    print(f"분석 대상: {len(pivot)}개 법정동")
    print(f"카테고리: {CATEGORIES}")

    priorities = get_user_priorities()
    scores = calculate_scores(normalized, priorities)
    display_results(pivot, normalized, scores, dong_names)

    again = input("\n다른 조건으로 다시 검색하시겠습니까? (y/n): ").strip().lower()
    if again == 'y':
        priorities = get_user_priorities()
        scores = calculate_scores(normalized, priorities)
        display_results(pivot, normalized, scores, dong_names)


if __name__ == "__main__":
    main()
