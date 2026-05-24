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
    PaginatorView, paginate_items, send_log,
    log_smb_balance_change, log_announce,
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
            await interaction.response.send_message(embed=error_embed("Only the bot owner can use this command."), ephemeral=True)
            return True
        return False

    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            platform = (interaction.namespace.platform or "") if interaction.namespace else ""
            categories = await db.smb_get_categories_for_platform(platform) if platform else []
            return [
                app_commands.Choice(name=c[:100], value=c[:100])
                for c in categories
                if current.lower() in c.lower()
            ][:25]
        except Exception:
            return []

    # ── SYNC ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="smbsync", description="Import all services from the SMB API for a platform (Admin)")
    @app_commands.describe(platform="Platform to sync — filters services where the category contains this name")
    @app_commands.choices(platform=[app_commands.Choice(name=p, value=p) for p in PLATFORMS])
    async def smbsync(self, interaction: discord.Interaction, platform: str):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not cfg.SMB_API_KEY:
            return await interaction.followup.send(embed=error_embed("SMB API key not set in Railway."))
        try:
            all_services = await smb_api.list_services()
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed to fetch services from SMB API:\n{e}"))
        if not all_services:
            return await interaction.followup.send(embed=error_embed("SMB API returned no services. Check your API key."))

        platform_lower = platform.lower()
        added = 0
        updated = 0

        for s in all_services:
            category = str(s.get("category") or "").strip()
            name = str(s.get("name") or "").strip()
            rate = str(s.get("rate") or "0")
            try:
                service_id = int(s.get("service") or s.get("id") or 0)
                min_qty = int(s.get("min") or s.get("min_qty") or 1)
                max_qty = int(s.get("max") or s.get("max_qty") or 10000)
            except (ValueError, TypeError):
                continue
            if not service_id or not name:
                continue
            if platform_lower not in category.lower():
                continue
            is_new = await db.smb_sync_service(platform, category, service_id, name, min_qty, max_qty, rate)
            if is_new:
                added += 1
            else:
                updated += 1

        total = added + updated
        embed = mango_embed(
            f"SMB Sync -- {platform}",
            f"{DIVIDER}\n\n"
            f"**{total}** services processed from the SMB API.\n\n"
            f"New (enabled): **{added}**\n"
            f"Updated (your settings preserved): **{updated}**\n"
            f"Skipped (no {platform} in category): **{len(all_services) - total}**\n\n"
            f"Use `/smbeditservice` to set `buyer_rate`, then `/smbtogglecategory` or `/smbtoggleplatform` to manage visibility."
        )
        await interaction.followup.send(embed=embed)

    # ── SMB MAINTENANCE ───────────────────────────────────────────────────────

    @app_commands.command(name="smbmaintenance", description="Toggle the socials panel on/off for buyers (Admin)")
    async def smbmaintenance(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        current = (await db.get_setting("smb_maintenance", "0")) == "1"
        new_state = not current
        await db.set_setting("smb_maintenance", "1" if new_state else "0")
        if new_state:
            embed = mango_embed("Socials Panel OFF", f"The `/socials` panel is now **disabled**.\n{DIVIDER_SHORT}\nUse `/smbmaintenance` again to turn it back on.")
        else:
            embed = mango_embed("Socials Panel ON", f"The `/socials` panel is now **enabled**.\n{DIVIDER_SHORT}\nBuyers can now use it.")
        await interaction.response.send_message(embed=embed)

    # ── SMB BALANCE MANAGEMENT ────────────────────────────────────────────────

    @app_commands.command(name="smbaddbalance", description="Add SMB balance to a user (Admin)")
    @app_commands.describe(user="The user to add SMB balance to", amount="Amount to add (e.g. 10.00)")
    async def smbaddbalance(self, interaction: discord.Interaction, user: discord.User, amount: float):
        if await self._check(interaction):
            return
        if amount <= 0:
            return await interaction.response.send_message(embed=error_embed("Amount must be greater than 0."), ephemeral=True)
        await db.ensure_user(str(user.id), user.name)
        await db.smb_add_user_balance(str(user.id), amount)
        new_bal = await db.smb_get_user_balance(str(user.id))
        embed = mango_embed("SMB Balance Updated", f"Added **${amount:.2f}** to **{user.name}**\n{DIVIDER_SHORT}\nNew SMB balance: **${new_bal:.2f}**")
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_smb_balance_change(interaction.user, user, "Add", amount, new_bal))

    @app_commands.command(name="smbsetbalance", description="Set a user's exact SMB balance (Admin)")
    @app_commands.describe(user="The user to update", amount="Exact SMB balance to set")
    async def smbsetbalance(self, interaction: discord.Interaction, user: discord.User, amount: float):
        if await self._check(interaction):
            return
        if amount < 0:
            return await interaction.response.send_message(embed=error_embed("Amount can't be negative."), ephemeral=True)
        await db.ensure_user(str(user.id), user.name)
        old = await db.smb_get_user_balance(str(user.id))
        await db.smb_set_user_balance(str(user.id), amount)
        embed = mango_embed("SMB Balance Set", f"**{user.name}**'s SMB balance set to **${amount:.2f}**")
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await send_log(self.bot, log_smb_balance_change(interaction.user, user, f"Set (was ${old:.2f})", amount, amount))

    # ── SMB SELLERS LIST ──────────────────────────────────────────────────────

    @app_commands.command(name="smbsellers", description="View all sellers with their SMB balances and orders (Admin)")
    async def smbsellers(self, interaction: discord.Interaction):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        sellers = await db.get_all_sellers()
        if not sellers:
            return await interaction.followup.send(embed=mango_embed("SMB Sellers", "No sellers registered yet."))
        chunks = paginate_items(sellers, 8)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n"
            for s in chunk:
                smb_bal = await db.smb_get_user_balance(s["discord_id"])
                orders = await db.smb_get_user_orders(s["discord_id"])
                desc += f"**{s['username']}**\n> SMB: **${smb_bal:.2f}**  •  {len(orders)} order(s)\n> `{s['discord_id']}`\n\n"
            embed = mango_embed(f"SMB Sellers -- Page {i}/{len(chunks)}", desc)
            embed.set_footer(text=f"🥭 {len(sellers)} sellers  •  Page {i}/{len(chunks)}")
            pages.append(embed)
        view = SmbSellerView(interaction.user.id, sellers)
        await interaction.followup.send(embed=pages[0], view=view)

    # ── CHECK ORDER BY ID ─────────────────────────────────────────────────────

    @app_commands.command(name="smbid", description="Check an SMB order by its order ID (Admin)")
    @app_commands.describe(order_id="The SMB order ID to check")
    async def smbid(self, interaction: discord.Interaction, order_id: str):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            status = await smb_api.get_order_status(int(order_id))
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed to fetch order:\n{e}"))
        order_status = status.get("status", "Unknown")
        color_map = {
            "Completed": discord.Colour.green(), "In progress": discord.Colour.orange(),
            "Partial": discord.Colour.yellow(), "Processing": discord.Colour.blue(),
            "Canceled": discord.Colour.red(),
        }
        embed = discord.Embed(
            title=f"Order #{order_id} -- {order_status}",
            description=(
                f"**Status:** {order_status}\n"
                f"**Start count:** {status.get('start_count', '?')}\n"
                f"**Remaining:** {status.get('remains', '?')}\n"
                f"**Charge:** {status.get('charge', '?')} {status.get('currency', 'USD')}"
            ),
            color=color_map.get(order_status, discord.Colour.greyple()),
        )
        embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
        await interaction.followup.send(embed=embed)

    # ── SMB ANNOUNCE ──────────────────────────────────────────────────────────

    @app_commands.command(name="smbannounce", description="DM all sellers an SMB panel announcement (Admin)")
    @app_commands.describe(title="Announcement title", message="The announcement message")
    async def smbannounce(self, interaction: discord.Interaction, title: str, message: str):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        sellers = await db.get_all_sellers()
        if not sellers:
            return await interaction.followup.send(embed=error_embed("No sellers registered yet."))
        announce_embed = discord.Embed(
            title=f"📱  {title}",
            description=message,
            color=discord.Colour.from_str("#1DA1F2"),
        )
        announce_embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
        announce_embed.timestamp = discord.utils.utcnow()
        sent = 0
        failed = 0
        failed_names = []
        for seller in sellers:
            try:
                user = await self.bot.fetch_user(int(seller["discord_id"]))
                await user.send(embed=announce_embed)
                sent += 1
            except Exception:
                failed += 1
                failed_names.append(seller["username"])
        result = f"Sent to **{sent}** seller(s).\n{DIVIDER_SHORT}\n"
        if failed:
            result += f"Failed: {', '.join(f'`{n}`' for n in failed_names[:20])}"
        await interaction.followup.send(embed=mango_embed("SMB Announcement Sent", result))
        await send_log(self.bot, log_announce(interaction.user, f"[SMB] {title}: {message}", sent, failed))

    # ── ADD SERVICE ───────────────────────────────────────────────────────────

    @app_commands.command(name="smbaddservice", description="Add or update an SMB service (Admin)")
    @app_commands.describe(
        platform="Platform this service belongs to",
        category="Existing category or type a new one",
        service_id="SMB service ID number",
        name="Display name for this service",
        min_qty="Minimum order quantity",
        max_qty="Maximum order quantity",
        rate="Your cost per 1,000 from SMB (hidden from buyers)",
        buyer_rate="What you charge buyers per 1,000 (shown to buyers)",
        link_hint="What to ask for in the link field (e.g. 'TikTok video URL')",
        extra_field_label="Extra input label if service needs it (e.g. 'Usernames (1 per line)')",
        extra_field_param="API parameter name for the extra field (e.g. 'usernames', 'comments')",
    )
    @app_commands.choices(platform=[app_commands.Choice(name=p, value=p) for p in PLATFORMS])
    @app_commands.autocomplete(category=category_autocomplete)
    async def smbaddservice(self, interaction: discord.Interaction, platform: str,
                            category: str, service_id: int, name: str,
                            min_qty: int, max_qty: int, rate: str,
                            buyer_rate: str = "", link_hint: str = "",
                            extra_field_label: str = "", extra_field_param: str = ""):
        if await self._check(interaction):
            return
        for label_name, val in [("rate", rate), *([ ("buyer_rate", buyer_rate)] if buyer_rate else [])]:
            try:
                float(val)
            except ValueError:
                return await interaction.response.send_message(embed=error_embed(f"`{label_name}` must be a number."), ephemeral=True)
        await db.smb_add_service(platform, category, service_id, name, min_qty, max_qty, rate,
                                  link_hint, buyer_rate, extra_field_label, extra_field_param)
        buyer_line = f"\nBuyer rate: **${buyer_rate}/1k**" if buyer_rate else "\nBuyer rate: *not set*"
        hint_line = f"\nLink hint: *{link_hint}*" if link_hint else ""
        extra_line = f"\nExtra field: **{extra_field_label}** (param: `{extra_field_param}`)" if extra_field_label else ""
        embed = success_embed(
            f"**{name}** added to **{platform}** > {category}\n{DIVIDER_SHORT}\n"
            f"Service ID: `{service_id}`\nYour cost: **${rate}/1k**{buyer_line}\n"
            f"Min: {min_qty:,}  •  Max: {max_qty:,}{hint_line}{extra_line}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── EDIT SERVICE ──────────────────────────────────────────────────────────

    @app_commands.command(name="smbeditservice", description="Edit any field on an existing SMB service (Admin)")
    @app_commands.describe(
        service_id="SMB service ID to edit",
        name="New display name",
        rate="New cost per 1,000 (your SMB cost)",
        buyer_rate="New buyer rate per 1,000",
        min_qty="New minimum quantity",
        max_qty="New maximum quantity",
        link_hint="New link hint text",
        extra_field_label="New extra field label",
        extra_field_param="New extra field API param (e.g. 'usernames', 'comments')",
        category="Move to a different category",
        platform="Move to a different platform",
        enabled="Enable or disable",
    )
    @app_commands.choices(
        platform=[app_commands.Choice(name=p, value=p) for p in PLATFORMS],
        enabled=[
            app_commands.Choice(name="Enable", value="enable"),
            app_commands.Choice(name="Disable", value="disable"),
        ],
    )
    async def smbeditservice(self, interaction: discord.Interaction, service_id: int,
                             name: str = None, rate: str = None, buyer_rate: str = None,
                             min_qty: int = None, max_qty: int = None, link_hint: str = None,
                             extra_field_label: str = None, extra_field_param: str = None,
                             category: str = None, platform: str = None, enabled: str = None):
        if await self._check(interaction):
            return
        service = await db.smb_get_service(service_id)
        if not service:
            return await interaction.response.send_message(embed=error_embed(f"No service with ID `{service_id}`."), ephemeral=True)
        for label_name, val in [("rate", rate), ("buyer_rate", buyer_rate)]:
            if val is not None:
                try:
                    float(val)
                except ValueError:
                    return await interaction.response.send_message(embed=error_embed(f"`{label_name}` must be a number."), ephemeral=True)
        updates = {}
        if name is not None: updates["name"] = name
        if rate is not None: updates["rate"] = rate
        if buyer_rate is not None: updates["buyer_rate"] = buyer_rate
        if min_qty is not None: updates["min_qty"] = min_qty
        if max_qty is not None: updates["max_qty"] = max_qty
        if link_hint is not None: updates["link_hint"] = link_hint
        if extra_field_label is not None: updates["extra_field_label"] = extra_field_label
        if extra_field_param is not None: updates["extra_field_param"] = extra_field_param
        if category is not None: updates["category"] = category
        if platform is not None: updates["platform"] = platform
        if enabled is not None: updates["enabled"] = 1 if enabled == "enable" else 0
        if not updates:
            return await interaction.response.send_message(embed=error_embed("No fields to update — provide at least one value."), ephemeral=True)
        await db.smb_edit_service(service_id, **updates)
        updated = await db.smb_get_service(service_id)
        changed = "\n".join(f"> **{k}:** {v}" for k, v in updates.items())
        embed = success_embed(f"**{updated['name']}** (ID: `{service_id}`) updated.\n{DIVIDER_SHORT}\n{changed}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── PLATFORM NOTES ────────────────────────────────────────────────────────

    @app_commands.command(name="smbplatformnotes", description="Set instructions shown to buyers when they select a platform (Admin)")
    @app_commands.describe(platform="Platform to set notes for", notes="Instructions shown to buyers when they pick this platform")
    @app_commands.choices(platform=[app_commands.Choice(name=p, value=p) for p in PLATFORMS])
    async def smbplatformnotes(self, interaction: discord.Interaction, platform: str, notes: str):
        if await self._check(interaction):
            return
        await db.smb_set_platform_notes(platform, notes)
        embed = success_embed(f"Notes set for **{platform}**\n{DIVIDER_SHORT}\n*{notes}*")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── REMOVE SERVICE ────────────────────────────────────────────────────────

    @app_commands.command(name="smbremoveservice", description="Remove an SMB service by service ID (Admin)")
    @app_commands.describe(service_id="The SMB service ID to remove")
    async def smbremoveservice(self, interaction: discord.Interaction, service_id: int):
        if await self._check(interaction):
            return
        service = await db.smb_get_service(service_id)
        if not service:
            return await interaction.response.send_message(embed=error_embed(f"No service with ID `{service_id}`."), ephemeral=True)
        await db.smb_remove_service(service_id)
        await interaction.response.send_message(embed=success_embed(f"**{service['name']}** (ID: `{service_id}`) removed."), ephemeral=True)

    # ── LIST SERVICES ─────────────────────────────────────────────────────────

    @app_commands.command(name="smbservices", description="List all configured SMB services (Admin)")
    @app_commands.describe(platform="Filter by platform (optional)")
    @app_commands.choices(platform=[app_commands.Choice(name="All platforms", value="all")] + [app_commands.Choice(name=p, value=p) for p in PLATFORMS])
    async def smbservices(self, interaction: discord.Interaction, platform: str = "all"):
        if await self._check(interaction):
            return
        all_services = await db.smb_get_all_services()
        if platform != "all":
            all_services = [s for s in all_services if s["platform"] == platform]
        if not all_services:
            return await interaction.response.send_message(embed=mango_embed("SMB Services", "No services configured yet."), ephemeral=True)
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
            buyer = f" > ${s['buyer_rate']}/1k" if s.get("buyer_rate") else ""
            hint = f"  •  *{s['link_hint']}*" if s.get("link_hint") else ""
            extra = f"  •  +{s['extra_field_label']}" if s.get("extra_field_label") else ""
            lines.append(f"> {status} `{s['service_id']}`  **{s['name']}**  -- ${s['rate']}/1k{buyer}  •  {s['min_qty']:,}-{s['max_qty']:,}{hint}{extra}")
        chunks = paginate_items(lines, 15)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            embed = mango_embed(f"SMB Services -- Page {i}/{len(chunks)}", "\n".join(chunk))
            embed.set_footer(text=f"🥭 {len(all_services)} total  •  Page {i}/{len(chunks)}")
            pages.append(embed)
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True)

    # ── SMB BALANCE CHECK ─────────────────────────────────────────────────────

    @app_commands.command(name="smbbalance", description="Check SMB API balance or a user's SMB balance (Admin)")
    @app_commands.describe(user="Check a specific user's SMB balance (optional)")
    async def smbbalance(self, interaction: discord.Interaction, user: discord.User = None):
        if await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if user:
            await db.ensure_user(str(user.id), user.name)
            bal = await db.smb_get_user_balance(str(user.id))
            orders = await db.smb_get_user_orders(str(user.id))
            embed = mango_embed(f"{user.name}'s SMB Balance", f"**${bal:.2f}**\n{DIVIDER_SHORT}\n{len(orders)} total order(s)")
            embed.set_thumbnail(url=user.display_avatar.url)
            return await interaction.followup.send(embed=embed)
        if not cfg.SMB_API_KEY:
            return await interaction.followup.send(embed=error_embed("SMB API key not set in Railway."))
        try:
            result = await smb_api.get_balance()
            balance = result.get("balance", "?")
            currency = result.get("currency", "USD")
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed to fetch balance:\n{e}"))
        embed = mango_embed("SMB API Balance", f"**${balance}** {currency}\n{DIVIDER_SHORT}\nYour SMBPanel account balance.")
        await interaction.followup.send(embed=embed)


# ── Seller orders view (shown in /smbsellers) ─────────────────────────────────

class SmbSellerView(discord.ui.View):
    def __init__(self, author_id, sellers):
        super().__init__(timeout=120)
        self.author_id = author_id
        if sellers:
            options = [
                discord.SelectOption(label=s["username"][:100], value=s["discord_id"], description=f"ID: {s['discord_id']}")
                for s in sellers[:25]
            ]
            select = discord.ui.Select(placeholder="View a seller's orders...", options=options)
            select.callback = self.on_seller_select
            self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    async def on_seller_select(self, interaction: discord.Interaction):
        discord_id = interaction.data["values"][0]
        orders = await db.smb_get_user_orders(discord_id)
        user = await db.get_user(discord_id)
        smb_bal = await db.smb_get_user_balance(discord_id)
        username = user["username"] if user else discord_id
        if not orders:
            return await interaction.response.send_message(embed=mango_embed(f"{username}'s Orders", "No orders yet."), ephemeral=True)
        desc = f"SMB Balance: **${smb_bal:.2f}**\n{DIVIDER}\n\n"
        for o in orders[:15]:
            desc += (
                f"**#{o['smb_order_id']}** -- {o['service_name'][:40]}\n"
                f"> {o['platform']}  •  {o['quantity']:,}  •  ${o['buyer_cost']:.2f}  •  {o['status']}\n"
                f"> {o['link'][:60]}\n"
                f"> {o['created_at'][:16]}\n\n"
            )
        embed = mango_embed(f"{username}'s Orders ({len(orders)} total)", desc)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Toggle commands (separate cog to avoid command limit) ─────────────────────

def _toggle_choices():
    return [
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ]


class SmbToggleCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def _check(self, interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(embed=server_only_error(), ephemeral=True)
            return True
        if not is_owner(interaction):
            await interaction.response.send_message(embed=error_embed("Only the bot owner can use this command."), ephemeral=True)
            return True
        return False

    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            platform = (interaction.namespace.platform or "") if interaction.namespace else ""
            categories = await db.smb_get_categories_for_platform(platform) if platform else []
            return [
                app_commands.Choice(name=c[:100], value=c[:100])
                for c in categories
                if current.lower() in c.lower()
            ][:25]
        except Exception:
            return []

    @app_commands.command(name="smbtoggle", description="Enable or disable a single SMB service (Admin)")
    @app_commands.describe(service_id="The SMB service ID", status="Enable or disable")
    @app_commands.choices(status=_toggle_choices())
    async def smbtoggle(self, interaction: discord.Interaction, service_id: int, status: str):
        if await self._check(interaction):
            return
        service = await db.smb_get_service(service_id)
        if not service:
            return await interaction.response.send_message(embed=error_embed(f"No service with ID `{service_id}`."), ephemeral=True)
        await db.smb_set_enabled(service_id, status == "enable")
        emoji = "🟢" if status == "enable" else "🔴"
        await interaction.response.send_message(embed=success_embed(f"{emoji} **{service['name']}** {status}d."), ephemeral=True)

    @app_commands.command(name="smbtogglecategory", description="Enable or disable all services in a category (Admin)")
    @app_commands.describe(platform="Platform", category="Category to toggle", status="Enable or disable")
    @app_commands.choices(
        platform=[app_commands.Choice(name=p, value=p) for p in PLATFORMS],
        status=_toggle_choices(),
    )
    @app_commands.autocomplete(category=category_autocomplete)
    async def smbtogglecategory(self, interaction: discord.Interaction, platform: str, category: str, status: str):
        if await self._check(interaction):
            return
        count = await db.smb_set_category_enabled(platform, category, status == "enable")
        if count == 0:
            return await interaction.response.send_message(embed=error_embed(f"No services found in **{platform}** > **{category}**."), ephemeral=True)
        emoji = "🟢" if status == "enable" else "🔴"
        await interaction.response.send_message(
            embed=success_embed(f"{emoji} **{count}** service(s) in **{platform}** > **{category}** {status}d."),
            ephemeral=True
        )

    @app_commands.command(name="smbtoggleplatform", description="Enable or disable ALL services for an entire platform (Admin)")
    @app_commands.describe(platform="Platform to toggle", status="Enable or disable")
    @app_commands.choices(
        platform=[app_commands.Choice(name=p, value=p) for p in PLATFORMS],
        status=_toggle_choices(),
    )
    async def smbtoggleplatform(self, interaction: discord.Interaction, platform: str, status: str):
        if await self._check(interaction):
            return
        count = await db.smb_set_platform_enabled(platform, status == "enable")
        if count == 0:
            return await interaction.response.send_message(embed=error_embed(f"No services found for **{platform}**."), ephemeral=True)
        emoji = "🟢" if status == "enable" else "🔴"
        await interaction.response.send_message(
            embed=success_embed(f"{emoji} All **{count}** **{platform}** service(s) {status}d."),
            ephemeral=True
        )


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(SmbAdmin(bot), guild=guild)
    await bot.add_cog(SmbToggleCommands(bot), guild=guild)



