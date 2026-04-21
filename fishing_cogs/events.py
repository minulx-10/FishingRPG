import discord
from discord.ext import commands, tasks
import datetime

from fishing_core.database import db
from fishing_core.shared import kst, FISH_DATA, env_state, update_weather_randomly

class EventCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.market_update_loop.start()
        self.weather_update_loop.start()
        self.daily_midnight_task.start()

    def cog_unload(self):
        self.market_update_loop.cancel()
        self.weather_update_loop.cancel()
        self.daily_midnight_task.cancel()

    @tasks.loop(minutes=10)
    async def market_update_loop(self):
        import random
        from fishing_core.shared import MARKET_PRICES
        
        async with db.conn.execute("SELECT item_name, amount_sold FROM market_sales") as cursor:
            sales_data = await cursor.fetchall()
            
        sales_dict = {row[0]: row[1] for row in sales_data}
        
        for fish, data in FISH_DATA.items():
            base_price = data["price"]
            sold = sales_dict.get(fish, 0)
            
            # 수요와 공급 기반 알고리즘
            if sold == 0:
                current_ratio = MARKET_PRICES.get(fish, base_price) / base_price
                now_hour = datetime.datetime.now(kst).hour
                # 심야/새벽 시간대(0시 ~ 8시) 처리: 유저 활동이 적으므로 인플레이션 방지를 위해 매우 미세하게 상승(1%)
                if 0 <= now_hour < 8:
                    increase_rate = 0.01
                else:
                    increase_rate = 0.03 # 낮 시간대에는 3% 상승
                    
                base_fluctuation = min(2.5, current_ratio + increase_rate)
            elif sold < 5:
                base_fluctuation = 1.0
            elif sold < 20:
                base_fluctuation = 0.8
            elif sold < 50:
                base_fluctuation = 0.5
            else:
                base_fluctuation = 0.2
                
            jitter = random.uniform(0.98, 1.02) # 2% 랜덤 노이즈 (안정성 강화)
            final_ratio = base_fluctuation * jitter
            
            new_price = int(base_price * final_ratio)
            MARKET_PRICES[fish] = max(int(base_price * 0.1), new_price)
            
        await db.execute("UPDATE market_sales SET amount_sold = 0")
        
        # 행동력(체력) 10분마다 자연 회복 (최대치 초과 방지)
        now_hour = datetime.datetime.now(kst).hour
        stamina_regen = 5 if 0 <= now_hour < 8 else 15  # 밤/새벽 시간대는 자연 회복률 1/3 토막
        
        try:
            await db.execute(f"UPDATE user_data SET stamina = stamina + {stamina_regen} WHERE stamina < max_stamina")
            await db.execute("UPDATE user_data SET stamina = max_stamina WHERE stamina > max_stamina")
        except:
            pass
            
        await db.commit()
        
        print(f"[{datetime.datetime.now(kst).strftime('%H:%M')}] 📈 시세 변경 및 전 유저 체력 {stamina_regen}⚡ 회복 완료.")

    @market_update_loop.before_loop
    async def before_market(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=60)
    async def weather_update_loop(self):
        new_weather = update_weather_randomly()
        print(f"[{datetime.datetime.now(kst).strftime('%H:%M')}] 🌤️ 바다 날씨가 {new_weather} (으)로 변경되었습니다.")

    @weather_update_loop.before_loop
    async def before_weather(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=kst))
    async def daily_midnight_task(self):
        await db.execute("""
            UPDATE user_data 
            SET coins = CAST(coins * 1.05 AS INTEGER) 
            WHERE user_id IN (
                SELECT user_id FROM inventory WHERE item_name = '세계를 감싼 뱀, 요르문간드 🐍' AND amount > 0
            )
        """)
        await db.commit()
        print(f"[{datetime.datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')}] 🐍 요르문간드의 축복으로 보유자들의 코인이 5% 증가했습니다.")

async def setup(bot):
    await bot.add_cog(EventCog(bot))
