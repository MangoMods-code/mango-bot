# cogs/smb_admin.py — Admin commands for managing SMB social media services.

import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
import smb as smb_api
from helpers import (
    is_owner, mango_embed, error_embed, success_embed,
    server_only_error, DIVIDER, DIVIDER_SHORT,
    PaginatorView, paginate_items,
)

PLATFORMS = [
    "Instagram", "TikTok", "YouTube", "Facebook", "Telegram",
    "Twitter", "Twitch", "Kick", "WhatsApp", "Snapchat",
    "Threads", "Reddit", "LinkedIn", "Spotify", "Discord",
]


class SmbAdmin(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def _check(self, interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(embed=server_only_error(), ephemeral=True)
            return True
        if not is_owner(interaction):
            await interaction.response.send_message(
                embed=error_embed("🔒 Only the bot owner can use this command."), ephemeral=True
            )
            return True
        return False

    # ── SMB MAINTENANCE ───────────────────────────────────────────────────────

    @app_commands.command(name="smbmaintenance", description="Toggle the socials panel on/off for buyers (Admin)")
    async def smbmaintenance(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        current = (await db.get_setting("smb_maintenance", "0")) == "1"
        new_state = not current
        await db.set_setting("smb_maintenance", "1" if new_state else "0")
        if new_state:
            embed = mango_embed(
                "🔧  Socials Panel — OFF",
                f"The `/socials` panel is now **disabled**.\n{DIVIDER_SHORT}\nUse `/smbmaintenance` again to turn it back on."
            )
        else:
            embed = mango_embed(
                "🟢  Socials Panel — ON",
                f"The `/socials` panel is now **enabled**.\n{DIVIDER_SHORT}\nBuyers can now use it."
            )
        await interaction.response.send_message(embed=embed)

    # ── ADD SERVICE ──────────────────────────────────────────────────────────

    @app_commands.command(name="smbaddservice", description="Add or update an SMB service (Admin)")
    @app_commands.describe(
        platform="Platform this service belongs to",
        category="Category name (e.g. 'Followers', 'Likes - Posts')",
        service_id="SMB service ID number",
        name="Display name for this service",
        min_qty="Minimum order quantity",
        max_qty="Maximum order quantity",
        rate="Price per 1,000 (e.g. 0.90)",
        link_hint="What to ask for in the link field (e.g. 'TikTok video URL', 'Instagram profile URL')",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name=p, value=p) for p in PLATFORMS
    ])
    async def smbaddservice(self, interaction: discord.Interaction, platform: str,
                            category: str, service_id: int, name: str,
                            min_qty: int, max_qty: int, rate: str,
                            link_hint: str = ""):
        if await self._check(interaction):
            return
        try:
            float(rate)
        except ValueError:
            return await interaction.response.send_message(
                embed=error_embed("Rate must be a number (e.g. `0.90`)."), ephemeral=True
            )
        await db.smb_add_service(platform, category, service_id, name, min_qty, max_qty, rate, link_hint)
        hint_line = f"\nLink hint: *{link_hint}*" if link_hint else ""
        embed = success_embed(
            f"**{name}** added to **{platform}** › {category}\n"
            f"{DIVIDER_SHORT}\n"
            f"Service ID: `{service_id}`  •  Rate: ${rate}/1k\n"
            f"Min: {min_qty:,}  •  Max: {max_qty:,}{hint_line}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── REMOVE SERVICE ───────────────────────────────────────────────────────

    @app_commands.command(name="smbremoveservice", description="Remove an SMB service by service ID (Admin)")
    @app_commands.describe(service_id="The SMB service ID to remove")
    async def smbremoveservice(self, interaction: discord.Interaction, service_id: int):
        if await self._check(interaction):
            return
        service = await db.smb_get_service(service_id)
        if not service:
            return await interaction.response.send_message(
                embed=error_embed(f"No service found with ID `{service_id}`."), ephemeral=True
            )
        await db.smb_remove_service(service_id)
        await interaction.response.send_message(
            embed=success_embed(f"**{service['name']}** (ID: `{service_id}`) removed."), ephemeral=True
        )

    # ── LIST SERVICES ─────────────────────────────────────────────────────────

    @app_commands.command(name="smbservices", description="List all configured SMB services (Admin)")
    @app_commands.describe(platform="Filter by platform (optional)")
    @app_commands.choices(platform=[
        app_commands.Choice(name="All platforms", value="all"),
    ] + [app_commands.Choice(name=p, value=p) for p in PLATFORMS])
    async def smbservices(self, interaction: discord.Interaction, platform: str = "all"):
        if await self._check(interaction):
            return
        all_services = await db.smb_get_all_services()
        if platform != "all":
            all_services = [s for s in all_services if s["platform"] == platform]
        if not all_services:
            return await interaction.response.send_message(
                embed=mango_embed("📊  SMB Services", "No services configured yet."), ephemeral=True
            )
        lines = []
        current_platform = None
        current_category = None
        for s in all_services:
            if s["platform"] != current_platform:
                current_platform = s["platform"]
                current_category = None
                lines.append(f"\n**{current_platform}**")
            if s["category"] != current_category:
                current_category = s["category"]
                lines.append(f"*{current_category}*")
            status = "🟢" if s["enabled"] else "🔴"
            hint = f"  •  *{s['link_hint']}*" if s.get("link_hint") else ""
            lines.append(
                f"> {status} `{s['service_id']}`  **{s['name']}**  "
                f"— ${s['rate']}/1k  •  {s['min_qty']:,}–{s['max_qty']:,}{hint}"
            )
        chunks = paginate_items(lines, 15)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            embed = mango_embed(f"📊  SMB Services — Page {i}/{len(chunks)}", "\n".join(chunk))
            embed.set_footer(text=f"🥭 {len(all_services)} total  •  Page {i}/{len(chunks)}")
            pages.append(embed)
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True
            )

    # ── SMB BALANCE ──────────────────────────────────────────────────────────

    @app_commands.command(name="smbbalance", description="Check your SMBPanel account balance (Admin)")
    async def smbbalance(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not cfg.SMB_API_KEY:
            return await interaction.followup.send(
                embed=error_embed("SMB API key not set.\n\nAdd `SMB_API_KEY` to your Railway environment variables.")
            )
        try:
            result = await smb_api.get_balance()
            balance = result.get("balance", "?")
            currency = result.get("currency", "USD")
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed to fetch balance:\n{e}"))
        embed = mango_embed(
            "💳  SMB Balance",
            f"**${balance}** {currency}\n{DIVIDER_SHORT}\nSMBPanel account balance."
        )
        await interaction.followup.send(embed=embed)

    # ── TOGGLE SERVICE ────────────────────────────────────────────────────────

    @app_commands.command(name="smbtoggle", description="Enable or disable an SMB service (Admin)")
    @app_commands.describe(service_id="The SMB service ID to toggle", status="Enable or disable")
    @app_commands.choices(status=[
        app_commands.Choice(name="🟢 Enable", value="enable"),
        app_commands.Choice(name="🔴 Disable", value="disable"),
    ])
    async def smbtoggle(self, interaction: discord.Interaction, service_id: int, status: str):
        if await self._check(interaction):
            return
        service = await db.smb_get_service(service_id)
        if not service:
            return await interaction.response.send_message(
                embed=error_embed(f"No service found with ID `{service_id}`."), ephemeral=True
            )
        await db.smb_set_enabled(service_id, status == "enable")
        emoji = "🟢" if status == "enable" else "🔴"
        await interaction.response.send_message(
            embed=success_embed(f"{emoji} **{service['name']}** **{status}d**."), ephemeral=True
        )


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(SmbAdmin(bot), guild=guild)

