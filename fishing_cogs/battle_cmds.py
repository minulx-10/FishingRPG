import discord
from discord.ext import commands
from discord import app_commands
import random

from fishing_core.database import db
from fishing_core.shared import FISH_DATA
from fishing_core.utils import check_boat_tier, inv_autocomplete
from fishing_core.views import BattleView, PvPBattleView

class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="배틀", description="나의 가장 강한 물고기로 야생의 NPC 물고기와 턴제 배틀을 진행합니다! (체력 15 소모)")
    @check_boat_tier(3)
    async def 배틀(self, interaction: discord.Interaction):
        # 체력 체크
        async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            st = await cursor.fetchone()
        if st and st[0] < 15:
            return await interaction.response.send_message(f"❌ 행동력(체력)이 부족합니다! (필요: 15⚡ / 현재: {st[0]}⚡)\n💡 `/출석`이나 `/휴식`으로 체력을 회복하세요.", ephemeral=True)
        await db.execute("UPDATE user_data SET stamina = stamina - 15 WHERE user_id=?", (interaction.user.id,))

        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()
        
        if not items:
            return await interaction.response.send_message("❌ 잠금(보호) 처리된 물고기가 없습니다! 인벤토리에서 `/잠금` 명령어로 전사를 보호하세요.", ephemeral=True)
        
        my_best_fish = None
        max_power = -1
        for (name,) in items:
            power = FISH_DATA.get(name, {}).get("power", -1)
            if power > max_power:
                max_power = power
                my_best_fish = name
                
        if max_power == -1 or not my_best_fish:
            return await interaction.response.send_message("❌ 출전할 유효한 물고기가 없습니다! (잠금된 목록에 일반 아이템만 존재합니다)", ephemeral=True)
                
        npc_pool = [name for name, data in FISH_DATA.items() if data.get("grade") != "히든"]
        npc_fish = random.choice(npc_pool)
        
        view = BattleView(interaction.user, my_best_fish, npc_fish)
        await interaction.response.send_message(embed=view.generate_embed(), view=view)

    @app_commands.command(name="잠금목록", description="나 또는 특정 유저의 가방에서 잠금(보호 및 배틀용) 처리된 목록을 확인합니다.")
    async def 잠금목록(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (target.id,)) as cursor:
            items = await cursor.fetchall()
        
        embed = discord.Embed(title=f"🔒 {target.name}의 잠금(보호) 목록", color=0x2ecc71)
        if items:
            item_list = ""
            for name, amt in items:
                power = FISH_DATA.get(name, {}).get("power", 0)
                if power > 0:
                    item_list += f"• {name}: {amt}마리 (전투력: {power}⚡)\n"
                else:
                    item_list += f"• {name}: {amt}개\n"
            embed.add_field(name="보존된 아이템 및 전사", value=item_list, inline=False)
        else:
            embed.add_field(name="텅 비었습니다...", value="`/잠금` 명령어를 통해 중요한 물고기와 아이템을 판매로부터 보호하세요.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="수산대전", description="다른 유저를 지목하여 마라맛 PvP 배틀(약탈)을 겁니다!")
    @check_boat_tier(5)
    async def 수산대전(self, interaction: discord.Interaction, 상대: discord.Member):
        try:
            if interaction.user == 상대:
                return await interaction.response.send_message("❌ 자기 자신과는 싸울 수 없습니다!", ephemeral=True)
            if 상대.bot:
                return await interaction.response.send_message("❌ 봇과는 싸울 수 없습니다!", ephemeral=True)

            await db.get_user_data(interaction.user.id)
            
            # 체력 체크 (PvP는 20 소모)
            async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
                st = await cursor.fetchone()
            if st and st[0] < 20:
                return await interaction.response.send_message(f"❌ 행동력(체력)이 부족합니다! (필요: 20⚡ / 현재: {st[0]}⚡)\n💡 `/출석`이나 `/휴식`으로 체력을 회복하세요.", ephemeral=True)
            await db.execute("UPDATE user_data SET stamina = stamina - 20 WHERE user_id=?", (interaction.user.id,))
            await db.get_user_data(상대.id)
            
            # 평화모드 체크
            async with db.conn.execute("SELECT peace_mode FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                res = await cursor.fetchone()
            if res and res[0] == 1:
                return await interaction.response.send_message(f"❌ '{상대.name}'님은 현재 **평화 모드** 🕊️ 상태입니다. (약탈 불가)", ephemeral=True)

            # === Phase 1: PvP 양학 방지 시스템 ===
            import datetime as dt
            kst_tz = dt.timezone(dt.timedelta(hours=9))
            now = dt.datetime.now(kst_tz)
            today_str = now.strftime('%Y-%m-%d')
            
            # 1) RP 차이 제한 (기본 500 차이, 고랭커는 완화)
            async with db.conn.execute("SELECT rating FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
                my_rp = (await cursor.fetchone())[0]
            async with db.conn.execute("SELECT rating FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                target_rp = (await cursor.fetchone())[0]
            
            rp_gap_limit = 500
            if my_rp > 2000: rp_gap_limit = 1000 # 고랭커 매칭 풀 확보
            
            if my_rp - target_rp > rp_gap_limit:
                return await interaction.response.send_message(
                    f"❌ 상대방과의 RP 격차가 너무 큽니다! (나: {my_rp} / 상대: {target_rp})\n"
                    f"⚖️ 비슷한 실력의 유저에게만 수산대전을 걸 수 있습니다. (현재 내 기준 최대 차이: {rp_gap_limit} RP)",
                    ephemeral=True
                )
            
            # 2) 방어자 보호막 (하루 3회까지만 약탈당함)
            async with db.conn.execute("SELECT pvp_shield_count, pvp_shield_date FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                shield_res = await cursor.fetchone()
            shield_count = shield_res[0] if shield_res else 3
            shield_date = shield_res[1] if shield_res else ""
            
            # 날짜가 바뀌면 보호막 리셋
            if shield_date != today_str:
                shield_count = 3
                await db.execute("UPDATE user_data SET pvp_shield_count=3, pvp_shield_date=? WHERE user_id=?", (today_str, 상대.id))
            
            if shield_count <= 0:
                return await interaction.response.send_message(
                    f"🛡️ '{상대.name}'님은 오늘 이미 3회 약탈당해 **보호막**이 발동 중입니다.\n"
                    f"다른 상대를 찾거나 내일 다시 도전하세요!",
                    ephemeral=True
                )
            
            # 3) 공격자 평화모드 강제 해제 + 1시간 쿨타임 (기존 6시간에서 단축)
            cooldown_until = (now + dt.timedelta(hours=1)).isoformat()
            await db.execute("UPDATE user_data SET peace_mode=0, peace_cooldown=? WHERE user_id=?", (cooldown_until, interaction.user.id))
            
            # 방어자 보호막 1회 차감
            await db.execute("UPDATE user_data SET pvp_shield_count = pvp_shield_count - 1, pvp_shield_date=? WHERE user_id=?", (today_str, 상대.id))
            await db.commit()

            async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
                items1 = await cursor.fetchall()
            if not items1:
                return await interaction.response.send_message("❌ 내 잠금 목록이 비어있습니다! `/잠금`으로 출전할 물고기를 보존하세요.", ephemeral=True)

            async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (상대.id,)) as cursor:
                items2 = await cursor.fetchall()
            if not items2:
                return await interaction.response.send_message(f"❌ 상대방({상대.name})의 잠금 목록이 비어있어 약탈할 수 없습니다!", ephemeral=True)

            def get_top3_fish(items):
                fish_list = []
                for (name,) in items:
                    p = FISH_DATA.get(name, {}).get("power", -1)
                    if p > 0:
                        fish_list.append((name, p))
                fish_list.sort(key=lambda x: x[1], reverse=True)
                return fish_list[:3]

            p1_deck = get_top3_fish(items1)
            p2_deck = get_top3_fish(items2)
            
            if not p1_deck: return await interaction.response.send_message("❌ 내 잠금 목록에 출전 가능한 유효한 물고기가 없습니다!", ephemeral=True)
            if not p2_deck: return await interaction.response.send_message(f"❌ 상대방({상대.name})에게 유효한 배틀 물고기가 없어 약탈할 수 없습니다!", ephemeral=True)

            title_str = await db.get_user_title(interaction.user.id)
            display_name1 = f"{title_str} {interaction.user.name}" if title_str else interaction.user.name

            view = PvPBattleView(interaction.user, 상대, p1_deck, p2_deck)
            
            await interaction.response.send_message(
                f"⚔️ {상대.mention}! **{display_name1}**님이 3v3 릴레이 수산대전을 걸어왔습니다!\n(방어하지 못하면 코인과 RP를 약탈당합니다!)", 
                embed=view.generate_embed(), 
                view=view
            )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            await interaction.response.send_message(f"❌ 수산대전 실행 중 오류 발생:\n```py\n{tb[:1900]}\n```", ephemeral=True)

    @app_commands.command(name="평화모드", description="수산대전(PvP) 약탈을 거부하는 평화 모드를 켜거나 끕니다. (전환 쿨타임: 24시간)")
    async def 평화모드(self, interaction: discord.Interaction):
        await db.get_user_data(interaction.user.id)
        async with db.conn.execute("SELECT peace_mode, peace_cooldown FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        
        current_mode = res[0] if res else 0
        peace_cooldown = res[1] if res and res[1] else ""
        
        # 쿨타임 체크 (24시간)
        import datetime as dt
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
        if peace_cooldown:
            try:
                cooldown_end = dt.datetime.fromisoformat(peace_cooldown)
                if now < cooldown_end:
                    remaining = cooldown_end - now
                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int((remaining.total_seconds() % 3600) // 60)
                    return await interaction.response.send_message(
                        f"⏳ 평화 모드 전환 쿨타임 중입니다! (`{hours}시간 {minutes}분` 후 전환 가능)\n"
                        f"💡 수산대전을 걸면 쿨타임이 추가로 부여됩니다.",
                        ephemeral=True
                    )
            except (ValueError, TypeError):
                pass
        
        new_mode = 1 if current_mode == 0 else 0
        status_text = "켜졌습니다 🕊️ (이제 다른 유저가 나를 약탈할 수 없습니다)" if new_mode == 1 else "꺼졌습니다 ⚔️ (이제 다른 유저와 PvP 전투가 가능합니다)"
        
        # 1시간 쿨타임 설정 (기존 24시간에서 단축)
        cooldown_until = (now + dt.timedelta(hours=1)).isoformat()
        
        await db.execute("UPDATE user_data SET peace_mode=?, peace_cooldown=? WHERE user_id=?", (new_mode, cooldown_until, interaction.user.id))
        await db.commit()
        
        await interaction.response.send_message(f"✅ 평화 모드가 **{status_text}**\n⏳ *다음 전환까지 1시간 쿨타임이 적용됩니다.*")

    @app_commands.command(name="레이드", description="서버 전체 유저들과 힘을 합쳐 월드 보스를 토벌합니다! (체력 25 소모, 30분 쿨타임)")
    @app_commands.checks.cooldown(1, 1800, key=lambda i: i.user.id)
    async def 레이드(self, interaction: discord.Interaction):
        import json
        
        # 체력 체크 (레이드는 25 소모)
        await db.get_user_data(interaction.user.id)
        async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            st = await cursor.fetchone()
        if st and st[0] < 25:
            return await interaction.response.send_message(f"❌ 행동력(체력)이 부족합니다! (필요: 25⚡ / 현재: {st[0]}⚡)\n💡 `/출석`이나 `/휴식`으로 체력을 회복하세요.", ephemeral=True)
        await db.execute("UPDATE user_data SET stamina = stamina - 25 WHERE user_id=?", (interaction.user.id,))

        # 보스 레벨 로드 (동적 스케일링)
        async with db.conn.execute("SELECT value FROM server_state WHERE key='RAID_BOSS_LEVEL'") as cursor:
            lvl_res = await cursor.fetchone()
        boss_level = int(lvl_res[0]) if lvl_res else 1
        
        # 보스 최대 HP = 기본 100만 × 1.1^(레벨-1) (기존 1.2배에서 하향)
        boss_max_hp = int(1000000 * (1.1 ** (boss_level - 1)))

        async with db.conn.execute("SELECT value FROM server_state WHERE key='RAID_BOSS_HP'") as cursor:
            res = await cursor.fetchone()
        
        boss_hp = int(res[0]) if res else boss_max_hp
        if boss_hp <= 0:
            boss_level += 1
            boss_max_hp = int(1000000 * (1.1 ** (boss_level - 1)))
            boss_hp = boss_max_hp
            await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_BOSS_LEVEL', ?)", (str(boss_level),))
            await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_DAMAGE_LOG', ?)", ('{}',))
            await interaction.channel.send(f"📢 **[시스템]** Lv.{boss_level} 월드 보스 **'공허의 파괴자, 아포칼립스 🌌'**가 더 강해져서 깨어났습니다! (HP: {boss_max_hp:,})")

        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()
            
        if not items:
            return await interaction.response.send_message("❌ 전투에 출전할 잠금(보호) 처리된 물고기가 없습니다!", ephemeral=True)
            
        max_power = 0
        for (name,) in items:
            pwr = FISH_DATA.get(name, {}).get("power", 0)
            if pwr > max_power: max_power = pwr
            
        if max_power == 0:
            return await interaction.response.send_message("❌ 유효한 전투력을 가진 물고기가 없습니다!", ephemeral=True)

        dmg = max_power * random.randint(5, 15)
        is_crit = random.random() < 0.2
        if is_crit: dmg *= 2
        
        # 레이드 작살 아이템 체크 (2배 데미지)
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='레이드 작살 🔱'", (interaction.user.id,)) as cursor:
            harpoon = await cursor.fetchone()
        harpoon_used = False
        if harpoon and harpoon[0] > 0:
            dmg *= 2
            harpoon_used = True
            await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='레이드 작살 🔱'", (interaction.user.id,))
        
        new_hp = max(0, boss_hp - dmg)
        
        await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_BOSS_HP', ?)", (str(new_hp),))
        
        # 딜량 누적 기록
        async with db.conn.execute("SELECT value FROM server_state WHERE key='RAID_DAMAGE_LOG'") as cursor:
            log_res = await cursor.fetchone()
        damage_log = json.loads(log_res[0]) if log_res and log_res[0] else {}
        user_id_str = str(interaction.user.id)
        damage_log[user_id_str] = damage_log.get(user_id_str, 0) + dmg
        await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_DAMAGE_LOG', ?)", (json.dumps(damage_log),))
        
        # 레이드 보상: 딜량의 0.2배 (하이퍼인플레이션 방지)
        reward = int(dmg * 0.2)
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (reward, interaction.user.id))
        await db.commit()
        
        crit_txt = "💥 **크리티컬 히트!!** " if is_crit else ""
        harpoon_txt = "\n🔱 **레이드 작살** 효과로 데미지 2배!" if harpoon_used else ""
        embed = discord.Embed(title=f"🌌 월드 보스 레이드 (Lv.{boss_level})", color=0x9932cc)
        embed.description = f"{interaction.user.mention}님의 가장 강한 전사가 보스를 향해 일격을 날립니다!\n\n{crit_txt}**{dmg:,}** 의 피해를 입혔습니다!{harpoon_txt}\n💰 보상: `{reward:,} C` 지급 완료."
        
        hp_ratio = new_hp / boss_max_hp
        bar = "🟥" * int(hp_ratio * 10) + "⬛" * (10 - int(hp_ratio * 10))
        embed.add_field(name="공허의 파괴자, 아포칼립스", value=f"남은 체력: {new_hp:,} / {boss_max_hp:,}\n{bar}", inline=False)
        
        # 누적 딜량 표시
        my_total_dmg = damage_log.get(user_id_str, 0)
        embed.add_field(name="📊 내 누적 딜량", value=f"`{my_total_dmg:,}` 데미지", inline=True)
        
        await interaction.response.send_message(embed=embed)
        
        if new_hp <= 0:
            # 딜량 순위별 추가 보상
            sorted_damage = sorted(damage_log.items(), key=lambda x: x[1], reverse=True)
            bonus_msg = f"🎉 **[월드 레이드 토벌 성공]** Lv.{boss_level} 보스가 쓰러졌습니다!!\n\n📊 **딜량 랭킹 및 추가 보상:**\n"
            
            rank_rewards = [0.30, 0.20, 0.10]  # 1등 30%, 2등 20%, 3등 10% (보스 기본가 기준)
            base_bonus = boss_max_hp // 10  # 기본 보너스 풀
            
            for idx, (uid, total_dmg) in enumerate(sorted_damage[:3]):
                bonus = int(base_bonus * rank_rewards[idx])
                await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (bonus, int(uid)))
                medal = ["🥇", "🥈", "🥉"][idx]
                bonus_msg += f"{medal} <@{uid}>: `{total_dmg:,}` 딜 → 보너스 `+{bonus:,} C`\n"
            
            await db.commit()
            
            # 다음 보스 준비
            await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_DAMAGE_LOG', ?)", ('{}',))
            await db.commit()
            
            await interaction.channel.send(bonus_msg)

    @레이드.error
    async def 레이드_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"⏳ 전사들이 지쳤습니다. `{error.retry_after/60:.1f}분` 후에 다시 레이드에 참여할 수 있습니다.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
