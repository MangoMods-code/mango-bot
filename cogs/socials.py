# cogs/socials.py — Interactive social media order panel.
# Global command — works in DMs and server. Sellers + owner only.

import discord
from discord import app_commands
from discord.ext import commands
import database as db
import smb as smb_api
import config as cfg
from helpers import (
    mango_embed, error_embed, success_embed, is_owner,
    DIVIDER, DIVIDER_SHORT, send_log, log_smb_order,
)

PLATFORM_EMOJI = {
    "Instagram": "📸", "TikTok": "🎵", "YouTube": "▶️", "Facebook": "👥",
    "Telegram": "✈️", "Twitter": "🐦", "Twitch": "💜", "Kick": "🟢",
    "WhatsApp": "💬", "Snapchat": "👻", "Threads": "🧵", "Reddit": "🤖",
    "LinkedIn": "💼", "Spotify": "🎶", "Discord": "🎮",
}


def platform_label(name):
    return f"{PLATFORM_EMOJI.get(name, '•')}  {name}"


def make_embed(title, description=""):
    embed = discord.Embed(title=title, description=description, color=discord.Colour(int(cfg.EMBED_COLOR, 16)))
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


def smb_maintenance_embed():
    embed = discord.Embed(
        title="🔧  Socials Panel — Unavailable",
        description="The socials panel is currently unavailable.\n\nPlease check back later.",
        color=discord.Colour.from_str("#FFA500"),
    )
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


def no_access_embed():
    return error_embed("🔒 You need **seller permissions** to use this command.\n\nContact the owner to get access.")


def price_display(service: dict, owner_mode: bool) -> str:
    if owner_mode:
        return f"${service['rate']} per 1,000 *(your cost)*"
    buyer_rate = (service.get("buyer_rate") or "").strip()
    return f"${buyer_rate} per 1,000" if buyer_rate else "Contact for pricing"


def service_dropdown_desc(service: dict, owner_mode: bool) -> str:
    if owner_mode:
        return f"${service['rate']}/1k  •  Min: {service['min_qty']}  •  Max: {service['max_qty']}"
    buyer_rate = (service.get("buyer_rate") or "").strip()
    rate_str = f"${buyer_rate}/1k" if buyer_rate else "See details"
    return f"{rate_str}  •  Min: {service['min_qty']}  •  Max: {service['max_qty']}"


# ── STEP 1: Platform ─────────────────────────────────────────────────────────

class PlatformView(discord.ui.View):
    def __init__(self, author_id, owner_mode=False):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.owner_mode = owner_mode

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self):
        platforms = await db.smb_get_platforms()
        if not platforms:
            return False
        options = [discord.SelectOption(label=p, value=p, emoji=PLATFORM_EMOJI.get(p, "•")) for p in platforms[:25]]
        select = discord.ui.Select(placeholder="🌐  Select a platform...", options=options)
        select.callback = self.on_platform_select
        self.add_item(select)
        return True

    async def on_platform_select(self, interaction):
        platform = interaction.data["values"][0]
        categories = await db.smb_get_categories(platform)
        if not categories:
            await interaction.response.edit_message(
                embed=make_embed(platform_label(platform), "No services configured for this platform yet."),
                view=BackView(self.author_id, PlatformView, self.owner_mode)
            )
            return
        view = CategoryView(self.author_id, platform, self.owner_mode)
        await view.build_select(categories)
        # Show platform notes if set
        notes = await db.smb_get_platform_notes(platform)
        notes_line = f"\n\n⚠️ **{platform} Note:**\n{notes}" if notes else ""
        await interaction.response.edit_message(
            embed=make_embed(f"{platform_label(platform)}  — Select Category", f"{DIVIDER}\n\nChoose a **category** to browse services.{notes_line}"),
            view=view
        )


# ── STEP 2: Category ─────────────────────────────────────────────────────────

class CategoryView(discord.ui.View):
    def __init__(self, author_id, platform, owner_mode=False):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.platform = platform
        self.owner_mode = owner_mode
        back = discord.ui.Button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self.go_back
        self.add_item(back)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self, categories):
        options = [discord.SelectOption(label=c[:100], value=c[:100]) for c in categories[:25]]
        select = discord.ui.Select(placeholder="📂  Select a category...", options=options, row=0)
        select.callback = self.on_category_select
        self.add_item(select)

    async def on_category_select(self, interaction):
        category = interaction.data["values"][0]
        services = await db.smb_get_services(self.platform, category)
        if not services:
            await interaction.response.edit_message(embed=make_embed(f"📂  {category}", "No services in this category yet."), view=self)
            return
        view = ServiceView(self.author_id, self.platform, category, self.owner_mode)
        await view.build_select(services)
        await interaction.response.edit_message(
            embed=make_embed(f"{platform_label(self.platform)}  ›  {category}", f"{DIVIDER}\n\nChoose a **service** to place an order."),
            view=view
        )

    async def go_back(self, interaction):
        view = PlatformView(self.author_id, self.owner_mode)
        await view.build_select()
        await interaction.response.edit_message(embed=make_embed("🌐  Socials Panel", f"{DIVIDER}\n\nSelect a **platform** to get started."), view=view)


# ── STEP 3: Service ──────────────────────────────────────────────────────────

class ServiceView(discord.ui.View):
    def __init__(self, author_id, platform, category, owner_mode=False):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.platform = platform
        self.category = category
        self.owner_mode = owner_mode
        back = discord.ui.Button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self.go_back
        self.add_item(back)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self, services):
        options = [
            discord.SelectOption(
                label=s["name"][:100],
                value=str(s["service_id"]),
                description=service_dropdown_desc(s, self.owner_mode)[:100],
            )
            for s in services[:25]
        ]
        select = discord.ui.Select(placeholder="🛒  Select a service...", options=options, row=0)
        select.callback = self.on_service_select
        self.add_item(select)

    async def on_service_select(self, interaction):
        service = await db.smb_get_service(int(interaction.data["values"][0]))
        if not service:
            return await interaction.response.send_message(embed=error_embed("Service not found."), ephemeral=True)
        view = OrderDetailView(self.author_id, self.platform, self.category, service, self.owner_mode)
        hint_line = f"\n**Link required:** {service['link_hint']}" if service.get("link_hint") else ""
        await interaction.response.edit_message(
            embed=make_embed(
                f"🛒  {service['name']}",
                f"{platform_label(self.platform)}  ›  {self.category}\n{DIVIDER}\n\n"
                f"**Rate:** {price_display(service, self.owner_mode)}\n"
                f"**Min quantity:** {service['min_qty']:,}\n"
                f"**Max quantity:** {service['max_qty']:,}"
                f"{hint_line}\n\n"
                f"Click **Place Order** to continue."
            ),
            view=view
        )

    async def go_back(self, interaction):
        categories = await db.smb_get_categories(self.platform)
        view = CategoryView(self.author_id, self.platform, self.owner_mode)
        await view.build_select(categories)
        await interaction.response.edit_message(
            embed=make_embed(f"{platform_label(self.platform)}  — Select Category", f"{DIVIDER}\n\nChoose a **category** to browse services."),
            view=view
        )


# ── STEP 4: Order Detail ─────────────────────────────────────────────────────

class OrderDetailView(discord.ui.View):
    def __init__(self, author_id, platform, category, service, owner_mode=False):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.platform = platform
        self.category = category
        self.service = service
        self.owner_mode = owner_mode

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def go_back(self, interaction, button):
        services = await db.smb_get_services(self.platform, self.category)
        view = ServiceView(self.author_id, self.platform, self.category, self.owner_mode)
        await view.build_select(services)
        await interaction.response.edit_message(
            embed=make_embed(f"{platform_label(self.platform)}  ›  {self.category}", f"{DIVIDER}\n\nChoose a **service** to place an order."),
            view=view
        )

    @discord.ui.button(label="🛒 Place Order", style=discord.ButtonStyle.success)
    async def place_order(self, interaction, button):
        await interaction.response.send_modal(OrderModal(self.service, self.owner_mode))


# ── STEP 5: Modal ────────────────────────────────────────────────────────────

class OrderModal(discord.ui.Modal):
    def __init__(self, service: dict, owner_mode: bool = False):
        super().__init__(title=f"Order — {service['name'][:35]}")
        self.service = service
        self.owner_mode = owner_mode

        link_hint = (service.get("link_hint") or "").strip()
        self.link_input = discord.ui.TextInput(
            label=(link_hint[:45] if link_hint else "Link / URL"),
            placeholder=(f"e.g. {link_hint}" if link_hint else "Paste the full URL here")[:100],
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

    async def on_submit(self, interaction):
        try:
            quantity = int(self.quantity_input.value.replace(",", "").strip())
        except ValueError:
            return await interaction.response.send_message(embed=error_embed("Quantity must be a whole number."), ephemeral=True)

        s = self.service
        if quantity < s["min_qty"] or quantity > s["max_qty"]:
            return await interaction.response.send_message(
                embed=error_embed(f"Quantity must be between **{s['min_qty']:,}** and **{s['max_qty']:,}**."), ephemeral=True
            )

        link = self.link_input.value.strip()

        if self.owner_mode:
            estimated_cost = (quantity / 1000) * float(s["rate"])
            cost_display = f"~${estimated_cost:.5f} *(your cost)*"
        else:
            buyer_rate = (s.get("buyer_rate") or "").strip()
            estimated_cost = (quantity / 1000) * float(buyer_rate if buyer_rate else s["rate"])
            cost_display = f"~${estimated_cost:.5f}" if buyer_rate else "Contact for pricing"

        balance_before_str = None
        balance_after_str = None
        if self.owner_mode:
            try:
                bal = await smb_api.get_balance()
                current_bal = float(bal.get("balance", 0))
                currency = bal.get("currency", "USD")
                balance_before_str = f"${current_bal:.5f} {currency}"
                balance_after_str = f"${max(0, current_bal - estimated_cost):.5f} {currency}"
            except Exception:
                pass

        desc = (
            f"**{s['name']}**\n{DIVIDER}\n\n"
            f"**Link:** {link}\n"
            f"**Quantity:** {quantity:,}\n"
            f"**Rate:** {price_display(s, self.owner_mode)}\n"
            f"**Estimated cost:** {cost_display}\n"
        )
        if self.owner_mode and balance_before_str:
            desc += f"\n**Your SMB balance:** {balance_before_str}\n**After order:** {balance_after_str}\n"
        desc += "\nConfirm or cancel below."

        view = ConfirmOrderView(interaction.user, s, link, quantity, estimated_cost, self.owner_mode, balance_before_str)
        await interaction.response.send_message(embed=make_embed("📋  Order Preview", desc), view=view, ephemeral=True)


# ── STEP 6: Confirm ──────────────────────────────────────────────────────────

class ConfirmOrderView(discord.ui.View):
    def __init__(self, user, service, link, quantity, estimated_cost, owner_mode, smb_balance_before):
        super().__init__(timeout=60)
        self.user = user
        self.service = service
        self.link = link
        self.quantity = quantity
        self.estimated_cost = estimated_cost
        self.owner_mode = owner_mode
        self.smb_balance_before = smb_balance_before

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    @discord.ui.button(label="✅ Confirm Order", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        await interaction.response.defer()

        # Deduct SMB balance from buyer (non-owner only)
        if not self.owner_mode:
            current_bal = await db.smb_get_user_balance(str(self.user.id))
            if current_bal < self.estimated_cost:
                return await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    embed=error_embed(f"Insufficient SMB balance.\n\nNeed: **${self.estimated_cost:.2f}**  •  Have: **${current_bal:.2f}**"),
                    view=None
                )
            await db.smb_subtract_user_balance(str(self.user.id), self.estimated_cost)

        try:
            result = await smb_api.add_order(service_id=self.service["service_id"], link=self.link, quantity=self.quantity)
        except Exception as e:
            # Refund buyer if API call failed
            if not self.owner_mode:
                await db.smb_add_user_balance(str(self.user.id), self.estimated_cost)
            return await interaction.followup.edit_message(message_id=interaction.message.id, embed=error_embed(f"Order failed:\n{e}"), view=None)

        order_id = result.get("order", "?")
        smb_balance_after = None
        new_balance_str = None
        try:
            bal = await smb_api.get_balance()
            smb_balance_after = f"${float(bal['balance']):.5f} {bal.get('currency', 'USD')}"
            new_balance_str = smb_balance_after
        except Exception:
            pass

        # Record order in database
        actual_cost = (self.quantity / 1000) * float(self.service["rate"])
        await db.smb_record_order(
            user_id=str(self.user.id),
            smb_order_id=str(order_id),
            service_id=self.service["service_id"],
            service_name=self.service["name"],
            platform=self.service["platform"],
            link=self.link,
            quantity=self.quantity,
            buyer_cost=self.estimated_cost,
            actual_cost=actual_cost,
        )

        buyer_new_bal = await db.smb_get_user_balance(str(self.user.id)) if not self.owner_mode else None

        desc = (
            f"**{self.service['name']}**\n{DIVIDER}\n\n"
            f"**Order ID:** `{order_id}`\n"
            f"**Link:** {self.link}\n"
            f"**Quantity:** {self.quantity:,}\n"
            f"**Cost:** ${self.estimated_cost:.2f}\n"
        )
        if self.owner_mode and new_balance_str:
            desc += f"\n**New SMB API balance:** {new_balance_str}\n"
        elif buyer_new_bal is not None:
            desc += f"\n**Your SMB balance:** **${buyer_new_bal:.2f}**\n"
        desc += "\nUse the buttons below to monitor your order."

        embed = discord.Embed(title="✅  Order Placed", description=desc, color=discord.Colour.green())
        embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
        order_id_int = int(order_id) if str(order_id).isdigit() else 0
        await interaction.followup.edit_message(
            message_id=interaction.message.id, embed=embed,
            view=OrderStatusView(self.user.id, order_id_int)
        )
        await send_log(
            interaction.client,
            log_smb_order(
                user=self.user,
                service_name=self.service["name"],
                platform=self.service["platform"],
                link=self.link,
                quantity=self.quantity,
                order_id=order_id,
                estimated_cost=self.estimated_cost,
                smb_balance_before=self.smb_balance_before,
                smb_balance_after=smb_balance_after,
            )
        )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(embed=make_embed("❌  Cancelled", "No order was placed."), view=None)


# ── POST-ORDER ────────────────────────────────────────────────────────────────

class OrderStatusView(discord.ui.View):
    def __init__(self, author_id, order_id):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.order_id = order_id

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    @discord.ui.button(label="🔄 Check Status", style=discord.ButtonStyle.primary)
    async def check_status(self, interaction, button):
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
    async def cancel_order(self, interaction, button):
        await interaction.response.defer()
        try:
            await smb_api.cancel_orders([self.order_id])
        except Exception as e:
            return await interaction.followup.send(embed=error_embed(f"Cancel failed: {e}"), ephemeral=True)
        await interaction.followup.send(embed=success_embed(f"Cancellation request sent for order **#{self.order_id}**."), ephemeral=True)


class BackView(discord.ui.View):
    def __init__(self, author_id, target_class, owner_mode=False):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target_class = target_class
        self.owner_mode = owner_mode

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def go_back(self, interaction, button):
        if self.target_class == PlatformView:
            view = PlatformView(self.author_id, self.owner_mode)
            await view.build_select()
            await interaction.response.edit_message(embed=make_embed("🌐  Socials Panel", f"{DIVIDER}\n\nSelect a **platform** to get started."), view=view)


# ── COG ───────────────────────────────────────────────────────────────────────

class Socials(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="socials", description="Open the social media order panel")
    async def socials(self, interaction: discord.Interaction):
        owner_mode = is_owner(interaction)

        # Check SMB maintenance — blocks everyone except owner
        smb_maint = (await db.get_setting("smb_maintenance", "0")) == "1"
        if smb_maint and not owner_mode:
            return await interaction.response.send_message(embed=smb_maintenance_embed(), ephemeral=True)

        # Must be seller or owner
        if not owner_mode:
            user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
            if not user["is_seller"]:
                return await interaction.response.send_message(embed=no_access_embed(), ephemeral=True)

        platforms = await db.smb_get_platforms()
        if not platforms:
            return await interaction.response.send_message(
                embed=make_embed("🌐  Socials Panel", "No services configured yet.\n\nUse `/smbaddservice` to add your first service."),
                ephemeral=True,
            )

        view = PlatformView(interaction.user.id, owner_mode=owner_mode)
        await view.build_select()
        await interaction.response.send_message(
            embed=make_embed("🌐  Socials Panel", f"{DIVIDER}\n\nSelect a **platform** to get started."),
            view=view, ephemeral=True
        )


async def setup(bot):
    # Global — no guild restriction so it appears in DMs for sellers
    await bot.add_cog(Socials(bot))






