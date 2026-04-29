import datetime as dt
import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.database import db
from fishing_core.logger import logger
from fishing_core.services.battle_service import BattleService
from fishing_core.shared import FISH_DATA, format_grade_label, kst
from fishing_core.utils import EmbedFactory, check_boat_tier, create_progress_bar, inv_autocomplete
from fishing_core.views_v2 import BattleView, PvPBattleView


class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _show_locked_list(self, interaction: discord.Interaction, target: discord.Member):
        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (target.id,)) as cursor:
            items = await cursor.fetchall()

        embed = EmbedFactory.build(title=f"🔒 {target.name}의 잠금(보호) 목록", style="success")
        if items:
            item_list = ""
            for name, amt in items:
                power = FISH_DATA.get(name, {}).get("power", 0)
                grade_label = format_grade_label(FISH_DATA.get(name, {}).get("grade", "일반")) if name in FISH_DATA else "📦 아이템"
                if power > 0:
                    item_list += f"• {name} `{grade_label}`: {amt}마리 (전투력: {power}⚡)\n"
                else:
                    item_list += f"• {name} `{grade_label}`: {amt}개\n"
            embed.add_field(name="보존된 아이템 및 전사", value=item_list, inline=False)
        else:
            embed.add_field(name="텅 비었습니다...", value="`/잠금` 명령어를 통해 중요한 물고기와 아이템을 판매로부터 보호하세요.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="배틀", description="나의 가장 강한 물고기로 야생의 NPC 물고기와 턴제 배틀을 진행합니다! (체력 15 소모)")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
    @check_boat_tier(3)
    async def 배틀(self, interaction: discord.Interaction):
        # 체력 체크
        async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            st = await cursor.fetchone()
        if st and st[0] < 15:
            return await interaction.response.send_message(f"❌ 행동력(체력)이 부족합니다! (필요: 15⚡ / 현재: {st[0]}⚡)\n💡 `/출석`이나 `/휴식`으로 체력을 회복하세요.", ephemeral=True)
        
        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()

        if not items:
            return await interaction.response.send_message("❌ 잠금(보호) 처리된 물고기가 없습니다! 인벤토리에서 `/잠금` 명령어로 전사를 보호하세요.", ephemeral=True)

        my_best_fish, max_power = BattleService.get_strongest_fish(items)

        if max_power == -1 or not my_best_fish:
            return await interaction.response.send_message("❌ 출전할 유효한 물고기가 없습니다! (잠금된 목록에 일반 아이템만 존재합니다)", ephemeral=True)

        await db.execute("UPDATE user_data SET stamina = stamina - 15 WHERE user_id=?", (interaction.user.id,))
        
        npc_pool = [name for name, data in FISH_DATA.items() if data.get("grade") not in ["히든", "special"]]
        npc_fish = random.choice(npc_pool)

        view = BattleView(interaction.user, my_best_fish, npc_fish)
        embed, file = view.generate_embed()
        await interaction.response.send_message(embed=embed, file=file, view=view)

    @app_commands.command(name="잠금목록", description="나 또는 특정 유저의 가방에서 잠금(보호 및 배틀용) 처리된 목록을 확인합니다.")
    async def 잠금목록(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        await self._show_locked_list(interaction, target)

    @app_commands.command(name="잠목", description="`/잠금목록`의 축약 명령어입니다.")
    async def 잠목(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        await self._show_locked_list(interaction, target)

    @app_commands.command(name="수산대전", description="다른 유저를 지목하여 마라맛 PvP 배틀(약탈)을 겁니다!")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
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
            
            await db.get_user_data(상대.id)

            # 평화모드 체크
            # 0) 초보자 보호 체크
            async with db.conn.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                target_boat = (await cursor.fetchone())[0]
            if target_boat <= 1:
                return await interaction.response.send_message(f"🔰 '{상대.name}'님은 아직 초보 어부(선박 Lv.1)입니다. 초보자는 약탈 대상에서 보호받습니다.", ephemeral=True)

            async with db.conn.execute("SELECT peace_mode FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                res = await cursor.fetchone()
            if res and res[0] == 1:
                return await interaction.response.send_message(f"❌ '{상대.name}'님은 현재 **평화 모드** 🕊️ 상태입니다. (약탈 불가)", ephemeral=True)

            now = dt.datetime.now(kst)
            today_str = now.strftime('%Y-%m-%d')

            # 1) RP 차이 제한
            async with db.conn.execute("SELECT rating FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
                my_rp = (await cursor.fetchone())[0]
            async with db.conn.execute("SELECT rating FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                target_rp = (await cursor.fetchone())[0]

            rp_gap_limit = 500
            if my_rp > 2000: rp_gap_limit = 1000

            if my_rp - target_rp > rp_gap_limit:
                return await interaction.response.send_message(
                    f"❌ 상대방과의 RP 격차가 너무 큽니다! (나: {my_rp} / 상대: {target_rp})\n⚖️ 비슷한 실력의 유저에게만 수산대전을 걸 수 있습니다.",
                    ephemeral=True,
                )

            # 2) 방어자 보호막
            async with db.conn.execute("SELECT pvp_shield_count, pvp_shield_date FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                shield_res = await cursor.fetchone()
            shield_count = shield_res[0] if shield_res else 3
            shield_date = shield_res[1] if shield_res else ""

            if shield_date != today_str:
                shield_count = 3
                await db.execute("UPDATE user_data SET pvp_shield_count=3, pvp_shield_date=? WHERE user_id=?", (today_str, 상대.id))

            if shield_count <= 0:
                return await interaction.response.send_message(f"🛡️ '{상대.name}'님은 오늘 이미 3회 약탈당해 **보호막**이 발동 중입니다.", ephemeral=True)

            # 덱 구성 가져오기
            p1_deck = await BattleService.get_pvp_deck(interaction.user.id)
            p2_deck = await BattleService.get_pvp_deck(상대.id)

            if not p1_deck:
                return await interaction.response.send_message("❌ 내 잠금 목록에 출전 가능한 전사가 없습니다!", ephemeral=True)
            if not p2_deck:
                return await interaction.response.send_message(f"❌ 상대방({상대.name})의 잠금 목록이 비어있어 약탈할 수 없습니다!", ephemeral=True)

            async with db.transaction():
                # 성공 시 체력 차감 및 상태 업데이트
                await db.execute("UPDATE user_data SET stamina = stamina - 20 WHERE user_id=?", (interaction.user.id,))
                cooldown_until = (now + dt.timedelta(hours=1)).isoformat()
                await db.execute("UPDATE user_data SET peace_mode=0, peace_cooldown=? WHERE user_id=?", (cooldown_until, interaction.user.id))
                await db.execute("UPDATE user_data SET pvp_shield_count = pvp_shield_count - 1, pvp_shield_date=? WHERE user_id=?", (today_str, 상대.id))

            # 호위 로직 반영
            async with db.conn.execute("SELECT last_active, guard_fish FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
                p2_data = await cursor.fetchone()
            p2_last_active, p2_guard = p2_data if p2_data else ("", "")

            is_p2_offline = False
            if p2_last_active:
                last_dt = dt.datetime.fromisoformat(p2_last_active)
                if (now - last_dt).total_seconds() > 6 * 3600:
                    is_p2_offline = True

            if p2_guard and any(f[0] == p2_guard for f in p2_deck):
                p2_deck = [(f[0], int(f[1]*1.15) if f[0] == p2_guard else f[1]) for f in p2_deck]

            offline_msg = "\n⚠️ **[오프라인 보호]** 상대가 장기 미접속 중입니다. 승리 시 약탈 금액이 감소합니다." if is_p2_offline else ""
            guard_msg = f"\n🛡️ **[호위 발동]** 상대의 **{p2_guard}**(이)가 방어 태세를 갖추고 있습니다!" if p2_guard and any(f[0] == p2_guard for f in p2_deck) else ""

            title_str = await db.get_user_title(interaction.user.id)
            display_name1 = f"{title_str} {interaction.user.name}" if title_str else interaction.user.name

            view = PvPBattleView(interaction.user, 상대, p1_deck, p2_deck)
            view.is_offline_target = is_p2_offline
            embed, file = view.generate_embed()

            await interaction.response.send_message(
                f"⚔️ {상대.mention}! **{display_name1}**님이 3v3 릴레이 수산대전을 걸어왔습니다!{offline_msg}{guard_msg}",
                embed=embed,
                file=file,
                view=view,
            )
        except Exception as e:
            logger.error(f"수산대전 실행 중 오류: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 수산대전 실행 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="평화모드", description="수산대전(PvP) 약탈을 거부하는 평화 모드를 켜거나 끕니다.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
    async def 평화모드(self, interaction: discord.Interaction):
        await db.get_user_data(interaction.user.id)
        async with db.conn.execute("SELECT peace_mode, peace_cooldown FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()

        current_mode = res[0] if res else 0
        peace_cooldown = res[1] if res and res[1] else ""

        now = dt.datetime.now(kst)
        if peace_cooldown:
            try:
                cooldown_end = dt.datetime.fromisoformat(peace_cooldown)
                if now < cooldown_end:
                    remaining = cooldown_end - now
                    minutes = int(remaining.total_seconds() // 60)
                    return await interaction.response.send_message(f"⏳ 평화 모드 전환 쿨타임 중입니다! (`{minutes}분` 후 전환 가능)", ephemeral=True)
            except (ValueError, TypeError):
                pass

        new_mode = 1 if current_mode == 0 else 0
        status_text = "켜졌습니다 🕊️" if new_mode == 1 else "꺼졌습니다 ⚔️"
        cooldown_until = (now + dt.timedelta(hours=1)).isoformat()

        async with db.transaction():
            await db.execute("UPDATE user_data SET peace_mode=?, peace_cooldown=? WHERE user_id=?", (new_mode, cooldown_until, interaction.user.id))

        await interaction.response.send_message(f"✅ 평화 모드가 **{status_text}**\n⏳ *다음 전환까지 1시간 쿨타임이 적용됩니다.*")

    @app_commands.command(name="레이드", description="서버 전체 유저들과 힘을 합쳐 월드 보스를 토벌합니다! (체력 25 소모, 30분 쿨타임)")
    @app_commands.checks.cooldown(1, 1800, key=lambda i: i.user.id)
    async def 레이드(self, interaction: discord.Interaction):
        try:
            if not db.conn:
                return await interaction.response.send_message("❌ 데이터베이스 연결이 끊겨 있습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)

            user_id = interaction.user.id
            await db.get_user_data(user_id)
            
            # 모든 DB 작업을 락으로 보호하여 안정성 확보
            async with db._lock:
                async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (user_id,)) as cursor:
                    st = await cursor.fetchone()
                if st and st[0] < 25:
                    return await interaction.response.send_message(f"❌ 행동력(체력)이 부족합니다! (필요: 25⚡ / 현재: {st[0]}⚡)", ephemeral=True)

                async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (user_id,)) as cursor:
                    items = await cursor.fetchall()
                if not items:
                    return await interaction.response.send_message("❌ 전투에 출전할 잠금 처리된 물고기가 없습니다!", ephemeral=True)

                strongest_fish, _ = BattleService.get_strongest_fish(items)
                if not strongest_fish:
                    return await interaction.response.send_message("❌ 출전할 유효한 전사가 없습니다!", ephemeral=True)

                # 보스 데이터 로드
                async with db.conn.execute("SELECT value FROM server_state WHERE key='RAID_BOSS_LEVEL'") as cursor:
                    lvl_res = await cursor.fetchone()
                
                try:
                    boss_level = int(lvl_res[0]) if lvl_res and lvl_res[0] is not None else 1
                except (ValueError, TypeError):
                    boss_level = 1
                    
                boss_max_hp = int(1000000 * (1.1 ** (boss_level - 1)))

                async with db.conn.execute("SELECT value FROM server_state WHERE key='RAID_BOSS_HP'") as cursor:
                    res = await cursor.fetchone()
                
                if not res or res[0] is None:
                    boss_hp = boss_max_hp
                    await db.conn.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_BOSS_HP', ?)", (str(boss_hp),))
                    await db.conn.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_DAMAGE_LOG', ?)", ('{}',))
                    await db.conn.commit()
                else:
                    try:
                        boss_hp = int(float(res[0]))
                    except (ValueError, TypeError):
                        boss_hp = boss_max_hp

                if boss_hp <= 0:
                    boss_level += 1
                    boss_max_hp = int(1000000 * (1.1 ** (boss_level - 1)))
                    boss_hp = boss_max_hp
                    await db.conn.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_BOSS_LEVEL', ?)", (str(boss_level),))
                    await db.conn.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_BOSS_HP', ?)", (str(boss_hp),))
                    await db.conn.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_DAMAGE_LOG', ?)", ('{}',))
                    await db.conn.commit()
                    await interaction.channel.send(f"📢 Lv.{boss_level} 월드 보스가 더 강해져서 깨어났습니다!")

            # 서비스 레이어를 통한 공격 처리 (내부에서 db.execute 사용 가능)
            result = await BattleService.process_raid_attack(user_id, strongest_fish, boss_hp, boss_max_hp)
            
            async with db.transaction():
                # DB 업데이트
                await db.execute("UPDATE user_data SET stamina = stamina - 25 WHERE user_id=?", (user_id,))
                await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_BOSS_HP', ?)", (str(result['new_hp']),))

                async with db.conn.execute("SELECT value FROM server_state WHERE key='RAID_DAMAGE_LOG'") as cursor:
                    log_res = await cursor.fetchone()
                
                try:
                    damage_log = json.loads(log_res[0]) if log_res and log_res[0] else {}
                except json.JSONDecodeError:
                    damage_log = {}
                    
                damage_log[str(user_id)] = damage_log.get(str(user_id), 0) + result['damage']
                await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RAID_DAMAGE_LOG', ?)", (json.dumps(damage_log),))
                
                await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (result['reward'], user_id))

            # 임베드 구성
            fish_grade = FISH_DATA.get(strongest_fish, {}).get("grade", "일반")
            is_defeated = result['new_hp'] <= 0
            embed_type = "success" if is_defeated else "info"
            
            embed = EmbedFactory.build(title=f"🌌 월드 보스 레이드 (Lv.{boss_level})", style=embed_type)
            health_bar = create_progress_bar(result['new_hp'], boss_max_hp, length=20)
            
            crit_msg = "💥 **[치명타!]** " if result['is_crit'] else "⚔️ "
            harpoon_msg = "🔱 **[작살 강화]** " if result['used_harpoon'] else ""
            
            embed.add_field(name="👾 보스 상태 (HP)", value=f"{health_bar}\n`{result['new_hp']:,} / {boss_max_hp:,}`", inline=False)
            embed.description = f"{crit_msg}{harpoon_msg}**{strongest_fish}** {format_grade_label(fish_grade)}의 맹공!\n" \
                                f"💥 보스에게 **{result['damage']:,}**의 피해를 입히고 **{result['reward']:,} C**를 획득했습니다!"
            
            embed.set_image(url="https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=800")
            embed.set_footer(text="레이드는 30분마다 참여 가능합니다. 모든 유저의 누적 데미지로 보스를 처치하세요!")
            
            await interaction.response.send_message(embed=embed)

            if is_defeated:
                await interaction.channel.send(f"🎉 Lv.{boss_level} 보스가 토벌되었습니다!")

        except Exception as e:
            logger.error(f"레이드 명령어 실행 중 예외 발생: {e}")
            error_msg = f"❌ 레이드 처리 중 오류가 발생했습니다: `{e!s}`"
            if not interaction.response.is_done():
                await interaction.response.send_message(error_msg, ephemeral=True)
            else:
                await interaction.followup.send(error_msg, ephemeral=True)

    @app_commands.command(name="호위설정", description="나의 전사 중 한 마리를 '호위 어종'으로 지정합니다.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
    @app_commands.autocomplete(물고기=inv_autocomplete)
    async def 호위설정(self, interaction: discord.Interaction, 물고기: str):
        async with db.conn.execute("SELECT amount, is_locked FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] <= 0:
            return await interaction.response.send_message(f"❌ 가방에 **{물고기}**가 없습니다.", ephemeral=True)
        if res[1] == 0:
            return await interaction.response.send_message("⚠️ 먼저 `/잠금`으로 배틀용 전사로 등록하세요.", ephemeral=True)

        async with db.transaction():
            await db.execute("UPDATE user_data SET guard_fish=? WHERE user_id=?", (물고기, interaction.user.id))
        await interaction.response.send_message(f"🛡️ **{물고기}**(을)를 호위 어종으로 설정했습니다!")

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
