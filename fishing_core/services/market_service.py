import random
from typing import Dict

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, MARKET_PRICES

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
            else:
                # 판매량이 0이면 기본가로 5%씩 회복
                if current_price < base_price:
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
