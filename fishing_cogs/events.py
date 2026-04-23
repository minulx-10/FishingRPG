import datetime
import random

from discord.ext import commands, tasks

from fishing_core.database import db
from fishing_core.logger import logger
from fishing_core.shared import FISH_DATA, MARKET_PRICES, env_state, kst, update_weather_randomly


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
        """10분마다 시세를 업데이트하고 유저의 체력을 회복시킵니다."""
        try:
            async with db.conn.execute("SELECT item_name, amount_sold FROM market_sales") as cursor:
                sales_data = await cursor.fetchall()

            sales_dict = {row[0]: row[1] for row in sales_data}

            for fish, data in FISH_DATA.items():
                base_price = data["price"]
                sold = sales_dict.get(fish, 0)

                # 수요와 공급 기반 알고리즘 (탄력성 강화)
                if sold == 0:
                    # 판매가 없으면 가격 상승 (0.5% ~ 3.5% 랜덤)
                    increase_rate = random.uniform(0.005, 0.035)
                    new_price = int(MARKET_PRICES.get(fish, base_price) * (1 + increase_rate))
                    # 최대 250% 제한
                    new_price = min(new_price, int(base_price * 2.5))
                else:
                    # 판매량에 따른 가격 하락 (지수적 하락)
                    drop_factor = max(0.1, 0.95 ** (sold / 2))
                    new_price = int(MARKET_PRICES.get(fish, base_price) * drop_factor)
                    # 최소 10% 제한
                    new_price = max(new_price, int(base_price * 0.1))

                jitter = random.uniform(0.97, 1.03) # 3% 랜덤 노이즈
                MARKET_PRICES[fish] = int(new_price * jitter)

            await db.execute("UPDATE market_sales SET amount_sold = 0")

            # 행동력(체력) 10분마다 자연 회복 (최대치 초과 방지)
            now_hour = datetime.datetime.now(kst).hour
            stamina_regen = 5 if (18 <= now_hour <= 23 or 0 <= now_hour < 6) else 15  # 밤/새벽 시간대는 자연 회복률 1/3 토막

            await db.execute(f"UPDATE user_data SET stamina = stamina + {stamina_regen} WHERE stamina < max_stamina")
            await db.execute("UPDATE user_data SET stamina = max_stamina WHERE stamina > max_stamina")
            await db.commit()

            logger.info(f"시세 업데이트 및 체력 {stamina_regen}⚡ 회복 완료.")
        except Exception as e:
            logger.error(f"시세 업데이트 루프 에러: {e}")

    @market_update_loop.before_loop
    async def before_market(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=60)
    async def weather_update_loop(self):
        """1시간마다 날씨를 업데이트합니다."""
        try:
            if env_state.get("WEATHER_QUEUE"):
                new_weather = env_state["WEATHER_QUEUE"].pop(0)
                env_state["CURRENT_WEATHER"] = new_weather
                if not env_state["WEATHER_QUEUE"]:
                    env_state.pop("WEATHER_QUEUE")
                logger.info(f"예보에 따라 날씨가 변경되었습니다: {new_weather}")
            else:
                new_weather = update_weather_randomly()
        except Exception as e:
            logger.error(f"날씨 업데이트 루프 에러: {e}")

    @weather_update_loop.before_loop
    async def before_weather(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=kst))
    async def daily_midnight_task(self):
        """자정마다 특별 효과(요르문간드 축복 등)를 처리합니다."""
        try:
            await db.execute("""
                UPDATE user_data
                SET coins = CAST(coins * 1.05 AS INTEGER)
                WHERE user_id IN (
                    SELECT user_id FROM inventory WHERE item_name = '세계를 감싼 뱀, 요르문간드 🐍' AND amount > 0
                )
            """)
            await db.commit()
            logger.info("요르문간드의 축복: 코인 5% 증가 처리 완료.")
        except Exception as e:
            logger.error(f"자정 태스크 에러: {e}")

async def setup(bot):
    await bot.add_cog(EventCog(bot))
