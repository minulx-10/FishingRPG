import asyncio
import discord
from unittest.mock import MagicMock
from fishing_core.views_v2 import BattleView
from fishing_core.shared import FISH_DATA

async def test_battle_view():
    user = MagicMock(spec=discord.User)
    user.name = "TestUser"
    
    # 가상의 물고기 데이터 설정 (FISH_DATA가 비어있을 수 있으므로 확인)
    if not FISH_DATA:
        print("Warning: FISH_DATA is empty. Adding mock data.")
        FISH_DATA["붕어"] = {"power": 5, "grade": "일반"}
        FISH_DATA["상어"] = {"power": 50, "grade": "희귀"}
    
    my_fish = "붕어"
    npc_fish = "상어"
    
    try:
        view = BattleView(user, my_fish, npc_fish)
        print("BattleView initialized.")
        
        embed, file = view.generate_embed()
        print("Embed generated successfully.")
        print(f"Embed Title: {embed.title}")
        print(f"File Path: {file.fp.name if hasattr(file.fp, 'name') else file.filename}")
        
    except Exception as e:
        print(f"Error during simulation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_battle_view())
