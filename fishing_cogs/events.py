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
        for fish, data in FISH_DATA.items():
            fluctuation = random.uniform(0.5, 2.0)
            MARKET_PRICES[fish] = int(data["price"] * fluctuation)
        print(f"[{datetime.datetime.now(kst).strftime('%H:%M')}] 📈 수산시장 시세가 변동되었습니다!")

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
