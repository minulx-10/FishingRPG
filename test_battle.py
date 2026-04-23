import asyncio

from fishing_core.database import db
from fishing_core.shared import FISH_DATA


class DummyUser:
    def __init__(self, uid, name, bot=False):
        self.id = uid
        self.name = name
        self.mention = f"<@{uid}>"
        self.bot = bot

class DummyInteraction:
    def __init__(self, uid, name):
        self.user = DummyUser(uid, name)
        self.response = self

    async def send_message(self, *args, **kwargs):
        print("SEND_MESSAGE:", args, kwargs)

async def test_susan_daejeon():
    await db.init_db()
    interaction = DummyInteraction(123, "TestUser")
    target = DummyUser(456, "TargetUser")

    await db.get_user_data(interaction.user.id)
    await db.get_user_data(target.id)

    # Give them some locked items
    await db.execute("INSERT OR REPLACE INTO inventory (user_id, item_name, amount, is_locked) VALUES (?, ?, 1, 1)", (interaction.user.id, "고등어"))
    await db.execute("INSERT OR REPLACE INTO inventory (user_id, item_name, amount, is_locked) VALUES (?, ?, 1, 1)", (target.id, "참치"))
    await db.commit()

    async with db.conn.execute("SELECT peace_mode FROM user_data WHERE user_id=?", (target.id,)) as cursor:
        res = await cursor.fetchone()
    if res and res[0] == 1:
        return print("PEACE MODE")

    async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
        items1 = await cursor.fetchall()

    async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (target.id,)) as cursor:
        items2 = await cursor.fetchall()

    def get_top3_fish(items):
        fish_list = []
        for (name,) in items:
            p = 99999 if name == "용왕 👑" else FISH_DATA.get(name, {}).get("power", -1)
            if p > 0:
                fish_list.append((name, p))
        fish_list.sort(key=lambda x: x[1], reverse=True)
        return fish_list[:3]

    p1_deck = get_top3_fish(items1)
    p2_deck = get_top3_fish(items2)
    print("p1_deck:", p1_deck)
    print("p2_deck:", p2_deck)

    async with db.conn.execute("SELECT title FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
        res = await cursor.fetchone()
    title1 = res[0] if res else ""
    display_name1 = f"{title1} {interaction.user.name}" if title1 else interaction.user.name

    from fishing_core.views import PvPBattleView
    view = PvPBattleView(interaction.user, target, p1_deck, p2_deck)

    await interaction.response.send_message(
        f"⚔️ {target.mention}! **{display_name1}**님이 3v3 릴레이 수산대전을 걸어왔습니다!",
        embed=view.generate_embed(),
        view=view,
    )
    print("SUCCESS")

asyncio.run(test_susan_daejeon())
