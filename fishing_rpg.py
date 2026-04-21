import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite # 🌟 sqlite3 대신 aiosqlite 사용!
import datetime
import random
import asyncio
from discord.ui import View, Button
import os
from dotenv import load_dotenv
import json
import aiohttp
import subprocess

# ==========================================
# 1. 봇 기본 설정 및 준비
# ==========================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

kst = datetime.timezone(datetime.timedelta(hours=9))
# 관리자들의 디스코드 고유 ID를 리스트 안에 쉼표(,)로 구분하여 넣습니다.
SUPER_ADMIN_IDS = [
    771274777443696650,  # 기존 관리자 (나)
    861106310439632896,  # 추가할 관리자 A의 디스코드 ID
    1478295213389774920   # 추가할 관리자 B의 디스코드 ID
]

db = None # 🌟 전역 데이터베이스 객체

def is_developer():
    # 'in' 연산자를 사용하여 명령어를 친 유저의 ID가 관리자 리스트에 포함되어 있는지 확인합니다.
    return app_commands.check(lambda i: i.user.id in SUPER_ADMIN_IDS)

# ==========================================
# 선박 등급 제한 확인 (해금 시스템)
# ==========================================
def check_boat_tier(min_tier: int):
    async def predicate(interaction: discord.Interaction):
        await db.execute("INSERT OR IGNORE INTO user_data (user_id) VALUES (?)", (interaction.user.id,))
        async with db.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        
        tier = res[0] if res else 1
        if tier < min_tier:
            tier_names = {1: "나룻배 🛶", 2: "어선 🚤", 3: "쇄빙선 🛳️", 4: "잠수함 ⛴️"}
            req_name = tier_names.get(min_tier, f"Lv.{min_tier}")
            current_name = tier_names.get(tier, f"Lv.{tier}")
            
            embed = discord.Embed(title="🚫 탑승 권한 부족!", description=f"이 명령어를 사용하려면 **[{req_name}]** 이상이 필요합니다.\n(현재 선박: **{current_name}**)", color=0xe74c3c)
            embed.set_footer(text="💡 '/선박개조' 명령어를 통해 배를 업그레이드하세요!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# ==========================================
# 2. 데이터베이스 비동기 초기화 및 함수
# ==========================================
async def init_db():
    global db
    db = await aiosqlite.connect('fishing_rpg.db')
    
    await db.execute('''
        CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0,
            rod_tier INTEGER DEFAULT 1,
            rating INTEGER DEFAULT 1000
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item_name TEXT,
            amount INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_name)
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS bucket (
            user_id INTEGER,
            item_name TEXT,
            amount INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_name)
        )
    ''')

    # 👇 여기에 도감(fish_dex) 테이블 생성 코드 추가! 👇
    await db.execute('''
        CREATE TABLE IF NOT EXISTS fish_dex (
            user_id INTEGER,
            item_name TEXT,
            PRIMARY KEY (user_id, item_name)
        )
    ''')

    await db.execute('''
        CREATE TABLE IF NOT EXISTS active_buffs (
            user_id INTEGER,
            buff_type TEXT,
            end_time TEXT,
            PRIMARY KEY (user_id, buff_type)
        )
    ''')

    await db.execute('''
        CREATE TABLE IF NOT EXISTS aquarium (
            user_id INTEGER,
            item_name TEXT,
            PRIMARY KEY (user_id, item_name)
        )
    ''')

    # 시간 비교 조회가 잦은 버프 테이블에 인덱스 생성
    await db.execute('CREATE INDEX IF NOT EXISTS idx_active_buffs_end_time ON active_buffs (user_id, end_time)')
    
    try:
        await db.execute("ALTER TABLE user_data ADD COLUMN last_daily TEXT DEFAULT ''")
    except aiosqlite.OperationalError:
        pass # 이미 컬럼이 존재함

    # 👇 여기에 보트 티어 컬럼 추가! 👇
    try:
        await db.execute("ALTER TABLE user_data ADD COLUMN boat_tier INTEGER DEFAULT 1")
    except aiosqlite.OperationalError:
        pass

    try:
        await db.execute("ALTER TABLE user_data ADD COLUMN quest_date TEXT DEFAULT ''")
        await db.execute("ALTER TABLE user_data ADD COLUMN quest_item TEXT DEFAULT ''")
        await db.execute("ALTER TABLE user_data ADD COLUMN quest_amount INTEGER DEFAULT 0")
        await db.execute("ALTER TABLE user_data ADD COLUMN quest_reward INTEGER DEFAULT 0")
        await db.execute("ALTER TABLE user_data ADD COLUMN quest_is_cleared INTEGER DEFAULT 0")
    except aiosqlite.OperationalError:
        pass

    await db.commit()

async def get_user_data(user_id):
    async with db.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,)) as cursor:
        res = await cursor.fetchone()
    
    # 유저 정보가 없으면 그때만 생성하고 커밋
    if not res:
        await db.execute("INSERT INTO user_data (user_id) VALUES (?)", (user_id,))
        await db.commit()
        return (0, 1, 1000) # 기본값 반환
        
    return res

# ==========================================
# 3. 게임 핵심 데이터 (물고기 도감 & 시세)
# ==========================================
def load_fish_data():
    try:
        with open('fish_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ 오류: fish_data.json 파일이 없습니다! 봇이 종료됩니다.")
        exit()

FISH_DATA = load_fish_data()
MARKET_PRICES = {fish: data["price"] for fish, data in FISH_DATA.items()}

def load_recipes():
    try:
        with open('recipes.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ 오류: recipes.json 파일이 없습니다!")
        return {}

RECIPES = load_recipes()

@tasks.loop(minutes=10)
async def market_update_loop():
    for fish, data in FISH_DATA.items():
        fluctuation = random.uniform(0.5, 2.0)
        MARKET_PRICES[fish] = int(data["price"] * fluctuation)
    print(f"[{datetime.datetime.now(kst).strftime('%H:%M')}] 📈 수산시장 시세가 변동되었습니다!")

# ==========================================
# 🌟 [신규] 날씨 환경 시스템
# ==========================================
CURRENT_WEATHER = "☀️ 맑음"
WEATHER_TYPES = ["☀️ 맑음", "☁️ 흐림", "🌧️ 비", "🌩️ 폭풍우", "🌫️ 안개"]

# 매 정각(60분)마다 날씨가 무작위로 바뀝니다.
@tasks.loop(minutes=60)
async def weather_update_loop():
    global CURRENT_WEATHER
    # 맑음(40%), 흐림(25%), 비(20%), 폭풍우(5%), 안개(10%) 확률
    CURRENT_WEATHER = random.choices(WEATHER_TYPES, weights=[40, 25, 20, 5, 10], k=1)[0]

# 기존 코드 (찾을 부분)
@tasks.loop(minutes=60)
async def weather_update_loop():
    global CURRENT_WEATHER
    # 맑음(40%), 흐림(25%), 비(20%), 폭풍우(5%), 안개(10%) 확률
    CURRENT_WEATHER = random.choices(WEATHER_TYPES, weights=[40, 25, 20, 5, 10], k=1)[0]

midnight_kst = datetime.time(hour=0, minute=0, tzinfo=kst)

@tasks.loop(time=midnight_kst)
async def daily_midnight_task():
    # 요르문간드 코인 5% 복사 (가방에 가지고 있는 유저 대상)
    await db.execute("""
        UPDATE user_data 
        SET coins = CAST(coins * 1.05 AS INTEGER) 
        WHERE user_id IN (
            SELECT user_id FROM inventory WHERE item_name = '세계를 감싼 뱀, 요르문간드 🐍' AND amount > 0
        )
    """)
    await db.commit()
    print(f"[{datetime.datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')}] 🐍 요르문간드의 축복으로 보유자들의 코인이 5% 증가했습니다.")

def get_element_multiplier(atk_elem, def_elem):
    if atk_elem == "무속성" or def_elem == "무속성": return 1.0
    if atk_elem == "표층" and def_elem == "심해": return 1.5
    if atk_elem == "심해" and def_elem == "암초": return 1.5
    if atk_elem == "암초" and def_elem == "표층": return 1.5
    if atk_elem == def_elem: return 1.0
    return 0.8 

# ==========================================
# 4. 상호작용 UI (버튼 뷰)
# ==========================================
class FishActionView(View):
    def __init__(self, user, target_fish):
        super().__init__(timeout=30)
        self.user = user
        self.target_fish = target_fish
        self.action_taken = False 

    @discord.ui.button(label="가방에 보관 (판매용)", style=discord.ButtonStyle.primary, emoji="🎒")
    async def btn_inv(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, self.target_fish))
        await db.commit()
        await interaction.response.edit_message(content=f"🎒 **{self.target_fish}**를 가방에 안전하게 넣었습니다!", view=None)

    @discord.ui.button(label="통에 보관 (배틀용)", style=discord.ButtonStyle.success, emoji="🪣")
    async def btn_bucket(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        await db.execute("INSERT INTO bucket (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, self.target_fish))
        await db.commit()
        await interaction.response.edit_message(content=f"🪣 **{self.target_fish}**를 통에 담았습니다! 이제 배틀에 출전할 수 있습니다.", view=None)

    @discord.ui.button(label="바로 판매", style=discord.ButtonStyle.danger, emoji="💰")
    async def btn_sell(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        price = MARKET_PRICES.get(self.target_fish, FISH_DATA[self.target_fish]["price"])
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (price, self.user.id))
        await db.commit()
        await interaction.response.edit_message(content=f"💰 **{self.target_fish}**를 시장에 바로 넘겨서 `{price} C`를 벌었습니다!", view=None)

# [1] 낚시 미니게임 UI (신화급 기믹 & 지도 조각 드랍 추가 버전)
class FishingView(View):
    def __init__(self, user, target_fish, rod_tier):
        super().__init__(timeout=15) 
        self.user = user
        self.target_fish = target_fish
        self.rod_tier = rod_tier 
        self.is_bite = False  
        self.start_time = 0
        self.message = None 

        # 만약 FISH_DATA에 없는 특수 아이템이 뽑혀도 에러가 나지 않도록 예외 처리
        fish_info = FISH_DATA.get(self.target_fish, {"base_window": 2.0, "grade": "일반"})
        base_window = fish_info["base_window"]
        bonus_time = (self.rod_tier - 1) * 0.2 
        self.limit_time = max(1.0, base_window + bonus_time)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            
        if self.message:
            try:
                await self.message.edit(content="⏰ 낚시 시간이 초과되어 낚싯대를 거두었습니다.", view=self)
            except:
                pass

    @discord.ui.button(label="대기 중...", style=discord.ButtonStyle.secondary, emoji="🎣", custom_id="fish_btn")
    async def fish_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("남의 낚싯대입니다! 🚫", ephemeral=True)
        
        self.stop() 
        
        if not self.is_bite:
            return await interaction.response.edit_message(content="🎣 앗! 너무 일찍 챘습니다. 물고기가 도망갔어요! 💨", view=None)
            
        elapsed = datetime.datetime.now().timestamp() - self.start_time
        fish_info = FISH_DATA.get(self.target_fish, {"grade": "보물"})
        grade = fish_info["grade"]
        
        # ==========================================
        # 🟢 낚시 성공 처리
        # ==========================================
        if elapsed <= self.limit_time:
            await db.execute("INSERT OR IGNORE INTO fish_dex (user_id, item_name) VALUES (?, ?)", (self.user.id, self.target_fish))
            await db.commit()
            
            embed = discord.Embed(title=f"🎉 낚시 성공! [{grade}]", description=f"**{self.target_fish}**를 낚았습니다!", color=0x00ff00)
            embed.add_field(name="반응 속도", value=f"`{elapsed:.3f}초` (판정 한도: {self.limit_time:.2f}초)")
            
            # 🌟 [지도 조각 드랍 기믹] 5% 확률로 찢어진 지도 조각 획득!
            if random.random() < 0.05:
                piece = random.choice(["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"])
                await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, piece))
                await db.commit()
                embed.add_field(name="🗺️ 바다의 파편 발견!", value=f"물고기와 함께 **{piece}**가 딸려왔습니다! (4부위를 모아 합성하세요)", inline=False)

            if self.target_fish == "심해의 파멸, 크라켄 🦑":
                # 무작위 다른 유저 한 명의 금고(코인이 1000 이상인 사람)를 타겟팅
                async with db.execute("SELECT user_id, coins FROM user_data WHERE user_id != ? AND coins > 1000 ORDER BY RANDOM() LIMIT 1", (self.user.id,)) as cursor:
                    target = await cursor.fetchone()
                
                if target:
                    stolen_amount = int(target[1] * 0.1) # 타겟 유저 자산의 10% 약탈
                    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (stolen_amount, target[0]))
                    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (stolen_amount, self.user.id))
                    await db.commit()
                    embed.add_field(name="🦑 크라켄의 촉수 발동!", value=f"심연에서 뻗어 나온 거대한 촉수가 누군가의 금고를 부수고 `{stolen_amount:,} C`를 훔쳐 당신에게 가져왔습니다!!", inline=False)
            
            action_view = FishActionView(self.user, self.target_fish)
            await interaction.response.edit_message(content="🎊 앗, 낚았습니다! 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
            
            # 🌟 [신화급 기믹] 서버 전체 알림!
            if grade == "신화":
                alert_embed = discord.Embed(
                    title="🚨 [경고] 심해의 거대한 진동이 감지되었습니다...", 
                    description=f"**{self.user.mention}**님이 방금 전설 속의 마수,\n**{self.target_fish}**를 심연에서 끌어올렸습니다!!!",
                    color=0xff0000
                )
                alert_embed.set_footer(text="바다가 요동치기 시작합니다...")
                await interaction.channel.send(content="@here", embed=alert_embed)

        # ==========================================
        # 🔴 낚시 실패 처리
        # ==========================================
        else:
            fail_msg = f"⏰ 너무 늦었습니다! `{elapsed:.3f}초` 걸림.\n(놓친 물고기: **{self.target_fish}** / 제한: {self.limit_time:.2f}초)"
            
            # 🌟 [페널티 기믹] 괴수의 힘에 낚싯대 파괴!
            if grade in ["레전드", "신화"] and self.rod_tier > 1:
                if random.random() < 0.5: # 50% 확률로 낚싯대 박살
                    await db.execute("UPDATE user_data SET rod_tier = rod_tier - 1 WHERE user_id = ?", (self.user.id,))
                    await db.commit()
                    fail_msg += "\n\n💥 **[치명적 손상]** 괴수의 힘을 이기지 못하고 **낚싯대가 부러졌습니다!** (낚싯대 레벨 1 하락)"
            
            await interaction.response.edit_message(content=fail_msg, view=None)

class BattleView(View):
    def __init__(self, user, my_fish, npc_fish):
        super().__init__(timeout=60)
        self.user = user
        self.my_fish = my_fish
        self.npc_fish = npc_fish
        
        self.my_max_hp = self.my_hp = FISH_DATA[my_fish]["power"] * 10
        self.my_atk = FISH_DATA[my_fish]["power"]
        self.my_ap = 1
        self.my_elem = FISH_DATA[my_fish]["element"]
        self.is_my_defending = False
        
        self.npc_max_hp = self.npc_hp = FISH_DATA[npc_fish]["power"] * 10
        self.npc_atk = FISH_DATA[npc_fish]["power"]
        self.npc_ap = 1
        self.npc_elem = FISH_DATA[npc_fish]["element"]
        self.is_npc_defending = False

        self.turn = 1
        self.battle_log = "전투가 시작되었습니다!\n"

    def generate_embed(self):
        embed = discord.Embed(title=f"⚔️ 턴제 수산 배틀 (Turn {self.turn})", color=0xff0000)
        my_hp_bar = "🟩" * max(0, int((self.my_hp / self.my_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.my_hp / self.my_max_hp) * 5)))
        embed.add_field(name=f"🔵 {self.user.name}의 [{self.my_elem}]", 
                        value=f"**{self.my_fish}**\n체력: {self.my_hp}/{self.my_max_hp} {my_hp_bar}\nAP: ⚡x{self.my_ap}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        npc_hp_bar = "🟥" * max(0, int((self.npc_hp / self.npc_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.npc_hp / self.npc_max_hp) * 5)))
        embed.add_field(name=f"🔴 야생의 [{self.npc_elem}]", 
                        value=f"**{self.npc_fish}**\n체력: {self.npc_hp}/{self.npc_max_hp} {npc_hp_bar}\nAP: ⚡x{self.npc_ap}", inline=True)
        embed.add_field(name="📜 전투 로그", value=f"```\n{self.battle_log}\n```", inline=False)
        return embed

    async def execute_turn(self, interaction: discord.Interaction, action: str):
        self.battle_log = ""
        
        if action == "attack":
            self.is_my_defending = False
            mult = get_element_multiplier(self.my_elem, self.npc_elem)
            dmg = int(self.my_atk * self.my_ap * mult)
            if self.is_npc_defending: dmg //= 2
            
            self.npc_hp -= dmg
            elem_txt = "(효과 발군!)" if mult > 1.0 else ("(효과 미미...)" if mult < 1.0 else "")
            self.battle_log += f"🔵 {self.my_fish}의 공격! 💥 {dmg} 피해! {elem_txt}\n"
            self.my_ap = 1 
        else: 
            self.is_my_defending = True
            self.my_ap += 1
            self.battle_log += f"🔵 {self.my_fish} 방어 태세! 피해 반감 & AP 1 회복.\n"

        if self.npc_hp <= 0:
            return await self.end_battle(interaction, is_win=True)

        npc_action = "attack" if (random.random() > 0.4 and self.npc_ap > 0) else "defend"
        
        if npc_action == "attack":
            self.is_npc_defending = False
            mult = get_element_multiplier(self.npc_elem, self.my_elem)
            dmg = int(self.npc_atk * self.npc_ap * mult)
            if self.is_my_defending: dmg //= 2
            
            self.my_hp -= dmg
            self.battle_log += f"🔴 {self.npc_fish}의 반격! 💥 {dmg} 피해!\n"
            self.npc_ap = 1
        else:
            self.is_npc_defending = True
            self.npc_ap += 1
            self.battle_log += f"🔴 {self.npc_fish} 방어 태세. 기를 모읍니다.\n"

        if self.my_hp <= 0:
            return await self.end_battle(interaction, is_win=False)

        self.turn += 1
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def end_battle(self, interaction, is_win):
        self.stop() 
        embed = self.generate_embed()
        
        if is_win:
            reward_rp = random.randint(10, 30)
            reward_coin = FISH_DATA[self.npc_fish]["power"] * 5
            await db.execute("UPDATE user_data SET rating = rating + ?, coins = coins + ? WHERE user_id = ?", (reward_rp, reward_coin, self.user.id))
            await db.commit()
            embed.description = f"🎉 **승리했습니다!** (보상: +{reward_rp} RP, +{reward_coin} C)"
            embed.color = 0x00ff00
        else:
            lose_rp = random.randint(5, 15)
            await db.execute("UPDATE user_data SET rating = MAX(0, rating - ?) WHERE user_id = ?", (lose_rp, self.user.id))
            await db.commit()
            embed.description = f"💀 **패배했습니다...** (패널티: -{lose_rp} RP)"
            embed.color = 0x555555

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="공격 (AP소모)", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def btn_attack(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "attack")

    @discord.ui.button(label="방어/기모으기 (AP+1)", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def btn_defend(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "defend")

# [3] 턴제 PvP (유저 간 약탈/대결) 배틀 UI
class PvPBattleView(View):
    def __init__(self, p1, p2, p1_fish, p2_fish):
        super().__init__(timeout=120) # 2분 동안 반응 없으면 종료
        self.p1 = p1
        self.p2 = p2
        self.p1_fish = p1_fish
        self.p2_fish = p2_fish
        
        # P1(공격자) 스탯
        self.p1_max_hp = self.p1_hp = FISH_DATA[p1_fish]["power"] * 10
        self.p1_atk = FISH_DATA[p1_fish]["power"]
        self.p1_ap = 1
        self.p1_elem = FISH_DATA[p1_fish]["element"]
        self.p1_defending = False
        
        # P2(방어자) 스탯
        self.p2_max_hp = self.p2_hp = FISH_DATA[p2_fish]["power"] * 10
        self.p2_atk = FISH_DATA[p2_fish]["power"]
        self.p2_ap = 1
        self.p2_elem = FISH_DATA[p2_fish]["element"]
        self.p2_defending = False

        self.turn_count = 1
        self.current_turn_user = p1 # 공격자가 먼저 선공
        self.battle_log = f"⚔️ {p1.name}님이 {p2.name}님에게 수산대전을 걸었습니다!\n"

    def generate_embed(self):
        embed = discord.Embed(title=f"⚔️ 수산대전 PvP (Turn {self.turn_count})", color=0xff0000)
        embed.description = f"**현재 턴:** {self.current_turn_user.mention} 님의 행동을 기다리는 중..."

        p1_hp_bar = "🟩" * max(0, int((self.p1_hp / self.p1_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.p1_hp / self.p1_max_hp) * 5)))
        embed.add_field(name=f"🔵 {self.p1.name} [{self.p1_elem}]", 
                        value=f"**{self.p1_fish}**\n체력: {self.p1_hp}/{self.p1_max_hp} {p1_hp_bar}\nAP: ⚡x{self.p1_ap}", inline=True)
        
        embed.add_field(name="VS", value="⚡", inline=True)

        p2_hp_bar = "🟥" * max(0, int((self.p2_hp / self.p2_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.p2_hp / self.p2_max_hp) * 5)))
        embed.add_field(name=f"🔴 {self.p2.name} [{self.p2_elem}]", 
                        value=f"**{self.p2_fish}**\n체력: {self.p2_hp}/{self.p2_max_hp} {p2_hp_bar}\nAP: ⚡x{self.p2_ap}", inline=True)
        
        # 로그가 너무 길어지지 않게 최근 5줄만 표시
        log_display = "\n".join(self.battle_log.split("\n")[-6:]) 
        embed.add_field(name="📜 전투 로그", value=f"```\n{log_display}\n```", inline=False)
        return embed

    async def execute_turn(self, interaction: discord.Interaction, action: str):
        if interaction.user != self.current_turn_user:
            return await interaction.response.send_message("❌ 당신의 턴이 아닙니다! 기다리세요.", ephemeral=True)

        is_p1 = (interaction.user == self.p1)

        attacker_name = self.p1.name if is_p1 else self.p2.name
        attacker_fish = self.p1_fish if is_p1 else self.p2_fish
        attacker_elem = self.p1_elem if is_p1 else self.p2_elem
        attacker_atk = self.p1_atk if is_p1 else self.p2_atk
        attacker_ap = self.p1_ap if is_p1 else self.p2_ap

        defender_elem = self.p2_elem if is_p1 else self.p1_elem
        defender_defending = self.p2_defending if is_p1 else self.p1_defending

        if action == "attack":
            if is_p1: self.p1_defending = False
            else: self.p2_defending = False

            mult = get_element_multiplier(attacker_elem, defender_elem)
            dmg = int(attacker_atk * attacker_ap * mult)
            if defender_defending: dmg //= 2

            if is_p1:
                self.p2_hp -= dmg
                self.p1_ap = 1
            else:
                self.p1_hp -= dmg
                self.p2_ap = 1

            elem_txt = "(효과 발군!)" if mult > 1.0 else ("(효과 미미...)" if mult < 1.0 else "")
            self.battle_log += f"[{attacker_name}] {attacker_fish}의 공격! 💥 {dmg} 피해! {elem_txt}\n"

        else: # defend
            if is_p1:
                self.p1_defending = True
                self.p1_ap += 1
            else:
                self.p2_defending = True
                self.p2_ap += 1
            self.battle_log += f"[{attacker_name}] 방어 태세! 피해 반감 & AP 1 회복.\n"

        # 사망(승패) 체크
        if self.p1_hp <= 0 or self.p2_hp <= 0:
            winner = self.p1 if self.p2_hp <= 0 else self.p2
            loser = self.p2 if self.p2_hp <= 0 else self.p1
            return await self.end_battle(interaction, winner, loser)

        # 다음 턴으로 넘기기
        self.current_turn_user = self.p2 if is_p1 else self.p1
        self.turn_count += 1
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def end_battle(self, interaction, winner, loser):
        self.stop() 
        embed = self.generate_embed()
        
        # 🌟 마라맛 보상 & 패널티 시스템
        reward_rp = random.randint(15, 30)
        reward_coin = random.randint(500, 2000) 
        
        # 승자는 얻고, 패자는 잃는다! (약탈)
        await db.execute("UPDATE user_data SET rating = rating + ?, coins = coins + ? WHERE user_id = ?", (reward_rp, reward_coin, winner.id))
        await db.execute("UPDATE user_data SET rating = MAX(0, rating - ?), coins = MAX(0, coins - ?) WHERE user_id = ?", (reward_rp, int(reward_coin * 0.5), loser.id))
        await db.commit()

        embed.description = f"🏆 **{winner.mention}님의 승리!!**\n\n**승자({winner.name}):** `+{reward_rp} RP`, `+{reward_coin} C`\n**패자({loser.name}):** `-{reward_rp} RP`, `-{int(reward_coin * 0.5)} C` (약탈당함!)"
        embed.color = 0x00ff00

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="공격 (AP소모)", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def btn_attack(self, interaction: discord.Interaction, button: Button):
        await self.execute_turn(interaction, "attack")

    @discord.ui.button(label="방어/기모으기 (AP+1)", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def btn_defend(self, interaction: discord.Interaction, button: Button):
        await self.execute_turn(interaction, "defend")

class MarketPaginationView(View):
    def __init__(self, items, per_page=10):
        super().__init__(timeout=120)
        self.items = list(items.items())
        self.per_page = per_page
        self.current_page = 0

    def make_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        current_items = self.items[start:end]
        
        embed = discord.Embed(title="📊 현재 수산시장 시세표", description=f"총 {len(self.items)}종의 물고기 시세입니다.", color=0xf1c40f)
        for fish, current_price in current_items:
            base = FISH_DATA[fish]["price"]
            ratio = current_price / base
            status = "📈 떡상" if ratio > 1.2 else ("📉 떡락" if ratio < 0.8 else "➖ 평범")
            embed.add_field(name=fish, value=f"현재가: **{current_price} C**\n({status})", inline=True)
        
        embed.set_footer(text=f"페이지: {self.current_page + 1} / {int((len(self.items)-1)/self.per_page) + 1}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: Button):
        if (self.current_page + 1) * self.per_page < len(self.items):
            self.current_page += 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

class DragonKingBlessingView(View):
    def __init__(self):
        super().__init__(timeout=300) # 5분간 유지
        self.claimed_users = set()

    @discord.ui.button(label="고개 조아리기", style=discord.ButtonStyle.success, emoji="🙇")
    async def bow_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. 유저 정보 확인 및 생성
        await get_user_data(interaction.user.id)
        
        if interaction.user.id in self.claimed_users:
            return await interaction.response.send_message("👑 용왕님: \"이미 축복을 내렸느니라. 과한 욕심은 화를 부르는 법이지.\"", ephemeral=True)

        self.claimed_users.add(interaction.user.id)

        # 2. 확률형 코인 지급 로직
        rand_val = random.randint(1, 1000)

        if rand_val == 1: # 0.1% 확률: 50만 코인 (잭팟)
            bonus_coin = 500000
            msg = "👑 **[전설적인 축복]** 용왕이 당신을 보며 파안대소합니다!\n"
            msg += f"💰 `{bonus_coin:,} C`를 하사받았습니다!\n\n"
            msg += "*\"허허, 마음에 쏙 드는구나! 혹시... 육지에 두고 왔다는 그 간도 나에게 줄 수 있겠느냐?\"*"

        elif rand_val <= 30: # 3% 확률: 10만 ~ 49.9만
            bonus_coin = random.randint(100000, 499999)
            msg = f"✨ **[특별한 시선]** 용왕이 당신을 눈여겨봅니다...\n💰 `{bonus_coin:,} C`를 하사받았습니다!"

        elif rand_val <= 200: # 17% 확률: 1만 ~ 9.9만
            bonus_coin = random.randint(10000, 99999)
            msg = f"🌊 용왕이 당신을 더욱 축복합니다.\n💰 `{bonus_coin:,} C`를 하사받았습니다."

        else: # 80% 확률: 500 ~ 9,999
            bonus_coin = random.randint(500, 9999)
            msg = f"🐢 용왕의 소소한 축복이 닿았습니다.\n💰 `{bonus_coin:,} C`를 획득했습니다."

        # 3. DB에 코인 지급
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (bonus_coin, interaction.user.id))
        await db.commit()

        await interaction.response.send_message(msg, ephemeral=True)

# ==========================================
# 5. 슬래시 명령어 (Slash Commands)
# ==========================================
# ==========================================
# 🌟 미끼 자동완성 함수 (내가 보유한 미끼만 표시)
# ==========================================
async def bait_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    baits = ["고급 미끼 🪱", "자석 미끼 🧲"]
    query = f"SELECT item_name FROM inventory WHERE user_id=? AND item_name IN ({','.join(['?']*len(baits))}) AND amount > 0"
    async with db.execute(query, [interaction.user.id] + baits) as cursor:
        items = await cursor.fetchall()
    
    choices = [app_commands.Choice(name="미끼 없음 (기본)", value="none")]
    for row in items:
        if current.lower() in row[0].lower():
            choices.append(app_commands.Choice(name=row[0], value=row[0]))
    return choices[:25]

async def fish_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = [
        app_commands.Choice(name=fish, value=fish)
        for fish in FISH_DATA.keys() if current.lower() in fish.lower()
    ]
    return choices[:25]

# 수족관 전용 자동완성 (내 가방에 있는 것만 보여줌)
async def inv_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with db.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in items if current.lower() in row[0].lower()][:25]

# 수족관 전용 자동완성 (내 수족관에 있는 것만 보여줌)
async def aqua_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with db.execute("SELECT item_name FROM aquarium WHERE user_id=?", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in items if current.lower() in row[0].lower()][:25]

@bot.tree.command(name="낚시", description="찌를 던져 물고기(또는 보물)를 낚습니다! (타이밍 미니게임)")
@app_commands.autocomplete(사용할미끼=bait_autocomplete)
async def 낚시(interaction: discord.Interaction, 사용할미끼: str = "none"):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    
    bait_used = 사용할미끼
    bait_text = ""
    
    # 1. 미끼 인벤토리 확인
    if bait_used != "none":
        async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used)) as cursor:
            bait_res = await cursor.fetchone()
        
        if not bait_res or bait_res[0] <= 0:
            return await interaction.response.send_message(f"❌ 가방에 **{bait_used}**가 없습니다! 상점에서 먼저 구매해주세요.", ephemeral=True)
            
        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
        await db.commit()
        bait_text = f" ({bait_used} 사용됨!)"

    now_str = datetime.datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')
    async with db.execute("SELECT buff_type FROM active_buffs WHERE user_id=? AND end_time > ?", (interaction.user.id, now_str)) as cursor:
        active_buffs = [row[0] for row in await cursor.fetchall()]

    candidates = []
    weights = []
    
    # 🌟 [망자의 해역] 기믹: 지도를 사용한 유저는 1시간 동안 이곳에서만 낚시함
    if "ghost_sea_open" in active_buffs:
        ghost_items = {
            "해적의 금화 🪙": 60, 
            "가라앉은 보물상자 🧰": 25, 
            "낡은 고철 ⚙️": 15
        }
        for item, prob in ghost_items.items():
            candidates.append(item)
            weights.append(prob)
        bait_text += "\n*(☠️ 망자의 해역: 주변에 물고기의 기척이 전혀 없습니다...)*"
        
    else:
        # 기존 일반 낚시 로직
        for fish, data in FISH_DATA.items():
            base_prob = data["prob"]
            grade = data["grade"]
            
            if bait_used == "자석 미끼 🧲":
                if fish not in ["낡은 고철 ⚙️", "해적의 금화 🪙", "가라앉은 보물상자 🧰"]:
                    continue
                base_prob *= 2.0 
                
            elif bait_used == "고급 미끼 🪱":
                if grade == "일반":
                    base_prob *= 0.1
                elif grade in ["희귀", "초희귀"]:
                    base_prob *= 1.5

            if "deep_sea_boost" in active_buffs and data["element"] == "심해":
                base_prob *= 2.0
                
            if grade in ["에픽", "레전드", "신화"]:
                base_prob *= (1 + (rod_tier * 0.1))

            candidates.append(fish)
            weights.append(base_prob)
        
    if not candidates:
        target_fish = "낡은 장화 🥾"
    else:
        target_fish = random.choices(candidates, weights=weights, k=1)[0]

    now_hour = datetime.datetime.now(kst).hour
    if target_fish == "바다의 원혼, 우미보즈 🌑" and not (0 <= now_hour < 4):
        target_fish = "낡은 장화 🥾"
        bait_text += "\n*(으스스한 기운이 맴돌았지만, 날이 밝아 흩어졌습니다...)*"
            
    if target_fish == "네스호의 그림자, 네시 🦕" and 'CURRENT_WEATHER' in globals() and CURRENT_WEATHER not in ["🌧️ 비", "🌫️ 안개"]:
        target_fish = "낡은 장화 🥾"
        bait_text += "\n*(거대한 그림자가 지나갔지만, 날씨가 맑아 깊은 곳으로 숨어버렸습니다...)*"

    view = FishingView(interaction.user, target_fish, rod_tier)
    await interaction.response.send_message(f"🌊 찌를 던졌습니다... 조용히 기다리세요.{bait_text}\n(내 낚싯대: Lv.{rod_tier})", view=view)
    
    wait_min, wait_max = (1, 3) if "cooldown_reduction" in active_buffs else (2, 6)
    wait_time = random.uniform(wait_min, wait_max)
    await asyncio.sleep(wait_time)
    
    view.is_bite = True
    view.start_time = datetime.datetime.now().timestamp()
    
    for item in view.children:
        item.label = "지금 챔질하세요!!!!"
        item.style = discord.ButtonStyle.success
        item.emoji = "‼️"
    
    try:
        msg = await interaction.edit_original_response(content="❗ **찌가 격렬하게 흔들립니다! 지금 누르세요!!!**", view=view)
        view.message = msg 
    except: 
        pass

@bot.tree.command(name="인벤토리", description="내 가방과 현재 스탯을 확인합니다.")
async def 인벤토리(interaction: discord.Interaction):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    embed = discord.Embed(title=f"🎒 {interaction.user.name}의 인벤토리", color=0x3498db)
    embed.add_field(name="🏆 전투 레이팅", value=f"`{rating} RP`", inline=True)
    embed.add_field(name="💰 보유 코인", value=f"`{coins:,} C`", inline=True)
    embed.add_field(name="🎣 낚싯대 레벨", value=f"`Lv.{rod_tier}`", inline=True)
    
    if items:
        item_list = "\n".join([f"• {name}: {amt}개" for name, amt in items])
        embed.add_field(name="🐟 물고기 도감", value=item_list, inline=False)
    else:
        embed.add_field(name="🐟 물고기 도감", value="텅 비었습니다...", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="시세", description="현재 수산시장의 글로벌 시세를 확인합니다. (물고기 이름을 검색할 수도 있습니다)")
@app_commands.autocomplete(검색어=fish_autocomplete) # 🌟 모든 물고기 이름 자동완성
async def 시세(interaction: discord.Interaction, 검색어: str = None):
    # 검색어를 입력한 경우 (단일 물고기 시세 조회)
    if 검색어:
        if 검색어 not in MARKET_PRICES:
            return await interaction.response.send_message(f"❌ '{검색어}'에 대한 정보가 수산시장에 없습니다.", ephemeral=True)
            
        base = FISH_DATA[검색어]["price"]
        current_price = MARKET_PRICES[검색어]
        ratio = current_price / base
        status = "📈 떡상" if ratio > 1.2 else ("📉 떡락" if ratio < 0.8 else "➖ 평범")
        
        embed = discord.Embed(title=f"📊 {검색어} 시세 정보", color=0xf1c40f)
        embed.add_field(name="현재 시장가", value=f"**{current_price} C**", inline=True)
        embed.add_field(name="시세 상태", value=status, inline=True)
        return await interaction.response.send_message(embed=embed)
        
    # 검색어를 입력하지 않은 경우 (기존 전체 페이지 조회)
    view = MarketPaginationView(MARKET_PRICES)
    await interaction.response.send_message(embed=view.make_embed(), view=view)

@bot.tree.command(name="판매", description="인벤토리에 있는 물고기를 일괄 판매합니다. (특정 물고기를 판매에서 제외할 수 있습니다)")
@app_commands.describe(제외1="판매하지 않고 보호할 아이템 1", 제외2="판매하지 않고 보호할 아이템 2", 제외3="판매하지 않고 보호할 아이템 3")
@app_commands.autocomplete(제외1=inv_autocomplete, 제외2=inv_autocomplete, 제외3=inv_autocomplete)
async def 판매(interaction: discord.Interaction, 제외1: str = None, 제외2: str = None, 제외3: str = None):
    # 🌟 1. 타임아웃 방지 (필수!)
    await interaction.response.defer()

    async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    # 기본적으로 보호되는 중요 아이템들 (고정)
    protected_items = ["낡은 고철 ⚙️", "가라앉은 보물상자 🧰", "고급 미끼 🪱", "자석 미끼 🧲", "찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]
    
    # 유저가 명령어를 칠 때 직접 선택한 제외 아이템들 추가
    user_excludes = [x for x in [제외1, 제외2, 제외3] if x is not None]
    protected_items.extend(user_excludes)
    
    # 보호 목록에 없는 아이템만 판매 목록에 담기
    sellable_items = [(name, amt) for name, amt in items if name not in protected_items]
    
    if not sellable_items:
        return await interaction.followup.send("❌ 판매할 수 있는 물고기가 없습니다!\n(모두 보호 처리되었거나 가방이 텅 비어있습니다.)", ephemeral=True)
        
    total_earned = 0
    msg = "**[💰 수산시장 일괄 판매 영수증]**\n"
    
    # 유저가 직접 제외한 항목이 있다면 영수증에 표시해줌
    if user_excludes:
        msg += f"*(🛡️ 선택 보호됨: {', '.join(user_excludes)})*\n\n"

    # 🌟 2. 영수증 내역 작성하기!
    for name, amt in sellable_items:
        # 시장 시세 변동가(MARKET_PRICES)를 먼저 확인하고, 없으면 기본가(FISH_DATA) 확인
        if name in MARKET_PRICES:
            price = MARKET_PRICES[name]
        elif name in FISH_DATA:
            price = FISH_DATA[name]["price"]
        elif name in RECIPES and "price" in RECIPES[name]: # 특급 참치 초밥(비싸게 팔리는 요리)인 경우
            price = RECIPES[name]["price"]
        else:
            price = 0 # 데이터에 없는 이상한 아이템은 0원 처리
            
        item_total = price * amt
        total_earned += item_total
        
        # 품목, 수량, 합계, 개당 가격을 영수증(msg)에 한 줄씩 추가합니다.
        msg += f"• {name} {amt}마리 : `{item_total:,} C` (개당 {price:,}C)\n"
    
    # 팔아야 할 아이템 리스트 생성
    delete_targets = [(interaction.user.id, name) for name, amt in sellable_items]

    # executemany로 한 번에 삭제 처리
    await db.executemany("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", delete_targets)
        
    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (total_earned, interaction.user.id))
    await db.commit()
    
    msg += f"\n**총 수익: +{total_earned:,} C**"
    
    # 🌟 3. 물고기 종류가 너무 많아서 디스코드 메시지 제한(2000자)을 넘길 경우 방어
    if len(msg) > 1900:
        msg = msg[:1900] + "\n... (목록이 너무 길어 생략됨) ...\n" + f"\n**총 수익: +{total_earned:,} C**"

    # 🌟 4. defer를 썼으므로 send_message 대신 followup.send 사용
    await interaction.followup.send(msg)

@bot.tree.command(name="강화", description="코인을 지불하여 낚싯대를 업그레이드합니다. (타이밍 판정 및 확률 증가)")
async def 강화(interaction: discord.Interaction):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    cost = rod_tier * 2000 
    
    if coins < cost:
        return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)", ephemeral=True)
        
    await db.execute("UPDATE user_data SET coins = coins - ?, rod_tier = rod_tier + 1 WHERE user_id = ?", (cost, interaction.user.id))
    await db.commit()
    await interaction.response.send_message(f"✨ 캉! 캉! 캉! ... 낚싯대가 **Lv.{rod_tier + 1}** 로 강화되었습니다!\n(낚시 판정 시간이 늘어나고, 희귀 물고기 획득률이 상승합니다!)")

@bot.tree.command(name="선박개조", description="코인과 고철을 모아 배를 다음 티어로 업그레이드하고 새로운 기능을 해금합니다!")
async def 선박개조(interaction: discord.Interaction):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    
    async with db.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
        res = await cursor.fetchone()
    current_tier = res[0] if res else 1

    # 가방에 있는 고철 갯수 확인
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (interaction.user.id,)) as cursor:
        scrap_res = await cursor.fetchone()
    scrap_amount = scrap_res[0] if scrap_res else 0

    # 티어별 업그레이드 비용 
    upgrade_costs = {
        1: {"coins": 10000, "scrap": 0, "next": "어선 🚤", "unlock": "/요리, /의뢰, /상점, /구매"},
        2: {"coins": 50000, "scrap": 15, "next": "쇄빙선 🛳️", "unlock": "/전시, /배틀"},
        3: {"coins": 150000, "scrap": 30, "next": "잠수함 ⛴️", "unlock": "/수산대전(PvP), 신화 어종 포획 가능"}
    }

    if current_tier >= 4:
        return await interaction.response.send_message("✨ 이미 최고의 선박인 **[잠수함 ⛴️]**을 보유하고 있습니다!", ephemeral=True)

    req = upgrade_costs[current_tier]
    
    if coins < req["coins"] or scrap_amount < req["scrap"]:
        embed = discord.Embed(title="❌ 재료 부족", description="선박을 개조하기 위한 자원이 부족합니다.", color=0xe74c3c)
        embed.add_field(name="필요 코인", value=f"`{req['coins']:,} C` (보유: `{coins:,} C`)", inline=True)
        if req["scrap"] > 0:
            embed.add_field(name="필요 고철 ⚙️", value=f"`{req['scrap']}개` (보유: `{scrap_amount}개`)", inline=True)
            embed.set_footer(text="💡 상점에서 자석 미끼를 구매해 바다에서 고철을 건져올리세요!")
        else:
            embed.set_footer(text="💡 열심히 낚시를 해서 코인을 모아보세요!")
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    # 재화 차감 및 승급
    await db.execute("UPDATE user_data SET coins = coins - ?, boat_tier = boat_tier + 1 WHERE user_id = ?", (req["coins"], interaction.user.id))
    if req["scrap"] > 0:
        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (req["scrap"], interaction.user.id))
    await db.commit()

    embed = discord.Embed(title="🎉 선박 개조 완료!", description=f"뚝딱뚝딱... 쾅!\n배가 **[{req['next']}]**(으)로 업그레이드 되었습니다!", color=0x2ecc71)
    embed.add_field(name="🔓 새로운 기능 해금!", value=f"`{req['unlock']}` 명령어를 이제 사용할 수 있습니다.", inline=False)
    await interaction.response.send_message(embed=embed)

    embed = discord.Embed(title="🎉 선박 개조 완료!", description=f"뚝딱뚝딱... 쾅!\n배가 **[{req['next']}]**(으)로 업그레이드 되었습니다!", color=0x2ecc71)
    embed.add_field(name="🔓 새로운 기능 해금!", value=f"`{req['unlock']}` 명령어를 이제 사용할 수 있습니다.", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="배틀", description="나의 가장 강한 물고기로 야생의 NPC 물고기와 턴제 배틀을 진행합니다!")
@check_boat_tier(3)
async def 배틀(interaction: discord.Interaction):
    await get_user_data(interaction.user.id) 
    
    async with db.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    if not items:
        return await interaction.response.send_message("❌ 통(배틀용)이 비어있습니다! 낚시 후 '통에 보관'을 선택해 전사를 포획하세요.", ephemeral=True)
    
    my_best_fish = None
    max_power = -1
    for (name,) in items:
        power = FISH_DATA[name]["power"]
        if power > max_power:
            max_power = power
            my_best_fish = name
            
    npc_pool = [name for name, data in FISH_DATA.items() if data["grade"] != "히든"]
    npc_fish = random.choice(npc_pool)
    
    view = BattleView(interaction.user, my_best_fish, npc_fish)
    await interaction.response.send_message(embed=view.generate_embed(), view=view)

@bot.tree.command(name="출석", description="하루에 한 번 출석체크하고 1000 코인을 받습니다!")
async def 출석(interaction: discord.Interaction):
    await get_user_data(interaction.user.id) 
    today = datetime.datetime.now(kst).strftime('%Y-%m-%d')
    
    async with db.execute("SELECT last_daily FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
        last_daily = (await cursor.fetchone())[0]
    
    if last_daily == today:
        return await interaction.response.send_message("❌ 오늘은 이미 출석하셨습니다! 내일 다시 와주세요.", ephemeral=True)
    
    reward = 1000
    await db.execute("UPDATE user_data SET coins = coins + ?, last_daily = ? WHERE user_id = ?", (reward, today, interaction.user.id))
    await db.commit()
    
    await interaction.response.send_message(f"✅ 출석 완료! 보상으로 `{reward} C`를 받았습니다. (잔액 확인: `/인벤토리`)")

# ==========================================
# 상점 & 구매 명령어 업데이트 (자석 미끼 추가)
# ==========================================
@bot.tree.command(name="상점", description="유용한 아이템을 구경할 수 있는 상점입니다.")
@check_boat_tier(2)
async def 상점(interaction: discord.Interaction):
    embed = discord.Embed(title="🏪 수산시장 아이템 상점", color=0xf1c40f)
    embed.add_field(name="고급 미끼 🪱 (가격: 500 C)", 
                    value="다음 낚시 때 일반 어종을 피하고 희귀 어종 등장 확률을 올려줍니다.", inline=False)
    embed.add_field(name="자석 미끼 🧲 (가격: 800 C)", 
                    value="물고기는 낚이지 않지만, 바다 밑에 가라앉은 고철이나 보물을 확정적으로 건져냅니다.", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="구매", description="상점에서 아이템을 구매합니다.")
@app_commands.choices(아이템=[
    app_commands.Choice(name="고급 미끼 🪱", value="고급 미끼 🪱"),
    app_commands.Choice(name="자석 미끼 🧲", value="자석 미끼 🧲")
])
@check_boat_tier(2)

async def 구매(interaction: discord.Interaction, 아이템: app_commands.Choice[str], 수량: int = 1):
    if 수량 <= 0: 
        return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)
        
    coins, _, _ = await get_user_data(interaction.user.id)
    price = 500 * 수량 if 아이템.value == "고급 미끼 🪱" else 800 * 수량
    
    if coins < price:
        return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {price} C / 현재: {coins} C)", ephemeral=True)
    
    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
    await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 아이템.value, 수량, 수량))
    await db.commit()
    
    await interaction.response.send_message(f"🛍️ **{아이템.value}** {수량}개를 구매했습니다! (남은 코인: `{coins - price} C`)")

@bot.tree.command(name="통", description="배틀에 출전할 수 있는 통(배틀 전용 저장소)을 확인합니다.")
async def 통(interaction: discord.Interaction):
    async with db.execute("SELECT item_name, amount FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    embed = discord.Embed(title=f"🪣 {interaction.user.name}의 통 (배틀 대기조)", color=0x2ecc71)
    if items:
        item_list = "\n".join([f"• {name}: {amt}마리 (전투력: {FISH_DATA[name]['power']}⚡)" for name, amt in items])
        embed.add_field(name="출전 가능한 물고기", value=item_list, inline=False)
    else:
        embed.add_field(name="텅 비었습니다...", value="낚시 성공 후 '통에 보관'을 눌러주세요.", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="개별판매", description="가방에 있는 특정 물고기/아이템을 원하는 수량만큼 판매합니다.")
@app_commands.autocomplete(물고기=inv_autocomplete) # 🌟 fish_autocomplete 대신 inv_autocomplete 적용
async def 개별판매(interaction: discord.Interaction, 물고기: str, 수량: int):
    target_fish = 물고기
    
    if 수량 <= 0:
        return await interaction.response.send_message("❌ 수량은 1마리 이상이어야 합니다.", ephemeral=True)
        
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, target_fish)) as cursor:
        res = await cursor.fetchone()
    current_amount = res[0] if res else 0
    
    if current_amount < 수량:
        return await interaction.response.send_message(f"❌ 가방에 **{target_fish}**가 부족합니다. (현재 보유: {current_amount}마리)", ephemeral=True)
    
    price_per_item = MARKET_PRICES.get(target_fish, FISH_DATA[target_fish]["price"])
    total_earned = price_per_item * 수량
    
    await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, target_fish))
    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (total_earned, interaction.user.id))
    await db.commit()
    
    await interaction.response.send_message(f"💰 **{target_fish}** {수량}마리를 팔아서 총 `{total_earned:,} C`를 얻었습니다! (개당 {price_per_item}C)")

@bot.tree.command(name="도감", description="내가 지금까지 발견한 모든 물고기 기록과 수집률을 확인합니다.")
async def 도감(interaction: discord.Interaction):
    # 유저의 도감 기록 불러오기
    async with db.execute("SELECT item_name FROM fish_dex WHERE user_id=?", (interaction.user.id,)) as cursor:
        dex_items = await cursor.fetchall()
    
    collected_names = [item[0] for item in dex_items]
    total_fish = len(FISH_DATA)
    collected_count = len(collected_names)
    percent = (collected_count / total_fish) * 100
    
    # 수집률에 따른 칭호(등급) 판별
    if percent == 100: dex_rank = "👑 그랜드 마스터 앵글러"
    elif percent >= 70: dex_rank = "🥇 엘리트 어류학자"
    elif percent >= 50: dex_rank = "🥈 어류학자"
    elif percent >= 30: dex_rank = "🥉 낚시계의 새싹"
    elif percent >= 10: dex_rank = "🌱 낚시계의 떡잎"
    else: dex_rank = "🥚 초보 낚시꾼"

    embed = discord.Embed(title=f"📖 {interaction.user.name}님의 낚시 도감", color=0x9b59b6)
    embed.add_field(name="현재 수집률", value=f"**{collected_count} / {total_fish} 종** (`{percent:.1f}%`)", inline=False)
    embed.add_field(name="도감 등급", value=f"**{dex_rank}**", inline=False)
    
    # 최근 모은 5가지 물고기 보여주기
    if collected_names:
        recent_fish = "\n".join([f"• {name}" for name in collected_names[-5:]]) # 리스트의 마지막 5개
        embed.add_field(name="최근 발견한 어종", value=recent_fish, inline=False)
    else:
        embed.add_field(name="최근 발견한 어종", value="아직 발견한 물고기가 없습니다.", inline=False)
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="바다", description="현재 바다의 시간대와 날씨 환경을 확인합니다.")
async def 바다(interaction: discord.Interaction):
    now_hour = datetime.datetime.now(kst).hour
    if 6 <= now_hour < 18: time_str = "☀️ 낮"
    elif 18 <= now_hour < 24: time_str = "🌙 밤"
    else: time_str = "🌑 새벽"

    embed = discord.Embed(title="🌊 현재 바다 상황", color=0x3498db)
    embed.add_field(name="현재 시간대", value=f"**{time_str}** (`{now_hour}시`)", inline=True)
    embed.add_field(name="현재 날씨", value=f"**{CURRENT_WEATHER}**", inline=True)
    
    # 환경에 따른 출몰 힌트
    hints = ""
    if time_str == "🌑 새벽": hints += "- ⚠️ [신화] 우미보즈가 출몰할 수 있는 으스스한 시간입니다.\n"
    if CURRENT_WEATHER in ["🌧️ 비", "🌫️ 안개"]: hints += "- ⚠️ [레전드] 네시가 활동하기 좋은 날씨입니다.\n"
    if not hints: hints = "- 평화로운 바다입니다. 낚시하기 딱 좋네요!"
    
    embed.add_field(name="생태계 정보", value=hints, inline=False)
    await interaction.response.send_message(embed=embed)

async def recipe_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=r, value=r) for r in RECIPES.keys() if current.lower() in r.lower()][:25]

@bot.tree.command(name="한강물", description="모든 측정소의 한강 수온을 확인합니다. (우회 접속)")
async def 한강물(interaction: discord.Interaction):
    await interaction.response.defer() 
    
    try:
        api_key = os.getenv('SEOUL_API_KEY', 'sample')
        proxy_url = "https://seoul-proxy.mingm7115.workers.dev" # 설정하신 진짜 주소로 유지하세요!
        # 여러 지점의 데이터를 충분히 가져오기 위해 1/10으로 범위를 넓힙니다.
        url = f"{proxy_url}/{api_key}/json/WPOSInformationTime/1/10/"
        
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if 'WPOSInformationTime' not in data:
                        return await interaction.followup.send("❌ 데이터를 불러올 수 없습니다. API 키를 확인해주세요.")

                    rows = data['WPOSInformationTime']['row']
                    
                    # 지점별로 중복되지 않게 최신 데이터만 담을 딕셔너리
                    latest_data = {}
                    for item in rows:
                        site = item['MSRSTN_NM']
                        # 이미 담긴 지점이 아니라면 (가장 위가 최신이므로) 추가
                        if site not in latest_data:
                            latest_data[site] = item
                    
                    embed = discord.Embed(title="🌊 한강 주요 지점 실시간 수온", color=0x00a8ff)
                    
                    operational_sites = 0
                    for site, info in latest_data.items():
                        temp = info['WATT']
                        date = info['YMD']
                        hour = info['HR']
                        
                        if temp == "점검중":
                            temp_text = "🛠️ 점검 중"
                        else:
                            temp_text = f"**{temp}°C**"
                            operational_sites += 1
                        
                        embed.add_field(name=f"📍 {site}", value=temp_text, inline=True)
                    
                    if operational_sites == 0:
                        embed.description = "⚠️ 현재 모든 측정소가 점검 중입니다."
                    else:
                        embed.description = f"현재 {operational_sites}개 측정소가 정상 작동 중입니다. 🎣"
                    
                    # 가장 첫 번째 데이터의 시간으로 푸터 설정
                    first_date = rows[0]['YMD']
                    first_hour = rows[0]['HR']
                    embed.set_footer(text=f"측정 일시: {first_date[:4]}-{first_date[4:6]}-{first_date[6:8]} {first_hour}시 기준")
                    
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(f"❌ 서버 응답 오류: {response.status}")
                    
    except Exception as e:
        await interaction.followup.send(f"❌ 연결 실패: 프록시 서버 또는 네트워크를 확인해주세요. (`{e}`)")
    
@bot.tree.command(name="요리", description="잡은 물고기로 요리를 만들어 버프를 얻거나 비싸게 팝니다.")
@app_commands.autocomplete(선택=recipe_autocomplete)
@check_boat_tier(2)
async def 요리(interaction: discord.Interaction, 선택: str):
    recipe = RECIPES.get(선택)
    if not recipe:
        return await interaction.response.send_message("❌ 존재하지 않는 레시피입니다.", ephemeral=True)

    # 재료 확인
    for item, amt in recipe["ingredients"].items():
        async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, item)) as cursor:
            res = await cursor.fetchone()
            if not res or res[0] < amt:
                return await interaction.response.send_message(f"❌ 재료가 부족합니다! (필요: `{item}` {amt}마리)", ephemeral=True)

    # 재료 차감
    for item, amt in recipe["ingredients"].items():
        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (amt, interaction.user.id, item))
    
    # 결과 처리
    if recipe["buff_type"] == "sell_only":
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, 선택))
        msg = f"👨‍🍳 **{선택}** 완성! 가방에 보관되었습니다. 시장에 비싸게 파세요!"
    else:
        end_time = datetime.datetime.now(kst) + datetime.timedelta(minutes=recipe["duration"])
        end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # 복어 독 기믹
        if 선택 == "복어 지리탕 🍲" and random.random() < 0.1:
            await db.execute("UPDATE user_data SET coins = MAX(0, coins - 5000) WHERE user_id=?", (interaction.user.id,))
            msg = "🤢 **아야!** 복어 독에 당했습니다... 해독비로 `5,000C`를 썼지만, 버프는 적용되었습니다."
        else:
            msg = f"😋 **{선택}**을(를) 맛있게 먹었습니다!\n**효과:** {recipe['description']}"
        
        await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)", 
                         (interaction.user.id, recipe["buff_type"], end_time_str))
    
    await db.commit()
    await interaction.response.send_message(msg)

# ==========================================
# 🌟 항구 게시판 (일일 의뢰) 기능
# ==========================================

# 납품하기 버튼 UI
class QuestDeliveryView(View):
    def __init__(self, user, item, amount, reward):
        super().__init__(timeout=60)
        self.user = user
        self.item = item
        self.amount = amount
        self.reward = reward

    @discord.ui.button(label="📦 의뢰 납품하기", style=discord.ButtonStyle.success)
    async def deliver_btn(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return

        # 가방에 물고기가 충분히 있는지 확인
        async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (self.user.id, self.item)) as cursor:
            res = await cursor.fetchone()

        current_amount = res[0] if res else 0

        if current_amount < self.amount:
            return await interaction.response.send_message(f"❌ 가방에 물고기가 부족합니다! (현재: {current_amount} / 필요: {self.amount})", ephemeral=True)

        # 납품 처리: 물고기 차감, 보상 지급, 퀘스트 완료 처리
        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (self.amount, self.user.id, self.item))
        await db.execute("UPDATE user_data SET coins = coins + ?, quest_is_cleared = 1 WHERE user_id=?", (self.reward, self.user.id))
        await db.commit()

        embed = discord.Embed(title="🎉 의뢰 완료!", description=f"항구 촌장님께 **{self.item}** {self.amount}마리를 납품했습니다!\n보상으로 두둑한 `{self.reward:,} C`를 받았습니다!", color=0xf1c40f)
        await interaction.response.edit_message(embed=embed, view=None)

# 의뢰 확인 명령어
@bot.tree.command(name="의뢰", description="항구 게시판에서 오늘의 특별한 낚시 의뢰를 확인합니다.")
@check_boat_tier(2)
async def 의뢰(interaction: discord.Interaction):
    await get_user_data(interaction.user.id) # 유저 데이터 보장
    today = datetime.datetime.now(kst).strftime('%Y-%m-%d')

    async with db.execute("SELECT quest_date, quest_item, quest_amount, quest_reward, quest_is_cleared FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
        q_date, q_item, q_amount, q_reward, q_cleared = await cursor.fetchone()

    # 오늘 첫 확인이거나 날짜가 지났으면 새로운 의뢰 발급
    if q_date != today:
        # 무리한 요구를 하지 않도록 일반~초희귀 중에서만 픽!
        quest_pool = [fish for fish, data in FISH_DATA.items() if data["grade"] in ["일반", "희귀", "초희귀"]]
        q_item = random.choice(quest_pool)
        q_amount = random.randint(1, 3) # 1~3마리 요구
        # 기본 가격의 3~5배에 달하는 엄청난 보상 책정
        q_reward = FISH_DATA[q_item]["price"] * q_amount * random.randint(3, 5)
        q_cleared = 0
        q_date = today

        await db.execute("UPDATE user_data SET quest_date=?, quest_item=?, quest_amount=?, quest_reward=?, quest_is_cleared=0 WHERE user_id=?",
                         (q_date, q_item, q_amount, q_reward, interaction.user.id))
        await db.commit()

    # 이미 오늘 의뢰를 완료한 경우
    if q_cleared == 1:
        embed = discord.Embed(title="📜 오늘의 항구 의뢰", description="오늘의 의뢰는 이미 완료했습니다!\n마을이 평화롭네요. 내일 다시 와주세요.", color=0x95a5a6)
        return await interaction.response.send_message(embed=embed)

    # 의뢰 내용 보여주기
    embed = discord.Embed(title="📜 오늘의 항구 의뢰", description="마을 촌장님이 급하게 생선을 찾고 있습니다!", color=0xe67e22)
    embed.add_field(name="🎯 타겟 어종", value=f"**{q_item}**", inline=True)
    embed.add_field(name="🔢 필요 수량", value=f"`{q_amount}마리`", inline=True)
    embed.add_field(name="💰 납품 보상", value=f"`{q_reward:,} C`", inline=False)

    # 유저가 현재 가방에 몇 마리를 가지고 있는지 체크해서 힌트 표시
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, q_item)) as cursor:
        res = await cursor.fetchone()
    current = res[0] if res else 0

    embed.set_footer(text=f"내 가방에 보유한 수량: {current} / {q_amount}")

    view = QuestDeliveryView(interaction.user, q_item, q_amount, q_reward)
    await interaction.response.send_message(embed=embed, view=view)

# ==========================================
# 🌟 나만의 수족관 (플렉스/자랑하기) 기능
# ==========================================

@bot.tree.command(name="전시", description="가방에 있는 물고기를 수족관에 전시합니다. (최대 5마리)")
@app_commands.autocomplete(물고기=inv_autocomplete)
@check_boat_tier(3)
async def 전시(interaction: discord.Interaction, 물고기: str):
    # 1. 5마리 제한 확인
    async with db.execute("SELECT COUNT(*) FROM aquarium WHERE user_id=?", (interaction.user.id,)) as cursor:
        count = (await cursor.fetchone())[0]
    if count >= 5:
        return await interaction.response.send_message("❌ 수족관이 꽉 찼습니다! (최대 5마리). `/전시해제`를 먼저 해주세요.", ephemeral=True)
        
    # 2. 가방에 물고기가 있는지 확인
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
        res = await cursor.fetchone()
    if not res or res[0] <= 0:
        return await interaction.response.send_message(f"❌ 가방에 **{물고기}**가 없습니다!", ephemeral=True)
        
    # 3. 전시 처리 (가방에서 빼고 수족관에 넣기)
    await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기))
    await db.execute("INSERT INTO aquarium (user_id, item_name) VALUES (?, ?)", (interaction.user.id, 물고기))
    await db.commit()
    
    await interaction.response.send_message(f"✨ **{물고기}**을(를) 수족관에 멋지게 전시했습니다! (`/수족관`으로 확인해보세요!)")

@bot.tree.command(name="전시해제", description="수족관에 전시된 물고기를 다시 가방으로 되돌립니다.")
@app_commands.autocomplete(물고기=aqua_autocomplete)
async def 전시해제(interaction: discord.Interaction, 물고기: str):
    async with db.execute("SELECT item_name FROM aquarium WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
        res = await cursor.fetchone()
    if not res:
        return await interaction.response.send_message(f"❌ 수족관에 **{물고기}**가 없습니다!", ephemeral=True)
        
    # 해제 처리
    await db.execute("DELETE FROM aquarium WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기))
    await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, 물고기))
    await db.commit()
    
    await interaction.response.send_message(f"🎒 **{물고기}**을(를) 수족관에서 조심스럽게 꺼내 가방에 넣었습니다.")

@bot.tree.command(name="수족관", description="나 또는 다른 유저의 수족관을 구경합니다.")
async def 수족관(interaction: discord.Interaction, 유저: discord.Member = None):
    target = 유저 or interaction.user
    async with db.execute("SELECT item_name FROM aquarium WHERE user_id=?", (target.id,)) as cursor:
        items = await cursor.fetchall()
        
    embed = discord.Embed(title=f"🏛️ {target.name}님의 수족관", color=0x00ffff)
    if not items:
        embed.description = "수족관이 텅 비어있습니다... 휑~ 🌬️"
    else:
        desc = ""
        # 등급별로 어울리는 이모지 매핑
        grade_emojis = {"일반": "⚪", "희귀": "🔵", "초희귀": "🟣", "에픽": "🔴", "레전드": "🟡", "신화": "🔥", "히든": "✨"}
        
        for (name,) in items:
            grade = FISH_DATA[name]["grade"]
            emoji = grade_emojis.get(grade, "🐟")
            desc += f"{emoji} **{name}** `[{grade}]`\n\n"
            
        embed.description = desc
        embed.set_footer(text="남들에게 자랑할 만한 희귀한 물고기를 수집해 보세요!")
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="수산대전", description="다른 유저를 지목하여 마라맛 PvP 배틀(약탈)을 겁니다!")
@check_boat_tier(4)
async def 수산대전(interaction: discord.Interaction, 상대: discord.Member):
    if interaction.user == 상대:
        return await interaction.response.send_message("❌ 자기 자신과는 싸울 수 없습니다!", ephemeral=True)
    if 상대.bot:
        return await interaction.response.send_message("❌ 봇과는 싸울 수 없습니다!", ephemeral=True)

    await get_user_data(interaction.user.id)
    await get_user_data(상대.id)

    # 1. 내 통에 물고기가 있는지 확인
    async with db.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items1 = await cursor.fetchall()
    if not items1:
        return await interaction.response.send_message("❌ 내 통(배틀용)이 비어있습니다! `/낚시` 후 통에 보관하세요.", ephemeral=True)

    # 2. 상대방 통에 물고기가 있는지 확인
    async with db.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (상대.id,)) as cursor:
        items2 = await cursor.fetchall()
    if not items2:
        return await interaction.response.send_message(f"❌ 상대방({상대.name})의 통이 비어있어 약탈할 수 없습니다!", ephemeral=True)

    # 통에서 가장 전투력이 높은 물고기를 대표로 선출
    def get_best_fish(items):
        best = None
        max_p = -1
        for (name,) in items:
            p = FISH_DATA[name]["power"]
            if p > max_p:
                max_p = p
                best = name
        return best

    p1_fish = get_best_fish(items1)
    p2_fish = get_best_fish(items2)

    view = PvPBattleView(interaction.user, 상대, p1_fish, p2_fish)
    
    # 상대를 멘션하며 전투 시작!
    await interaction.response.send_message(
        f"⚔️ {상대.mention}! **{interaction.user.name}**님이 수산대전을 걸어왔습니다!\n(방어하지 못하면 코인과 RP를 약탈당합니다!)", 
        embed=view.generate_embed(), 
        view=view
    )

# ==========================================
# 🌟 [신규] 보물 감정 시스템 (초대박 가챠)
# ==========================================
@bot.tree.command(name="감정", description="코인을 지불하고 '가라앉은 보물상자 🧰'를 열어 대박을 노립니다!")
async def 감정(interaction: discord.Interaction):
    fee = 2000 # 감정 비용
    coins, _, _ = await get_user_data(interaction.user.id)

    # 1. 가방에 보물상자가 있는지 확인
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='가라앉은 보물상자 🧰'", (interaction.user.id,)) as cursor:
        res = await cursor.fetchone()
    
    if not res or res[0] <= 0:
        return await interaction.response.send_message("❌ 가방에 '가라앉은 보물상자 🧰'가 없습니다. (상점에서 자석 미끼를 사서 낚아보세요!)", ephemeral=True)
        
    if coins < fee:
        return await interaction.response.send_message(f"❌ 감정 비용이 부족합니다. 열쇠공을 부르려면 `{fee} C`가 필요합니다.", ephemeral=True)

    # 2. 재화 및 상자 차감
    await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='가라앉은 보물상자 🧰'", (interaction.user.id,))
    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id=?", (fee, interaction.user.id))
    
    # 3. 보상 풀 (하이 리스크 하이 리턴으로 대폭 상향!)
    rand = random.random()
    if rand < 0.4: # 40% 확률: 꽝 (상자를 팔았을 때의 기회비용을 날림)
        reward_msg = "아뿔싸... 텅 빈 상자였습니다. 바닥에 굴러다니는 **낡은 고철 ⚙️** (5개)만 주웠습니다."
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 5) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 5", (interaction.user.id, "낡은 고철 ⚙️"))
        
    elif rand < 0.75: # 35% 확률: 상자 시세(1만~2만) 이상의 코인 환수
        reward_coin = random.randint(20000, 40000) 
        reward_msg = f"✨ 번쩍이는 금은보화가 가득합니다! 귀금속을 팔아 **`{reward_coin:,} C`**를 얻었습니다."
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (reward_coin, interaction.user.id))
        
    elif rand < 0.98: # 23% 확률: 대박 (금화 무더기)
        reward_item = "해적의 금화 🪙"
        reward_amt = random.randint(15, 30) # 금화 15~30개 획득 (약 1.5만 ~ 3만 코인 이상의 가치)
        reward_msg = f"🎉 잭팟!! 고대 해적의 유물인 **{reward_item}** {reward_amt}개를 무더기로 발견했습니다!"
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, reward_item, reward_amt, reward_amt))
        
    else: # 2% 확률: 초극악 히든 아이템 + 10만 코인
        reward_item = "💎 GSM 황금 키보드"
        reward_coin = 100000
        reward_msg = f"🚨 **[기적]** 상자 밑바닥에서 엄청난 빛이 뿜어져 나옵니다!!!\n**`{reward_coin:,} C`**와 함께 전설의 **{reward_item}**를 얻었습니다!"
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (reward_coin, interaction.user.id))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, reward_item))
        
    await db.commit()
    await interaction.response.send_message(f"🧰 덜컹... 자물쇠를 부수고 상자를 열었습니다.\n\n{reward_msg}")

# ==========================================
# 🌟 [신규] 용왕 기도 시스템 (가챠)
# ==========================================
@bot.tree.command(name="기도", description="심해의 지배자, 용왕님께 기도를 올립니다. (0.05% 확률로 강림!)")
@app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id) # 도배 방지: 1분마다 1번만 가능
async def 기도(interaction: discord.Interaction):
    # 0.05% 확률 계산
    success_chance = 0.00005
    is_success = random.random() < success_chance

    if is_success:
        # --- [성공 : 해신 강림 연출] ---
        await interaction.response.send_message("🌊 심해에서 알 수 없는 거대한 진동이 시작됩니다...", ephemeral=True)
        await asyncio.sleep(3) 

        # 전 서버 알림 임베드
        alert_embed = discord.Embed(
            title="👑 [海神降臨 : 해신 강림] 찬란한 수궁의 문이 열렸습니다!",
            description=f"{interaction.user.mention}님의 지극한 정성에 수궁의 주인이 응답하셨습니다.\n\n바다의 절대자, **용왕 👑🐉**께서 스스로 강림하여 당신을 선택하셨으니...\n\n**모두 고개를 조아리십시오... 위대한 용왕을 맞이할 시간입니다.**",
            color=0xffd700
        )
        alert_embed.set_footer(text="바다의 모든 피조물들이 일제히 숨을 죽이고 고개를 조아립니다...")

        # 현재 낚시가 진행되는 채널 전체에 알림 및 축복 뷰 전송
        await interaction.channel.send(content="@here", embed=alert_embed, view=DragonKingBlessingView())

        # 기도 성공한 유저에게 확정으로 용왕 물고기 지급 (도감 및 인벤토리)
        await db.execute("INSERT OR IGNORE INTO fish_dex (user_id, item_name) VALUES (?, ?)", (interaction.user.id, "용왕 👑"))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, "용왕 👑"))
        await db.commit()

    else:
        # --- [실패 : 고요한 바다] ---
        fail_messages = [
            "수면 위로 잔잔한 파도만이 일렁입니다.",
            "바다는 대답이 없습니다. 기도가 부족한 듯합니다.",
            "먼바다에서 전어 한 마리가 튀어 오르는 소리만 들려옵니다.",
            "아직은 때가 아닌 듯합니다. 용왕님은 침묵을 지키고 계십니다."
        ]
        await interaction.response.send_message(f"✨ {random.choice(fail_messages)}")

# 기도 명령어 쿨타임 에러 처리 (기존 on_app_command_error 에러 핸들러가 있다면 거기에 합쳐주세요)
@기도.error
async def 기도_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"🙏 기도는 정성이 중요합니다. `{error.retry_after:.0f}초` 후에 다시 기도를 올려주세요.", ephemeral=True)

# ==========================================
# 🌟 [신규] 보물지도 조각 모음 & 망자의 해역 시스템
# ==========================================
@bot.tree.command(name="지도합성", description="가방에 있는 찢어진 지도 조각(A, B, C, D)을 모아 '고대 해적의 보물지도'를 완성합니다.")
async def 지도합성(interaction: discord.Interaction):
    pieces = ["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]
    
    # 유저가 4부위를 모두 1개 이상 가졌는지 확인
    async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        inv_items = {row[0]: row[1] for row in await cursor.fetchall()}
        
    for p in pieces:
        if inv_items.get(p, 0) < 1:
            return await interaction.response.send_message(f"❌ 조각이 부족합니다!\n(부족한 부위: **{p}**)\n낚시를 통해 4부위를 모두 모아보세요.", ephemeral=True)

    # 조각 4개 차감
    for p in pieces:
        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (interaction.user.id, p))
    
    # 보물지도 지급
    await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, "고대 해적의 보물지도 🗺️"))
    await db.commit()
    
    embed = discord.Embed(title="🗺️ 보물지도 합성 성공!", description="4개의 조각을 이어 붙여 **고대 해적의 보물지도 🗺️**를 완성했습니다!\n`/지도사용` 명령어를 통해 망자의 해역으로 떠나보세요.", color=0xf1c40f)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="지도사용", description="'고대 해적의 보물지도'를 사용하여 1시간 동안 금화만 낚이는 [망자의 해역]을 개방합니다.")
async def 지도사용(interaction: discord.Interaction):
    # 지도 보유 확인
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='고대 해적의 보물지도 🗺️'", (interaction.user.id,)) as cursor:
        res = await cursor.fetchone()
        
    if not res or res[0] < 1:
        return await interaction.response.send_message("❌ 가방에 **고대 해적의 보물지도 🗺️**가 없습니다!", ephemeral=True)

    # 지도 차감
    await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='고대 해적의 보물지도 🗺️'", (interaction.user.id,))
    
    # 1시간 동안 망자의 해역 버프 부여
    end_time = datetime.datetime.now(kst) + datetime.timedelta(hours=1)
    end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
    
    await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)", (interaction.user.id, "ghost_sea_open", end_time_str))
    await db.commit()
    
    embed = discord.Embed(title="☠️ 망자의 해역 개방...", description="지도의 낡은 좌표를 따라 안개가 자욱한 해역에 도착했습니다.\n\n앞으로 **1시간 동안**, 당신의 낚싯대에는 물고기 대신 **금화와 보물상자**만 걸려 올라올 것입니다!", color=0x2c3e50)
    await interaction.response.send_message(embed=embed)

# ==========================================
# 6. 관리자 전용 직권 명령어 (어뷰징 관리, 이벤트용)
# ==========================================
@bot.tree.command(name="코인지급", description="[관리자 전용] 특정 유저에게 코인을 강제로 지급합니다.")
@is_developer()
async def 코인지급(interaction: discord.Interaction, target: discord.Member, amount: int):
    await get_user_data(target.id)
    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (amount, target.id))
    await db.commit()
    await interaction.response.send_message(f"💰 관리자 권한으로 **{target.name}**님에게 `{amount:,} C`를 지급했습니다!")

# ==========================================
# 🌟 [수정됨] 관리자 전용: 데이터 실시간 새로고침 (Git Pull 포함)
# ==========================================
@bot.tree.command(name="데이터새로고침", description="[관리자 전용] GitHub에서 최신 데이터를 가져온 후 봇 재시작 없이 반영합니다.")
@is_developer()
async def 데이터새로고침(interaction: discord.Interaction):
    global FISH_DATA, MARKET_PRICES, RECIPES
    
    # 깃허브에서 다운받는 시간이 걸릴 수 있으니 디스코드에 '생각 중...'을 먼저 띄웁니다.
    await interaction.response.defer(ephemeral=True) 
    
    try:
        # 1. 봇이 직접 서버 터미널에서 'git pull'을 실행하여 최신 파일을 다운로드합니다.
        process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        
        # 2. 다운로드된 최신 JSON 데이터를 봇의 뇌(메모리)에 다시 집어넣습니다.
        FISH_DATA = load_fish_data()
        MARKET_PRICES = {fish: data["price"] for fish, data in FISH_DATA.items()}
        RECIPES = load_recipes()
        
        # 3. 성공 메시지와 깃허브 다운로드 로그를 함께 보여줍니다.
        msg = f"✅ 최신 데이터를 깃허브에서 가져와 성공적으로 반영했습니다!\n```bash\n{stdout}```"
        await interaction.followup.send(msg)
        
    except Exception as e:
        await interaction.followup.send(f"❌ 데이터 업데이트 중 오류가 발생했습니다.\n(JSON 파일에 오타나 문법 오류가 없는지 확인하세요!)\n**상세 오류:** `{e}`")

# ==========================================
# 7. 봇 이벤트 
# ==========================================
@bot.event
async def setup_hook():
    await init_db() # 🌟 봇 켜질 때 DB 초기화 먼저 실행!
    await bot.tree.sync()

@bot.event
async def on_ready():
    print(f'🎣 수산시장 낚시 RPG 봇 로딩 완료: {bot.user.name}')
    await bot.change_presence(activity=discord.Game("/낚시 | /시세 | /배틀 | /바다")) # 상태메시지 업데이트
    
    if not market_update_loop.is_running():
        market_update_loop.start()
        
    # 👇 봇이 켜질 때 날씨 루프도 함께 시작되도록 추가! 👇
    if not weather_update_loop.is_running():
        weather_update_loop.start()

    if not daily_midnight_task.is_running():
        daily_midnight_task.start()

if __name__ == "__main__":
    load_dotenv() 
    TOKEN = os.getenv('DISCORD_TOKEN') 
    bot.run(TOKEN)
