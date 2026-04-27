import json
from typing import Any, ClassVar

# Mock FISH_DATA and other dependencies
with open('fish_data.json', encoding='utf-8') as f:
    FISH_DATA = json.load(f)

class FishingService:
    REGION_CONFIG: ClassVar[dict[str, Any]] = {
        "연안": {"min_tier": 1, "elements": ["표층", "무속성"], "grades": ["잡동사니", "피식자", "소형 포식자"], "bonus": 1.0},
        "먼 바다": {"min_tier": 2, "elements": ["표층", "암초", "무속성"], "grades": ["잡동사니", "피식자", "소형 포식자", "대형 포식자"], "bonus": 1.2},
        "산호초": {"min_tier": 3, "elements": ["암초", "표층"], "grades": ["피식자", "소형 포식자", "대형 포식자", "포식자-상어"], "bonus": 1.3},
        "심해": {"min_tier": 4, "elements": ["심해", "무속성"], "grades": ["소형 포식자", "대형 포식자", "포식자-상어", "레전드"], "bonus": 1.5},
        "북해": {"min_tier": 5, "elements": ["레전드", "신화", "태고", "환상", "미스터리", "심해"], "grades": ["대형 포식자", "포식자-상어", "포식자-고래", "레전드", "신화", "태고", "환상", "미스터리"], "bonus": 2.0},
    }

    @staticmethod
    def calculate_fish_probabilities(user_id, rod_tier, bait_used, active_buffs, title, current_weather, region="연안"):
        config = FishingService.REGION_CONFIG.get(region, FishingService.REGION_CONFIG["연안"])
        candidates = []
        weights = []

        for fish, data in FISH_DATA.items():
            grade = data["grade"]
            element = data.get("element", "무속성")

            # 1. 해역 필터링 (속성 및 등급)
            is_element_match = (element in config["elements"] or element == "무속성")
            is_grade_match = (grade in config["grades"])
            
            # 신화 등급은 3레역(산호초) 이상에서만 아주 낮은 확률로 등장 가능하도록 예외 허용
            if not is_grade_match and grade == "신화" and config["min_tier"] >= 3:
                is_grade_match = True

            if not is_element_match or not is_grade_match:
                continue

            base_prob = data["prob"] * config["bonus"]

            # (Skip most buffs for simplicity in this test)
            if grade in ["대형 포식자", "포식자-상어", "포식자-고래", "레전드", "신화", "태고", "환상", "미스터리"]:
                base_prob *= (1 + (rod_tier * 0.1))

            candidates.append(fish)
            weights.append(base_prob)

        return candidates, weights

def test():
    regions = ["산호초", "심해", "북해"]
    for reg in regions:
        print(f"--- Region: {reg} ---")
        candidates, weights = FishingService.calculate_fish_probabilities(1, 10, "없음", [], "", "☀️ 맑음", reg)
        
        # Sort by weight descending
        results = sorted(zip(candidates, weights, strict=True), key=lambda x: x[1], reverse=True)
        
        total_w = sum(weights)
        print(f"Total Weight: {total_w}")
        print("Top 10 candidates:")
        for name, weight in results[:10]:
            print(f"  {name}: {weight:.4f} ({ (weight/total_w)*100 if total_w > 0 else 0 :.2f}%)")
        
        # Check Mythic distribution
        mythic_w = sum(w for n, w in zip(candidates, weights, strict=True) if FISH_DATA[n]["grade"] == "신화")
        print(f"Mythic total probability: { (mythic_w/total_w)*100 if total_w > 0 else 0 :.2f}%")
        print("\n")

test()
