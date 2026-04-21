import os
import secrets
import json
from aiohttp import web
import discord

from .database import db
from .shared import FISH_DATA, MARKET_PRICES, env_state

# 메모리에 토큰 저장 (서버 재시작 시 강제 로그아웃됨 - 보안상 유리)
ACTIVE_SESSIONS = set()

def require_auth(func):
    async def wrapper(self, request):
        # 개발 환경이나 로컬 편의를 위해 쿠키 혹은 헤더 토큰 검증
        token = request.headers.get("Authorization")
        if not token or token.replace("Bearer ", "") not in ACTIVE_SESSIONS:
            return web.json_response({"error": "Unauthorized"}, status=401)
        return await func(self, request)
    return wrapper

class DashboardServer:
    def __init__(self, bot):
        self.bot = bot
        self.app = web.Application()
        self.USER_CACHE = {} # 외부 통신 부하를 줄이기 위한 임시 캐시
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
        ])
        self.app.add_routes([
            web.get('/', self.serve_index)
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
            ACTIVE_SESSIONS.add(token)
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
                "total_fish_species": len(FISH_DATA)
            }
            return web.json_response({"success": True, "data": stats})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({"error": str(e)}, status=500)

    @require_auth
    async def api_users(self, request):
        try:
            # 기본적으로 모든 유저 스탯 조회
            async with db.conn.execute("SELECT user_id, rating, coins, boat_tier, rod_tier, last_daily FROM user_data ORDER BY coins DESC, rating DESC") as cursor:
                rows = await cursor.fetchall()
                
            users = []
            for r in rows:
                user_id, rating, coins, boat_tier, rod_tier, last_daily = r
                
                name = str(user_id)
                avatar = None
                
                # 유저 이름 봇 캐시에서 불러오기 시도 (캐시 히트 최우선)
                discord_user = self.bot.get_user(int(user_id))
                
                # 만약 메모리에 유저가 없다면 디스코드 API로 조회 (제한 피하기 위해 자체 USER_CACHE 확인)
                if not discord_user:
                    if user_id in self.USER_CACHE:
                        discord_user = self.USER_CACHE[user_id]
                    else:
                        try:
                            fetched_user = await self.bot.fetch_user(int(user_id))
                            self.USER_CACHE[user_id] = fetched_user
                            discord_user = fetched_user
                        except Exception:
                            pass # 계정이 삭제되었거나 API 한계 도달 시

                if discord_user:
                    name = discord_user.name
                    avatar = discord_user.avatar.url if discord_user.avatar else None

                users.append({
                    "user_id": str(user_id),
                    "name": name,
                    "avatar": avatar,
                    "rating": rating,
                    "coins": coins,
                    "boat_tier": boat_tier,
                    "rod_tier": rod_tier,
                    "last_daily": last_daily
                })
                
            return web.json_response({"success": True, "data": users})
        except Exception as e:
            import traceback
            traceback.print_exc()
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
                    "market_price": MARKET_PRICES.get(fish_name, info.get("price", 0))
                })
            return web.json_response({"success": True, "data": res_data})
        except Exception as e:
            import traceback
            traceback.print_exc()
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
            embed = discord.Embed(title=f"📢 [시스템 공지] {title}", description=content, color=0xff0000)
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
            return web.json_response({"success": True, "current_weather": weather})
        return web.json_response({"error": "Invalid weather"}, status=400)

async def start_web_server(bot):
    port = int(os.getenv("WEB_PORT", 8888))
    server = DashboardServer(bot)
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✨ 웹 관리자 대시보드가 포트 {port} 에서 백그라운드 구동됩니다.")
