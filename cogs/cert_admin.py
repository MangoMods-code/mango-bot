# cogs/cert_admin.py — Admin commands for managing the Nekoo cert gen system.
# Server-only, owner-only.

import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
import nekoo
from helpers import (
    is_owner, mango_embed, error_embed, success_embed,
    server_only_error, DIVIDER, DIVIDER_SHORT, paginate_items, PaginatorView,
)


class CertAdmin(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def _check(self, interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(embed=server_only_error(), ephemeral=True)
            return True
        if not is_owner(interaction):
            await interaction.response.send_message(
                embed=error_embed("Only the bot owner can use this command."), ephemeral=True
            )
            return True
        return False

    async def plan_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            plans = await db.cert_get_all_plans()
            return [
                app_commands.Choice(name=f"{p['plan_name']} ({p['plan_id'][:12]})", value=p["plan_id"])
                for p in plans if current.lower() in p["plan_name"].lower()
            ][:25]
        except Exception:
            return []

    # ── SYNC PLANS FROM NEKOO API ─────────────────────────────────────────────

    @app_commands.command(name="certsyncplans", description="Sync available plans from Nekoo API (Admin)")
    async def certsyncplans(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        if not cfg.NEKOO_API_KEY:
            return await interaction.followup.send(
                embed=error_embed("NEKOO_API_KEY not set in Railway environment variables.")
            )

        try:
            plans = await nekoo.get_plans()
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed to fetch plans:\n`{e}`"))

        if not plans:
            return await interaction.followup.send(embed=error_embed("No plans returned from Nekoo API."))

        added = 0
        updated = 0
        for p in plans:
            plan_id = p.get("id", "")
            plan_name = p.get("plan_name", "Unknown")
            cost = float(p.get("cost", 0))
            existing = await db.cert_get_plan(plan_id)
            await db.cert_upsert_plan(plan_id, plan_name, cost)
            if existing:
                updated += 1
            else:
                added += 1

        desc = (
            f"{DIVIDER}\n\n"
            f"**{len(plans)}** plan(s) synced from Nekoo.\n\n"
            f"New: **{added}**\nUpdated: **{updated}**\n\n"
            f"Use `/certsetprice` to set seller prices, then `/certtoggleplan` to enable them."
        )
        await interaction.followup.send(embed=mango_embed("📜  Plans Synced", desc))

    # ── SET SELLER PRICE ──────────────────────────────────────────────────────

    @app_commands.command(name="certsetprice", description="Set the seller price for a cert plan (Admin)")
    @app_commands.describe(plan="The plan to update", price="Internal balance cost for sellers")
    @app_commands.autocomplete(plan=plan_autocomplete)
    async def certsetprice(self, interaction: discord.Interaction, plan: str, price: int):
        if await self._check(interaction):
            return
        if price < 0:
            return await interaction.response.send_message(embed=error_embed("Price can't be negative."), ephemeral=True)

        plan_row = await db.cert_get_plan(plan)
        if not plan_row:
            return await interaction.response.send_message(embed=error_embed(f"Plan `{plan}` not found. Run `/certsyncplans` first."), ephemeral=True)

        old_price = plan_row["seller_price"]
        await db.cert_set_price(plan, price)

        embed = success_embed(
            f"**{plan_row['plan_name']}**\n{DIVIDER_SHORT}\n"
            f"{old_price} bal -> **{price}** bal per cert\n"
            f"*(Nekoo cost: ${plan_row['nekoo_cost']})*"
        )
        await interaction.response.send_message(embed=embed)

    # ── TOGGLE PLAN ───────────────────────────────────────────────────────────

    @app_commands.command(name="certtoggleplan", description="Enable or disable a cert plan (Admin)")
    @app_commands.describe(plan="The plan to toggle", status="Enable or disable")
    @app_commands.autocomplete(plan=plan_autocomplete)
    @app_commands.choices(status=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def certtoggleplan(self, interaction: discord.Interaction, plan: str, status: str):
        if await self._check(interaction):
            return
        plan_row = await db.cert_get_plan(plan)
        if not plan_row:
            return await interaction.response.send_message(embed=error_embed(f"Plan not found."), ephemeral=True)

        await db.cert_set_enabled(plan, status == "enable")
        emoji = "🟢" if status == "enable" else "🔴"
        await interaction.response.send_message(
            embed=success_embed(f"{emoji} **{plan_row['plan_name']}** {status}d.")
        )

    # ── VIEW ALL PLANS ────────────────────────────────────────────────────────

    @app_commands.command(name="certplansadmin", description="View all cert plans with pricing (Admin)")
    async def certplansadmin(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return

        plans = await db.cert_get_all_plans()
        if not plans:
            return await interaction.response.send_message(
                embed=mango_embed("📜  Cert Plans", "No plans yet. Run `/certsyncplans` to import from Nekoo."),
                ephemeral=True,
            )

        desc = f"{DIVIDER}\n\n"
        for p in plans:
            status = "🟢" if p["enabled"] else "🔴"
            desc += (
                f"{status} **{p['plan_name']}**\n"
                f"> Nekoo cost: **${p['nekoo_cost']}**  •  Seller price: **{p['seller_price']}** bal\n"
                f"> ID: `{p['plan_id']}`\n\n"
            )

        await interaction.response.send_message(embed=mango_embed("📜  All Cert Plans", desc), ephemeral=True)

    # ── NEKOO BALANCE ─────────────────────────────────────────────────────────

    @app_commands.command(name="nekoobalance", description="Check your Nekoo account balance (Admin)")
    async def nekoobalance(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        if not cfg.NEKOO_API_KEY:
            return await interaction.followup.send(embed=error_embed("NEKOO_API_KEY not set in Railway."))

        try:
            me = await nekoo.get_me()
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed:\n`{e}`"))

        embed = mango_embed(
            "📜  Nekoo Balance",
            f"**${me.get('balance', '?')}**\n{DIVIDER_SHORT}\n"
            f"Account: {me.get('name', '?')} (`{me.get('username', '?')}`)\n"
            f"API enabled: {'Yes' if me.get('api_enabled') else 'No'}"
        )
        await interaction.followup.send(embed=embed)

    # ── CERT ORDER HISTORY ────────────────────────────────────────────────────

    @app_commands.command(name="certorders", description="View recent cert orders across all sellers (Admin)")
    async def certorders(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        orders = await db.cert_get_all_orders(50)
        if not orders:
            return await interaction.followup.send(
                embed=mango_embed("📜  Cert Orders", "No orders yet.")
            )

        chunks = paginate_items(orders, 8)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n"
            for o in chunk:
                free = " *(free)*" if o["already_registered"] else ""
                desc += (
                    f"**{o['plan_name']}**{free}\n"
                    f"> User: `{o['user_id']}`\n"
                    f"> UDID: `{o['udid'][:20]}...`\n"
                    f"> Cert: `{o['certificate_id']}`\n"
                    f"> Cost: {o['seller_cost']} bal *(Nekoo: ${o['nekoo_cost']})*\n"
                    f"> {o['created_at'][:16]}\n\n"
                )
            embed = mango_embed(f"📜  Cert Orders — Page {i}/{len(chunks)}", desc)
            embed.set_footer(text=f"🥭 {len(orders)} total  •  Page {i}/{len(chunks)}")
            pages.append(embed)

        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0])
        else:
            await interaction.followup.send(embed=pages[0], view=PaginatorView(pages, interaction.user.id))

    # ── LOOKUP CERT BY UDID (ADMIN) ───────────────────────────────────────────

    @app_commands.command(name="certlookup", description="Look up any cert by UDID via Nekoo API (Admin)")
    @app_commands.describe(udid="Device UDID to look up")
    async def certlookup(self, interaction: discord.Interaction, udid: str):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        if not cfg.NEKOO_API_KEY:
            return await interaction.followup.send(embed=error_embed("NEKOO_API_KEY not set in Railway."))

        try:
            result = await nekoo.get_certificate(udid=udid.strip())
        except Exception as e:
            err = str(e)
            if "not_found" in err:
                return await interaction.followup.send(
                    embed=mango_embed("📜  Not Found", f"No certificate found for UDID:\n`{udid.strip()}`")
                )
            return await interaction.followup.send(embed=error_embed(f"API error:\n`{err}`"))

        certs = result.get("certificates", [])
        if not certs:
            return await interaction.followup.send(
                embed=mango_embed("📜  Not Found", f"No certs for `{udid.strip()}`")
            )

        desc = f"**UDID:** `{udid.strip()}`\n{DIVIDER}\n\n"
        for c in certs[:5]:
            status_icon = "🟢" if c.get("status") == "signed" and c.get("provision_valid") else "🔴"
            from cogs.certs import seconds_to_days
            desc += (
                f"{status_icon} **{c.get('id', '?')}**\n"
                f"> Status: {c.get('status')}  •  Valid: {'Yes' if c.get('provision_valid') else 'No'}\n"
                f"> Expired: {'Yes' if c.get('expired') else 'No'}\n"
                f"> Warranty: {seconds_to_days(c.get('warranty_remaining_seconds', 0))}\n"
                f"> Plan: {c.get('plan', 'N/A')}\n"
                f"> Cert: {c.get('pname', 'N/A')[:60]}\n\n"
            )

        await interaction.followup.send(embed=mango_embed("📜  Cert Lookup", desc))


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(CertAdmin(bot), guild=guild)
