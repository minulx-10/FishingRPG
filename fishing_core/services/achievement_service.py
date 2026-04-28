import datetime
from typing import Any, ClassVar

from fishing_core.database import db


class AchievementService:
    ACHIEVEMENTS: ClassVar[dict[str, Any]] = {
        "FIRST_CATCH": {"name": "🌱 첫 걸음", "desc": "처음으로 물고기를 낚았습니다.", "reward": 1000},
        "LEGENDARY_FISHER": {"name": "🌟 전설의 강림", "desc": "레전드 등급 이상의 물고기를 낚았습니다.", "reward": 10000},
        "MARKET_MASTER": {"name": "💰 시장의 큰손", "desc": "누적 판매 금액 100,000 C를 달성했습니다.", "reward": 5000},
        "BATTLE_WARRIOR": {"name": "⚔️ 전장의 투사", "desc": "수산대전에서 첫 승리를 거두었습니다.", "reward": 3000},
        "ROD_MASTER": {"name": "🔧 대장장이의 자존심", "desc": "낚싯대 30강을 달성했습니다.", "reward": 20000},
        "SEA_EXPLORER": {"name": "🧭 대해적", "desc": "5개 이상의 모든 해역을 방문했습니다.", "reward": 15000},
    }

    @staticmethod
    async def check_achievement(user_id: int, achievement_id: str) -> dict | None:
        """특정 업적의 달성 여부를 확인하고, 미달성 시 보상을 지급합니다."""
        if achievement_id not in AchievementService.ACHIEVEMENTS:
            return None

        async with db.conn.execute(
            "SELECT is_completed FROM user_achievements WHERE user_id=? AND achievement_id=?",
            (user_id, achievement_id)
        ) as cursor:
            row = await cursor.fetchone()
        
        if row and row[0] == 1:
            return None # 이미 달성함

        # 업적 달성 처리
        config = AchievementService.ACHIEVEMENTS[achievement_id]
        now = datetime.datetime.now().isoformat()
        
        await db.execute(
            "INSERT INTO user_achievements (user_id, achievement_id, is_completed, completed_at) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(user_id, achievement_id) DO UPDATE SET is_completed=1, completed_at=?",
            (user_id, achievement_id, now, now)
        )
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (config["reward"], user_id))
        await db.log_action(user_id, "ACHIEVEMENT_UNLOCKED", f"ID: {achievement_id}, Reward: {config['reward']} C")
        
        return config

    @staticmethod
    async def get_user_achievements(user_id: int) -> list[dict]:
        """유저의 업적 달성 현황을 가져옵니다."""
        async with db.conn.execute(
            "SELECT achievement_id, is_completed, completed_at FROM user_achievements WHERE user_id=?",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            
        completed_map = {row[0]: {"is_completed": row[1], "at": row[2]} for row in rows}
        
        result = []
        for aid, data in AchievementService.ACHIEVEMENTS.items():
            comp_data = completed_map.get(aid, {"is_completed": 0, "at": None})
            result.append({
                "id": aid,
                "name": data["name"],
                "desc": data["desc"],
                "reward": data["reward"],
                "is_completed": comp_data["is_completed"],
                "completed_at": comp_data["at"]
            })
        return result
