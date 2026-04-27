import os
import secrets

from aiohttp import web

from fishing_core.utils import EmbedFactory

from .database import db
from .logger import logger
from .shared import FISH_DATA, MARKET_PRICES, env_state


def require_auth(func):
    async def wrapper(self, request):
        token = request.headers.get("Authorization")
        if not token:
            return web.json_response({"error": "Unauthorized"}, status=401)

        raw_token = token.replace("Bearer ", "")
        async with db.conn.execute("SELECT 1 FROM admin_sessions WHERE token=?", (raw_token,)) as cursor:
            res = await cursor.fetchone()

        if not res:
            return web.json_response({"error": "Unauthorized"}, status=401)

        return await func(self, request)
    return wrapper

class DashboardServer:
    def __init__(self, bot):
        self.bot = bot
        self.app = web.Application()
        self.app.add_routes([
            web.post('/api/login', self.api_login),
            web.get('/api/stats', self.api_stats),
            web.get('/api/users', self.api_users),
            web.post('/api/users/{user_id}', self.api_update_user),
            web.post('/api/users/{user_id}/items', self.api_modify_item),
            web.get('/api/market', self.api_get_market),
            web.post('/api/market', self.api_update_market),
            web.post('/api/admin/broadcast', self.api_broadcast),
            web.post('/api/admin/weather', self.api_set_weather),
            web.get('/api/admin/logs', self.api_get_logs),
            web.get('/api/users/{user_id}/inventory', self.api_get_user_inventory),
        ])
        self.app.add_routes([
            web.get('/', self.serve_index),
        ])

        # 정적 파일 서빙: 프론트엔드
        os.makedirs('dashboard', exist_ok=True)
        self.app.router.add_static('/', 'dashboard', show_index=False)

    async def serve_index(self, request):
        return web.FileResponse('dashboard/index.html')

    async def api_login(self, request):
        data = await request.json()
        password = data.get("password", "")
        master_pw = os.getenv("ADMIN_PASSWORD", "admin1234!") # 기본 갓비번

        if password == master_pw:
            token = secrets.token_hex(32)
            await db.execute("INSERT INTO admin_sessions (token) VALUES (?)", (token,))
            await db.commit()
            return web.json_response({"success": True, "token": token})

        return web.json_response({"success": False, "error": "Invalid Password"}, status=401)

    @require_auth
    async def api_stats(self, request):
        try:
            async with db.conn.execute("SELECT COUNT(*), SUM(coins) FROM user_data") as cursor:
                res = await cursor.fetchone()
                total_users, total_coins = res if res and res[0] else (0, 0)

            stats = {
                "bot_latency": round(self.bot.latency * 1000, 2),
                "total_users": total_users,
                "total_coins": int(total_coins) if total_coins else 0,
                "current_weather": env_state.get("CURRENT_WEATHER", "맑음"),
                "total_fish_species": len(FISH_DATA),
            }
            return web.json_response({"success": True, "data": stats})
        except Exception as e:
            logger.error("웹 API(stats) 처리 중 오류 발생", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_users(self, request):
        try:
            # 기본적으로 모든 유저 스탯 조회 (username 포함)
            async with db.conn.execute("SELECT user_id, username, rating, coins, boat_tier, rod_tier, last_daily FROM user_data ORDER BY coins DESC, rating DESC") as cursor:
                rows = await cursor.fetchall()

            users = []
            for r in rows:
                user_id, username_db, rating, coins, boat_tier, rod_tier, last_daily = r

                name = username_db if username_db else str(user_id)
                avatar = None

                # 유저 이름 봇 메모리 캐시에서 우선 확인 (비동기 fetch_user 호출 원천 차단하여 Rate Limit 방지)
                discord_user = self.bot.get_user(int(user_id))

                if discord_user:
                    name = discord_user.name
                    avatar = discord_user.avatar.url if discord_user.avatar else None
                elif not username_db:
                    # 캐시에도 없고 DB에도 없는 최초 상태일 경우에만 fetch_user 1회 호출 후 DB에 저장
                    try:
                        fetched = await self.bot.fetch_user(int(user_id))
                        name = fetched.name
                        avatar = fetched.avatar.url if fetched.avatar else None
                        await db.execute("UPDATE user_data SET username=? WHERE user_id=?", (name, user_id))
                    except Exception:
                        pass

                users.append({
                    "user_id": str(user_id),
                    "name": name,
                    "avatar": avatar,
                    "rating": rating,
                    "coins": coins,
                    "boat_tier": boat_tier,
                    "rod_tier": rod_tier,
                    "last_daily": last_daily,
                })

            await db.commit()
            return web.json_response({"success": True, "data": users})
        except Exception as e:
            logger.error("웹 API(users) 처리 중 오류 발생", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_update_user(self, request):
        user_id = request.match_info['user_id']
        data = await request.json()

        try:
            if 'coins' in data:
                await db.execute("UPDATE user_data SET coins = ? WHERE user_id = ?", (int(data['coins']), int(user_id)))
            if 'boat_tier' in data:
                await db.execute("UPDATE user_data SET boat_tier = ? WHERE user_id = ?", (int(data['boat_tier']), int(user_id)))
            if 'rod_tier' in data:
                await db.execute("UPDATE user_data SET rod_tier = ? WHERE user_id = ?", (int(data['rod_tier']), int(user_id)))
            if 'rating' in data:
                await db.execute("UPDATE user_data SET rating = ? WHERE user_id = ?", (int(data['rating']), int(user_id)))

            await db.commit()
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_modify_item(self, request):
        user_id = request.match_info['user_id']
        data = await request.json()
        item_name = data.get("item_name")
        amount = int(data.get("amount", 0))
        action = data.get("action") # 'give' or 'take'

        try:
            if action == 'give':
                await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (int(user_id), item_name, amount, amount))
            elif action == 'take':
                await db.execute("UPDATE inventory SET amount = MAX(0, amount - ?) WHERE user_id = ? AND item_name = ?", (amount, int(user_id), item_name))
                await db.execute("DELETE FROM inventory WHERE amount <= 0")
            await db.commit()
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_get_market(self, request):
        try:
            res_data = []
            for fish_name, info in FISH_DATA.items():
                res_data.append({
                    "fish_name": fish_name,
                    "grade": info.get("grade", "일반"),
                    "base_price": info.get("price", 0),
                    "element": info.get("element", "무속성"),
                    "market_price": MARKET_PRICES.get(fish_name, info.get("price", 0)),
                })
            return web.json_response({"success": True, "data": res_data})
        except Exception as e:
            logger.error("웹 API(market) 처리 중 오류 발생", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_update_market(self, request):
        data = await request.json()
        fish_name = data.get("fish_name")
        price = int(data.get("price", 0))

        try:
            if fish_name in MARKET_PRICES:
                MARKET_PRICES[fish_name] = price
                return web.json_response({"success": True})
            return web.json_response({"error": "Fish not found"}, status=400)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_broadcast(self, request):
        data = await request.json()
        title = data.get("title", "공지사항")
        content = data.get("content", "")

        try:
            embed = EmbedFactory.build(title=f"📢 [시스템 공지] {title}", description=content, type="error")
            embed.set_footer(text="수산시장 웹 통제실에서 발송된 메시지입니다.")

            # 모든 서버의 첫 번째 텍스트 채널에 발송 (혹은 특정 채널 ID 지정 가능)
            count = 0
            for guild in self.bot.guilds:
                if guild.system_channel:
                    await guild.system_channel.send(embed=embed)
                    count += 1
                else:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            await channel.send(embed=embed)
                            count += 1
                            break

            return web.json_response({"success": True, "channels_notified": count})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_set_weather(self, request):
        data = await request.json()
        weather = data.get("weather")

        if weather:
            env_state["CURRENT_WEATHER"] = weather
            await db.execute("INSERT INTO server_state (key, value) VALUES ('CURRENT_WEATHER', ?) ON CONFLICT(key) DO UPDATE SET value=?", (weather, weather))
            await db.commit()
            return web.json_response({"success": True, "current_weather": weather})
        return web.json_response({"error": "Invalid weather"}, status=400)

    @require_auth
    async def api_get_logs(self, request):
        try:
            log_path = "logs/fishing_bot.log"
            logs = []
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8") as f:
                    lines = f.readlines()[-50:] # 최근 50줄
                    for line in lines:
                        # [2026-04-27 15:00:00] [INFO] Message format
                        parts = line.strip().split("] [")
                        if len(parts) >= 2:
                            time = parts[0][1:]
                            level = parts[1].split("]")[0]
                            message = line.split("] ", 2)[-1]
                            logs.append({"time": time, "level": level, "message": message})
            return web.json_response({"success": True, "data": logs})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_get_user_inventory(self, request):
        user_id = request.match_info['user_id']
        try:
            async with db.conn.execute("SELECT item_name, amount, is_locked FROM inventory WHERE user_id=? AND amount > 0 ORDER BY amount DESC", (int(user_id),)) as cursor:
                rows = await cursor.fetchall()
            
            items = []
            for name, amount, locked in rows:
                items.append({"name": name, "amount": amount, "locked": bool(locked)})
                
            return web.json_response({"success": True, "data": items})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

async def start_web_server(bot):
    port = int(os.getenv("WEB_PORT", "8888"))

    # 서버 기동 시 DB에서 날씨 상태 복구
    async with db.conn.execute("SELECT value FROM server_state WHERE key='CURRENT_WEATHER'") as cursor:
        res = await cursor.fetchone()
        if res:
            env_state["CURRENT_WEATHER"] = res[0]

    server = DashboardServer(bot)
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✨ 웹 관리자 대시보드가 포트 {port} 에서 백그라운드 구동됩니다.")
