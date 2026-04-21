import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

from fishing_core.database import db
from fishing_core.web_server import start_web_server

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

COGS = [
    "fishing_cogs.fishing_cmds",
    "fishing_cogs.market_cmds",
    "fishing_cogs.ship_cmds",
    "fishing_cogs.battle_cmds",
    "fishing_cogs.quest_cmds",
    "fishing_cogs.admin_cmds",
    "fishing_cogs.events"
]

@bot.event
async def setup_hook():
    await db.init_db() 
    for cog in COGS:
        await bot.load_extension(cog)
    await bot.tree.sync()
    bot.loop.create_task(start_web_server(bot))

@bot.event
async def on_ready():
    print(f'🎣 수산시장 낚시 RPG 봇 로딩 완료: {bot.user.name}')
    await bot.change_presence(activity=discord.Game("/낚시 | /시세 | /배틀 | /바다")) 

if __name__ == "__main__":
    load_dotenv() 
    TOKEN = os.getenv('DISCORD_TOKEN') 
    bot.run(TOKEN)
