import datetime

from discord.ext import commands, tasks

from fishing_core.database import db
from fishing_core.logger import logger
from fishing_core.services.market_service import MarketService
from fishing_core.shared import env_state, kst, update_weather_randomly


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
        """10분마다 시세 업데이트, 버프 정리, 체력 회복을 수행합니다."""
        try:
            # 1. 시장 시세 업데이트 (공급/수요 기반)
            await MarketService.update_market_prices()
            
            # 2. 만료된 버프 정리
            await MarketService.cleanup_expired_buffs()

            # 3. 행동력(체력) 자연 회복
            stamina_regen = await MarketService.recover_user_stamina()

            logger.info(f"정기 시스템 점검 완료 (시세 변동 / 버프 정리 / 체력 {stamina_regen}⚡ 회복)")
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
                SET coins = coins + 50000
                WHERE user_id IN (
                    SELECT user_id FROM inventory WHERE item_name = '세계를 감싼 뱀, 요르문간드 🐍' AND amount > 0
                )
            """)
            logger.info("요르문간드의 축복: 고정 50,000 코인 지급 완료.")
        except Exception as e:
            logger.error(f"자정 태스크 에러: {e}")

async def setup(bot):
    await bot.add_cog(EventCog(bot))
