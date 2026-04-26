import datetime
import random
from typing import Any

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, MARKET_PRICES, kst


class MarketService:
    @staticmethod
    async def update_market_prices():
        """
        판매량(supply)에 따라 시세를 변동시킵니다.
        많이 팔린 어종은 가격이 하락하고, 팔리지 않은 어종은 서서히 기본가로 회복합니다.
        """
        async with db.conn.execute("SELECT item_name, amount_sold FROM market_sales") as cursor:
            sales_data = await cursor.fetchall()
        
        # 판매량 기반 가격 조정
        for item_name, amount in sales_data:
            if item_name not in MARKET_PRICES or item_name not in FISH_DATA:
                continue
            
            base_price = FISH_DATA[item_name]["price"]
            current_price = MARKET_PRICES[item_name]
            
            # 판매량에 따른 하락폭 (최대 40% 하락 제한)
            # 예: 100마리 팔리면 10% 하락
            drop_ratio = min(0.4, (amount / 1000.0)) 
            
            if amount > 0:
                new_price = int(current_price * (1 - drop_ratio))
                # 최소 가격은 기본가의 50%
                MARKET_PRICES[item_name] = max(int(base_price * 0.5), new_price)
            # 판매량이 0이면 기본가로 5%씩 회복
            elif current_price < base_price:
                MARKET_PRICES[item_name] = min(base_price, int(current_price * 1.05))
            elif current_price > base_price:
                MARKET_PRICES[item_name] = max(base_price, int(current_price * 0.95))
        
        # 시세 변동 후 판매량 초기화 (다음 텀을 위해)
        await db.execute("UPDATE market_sales SET amount_sold = 0")
        await db.commit()
        
        # 랜덤 변동 (소폭의 무작위성 추가)
        for item in MARKET_PRICES:
            if random.random() < 0.1: # 10% 확률로 소폭 변동
                MARKET_PRICES[item] = int(MARKET_PRICES[item] * random.uniform(0.98, 1.02))

    @staticmethod
    def apply_weather_bonus(item_name: str, base_price: int, weather: str) -> int:
        """날씨에 따른 가격 보너스를 계산합니다."""
        grade = FISH_DATA.get(item_name, {}).get("grade", "일반")
        
        if weather == "☀️ 맑음" and grade in ["일반", "희귀"]:
            return int(base_price * 1.3)
        
        if weather == "🌩️ 폭풍우" and grade in ["신화", "태고", "환상", "미스터리"]:
            return int(base_price * 1.2)
            
        return base_price

    @staticmethod
    async def cleanup_expired_buffs():
        """만료된 버프를 데이터베이스에서 정리합니다."""
        now_str = datetime.datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')
        await db.execute("DELETE FROM active_buffs WHERE end_time <= ?", (now_str,))
        await db.commit()

    @staticmethod
    async def recover_user_stamina():
        """유저들의 행동력을 시간대에 따라 자연 회복시킵니다."""
        now_hour = datetime.datetime.now(kst).hour
        # 밤/새벽(18시~06시)은 회복률 감소 (5⚡), 낮 시간은 15⚡
        stamina_regen = 5 if (now_hour >= 18 or now_hour < 6) else 15
        
        await db.execute(f"UPDATE user_data SET stamina = stamina + {stamina_regen} WHERE stamina < max_stamina")
        await db.execute("UPDATE user_data SET stamina = max_stamina WHERE stamina > max_stamina")
        await db.commit()
        return stamina_regen

    @staticmethod
    def get_price_status(item_name: str) -> dict[str, Any]:
        """특정 어종의 현재 시세 상태(떡상/떡락/평범)를 반환합니다."""
        if item_name not in MARKET_PRICES or item_name not in FISH_DATA:
            return {"ratio": 1.0, "status": "➖ 평범"}
        
        base = FISH_DATA[item_name]["price"]
        current = MARKET_PRICES[item_name]
        ratio = current / base
        
        if ratio > 1.2: status = "📈 떡상"
        elif ratio < 0.8: status = "📉 떡락"
        else: status = "➖ 평범"
        
        return {"ratio": ratio, "status": status, "current": current, "base": base}

    @staticmethod
    async def calculate_sell_price(user_id: int, item_name: str, base_price: int, weather: str) -> int:
        """날씨, 칭호 등 모든 보너스를 포함한 최종 판매가를 계산합니다."""
        # 1. 시장 시세 적용
        price = MARKET_PRICES.get(item_name, base_price)
        
        # 2. 날씨 보너스
        grade = FISH_DATA.get(item_name, {}).get("grade", "일반")
        if weather == "☀️ 맑음" and grade in ["일반", "희귀"]:
            price = int(price * 1.3)
        elif weather == "🌩️ 폭풍우" and grade in ["신화", "태고", "환상", "미스터리"]:
            price = int(price * 1.2)
            
        # 3. 칭호 보너스
        title = await db.get_user_title(user_id)
        if title == "[갑부]":
            price = int(price * 1.05)
            
        return price

    @staticmethod
    async def process_purchase(user_id: int, item_name: str, amount: int) -> dict[str, Any]:
        """아이템 구매 로직을 처리합니다."""
        if amount <= 0:
            return {"success": False, "message": "❌ 수량은 1개 이상이어야 합니다."}

        coins, _, _ = await db.get_user_data(user_id)
        
        item_prices = {
            "고급 미끼 🪱": 500,
            "자석 미끼 🧲": 800,
            "초급 그물망 🕸️": 500,
            "튼튼한 그물망 🕸️": 1200,
            "에너지 드링크 ⚡": 1500,
            "가속 포션 💨": 3000,
            "특수 떡밥 🎣": 2000,
            "레이드 작살 🔱": 5000,
        }

        if item_name not in item_prices:
            return {"success": False, "message": "❌ 판매하지 않는 아이템입니다."}

        total_price = item_prices[item_name] * amount
        if coins < total_price:
            return {"success": False, "message": f"❌ 코인이 부족합니다! (필요: {total_price:,} C / 현재: {coins:,} C)"}

        # 1. 재화 차감
        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id=?", (total_price, user_id))

        # 2. 아이템별 특수 처리
        msg = f"✅ **{item_name}** {amount}개를 구매했습니다! (소모: {total_price:,} C)"
        
        if item_name == "에너지 드링크 ⚡":
            heal = 50 * amount
            await db.execute("UPDATE user_data SET stamina = MIN(max_stamina, stamina + ?) WHERE user_id=?", (heal, user_id))
            async with db.conn.execute("SELECT stamina, max_stamina FROM user_data WHERE user_id=?", (user_id,)) as cursor:
                st = await cursor.fetchone()
            msg = f"⚡ 에너지 드링크를 {amount}개 마셨습니다! 체력 +{heal}⚡ (현재: {st[0]}/{st[1]}⚡)\n(소모: {total_price:,} C)"
        
        elif item_name in ["가속 포션 💨", "특수 떡밥 🎣"]:
            buff_type = "fishing_speed_up" if item_name == "가속 포션 💨" else "rare_boost"
            duration = 30 * amount
            end_time = (datetime.datetime.now(kst) + datetime.timedelta(minutes=duration)).strftime('%Y-%m-%d %H:%M:%S')
            await db.execute(
                "INSERT INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, buff_type) DO UPDATE SET end_time = ?",
                (user_id, buff_type, end_time, end_time)
            )
            msg = f"✨ **{item_name}** {amount}개를 사용하여 {duration}분간 버프가 적용됩니다! (소모: {total_price:,} C)"
            
        else:
            # 일반 아이템 인벤토리 추가
            await db.execute(
                "INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?",
                (user_id, item_name, amount, amount)
            )

        await db.log_action(user_id, "MARKET_BUY", f"Item: {item_name}, Amount: {amount}, Spent: {total_price} C")
        await db.commit()

        return {"success": True, "message": msg, "total_price": total_price}
