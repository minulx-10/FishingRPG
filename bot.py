import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import datetime
import holidays 
import aiohttp
from discord.ui import View
from aiohttp import web
import asyncio
import json

# --- 봇 기본 설정 ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

kst = datetime.timezone(datetime.timedelta(hours=9))

def record_log(interaction: discord.Interaction, command_name, details=""):
    now = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    guild_name = interaction.guild.name if interaction.guild else "DM(개인메시지)"
    user_name = interaction.user.name
    log_msg = f"[{now}] [서버: {guild_name}] 👤{user_name} 님이 [/{command_name}] 사용" + (f" ➡️ 세부내용: {details}\n" if details else "\n")
    with open("/home/ubuntu/cmd_log.txt", "a", encoding="utf-8") as f:
        f.write(log_msg)
    print(log_msg.strip())

SUPER_ADMINS = ['min_ulx.10'] 

def is_manager_or_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.name in SUPER_ADMINS:
            return True
        if interaction.user.guild_permissions.manage_messages:
            return True
        return False
    return app_commands.check(predicate)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("🚫 권한이 없습니다! 반장/부반장 또는 봇 관리자만 사용 가능합니다.", ephemeral=True)

# --- 데이터베이스 설정 ---
conn = sqlite3.connect('school_tasks.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        task_type TEXT, deadline TEXT, content TEXT, channel_id INTEGER
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS config (
        guild_id INTEGER, key TEXT, value TEXT,
        PRIMARY KEY (guild_id, key)
    )
''')
conn.commit()

# --- 타임머신 버그 방지 ---
def parse_deadline(deadline_str: str, now: datetime.datetime) -> datetime.datetime:
    m, d = map(int, deadline_str.split('/'))
    target_year = now.year
    if now.month >= 11 and m <= 2:
        target_year += 1
    return datetime.datetime(target_year, m, d, tzinfo=kst)

def parse_exam_dates(date_range_str: str, now: datetime.datetime):
    if '~' in date_range_str:
        start_str, end_str = date_range_str.split('~')
    else:
        start_str = end_str = date_range_str
        
    start_dt = parse_deadline(start_str.strip(), now)
    end_dt = parse_deadline(end_str.strip(), now)
    return start_dt, end_dt

# --- 나이스(NEIS) API 연동 함수 ---
async def fetch_neis_timetable(date_str: str, grade: str, class_nm: str) -> list:
    url = "https://open.neis.go.kr/hub/hisTimetable"
    params = {
        "KEY": "04bef629b45c47bcb7e5dfadb82fbfb0", 
        "Type": "json", "pIndex": 1, "pSize": 50,
        "ATPT_OFCDC_SC_CODE": "F10", "SD_SCHUL_CODE": "7380292",  
        "ALL_TI_YMD": date_str, "GRADE": str(grade), "CLASS_NM": str(class_nm)
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "hisTimetable" in data:
                        rows = data["hisTimetable"][1]["row"]
                        timetable_dict = {}
                        for r in rows:
                            perio = int(r["PERIO"])
                            if perio not in timetable_dict:
                                timetable_dict[perio] = r["ITRT_CNTNT"]
                        return sorted(timetable_dict.items())
    except Exception as e:
        print(f"NEIS API 에러: {e}")
    return []

async def get_schedule_message(target_date: datetime.datetime, guild_id: int) -> str:
    weekday_num = target_date.weekday()
    target_kr_str = f"<{target_date.month}/{target_date.day}일 {['월', '화', '수', '목', '금', '토', '일'][weekday_num]}요일>"
    msg = f"# {target_kr_str}\n\n"
    
    now = datetime.datetime.now(kst)
    # 💡 수정된 부분: target_date가 아닌 now를 기준으로 '오늘' 날짜를 설정합니다.
    today_date = now.replace(hour=0, minute=0, second=0, microsecond=0) 
    
    for e_key, e_name in [("midterm_date", "중간고사"), ("final_date", "기말고사")]:
        cursor.execute("SELECT value FROM config WHERE key=? AND guild_id=?", (e_key, guild_id))
        row = cursor.fetchone()
        if row:
            try:
                start_dt, end_dt = parse_exam_dates(row[0], now)
                days_to_start = (start_dt.replace(hour=0, minute=0, second=0, microsecond=0) - today_date).days
                days_to_end = (end_dt.replace(hour=0, minute=0, second=0, microsecond=0) - today_date).days
                
                if days_to_start > 0:
                    msg += f"🚨 **[{e_name}]까지 D-{days_to_start}** (기간: {row[0]})\n"
                elif days_to_end >= 0:
                    day_num = abs(days_to_start) + 1
                    msg += f"🔥 **[{e_name}] 진행 중! ({day_num}일차)** (기간: {row[0]})\n"
            except Exception: pass
    
    if "🚨" in msg or "🔥" in msg: msg += "\n"
        
    msg += "**[시간표]**\n"
    cursor.execute("SELECT value FROM config WHERE key='grade' AND guild_id=?", (guild_id,))
    g_row = cursor.fetchone()
    cursor.execute("SELECT value FROM config WHERE key='class_nm' AND guild_id=?", (guild_id,))
    c_row = cursor.fetchone()

    if weekday_num >= 5: msg += "• 수업 일정이 없는 휴일입니다!\n"
    elif g_row and c_row:
        date_str = target_date.strftime("%Y%m%d")
        timetable = await fetch_neis_timetable(date_str, g_row[0], c_row[0])
        if timetable:
            for perio, subject in timetable: msg += f"• {perio}교시: {subject}\n"
        else: msg += "• 해당 날짜의 나이스(NEIS) 시간표 데이터가 없습니다.\n"
    else: msg += "• ⚠️ `/학급설정` 명령어로 먼저 학년과 반을 설정해주세요!\n"
        
    msg += "\n**[학급 일정 (숙제/수행 등)]**\n"
    cursor.execute('SELECT task_type, content FROM tasks WHERE deadline = ? AND guild_id = ?', (target_date.strftime("%m/%d"), guild_id))
    target_tasks = cursor.fetchall()
    
    if not target_tasks: msg += "• 해당일에 마감인 일정이 없습니다. 푹 쉬세요!\n"
    else:
        tasks_dict = {}
        for t_type, content in target_tasks: tasks_dict.setdefault(t_type, []).append(content)
        for t_type, contents in tasks_dict.items():
            msg += f"**[{t_type}]**\n" + "".join([f"• {c}\n" for c in contents])
            
    return msg.strip()

class DashboardView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="새로고침", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="refresh_dashboard")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        record_log(interaction, "대시보드_새로고침")
        await interaction.response.defer(ephemeral=True)
        await update_dashboard(interaction.guild_id)
        await interaction.followup.send("🔄 대시보드 상태가 최신화되었습니다!", ephemeral=True)

async def update_dashboard(target_guild_id=None):
    now = datetime.datetime.now(kst)
    today_date = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if target_guild_id: guilds = [(target_guild_id,)]
    else:
        cursor.execute("SELECT DISTINCT guild_id FROM config WHERE key='dashboard_channel'")
        guilds = cursor.fetchall()

    for (g_id,) in guilds:
        cursor.execute('SELECT id, task_type, deadline, content FROM tasks WHERE guild_id = ? AND task_type != "시험범위"', (g_id,))
        tasks_list = cursor.fetchall()
        dated_tasks, tbd_tasks, embed_desc = [], [], ""
        
        for row in tasks_list:
            if row[2] == "미정": tbd_tasks.append(row)
            else:
                try:
                    target_date = parse_deadline(row[2], now)
                    days_left = (target_date - today_date).days
                    if days_left >= 0: dated_tasks.append((days_left, row))
                except ValueError: pass
                
        dated_tasks.sort(key=lambda x: x[0])
        
        for days, (t_id, t_type, d_str, content) in dated_tasks:
            d_txt = "당일!" if days == 0 else f"D-{days}"
            embed_desc += f"`ID:{t_id}` [{t_type}] {content} (마감: {d_str} / **{d_txt}**)\n"
        for t_id, t_type, d_str, content in tbd_tasks:
            embed_desc += f"`ID:{t_id}` [{t_type}] {content} (**마감 미정**)\n"
            
        if not embed_desc: embed_desc = "현재 등록된 일정이 없습니다. 푹 쉬세요!"

        cursor.execute("SELECT value FROM config WHERE key='dashboard_channel' AND guild_id=?", (g_id,))
        ch_row = cursor.fetchone()
        cursor.execute("SELECT value FROM config WHERE key='dashboard_message' AND guild_id=?", (g_id,))
        msg_row = cursor.fetchone()

        if ch_row and msg_row:
            channel = bot.get_channel(int(ch_row[0]))
            if channel:
                try:
                    msg = await channel.fetch_message(int(msg_row[0]))
                    embed = discord.Embed(title="📊 실시간 학급 일정 대시보드", description=embed_desc, color=0xf5a442)
                    embed.set_footer(text=f"마지막 새로고침: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    await msg.edit(embed=embed, view=DashboardView())
                except discord.NotFound: pass

    await bot.change_presence(activity=discord.Game("학급 일정 관리 중!"))

@bot.event
async def setup_hook():
    bot.add_view(DashboardView())
    await bot.tree.sync()

@bot.event
async def on_ready():
    print(f'SyncTask 봇 로그인 완료: {bot.user.name}')
    await update_dashboard() 
    if not send_reminder.is_running(): send_reminder.start()
    if not auto_update_loop.is_running(): auto_update_loop.start()

# --- 슬래시 명령어들 ---

@bot.tree.command(name="학급설정", description="시간표 조회를 위해 우리 반의 학년과 반을 설정합니다.")
@is_manager_or_admin() 
async def 학급설정(interaction: discord.Interaction, grade: int, class_nm: int):
    record_log(interaction, "학급설정", f"{grade}학년 {class_nm}반")
    cursor.execute("REPLACE INTO config (guild_id, key, value) VALUES (?, 'grade', ?)", (interaction.guild_id, str(grade)))
    cursor.execute("REPLACE INTO config (guild_id, key, value) VALUES (?, 'class_nm', ?)", (interaction.guild_id, str(class_nm)))
    conn.commit()
    await interaction.response.send_message(f"🏫 이 서버의 시간표가 **{grade}학년 {class_nm}반**으로 설정되었습니다!", ephemeral=True)

@bot.tree.command(name="공지설정", description="이 채널에 실시간 대시보드를 생성합니다.")
@is_manager_or_admin() 
async def 공지설정(interaction: discord.Interaction):
    record_log(interaction, "공지설정")
    await interaction.response.send_message("📊 대시보드 설치 완료!", ephemeral=True)
    msg = await interaction.channel.send(embed=discord.Embed(title="대시보드 로딩 중..."), view=DashboardView())
    cursor.execute("REPLACE INTO config (guild_id, key, value) VALUES (?, 'dashboard_channel', ?)", (interaction.guild_id, str(msg.channel.id)))
    cursor.execute("REPLACE INTO config (guild_id, key, value) VALUES (?, 'dashboard_message', ?)", (interaction.guild_id, str(msg.id)))
    conn.commit()
    await update_dashboard(interaction.guild_id)

@bot.tree.command(name="추가", description="새로운 숙제나 일정을 추가합니다.")
@is_manager_or_admin() 
@app_commands.choices(task_type=[
    app_commands.Choice(name="숙제", value="숙제"),
    app_commands.Choice(name="수행평가", value="수행평가"),
    app_commands.Choice(name="기타일정", value="기타일정")
])
async def 추가(interaction: discord.Interaction, task_type: app_commands.Choice[str], deadline: str, content: str):
    record_log(interaction, "추가", f"종류:[{task_type.value}], 마감:[{deadline}], 내용:[{content}]")
    if deadline != "미정":
        try:
            m, d = map(int, deadline.split('/'))
            deadline = f"{m:02d}/{d:02d}"
        except ValueError:
            return await interaction.response.send_message("⚠️ 마감일은 `MM/DD` 형식이나 `미정`으로 입력!", ephemeral=True)
    
    cursor.execute('INSERT INTO tasks (guild_id, task_type, deadline, content, channel_id) VALUES (?, ?, ?, ?, ?)', 
                   (interaction.guild_id, task_type.value, deadline, content, interaction.channel_id))
    conn.commit()
    await interaction.response.send_message(f'✅ 등록 완료! (`{content}`)', ephemeral=True)
    await update_dashboard(interaction.guild_id)

@bot.tree.command(name="삭제", description="등록된 일정을 삭제합니다.")
@is_manager_or_admin()
async def 삭제(interaction: discord.Interaction, ids_str: str):
    record_log(interaction, "삭제", f"대상 ID:[{ids_str}]")
    id_list = [int(i.strip()) for i in ids_str.split(',') if i.strip().isdigit()]
    if not id_list: return await interaction.response.send_message("⚠️ 삭제할 ID를 숫자로 입력해주세요!", ephemeral=True)
    
    placeholders = ', '.join('?' for _ in id_list)
    cursor.execute(f'DELETE FROM tasks WHERE id IN ({placeholders}) AND guild_id = ?', id_list + [interaction.guild_id])
    conn.commit()
    await interaction.response.send_message(f'🗑️ 삭제 완료! (ID: {", ".join(map(str, id_list))})', ephemeral=True)
    await update_dashboard(interaction.guild_id)

@bot.tree.command(name="전체일정", description="모든 일정을 한 번에 보여줍니다.")
async def 전체일정(interaction: discord.Interaction):
    record_log(interaction, "전체일정")
    cursor.execute('SELECT id, task_type, deadline, content FROM tasks WHERE guild_id = ? AND task_type != "시험범위"', (interaction.guild_id,))
    tasks_list = cursor.fetchall()
    if not tasks_list: return await interaction.response.send_message("✅ 현재 등록된 일정이 없습니다!")
    msg = "📋 **[전체 일정 목록]**\n"
    for r in tasks_list: msg += f"`ID:{r[0]}` [{r[1]}] {r[3]} (마감: {r[2]})\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="오늘", description="오늘의 시간표와 마감 일정을 보여줍니다.")
async def 오늘(interaction: discord.Interaction):
    record_log(interaction, "오늘")
    msg = await get_schedule_message(datetime.datetime.now(kst), interaction.guild_id)
    await interaction.response.send_message(msg)

@bot.tree.command(name="내일", description="내일(다음 등교일)의 시간표와 일정을 보여줍니다.")
async def 내일(interaction: discord.Interaction):
    record_log(interaction, "내일")
    now = datetime.datetime.now(kst)
    target_date = now + datetime.timedelta(days=1)
    kr_holidays = holidays.KR(years=now.year)
    while target_date.weekday() >= 5 or target_date.date() in kr_holidays: target_date += datetime.timedelta(days=1)
    
    msg = await get_schedule_message(target_date, interaction.guild_id)
    await interaction.response.send_message(msg)

@bot.tree.command(name="시간표", description="선택한 날짜의 시간표를 보여줍니다.")
@app_commands.choices(target=[app_commands.Choice(name="오늘", value="오늘"), app_commands.Choice(name="내일", value="내일")])
async def 시간표(interaction: discord.Interaction, target: app_commands.Choice[str] = None):
    val = target.value if target else "오늘"
    record_log(interaction, "시간표", f"대상:[{val}]")
    now = datetime.datetime.now(kst)
    target_date = now if val == "오늘" else now + datetime.timedelta(days=1)
    if val == "내일":
        kr_holidays = holidays.KR(years=now.year)
        while target_date.weekday() >= 5 or target_date.date() in kr_holidays: target_date += datetime.timedelta(days=1)
        
    msg = await get_schedule_message(target_date, interaction.guild_id)
    await interaction.response.send_message(msg)

@bot.tree.command(name="숙제", description="앞으로 남은 숙제 목록을 D-Day 순으로 보여줍니다.")
async def 숙제(interaction: discord.Interaction):
    record_log(interaction, "숙제")
    await send_task_list(interaction, "숙제")

@bot.tree.command(name="수행평가", description="앞으로 남은 수행평가 목록을 D-Day 순으로 보여줍니다.")
async def 수행평가(interaction: discord.Interaction):
    record_log(interaction, "수행평가")
    await send_task_list(interaction, "수행평가")

@bot.tree.command(name="시험일정설정", description="중간/기말고사의 시작일과 종료일을 설정합니다.")
@is_manager_or_admin()
@app_commands.choices(exam_type=[
    app_commands.Choice(name="중간고사", value="midterm_date"),
    app_commands.Choice(name="기말고사", value="final_date")
])
async def 시험일정설정(interaction: discord.Interaction, exam_type: app_commands.Choice[str], start_date: str, end_date: str):
    record_log(interaction, "시험일정설정", f"{exam_type.name} 기간: {start_date}~{end_date}")
    try:
        sm, sd = map(int, start_date.split('/'))
        em, ed = map(int, end_date.split('/'))
        formatted_date = f"{sm:02d}/{sd:02d}~{em:02d}/{ed:02d}"
    except ValueError:
        return await interaction.response.send_message("⚠️ 날짜는 `MM/DD` 형식으로 입력해주세요!", ephemeral=True)
    
    cursor.execute("REPLACE INTO config (guild_id, key, value) VALUES (?, ?, ?)", (interaction.guild_id, exam_type.value, formatted_date))
    conn.commit()
    await interaction.response.send_message(f"🗓️ 이 서버의 **{exam_type.name}** 기간이 **{formatted_date}**로 설정되었습니다!", ephemeral=True)

@bot.tree.command(name="시험범위추가", description="과목별 시험 범위를 등록합니다.")
@is_manager_or_admin()
@app_commands.choices(exam_type=[
    app_commands.Choice(name="중간고사", value="중간고사"),
    app_commands.Choice(name="기말고사", value="기말고사")
])
async def 시험범위추가(interaction: discord.Interaction, exam_type: app_commands.Choice[str], subject: str, scope: str):
    record_log(interaction, "시험범위추가", f"{exam_type.name} [{subject}] {scope}")
    content = f"[{subject}] {scope}"
    cursor.execute('INSERT INTO tasks (guild_id, task_type, deadline, content, channel_id) VALUES (?, ?, ?, ?, ?)', 
                   (interaction.guild_id, "시험범위", exam_type.value, content, interaction.channel_id))
    conn.commit()
    await interaction.response.send_message(f"✅ **{exam_type.name}** `{subject}` 과목 시험 범위 등록 완료!", ephemeral=True)

@bot.tree.command(name="시험범위", description="등록된 시험 범위와 디데이(D-Day)를 확인합니다.")
async def 시험범위(interaction: discord.Interaction):
    record_log(interaction, "시험범위_조회")
    now = datetime.datetime.now(kst)
    today_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    msg = "📚 **[시험 범위 및 D-Day]**\n\n"
    for e_key, e_name in [("midterm_date", "중간고사"), ("final_date", "기말고사")]:
        cursor.execute("SELECT value FROM config WHERE key=? AND guild_id=?", (e_key, interaction.guild_id))
        row = cursor.fetchone()
        if row:
            try:
                start_dt, end_dt = parse_exam_dates(row[0], now)
                days_to_start = (start_dt.replace(hour=0, minute=0, second=0, microsecond=0) - today_date).days
                days_to_end = (end_dt.replace(hour=0, minute=0, second=0, microsecond=0) - today_date).days
                
                if days_to_start > 0: msg += f"🚨 **{e_name} (기간: {row[0]} / D-{days_to_start})**\n"
                elif days_to_end >= 0: msg += f"🔥 **{e_name} 진행 중! (기간: {row[0]} / {abs(days_to_start) + 1}일차)**\n"
                else: msg += f"✅ **{e_name} (기간: {row[0]} / 종료)**\n"
            except Exception: msg += f"🚨 **{e_name} (기간: {row[0]})**\n"
        else: msg += f"🚨 **{e_name} (일정 미등록)**\n"
        
        cursor.execute("SELECT id, content FROM tasks WHERE task_type='시험범위' AND deadline=? AND guild_id=?", (e_name, interaction.guild_id))
        tasks = cursor.fetchall()
        if tasks:
            for t_id, content in tasks: msg += f"  • `ID:{t_id}` {content}\n"
        else: msg += "  • 아직 등록된 시험 범위가 없습니다.\n"
        msg += "\n"
        
    await interaction.response.send_message(msg.strip())

async def send_task_list(interaction: discord.Interaction, task_type_name: str):
    now = datetime.datetime.now(kst)
    today_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cursor.execute('SELECT id, deadline, content FROM tasks WHERE task_type = ? AND guild_id = ?', (task_type_name, interaction.guild_id))
    tasks_list = cursor.fetchall()
    
    if not tasks_list: return await interaction.response.send_message(f"✅ 현재 등록된 **{task_type_name}** 일정이 없습니다!")
    dated_tasks, tbd_tasks, msg = [], [], f"📌 **[남은 {task_type_name} 목록]**\n\n"
    
    for r in tasks_list:
        if r[1] == "미정": tbd_tasks.append(r)
        else:
            try:
                target = parse_deadline(r[1], now)
                dated_tasks.append(((target - today_date).days, r))
            except ValueError: pass
            
    dated_tasks.sort(key=lambda x: x[0])
    for days, r in dated_tasks:
        d_txt = "당일!" if days == 0 else (f"D+{-days} (종료)" if days < 0 else f"D-{days}")
        msg += f"`ID:{r[0]}` {r[2]} (마감: {r[1]} / **{d_txt}**)\n"
    for r in tbd_tasks: msg += f"`ID:{r[0]}` {r[2]} (**마감 미정**)\n"
    await interaction.response.send_message(msg)

# --- 백그라운드 루프 ---
@tasks.loop(minutes=5)
async def auto_update_loop():
    now = datetime.datetime.now(kst)
    today_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cursor.execute('SELECT id, deadline FROM tasks WHERE deadline != "미정" AND task_type != "시험범위"')
    ids_to_delete = []
    for t_id, d_str in cursor.fetchall():
        try:
            target_date = parse_deadline(d_str, now)
            if (target_date - today_date).days <= -2: 
                ids_to_delete.append(t_id)
        except ValueError: pass
        
    if ids_to_delete:
        placeholders = ', '.join('?' for _ in ids_to_delete)
        cursor.execute(f'DELETE FROM tasks WHERE id IN ({placeholders})', ids_to_delete) 
        conn.commit()
    await update_dashboard()

@tasks.loop(time=[datetime.time(hour=6, minute=30, tzinfo=kst), datetime.time(hour=19, minute=30, tzinfo=kst)])
async def send_reminder():
    now = datetime.datetime.now(kst)
    is_evening = now.hour >= 18
    
    # 💡 추가된 로직 1: 금요일(4) 또는 토요일(5) 저녁에는 '내일 일정 미리보기' 생략
    if is_evening and now.weekday() in [4, 5]:
        return
        
    # 💡 추가된 로직 2: 토요일(5) 또는 일요일(6) 아침에는 '오늘 일정 알림' 생략
    if not is_evening and now.weekday() in [5, 6]:
        return
    
    target_date = now + datetime.timedelta(days=1) if is_evening else now
    
    if is_evening:
        kr_holidays = holidays.KR(years=now.year)
        while target_date.weekday() >= 5 or target_date.date() in kr_holidays: target_date += datetime.timedelta(days=1)
        prefix = "🌙 **[내일 일정 미리보기]**\n"
    else: 
        prefix = "☀️ **[오늘 일정 알림]**\n"

    cursor.execute("SELECT guild_id, value FROM config WHERE key='dashboard_channel'")
    for g_id, ch_id in cursor.fetchall():
        channel = bot.get_channel(int(ch_id))
        if channel: 
            msg = await get_schedule_message(target_date, g_id)
            await channel.send(f"{prefix}\n{msg}")

# --- 관리자 전용 서버 CCTV 웹사이트 ---
async def admin_log_dashboard(request):
    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GSM 알리미 관리자 CCTV</title>
        <style>
            body { font-family: 'Consolas', 'Malgun Gothic', monospace; background-color: #1e1e1e; color: #d4d4d4; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; background: #252526; padding: 30px; border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid #333; }
            h1 { color: #569cd6; text-align: center; border-bottom: 2px solid #333; padding-bottom: 15px; letter-spacing: 2px; }
            ul { list-style: none; padding: 0; margin-top: 20px; }
            li { background: #1e1e1e; margin: 8px 0; padding: 12px 15px; border-radius: 5px; border-left: 4px solid #c586c0; font-size: 0.95em; word-wrap: break-word; }
            li:hover { background: #2a2d2e; }
            .footer { text-align: center; margin-top: 30px; font-size: 0.85em; color: #4CAF50; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🖥️ 실시간 봇 명령어 감시 (Admin Log)</h1>
            <ul id="log-list">
                <li style='text-align:center;'>위성(서버)과 연결 중... 데이터를 불러옵니다 🔄</li>
            </ul>
            <div class="footer">🟢 실시간 라이브 모니터링 작동 중 (3초 자동 갱신)</div>
        </div>

        <script>
            function fetchLogs() {
                fetch('/api/logs?t=' + new Date().getTime())
                .then(response => response.text())
                .then(html => {
                    document.getElementById('log-list').innerHTML = html;
                });
            }
            fetchLogs();
            setInterval(fetchLogs, 3000);
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def api_get_logs(request):
    try:
        with open("/home/ubuntu/cmd_log.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        lines.reverse()
        recent_logs = lines[:50] 
        log_html = ""
        for line in recent_logs:
            if not line.strip(): continue
            log_html += f"<li>{line.strip()}</li>"
            
        if not log_html: log_html = "<li style='text-align:center;'>아직 기록된 명령어가 없습니다.</li>"
        return web.Response(text=log_html, content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="<li style='text-align:center;'>로그 파일이 아직 없습니다.</li>", content_type='text/html')
    except Exception as e:
        return web.Response(text=f"<li>에러 발생: {e}</li>", content_type='text/html')

async def api_get_tasks(request):
    try:
        grade = request.query.get('grade')
        class_nm = request.query.get('class_nm')
        common_guilds = []
        if grade and class_nm:
            cursor.execute("SELECT guild_id FROM config WHERE key='grade' AND value=?", (str(grade),))
            grade_guilds = set([row[0] for row in cursor.fetchall()])
            cursor.execute("SELECT guild_id FROM config WHERE key='class_nm' AND value=?", (str(class_nm),))
            class_guilds = set([row[0] for row in cursor.fetchall()])
            common_guilds = list(grade_guilds.intersection(class_guilds))
        
        if common_guilds:
            placeholders = ','.join('?' for _ in common_guilds)
            cursor.execute(f'SELECT id, task_type, deadline, content FROM tasks WHERE guild_id IN ({placeholders})', common_guilds)
        else:
            return web.Response(text="[]", content_type='application/json')
            
        rows = cursor.fetchall()
        tasks_list = [{"id": r[0], "task_type": r[1], "deadline": r[2], "content": r[3]} for r in rows]
        return web.Response(text=json.dumps(tasks_list, ensure_ascii=False), content_type='application/json')
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), status=500, content_type='application/json')

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', admin_log_dashboard)          
    app.router.add_get('/api/logs', api_get_logs)         
    app.router.add_get('/api/tasks', api_get_tasks)       
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000) 
    await site.start()
    print("🌍 관리자 CCTV 웹사이트 & API 서버 정상 작동 시작! (포트 10000)")

async def main():
    async with bot:
        bot.loop.create_task(run_web_server())
        await bot.start(os.getenv('DISCORD_TOKEN'))

if __name__ == "__main__":
    asyncio.run(main())
