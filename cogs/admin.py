# cogs/admin.py — Admin commands (server-only, owner-only).

import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
from helpers import (
    is_owner, mango_embed, error_embed, success_embed,
    server_only_error, DIVIDER, DIVIDER_SHORT,
    PaginatorView, paginate_items,
    send_log, log_balance_change, log_seller_change, log_maintenance, log_clear_keys,
)


class Admin(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def _admin_check(self, interaction):
        if not interaction.guild:
            await interaction.response.send_message(embed=server_only_error(), ephemeral=True)
            return True
        if not is_owner(interaction):
            await interaction.response.send_message(embed=error_embed("🔒 Only the bot owner can use this command."), ephemeral=True)
            return True
        return False

    # ── MAINTENANCE ──────────────────────────────────────────────────────────

    @app_commands.command(name="maintenance", description="Toggle maintenance mode on/off (Admin)")
    async def maintenance(self, interaction: discord.Interaction):
        if await self._admin_check(interaction):
            return
        current = await db.is_maintenance()
        new_state = not current
        await db.set_maintenance(new_state)
        if new_state:
            embed = mango_embed("🔧  Maintenance Mode — ON", f"Key generation **disabled** for sellers.\n{DIVIDER_SHORT}\nUse `/maintenance` again to turn it off.")
        else:
            embed = mango_embed("🟢  Maintenance Mode — OFF", f"Key generation back **online**.\n{DIVIDER_SHORT}\nSellers can generate keys again.")
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_maintenance(interaction.user, new_state))

    # ── USER MANAGEMENT ──────────────────────────────────────────────────────

    @app_commands.command(name="setseller", description="Grant or revoke seller permissions (Admin)")
    @app_commands.describe(user="The user to update", action="Grant or revoke seller status")
    @app_commands.choices(action=[
        app_commands.Choice(name="Grant", value="grant"),
        app_commands.Choice(name="Revoke", value="revoke"),
    ])
    async def setseller(self, interaction: discord.Interaction, user: discord.User, action: str):
        if await self._admin_check(interaction):
            return
        await db.ensure_user(str(user.id), user.name)
        granted = action == "grant"
        await db.set_seller_status(str(user.id), granted)
        if granted:
            embed = success_embed(f"**{user.name}** granted seller permissions.\n\nThey can now DM the bot and use `/generatekey`!")
        else:
            embed = success_embed(f"**{user.name}** seller permissions revoked.")
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_seller_change(interaction.user, user, granted))

    @app_commands.command(name="addbalance", description="Add balance to a user (Admin)")
    @app_commands.describe(user="The user to add balance to", amount="Amount to add")
    async def addbalance(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if await self._admin_check(interaction):
            return
        if amount < 1:
            return await interaction.response.send_message(embed=error_embed("Amount must be at least **1**."), ephemeral=True)
        await db.ensure_user(str(user.id), user.name)
        await db.add_balance(str(user.id), amount)
        updated = await db.get_user(str(user.id))
        embed = mango_embed("💰  Balance Updated", f"Added **{amount}** to **{user.name}**\n{DIVIDER_SHORT}\nNew balance: **{updated['balance']}**")
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_balance_change(interaction.user, user, "Add", amount, updated["balance"]))

    @app_commands.command(name="setbalance", description="Set a user's exact balance (Admin)")
    @app_commands.describe(user="The user to update", amount="The exact balance to set")
    async def setbalance(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if await self._admin_check(interaction):
            return
        if amount < 0:
            return await interaction.response.send_message(embed=error_embed("Amount can't be negative."), ephemeral=True)
        await db.ensure_user(str(user.id), user.name)
        old = await db.get_user(str(user.id))
        await db.set_balance(str(user.id), amount)
        embed = mango_embed("💰  Balance Set", f"**{user.name}**'s balance → **{amount}**")
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_balance_change(interaction.user, user, f"Set (was {old['balance']})", amount, amount))

    @app_commands.command(name="resetbalance", description="Reset a user's balance to 0 (Admin)")
    @app_commands.describe(user="The user to reset")
    async def resetbalance(self, interaction: discord.Interaction, user: discord.User):
        if await self._admin_check(interaction):
            return
        await db.ensure_user(str(user.id), user.name)
        old = await db.get_user(str(user.id))
        await db.reset_balance(str(user.id))
        embed = mango_embed("💰  Balance Reset", f"**{user.name}**'s balance → **0**")
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_balance_change(interaction.user, user, f"Reset (was {old['balance']})", 0, 0))

    @app_commands.command(name="viewusers", description="View all users with their balances and keys (Admin)")
    async def viewusers(self, interaction: discord.Interaction):
        if await self._admin_check(interaction):
            return
        users = await db.get_all_users()
        if not users:
            return await interaction.response.send_message(embed=mango_embed("👥  Users", "No users registered yet."), ephemeral=True)
        chunks = paginate_items(users, 8)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n"
            for u in chunk:
                keys = await db.get_keys_by_user(u["discord_id"])
                icon = "🏷️" if u["is_seller"] else "👤"
                status = "Seller" if u["is_seller"] else "User"
                desc += f"{icon}  **{u['username']}** — *{status}*\n> 💰 **{u['balance']}**  •  🔑 **{len(keys)}** keys\n> `{u['discord_id']}`\n\n"
            embed = mango_embed(f"👥  All Users — Page {i}/{len(chunks)}", desc)
            embed.set_footer(text=f"🥭 {len(users)} total users  •  Page {i}/{len(chunks)}")
            pages.append(embed)
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True)

    # ── KEY MANAGEMENT ───────────────────────────────────────────────────────

    @app_commands.command(name="bankey", description="Ban a license key (Admin)")
    @app_commands.describe(key="The license key or key ID to ban")
    async def bankey(self, interaction: discord.Interaction, key: str):
        if await self._admin_check(interaction):
            return
        key_row = await db.get_key_by_id(int(key)) if key.isdigit() else None
        if not key_row:
            key_row = await db.get_key_by_value(key)
        if not key_row:
            return await interaction.response.send_message(embed=error_embed("Key not found."), ephemeral=True)
        if key_row["is_banned"]:
            return await interaction.response.send_message(embed=error_embed("Already banned."), ephemeral=True)
        await db.ban_key(key_row["id"])
        label = f"{key_row['product_name']} — {key_row['variant_name']}"
        await interaction.response.send_message(embed=mango_embed("🚫  Key Banned", f"**{label}** — Key #{key_row['id']}\n{DIVIDER_SHORT}\n`{key_row['key_value']}`"))

    @app_commands.command(name="unbankey", description="Unban a license key (Admin)")
    @app_commands.describe(key="The license key or key ID to unban")
    async def unbankey(self, interaction: discord.Interaction, key: str):
        if await self._admin_check(interaction):
            return
        key_row = await db.get_key_by_id(int(key)) if key.isdigit() else None
        if not key_row:
            key_row = await db.get_key_by_value(key)
        if not key_row:
            return await interaction.response.send_message(embed=error_embed("Key not found."), ephemeral=True)
        if not key_row["is_banned"]:
            return await interaction.response.send_message(embed=error_embed("Not banned."), ephemeral=True)
        await db.unban_key(key_row["id"])
        label = f"{key_row['product_name']} — {key_row['variant_name']}"
        await interaction.response.send_message(embed=success_embed(f"Key **#{key_row['id']}** for **{label}** unbanned.\n`{key_row['key_value']}`"))

    @app_commands.command(name="removekey", description="Permanently remove a license key (Admin)")
    @app_commands.describe(key="The license key or key ID to remove")
    async def removekey(self, interaction: discord.Interaction, key: str):
        if await self._admin_check(interaction):
            return
        key_row = await db.get_key_by_id(int(key)) if key.isdigit() else None
        if not key_row:
            key_row = await db.get_key_by_value(key)
        if not key_row:
            return await interaction.response.send_message(embed=error_embed("Key not found."), ephemeral=True)
        label = f"{key_row['product_name']} — {key_row['variant_name']}"
        key_id = key_row["id"]
        await db.remove_key(key_row["id"])
        await interaction.response.send_message(embed=success_embed(f"Key **#{key_id}** for **{label}** permanently removed."))

    @app_commands.command(name="clearkeyhistory", description="Delete ALL generated key records (Admin)")
    async def clearkeyhistory(self, interaction: discord.Interaction):
        if await self._admin_check(interaction):
            return
        view = ConfirmClearView(interaction.user.id, self.bot)
        embed = mango_embed("⚠️  Clear Key History", f"This will **permanently delete** every generated key record.\nStock already used stays used.\n{DIVIDER_SHORT}\n**Are you sure?**")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ConfirmClearView(discord.ui.View):
    def __init__(self, author_id, bot):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.bot = bot

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Yes, clear everything", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction, button):
        count = await db.clear_all_keys()
        await interaction.response.edit_message(embed=success_embed(f"Cleared **{count}** key record(s) from history."), view=None)
        await send_log(self.bot, log_clear_keys(interaction.user, count))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(embed=mango_embed("👍  Cancelled", "Key history was not cleared."), view=None)


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(Admin(bot), guild=guild)
