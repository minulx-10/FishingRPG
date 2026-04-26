import random
import datetime
from typing import List, Tuple, Dict, Any

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, kst

class BattleService:
    @staticmethod
    def get_strongest_fish(inventory_items: List[Tuple[str, int]]) -> Tuple[str, int]:
        """잠금된 아이템 중 가장 전투력이 높은 물고기를 반환합니다."""
        max_power = -1
        best_fish = None
        
        for name, amt in inventory_items:
            power = FISH_DATA.get(name, {}).get("power", -1)
            if power > max_power:
                max_power = power
                best_fish = name
                
        return best_fish, max_power

    @staticmethod
    def calculate_damage(attacker_power: int, is_crit: bool = False, multiplier: float = 1.0) -> int:
        """기본 데미지를 계산합니다."""
        dmg = attacker_power * random.uniform(0.9, 1.1) * multiplier
        if is_crit:
            dmg *= 2.0
        return int(dmg)

    @staticmethod
    async def process_raid_attack(user_id: int, fish_name: str, boss_hp: int, boss_max_hp: int) -> Dict[str, Any]:
        """레이드 공격 로직을 처리하고 결과를 반환합니다."""
        power = FISH_DATA.get(fish_name, {}).get("power", 100)
        grade = FISH_DATA.get(fish_name, {}).get("grade", "일반")
        
        # 기본 데미지 베이스
        dmg = power * random.randint(5, 15)
        
        # 등급 보너스 (희귀 이상 25% 확률로 1.5배)
        if grade in ["레전드", "신화", "태고", "환상", "미스터리"] and random.random() < 0.25:
            dmg = int(dmg * 1.5)
            
        # 치명타 (20%)
        is_crit = random.random() < 0.2
        if is_crit:
            dmg *= 2
            
        # 레이드 작살 소모 및 보너스
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='레이드 작살 🔱'", (user_id,)) as cursor:
            row = await cursor.fetchone()
        
        has_harpoon = row and row[0] > 0
        if has_harpoon:
            dmg *= 2
            await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='레이드 작살 🔱'", (user_id,))
            
        # 최종 체력 반영
        new_hp = max(0, boss_hp - dmg)
        
        # 보상 계산 (데미지에 비례)
        reward = int((dmg ** 0.8) * 2)
        
        return {
            "damage": dmg,
            "new_hp": new_hp,
            "reward": reward,
            "is_crit": is_crit,
            "used_harpoon": has_harpoon
        }

    @staticmethod
    async def get_pvp_deck(user_id: int) -> List[Tuple[str, int]]:
        """유저의 PvP 덱(상위 3마리)을 가져옵니다."""
        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (user_id,)) as cursor:
            items = await cursor.fetchall()
            
        fish_list = []
        for (name,) in items:
            p = FISH_DATA.get(name, {}).get("power", -1)
            if p > 0:
                fish_list.append((name, p))
        
        fish_list.sort(key=lambda x: x[1], reverse=True)
        return fish_list[:3]
