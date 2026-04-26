import datetime
import random
from typing import Dict, List, Tuple

from fishing_core.shared import FISH_DATA, env_state, kst

class FishingService:
    @staticmethod
    def calculate_fish_probabilities(
        user_id: int,
        rod_tier: int,
        bait_used: str,
        active_buffs: List[str],
        title: str,
        current_weather: str
    ) -> Tuple[List[str], List[float]]:
        candidates = []
        weights = []

        if "ghost_sea_open" in active_buffs:
            ghost_items = {"해적의 금화 🪙": 60, "가라앉은 보물상자 🧰": 25, "낡은 고철 ⚙️": 15}
            for item, prob in ghost_items.items():
                candidates.append(item)
                weights.append(prob)
            return candidates, weights

        for fish, data in FISH_DATA.items():
            base_prob = data["prob"]
            grade = data["grade"]

            # 미끼 효과
            if bait_used == "자석 미끼 🧲":
                if fish not in ["낡은 고철 ⚙️", "해적의 금화 🪙", "가라앉은 보물상자 🧰"]:
                    continue
                base_prob *= 2.0
            elif "prayer_trash_boost" in active_buffs:
                if fish in ["낡은 고철 ⚙️", "바지락 🐚", "홍합 🐚", "낡은 장화 🥾"]:
                    base_prob *= 3.0
            elif bait_used == "고급 미끼 🪱":
                if grade == "일반":
                    base_prob *= 0.1
                elif grade in ["희귀", "초희귀"]:
                    base_prob *= 1.5

            # 심해 지역 효과
            if "deep_sea_rift" in active_buffs and data["element"] == "심해":
                base_prob *= 3.0
            elif "deep_sea_boost" in active_buffs and data["element"] == "심해":
                base_prob *= 2.0

            # 1. 강화 레벨 보너스
            if grade in ["대형 포식자", "포식자-상어", "포식자-고래", "레전드", "신화", "태고", "환상", "미스터리"]:
                base_prob *= (1 + (rod_tier * 0.1))

            # 2. 버프 효과
            if "large_predator_frenzy" in active_buffs and grade == "대형 포식자":
                base_prob *= 5.0
            if "large_predator_equalizer" in active_buffs and grade not in ["레전드", "신화", "태고", "환상", "미스터리", "해신(海神)"]:
                base_prob = 10.0
            if "only_large_predator_mode" in active_buffs and grade != "대형 포식자":
                base_prob = 0
            if "skip_normal" in active_buffs and grade == "일반":
                base_prob = 0
            if "deep_sea_sniper" in active_buffs:
                if data["element"] == "심해":
                    base_prob *= 5.0
                if grade in ["일반", "희귀"]:
                    base_prob = 0
            if "reduce_freshwater" in active_buffs and data["element"] == "무속성":
                base_prob *= 0.5

            if "rare_boost" in active_buffs and grade not in ["일반", "희귀"]:
                base_prob *= 1.5
            if "high_risk_rare_boost" in active_buffs and grade == "초희귀":
                base_prob *= 3.0

            # 3. 날씨 연동 글로벌 확률
            if current_weather == "☀️ 맑음" and grade in ["일반", "희귀"]:
                base_prob *= 1.3
            elif current_weather == "🌧️ 비" and grade == "대형 포식자":
                base_prob *= 1.5
            elif current_weather == "🌫️ 안개" and grade == "레전드":
                base_prob *= 2.0
            elif current_weather == "🌩️ 폭풍우" and grade in ["신화", "태고", "환상", "미스터리"]:
                base_prob *= 2.0

            # 4. 칭호 보너스
            if title == "[해신]" and grade in ["신화", "미스터리", "태고", "환상"]:
                base_prob *= 1.3

            candidates.append(fish)
            weights.append(base_prob)

        return candidates, weights

    @staticmethod
    def get_waiting_time(active_buffs: List[str], title: str) -> float:
        if "fishing_speed_up" in active_buffs:
            wait_min, wait_max = 0.5, 2.0
        elif "cooldown_reduction" in active_buffs:
            wait_min, wait_max = 1.0, 3.0
        else:
            wait_min, wait_max = 2.0, 6.0

        if "prayer_fog_delay" in active_buffs:
            wait_min += 1.0
            wait_max += 2.0

        if "wet_clothes" in active_buffs:
            wait_min += 3.0
            wait_max += 5.0

        if title == "[강태공]":
            wait_min *= 0.85
            wait_max *= 0.85

        return random.uniform(wait_min, wait_max)
