import os
import secrets

import discord
from aiohttp import web

from .database import db
from .logger import logger
from .shared import FISH_DATA, MARKET_PRICES, RECIPES, env_state


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
            web.get('/api/users/{user_id}/inventory', self.api_get_user_inventory),
            web.post('/api/users/{user_id}/items', self.api_modify_item),
            web.get('/api/market', self.api_get_market),
            web.post('/api/market', self.api_update_market),
            web.post('/api/admin/broadcast', self.api_broadcast),
            web.post('/api/admin/weather', self.api_set_weather),
            web.get('/api/admin/logs', self.api_get_logs),
            web.get('/api/stats/history', self.api_stats_history),
            web.get('/api/items/all', self.api_all_items),
            web.post('/api/users/bulk/items', self.api_bulk_modify_items),
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
        try:
            data = await request.json()
            title = data.get('title', '공지사항')
            content = data.get('content', '')
            color_hex = data.get('color', '#ef4444').replace('#', '')
            thumb_url = data.get('thumbnail')
            image_url = data.get('image')
            footer_text = data.get('footer')

            if not content:
                return web.json_response({"error": "Content is required"}, status=400)

            color = int(color_hex, 16)
            success_count = 0
            
            # 모든 길드에 전송 시도
            for guild in self.bot.guilds:
                # 적절한 채널 찾기 (기본 채널 또는 첫 번째 텍스트 채널)
                target_channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                
                if target_channel:
                    try:
                        embed = discord.Embed(title=f"📢 {title}", description=content, color=color)
                        if thumb_url: embed.set_thumbnail(url=thumb_url)
                        if image_url: embed.set_image(url=image_url)
                        if footer_text: embed.set_footer(text=footer_text)
                        
                        await target_channel.send(embed=embed)
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Broadcast failed for guild {guild.id}: {e}")

            await db.log_action(0, "ADMIN_BROADCAST", f"Title: {title}, Content: {content[:50]}...")
            return web.json_response({"success": True, "channels_notified": success_count})
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

    @require_auth
    async def api_stats_history(self, request):
        try:
            async with db.conn.execute("SELECT recorded_at, total_coins, avg_fish_price FROM stats_history ORDER BY recorded_at DESC LIMIT 20") as cursor:
                rows = await cursor.fetchall()
            
            rows = rows[::-1] # 시간순 정렬
            labels = [r[0].split(" ")[1][:5] for r in rows] # HH:MM
            coins = [r[1] for r in rows]
            prices = [r[2] for r in rows]

            return web.json_response({
                "success": True, 
                "data": {
                    "labels": labels,
                    "prices": prices,
                    "total_coins": coins[-1] if coins else 0,
                    "coins": coins
                }
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_bulk_modify_items(self, request):
        data = await request.json()
        user_ids = data.get("user_ids", [])
        item_name = data.get("item_name")
        amount = int(data.get("amount", 1))

        if not user_ids or not item_name:
            return web.json_response({"error": "Missing params"}, status=400)

        success_count = 0
        try:
            for uid in user_ids:
                await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (int(uid), item_name, amount, amount))
                success_count += 1
            await db.commit()
            return web.json_response({"success": True, "success_count": success_count})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_all_items(self, request):
        """시스템에 존재하는 모든 아이템 명칭을 반환합니다 (관리자용 자동완성)."""
        try:
            items = list(FISH_DATA.keys()) + list(RECIPES.keys())
            shop_items = ["고급 미끼 🪱", "자석 미끼 🧲", "초급 그물망 🕸️", "튼튼한 그물망 🕸️", "에너지 드링크 ⚡", "가속 포션 💨", "특수 떡밥 🎣", "레이드 작살 🔱", "가라앉은 보물상자 🧰", "보물지도 🗺️"]
            items.extend(shop_items)
            return web.json_response({"success": True, "data": sorted(list(set(items)))})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

async def _record_stats_task(bot):
    import asyncio
    while True:
        try:
            async with db.conn.execute("SELECT COUNT(*), SUM(coins) FROM user_data") as cursor:
                res = await cursor.fetchone()
                total_users, total_coins = res if res and res[0] else (0, 0)
            
            avg_price = sum(MARKET_PRICES.values()) / len(MARKET_PRICES) if MARKET_PRICES else 0
            
            await db.execute("INSERT INTO stats_history (total_users, total_coins, avg_fish_price) VALUES (?, ?, ?)", 
                             (total_users, int(total_coins) if total_coins else 0, int(avg_price)))
            await db.commit()
        except Exception as e:
            logger.error(f"Error in stats recording task: {e}")
        
        await asyncio.sleep(1800) # 30분마다

async def start_web_server(bot):
    import asyncio
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
    
    # 통계 기록 태스크 시작
    asyncio.create_task(_record_stats_task(bot))
