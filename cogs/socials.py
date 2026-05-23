# cogs/socials.py — Interactive social media order panel.
# Owner-only for now. /smbmaintenance controls if it's visible to buyers later.

import discord
from discord import app_commands
from discord.ext import commands
import database as db
import smb as smb_api
import config as cfg
from helpers import mango_embed, error_embed, success_embed, is_owner, DIVIDER, DIVIDER_SHORT

PLATFORM_EMOJI = {
    "Instagram": "📸", "TikTok": "🎵", "YouTube": "▶️", "Facebook": "👥",
    "Telegram": "✈️", "Twitter": "🐦", "Twitch": "💜", "Kick": "🟢",
    "WhatsApp": "💬", "Snapchat": "👻", "Threads": "🧵", "Reddit": "🤖",
    "LinkedIn": "💼", "Spotify": "🎶", "Discord": "🎮",
}


def platform_label(name: str) -> str:
    return f"{PLATFORM_EMOJI.get(name, '•')}  {name}"


def make_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Colour(int(cfg.EMBED_COLOR, 16)))
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


def smb_maintenance_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔧  Socials Panel — Unavailable",
        description="The socials panel is currently unavailable.\n\nPlease check back later.",
        color=discord.Colour.from_str("#FFA500"),
    )
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Platform Select
# ═══════════════════════════════════════════════════════════════════════════════

class PlatformView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self):
        platforms = await db.smb_get_platforms()
        if not platforms:
            return False
        options = [
            discord.SelectOption(label=p, value=p, emoji=PLATFORM_EMOJI.get(p, "•"))
            for p in platforms[:25]
        ]
        select = discord.ui.Select(placeholder="🌐  Select a platform...", options=options)
        select.callback = self.on_platform_select
        self.add_item(select)
        return True

    async def on_platform_select(self, interaction: discord.Interaction):
        platform = interaction.data["values"][0]
        categories = await db.smb_get_categories(platform)
        if not categories:
            await interaction.response.edit_message(
                embed=make_embed(f"{platform_label(platform)}", "No services configured for this platform yet."),
                view=BackView(self.author_id, PlatformView)
            )
            return
        view = CategoryView(self.author_id, platform)
        await view.build_select(categories)
        embed = make_embed(
            f"{platform_label(platform)}  — Select Category",
            f"{DIVIDER}\n\nChoose a **category** to browse services."
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Category Select
# ═══════════════════════════════════════════════════════════════════════════════

class CategoryView(discord.ui.View):
    def __init__(self, author_id: int, platform: str):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.platform = platform
        back = discord.ui.Button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self.go_back
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self, categories: list[str]):
        options = [discord.SelectOption(label=c[:100], value=c[:100]) for c in categories[:25]]
        select = discord.ui.Select(placeholder="📂  Select a category...", options=options, row=0)
        select.callback = self.on_category_select
        self.add_item(select)

    async def on_category_select(self, interaction: discord.Interaction):
        category = interaction.data["values"][0]
        services = await db.smb_get_services(self.platform, category)
        if not services:
            await interaction.response.edit_message(
                embed=make_embed(f"📂  {category}", "No services in this category yet."), view=self
            )
            return
        view = ServiceView(self.author_id, self.platform, category)
        await view.build_select(services)
        embed = make_embed(
            f"{platform_label(self.platform)}  ›  {category}",
            f"{DIVIDER}\n\nChoose a **service** to place an order."
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_back(self, interaction: discord.Interaction):
        view = PlatformView(self.author_id)
        await view.build_select()
        embed = make_embed("🌐  Socials Panel", f"{DIVIDER}\n\nSelect a **platform** to get started.")
        await interaction.response.edit_message(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Service Select
# ═══════════════════════════════════════════════════════════════════════════════

class ServiceView(discord.ui.View):
    def __init__(self, author_id: int, platform: str, category: str):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.platform = platform
        self.category = category
        back = discord.ui.Button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self.go_back
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self, services: list[dict]):
        options = [
            discord.SelectOption(
                label=s["name"][:100],
                value=str(s["service_id"]),
                description=f"${s['rate']}/1k  •  Min: {s['min_qty']}  •  Max: {s['max_qty']}"[:100],
            )
            for s in services[:25]
        ]
        select = discord.ui.Select(placeholder="🛒  Select a service...", options=options, row=0)
        select.callback = self.on_service_select
        self.add_item(select)

    async def on_service_select(self, interaction: discord.Interaction):
        service_id = int(interaction.data["values"][0])
        service = await db.smb_get_service(service_id)
        if not service:
            await interaction.response.send_message(embed=error_embed("Service not found."), ephemeral=True)
            return
        view = OrderDetailView(self.author_id, self.platform, self.category, service)
        embed = make_embed(
            f"🛒  {service['name']}",
            f"{platform_label(self.platform)}  ›  {self.category}\n{DIVIDER}\n\n"
            f"**Service ID:** `{service['service_id']}`\n"
            f"**Rate:** ${service['rate']} per 1,000\n"
            f"**Min quantity:** {service['min_qty']:,}\n"
            f"**Max quantity:** {service['max_qty']:,}\n\n"
            f"Click **Place Order** to continue."
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_back(self, interaction: discord.Interaction):
        categories = await db.smb_get_categories(self.platform)
        view = CategoryView(self.author_id, self.platform)
        await view.build_select(categories)
        embed = make_embed(
            f"{platform_label(self.platform)}  — Select Category",
            f"{DIVIDER}\n\nChoose a **category** to browse services."
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Order Detail View
# ═══════════════════════════════════════════════════════════════════════════════

class OrderDetailView(discord.ui.View):
    def __init__(self, author_id: int, platform: str, category: str, service: dict):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.platform = platform
        self.category = category
        self.service = service

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        services = await db.smb_get_services(self.platform, self.category)
        view = ServiceView(self.author_id, self.platform, self.category)
        await view.build_select(services)
        embed = make_embed(
            f"{platform_label(self.platform)}  ›  {self.category}",
            f"{DIVIDER}\n\nChoose a **service** to place an order."
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="🛒 Place Order", style=discord.ButtonStyle.success)
    async def place_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OrderModal(self.service))


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Order Modal
# ═══════════════════════════════════════════════════════════════════════════════

class OrderModal(discord.ui.Modal):
    def __init__(self, service: dict):
        super().__init__(title=f"Order — {service['name'][:40]}")
        self.service = service
        self.link_input = discord.ui.TextInput(
            label="Link / URL",
            placeholder="e.g. https://instagram.com/yourusername",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
        )
        self.quantity_input = discord.ui.TextInput(
            label=f"Quantity (Min: {service['min_qty']}  •  Max: {service['max_qty']})",
            placeholder=f"Enter a number between {service['min_qty']} and {service['max_qty']}",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
        )
        self.add_item(self.link_input)
        self.add_item(self.quantity_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            quantity = int(self.quantity_input.value.replace(",", "").strip())
        except ValueError:
            return await interaction.response.send_message(
                embed=error_embed("Quantity must be a whole number."), ephemeral=True
            )

        s = self.service
        if quantity < s["min_qty"] or quantity > s["max_qty"]:
            return await interaction.response.send_message(
                embed=error_embed(f"Quantity must be between **{s['min_qty']:,}** and **{s['max_qty']:,}**."),
                ephemeral=True,
            )

        link = self.link_input.value.strip()
        estimated_cost = (quantity / 1000) * float(s["rate"])

        balance_before = "N/A"
        balance_after = "N/A"
        try:
            bal = await smb_api.get_balance()
            current_bal = float(bal.get("balance", 0))
            currency = bal.get("currency", "USD")
            balance_before = f"${current_bal:.5f} {currency}"
            balance_after = f"${max(0, current_bal - estimated_cost):.5f} {currency}"
        except Exception:
            pass

        embed = make_embed(
            "📋  Order Preview",
            f"**{s['name']}**\n{DIVIDER}\n\n"
            f"**Link:** {link}\n"
            f"**Quantity:** {quantity:,}\n"
            f"**Rate:** ${s['rate']} per 1,000\n"
            f"**Estimated cost:** ~${estimated_cost:.5f}\n\n"
            f"**Your balance:** {balance_before}\n"
            f"**After order:** {balance_after}\n\n"
            f"Confirm or cancel below."
        )
        view = ConfirmOrderView(interaction.user.id, s, link, quantity, estimated_cost)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Confirm / Cancel
# ═══════════════════════════════════════════════════════════════════════════════

class ConfirmOrderView(discord.ui.View):
    def __init__(self, author_id: int, service: dict, link: str, quantity: int, estimated_cost: float):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.service = service
        self.link = link
        self.quantity = quantity
        self.estimated_cost = estimated_cost

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="✅ Confirm Order", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            result = await smb_api.add_order(
                service_id=self.service["service_id"],
                link=self.link,
                quantity=self.quantity,
            )
        except Exception as e:
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=error_embed(f"Order failed:\n{e}"), view=None)
            return

        order_id = result.get("order", "?")

        balance_str = "N/A"
        try:
            bal = await smb_api.get_balance()
            balance_str = f"${float(bal['balance']):.5f} {bal.get('currency', 'USD')}"
        except Exception:
            pass

        embed = discord.Embed(
            title="✅  Order Placed",
            description=(
                f"**{self.service['name']}**\n{DIVIDER}\n\n"
                f"**Order ID:** `{order_id}`\n"
                f"**Link:** {self.link}\n"
                f"**Quantity:** {self.quantity:,}\n"
                f"**Est. cost:** ~${self.estimated_cost:.5f}\n\n"
                f"**New balance:** {balance_str}\n\n"
                f"Use the buttons below to monitor your order."
            ),
            color=discord.Colour.green(),
        )
        embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")

        order_id_int = int(order_id) if str(order_id).isdigit() else 0
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            embed=embed,
            view=OrderStatusView(interaction.user.id, order_id_int),
        )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=make_embed("❌  Cancelled", "No order was placed."), view=None)


# ═══════════════════════════════════════════════════════════════════════════════
# POST-ORDER — Check Status / Cancel Order
# ═══════════════════════════════════════════════════════════════════════════════

class OrderStatusView(discord.ui.View):
    def __init__(self, author_id: int, order_id: int):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.order_id = order_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="🔄 Check Status", style=discord.ButtonStyle.primary)
    async def check_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            status = await smb_api.get_order_status(self.order_id)
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Failed to get status: {e}"), ephemeral=True)

        order_status = status.get("status", "Unknown")
        color_map = {
            "Completed": discord.Colour.green(), "In progress": discord.Colour.orange(),
            "Partial": discord.Colour.yellow(), "Processing": discord.Colour.blue(),
            "Canceled": discord.Colour.red(),
        }
        embed = discord.Embed(
            title=f"📊  Order #{self.order_id} — {order_status}",
            description=(
                f"**Status:** {order_status}\n"
                f"**Start count:** {status.get('start_count', '?')}\n"
                f"**Remaining:** {status.get('remains', '?')}\n"
                f"**Charge:** {status.get('charge', '?')} {status.get('currency', 'USD')}"
            ),
            color=color_map.get(order_status, discord.Colour.greyple()),
        )
        embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🚫 Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await smb_api.cancel_orders([self.order_id])
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Cancel failed: {e}"), ephemeral=True)
        await interaction.followup.send(
            embed=success_embed(f"Cancellation request sent for order **#{self.order_id}**."), ephemeral=True
        )


class BackView(discord.ui.View):
    def __init__(self, author_id, target_class):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target_class = target_class

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.target_class == PlatformView:
            view = PlatformView(self.author_id)
            await view.build_select()
            embed = make_embed("🌐  Socials Panel", f"{DIVIDER}\n\nSelect a **platform** to get started.")
            await interaction.response.edit_message(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════════════════════
# COG
# ═══════════════════════════════════════════════════════════════════════════════

class Socials(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="socials", description="Open the social media order panel")
    async def socials(self, interaction: discord.Interaction):
        # Check SMB maintenance — blocks everyone except the owner
        smb_maint = (await db.get_setting("smb_maintenance", "0")) == "1"

        if not is_owner(interaction):
            if smb_maint:
                return await interaction.response.send_message(embed=smb_maintenance_embed(), ephemeral=True)
            # Future: when opened to buyers, add seller check here
            return await interaction.response.send_message(
                embed=error_embed("🔒 Only the bot owner can use this command."), ephemeral=True
            )

        platforms = await db.smb_get_platforms()
        if not platforms:
            return await interaction.response.send_message(
                embed=make_embed(
                    "🌐  Socials Panel",
                    "No services configured yet.\n\nUse `/smbaddservice` to add your first service."
                ),
                ephemeral=True,
            )

        view = PlatformView(interaction.user.id)
        await view.build_select()
        embed = make_embed("🌐  Socials Panel", f"{DIVIDER}\n\nSelect a **platform** to get started.")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(Socials(bot), guild=guild)
