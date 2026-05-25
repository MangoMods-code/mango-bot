# cogs/smb_owner.py — Interactive SMB service management panel for the owner.
# /smbowner opens a browse panel: Platform > Category > Service > Edit

import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
from helpers import is_owner, mango_embed, error_embed, success_embed, DIVIDER, DIVIDER_SHORT

PLATFORM_EMOJI = {
    "Instagram": "📸", "TikTok": "🎵", "YouTube": "▶️", "Facebook": "👥",
    "Telegram": "✈️", "Twitter": "🐦", "Twitch": "💜", "Kick": "🟢",
    "WhatsApp": "💬", "Snapchat": "👻", "Threads": "🧵", "Reddit": "🤖",
    "LinkedIn": "💼", "Spotify": "🎶", "Discord": "🎮",
}


def make_embed(title, description=""):
    embed = discord.Embed(title=title, description=description, color=discord.Colour(int(cfg.EMBED_COLOR, 16)))
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


def service_detail_embed(service: dict) -> discord.Embed:
    enabled = "🟢 Enabled" if service["enabled"] else "🔴 Disabled"
    buyer_rate = f"${service['buyer_rate']}/1k" if service.get("buyer_rate") else "*not set*"
    link_hint = service.get("link_hint") or "*not set*"
    extra = f"{service['extra_field_label']} (param: `{service['extra_field_param']}`)" if service.get("extra_field_label") else "*none*"
    category = service.get("category", "?")

    desc = (
        f"**Platform:** {service['platform']}\n"
        f"**Category:** {category}\n"
        f"**Service ID:** `{service['service_id']}`\n"
        f"{DIVIDER_SHORT}\n"
        f"**Status:** {enabled}\n"
        f"**Your cost:** ${service['rate']}/1k\n"
        f"**Buyer rate:** {buyer_rate}\n"
        f"**Min qty:** {service['min_qty']:,}\n"
        f"**Max qty:** {service['max_qty']:,}\n"
        f"**Link hint:** {link_hint}\n"
        f"**Extra field:** {extra}\n"
    )
    embed = discord.Embed(
        title=f"🛠️  {service['name'][:80]}",
        description=desc,
        color=discord.Colour.green() if service["enabled"] else discord.Colour.red(),
    )
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


# ── STEP 1: Platform ─────────────────────────────────────────────────────────

class OwnerPlatformView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def build_select(self):
        platforms = await db.smb_get_platforms()
        # Also include platforms with disabled services
        all_cats = await db.smb_get_all_categories()
        all_platforms = sorted(set(c["platform"] for c in all_cats))
        if not all_platforms:
            return False
        options = []
        for p in all_platforms[:25]:
            emoji = PLATFORM_EMOJI.get(p, "•")
            options.append(discord.SelectOption(label=p, value=p, emoji=emoji))
        select = discord.ui.Select(placeholder="Select a platform to browse...", options=options)
        select.callback = self.on_platform_select
        self.add_item(select)
        return True

    async def on_platform_select(self, interaction):
        platform = interaction.data["values"][0]
        # Get all categories (including disabled services)
        all_services = await db.smb_get_all_services()
        categories = sorted(set(s["category"] for s in all_services if s["platform"] == platform))
        if not categories:
            await interaction.response.edit_message(
                embed=make_embed(f"{platform} — No services found"),
                view=self
            )
            return
        view = OwnerCategoryView(self.author_id, platform, categories)
        embed = make_embed(
            f"{PLATFORM_EMOJI.get(platform, '')} {platform} — Select Category",
            f"{DIVIDER}\n\n**{len(categories)}** categories  •  Pick one to browse services."
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ── STEP 2: Category ─────────────────────────────────────────────────────────

class OwnerCategoryView(discord.ui.View):
    def __init__(self, author_id: int, platform: str, categories: list):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.platform = platform
        self.categories = categories
        self.page = 0
        self._build_select()

    def _build_select(self):
        self.clear_items()
        # Paginate categories (25 per page)
        start = self.page * 24
        chunk = self.categories[start:start + 24]
        options = [discord.SelectOption(label=c[:100], value=c[:100]) for c in chunk]
        select = discord.ui.Select(placeholder=f"Select a category... (page {self.page + 1})", options=options, row=0)
        select.callback = self.on_category_select
        self.add_item(select)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        if len(self.categories) > 24:
            if self.page > 0:
                prev_btn = discord.ui.Button(label="Prev Page", style=discord.ButtonStyle.secondary, row=1)
                prev_btn.callback = self.prev_page
                self.add_item(prev_btn)
            if start + 24 < len(self.categories):
                next_btn = discord.ui.Button(label="Next Page", style=discord.ButtonStyle.secondary, row=1)
                next_btn.callback = self.next_page
                self.add_item(next_btn)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def on_category_select(self, interaction):
        category = interaction.data["values"][0]
        all_services = await db.smb_get_all_services()
        services = [s for s in all_services if s["platform"] == self.platform and s["category"] == category]
        if not services:
            await interaction.response.edit_message(embed=make_embed("No services in this category."), view=self)
            return
        view = OwnerServiceView(self.author_id, self.platform, category, services)
        enabled_count = sum(1 for s in services if s["enabled"])
        embed = make_embed(
            f"{self.platform} > {category[:50]}",
            f"{DIVIDER}\n\n**{len(services)}** services  •  🟢 {enabled_count} enabled  •  🔴 {len(services) - enabled_count} disabled\n\nSelect a service to view and edit."
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_back(self, interaction):
        view = OwnerPlatformView(self.author_id)
        await view.build_select()
        embed = make_embed("SMB Owner Panel", f"{DIVIDER}\n\nSelect a platform to browse.")
        await interaction.response.edit_message(embed=embed, view=view)

    async def prev_page(self, interaction):
        self.page -= 1
        self._build_select()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction):
        self.page += 1
        self._build_select()
        await interaction.response.edit_message(view=self)


# ── STEP 3: Service ──────────────────────────────────────────────────────────

class OwnerServiceView(discord.ui.View):
    def __init__(self, author_id: int, platform: str, category: str, services: list):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.platform = platform
        self.category = category
        self.services = services
        self.page = 0
        self._build_select()

    def _build_select(self):
        self.clear_items()
        start = self.page * 24
        chunk = self.services[start:start + 24]
        options = []
        for s in chunk:
            status = "🟢" if s["enabled"] else "🔴"
            buyer = f"${s['buyer_rate']}/1k" if s.get("buyer_rate") else "no price"
            label = f"{status} {s['name']}"[:100]
            desc = f"Cost: ${s['rate']}/1k  •  Buyer: {buyer}  •  ID: {s['service_id']}"[:100]
            options.append(discord.SelectOption(label=label, value=str(s["service_id"]), description=desc))
        select = discord.ui.Select(placeholder=f"Select a service... (page {self.page + 1})", options=options, row=0)
        select.callback = self.on_service_select
        self.add_item(select)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        if len(self.services) > 24:
            if self.page > 0:
                prev_btn = discord.ui.Button(label="Prev Page", style=discord.ButtonStyle.secondary, row=1)
                prev_btn.callback = self.prev_page
                self.add_item(prev_btn)
            if start + 24 < len(self.services):
                next_btn = discord.ui.Button(label="Next Page", style=discord.ButtonStyle.secondary, row=1)
                next_btn.callback = self.next_page
                self.add_item(next_btn)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    async def on_service_select(self, interaction):
        service_id = int(interaction.data["values"][0])
        service = await db.smb_get_service(service_id)
        if not service:
            return await interaction.response.send_message(embed=error_embed("Service not found."), ephemeral=True)
        view = OwnerServiceDetailView(self.author_id, self.platform, self.category, self.services, service)
        await interaction.response.edit_message(embed=service_detail_embed(service), view=view)

    async def go_back(self, interaction):
        all_services = await db.smb_get_all_services()
        categories = sorted(set(s["category"] for s in all_services if s["platform"] == self.platform))
        view = OwnerCategoryView(self.author_id, self.platform, categories)
        enabled_count = sum(1 for s in self.services if s["enabled"])
        embed = make_embed(
            f"{PLATFORM_EMOJI.get(self.platform, '')} {self.platform} -- Select Category",
            f"{DIVIDER}\n\n**{len(categories)}** categories  •  Pick one to browse services."
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def prev_page(self, interaction):
        self.page -= 1
        self._build_select()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction):
        self.page += 1
        self._build_select()
        await interaction.response.edit_message(view=self)


# ── STEP 4: Service Detail + Edit/Toggle ─────────────────────────────────────

class OwnerServiceDetailView(discord.ui.View):
    def __init__(self, author_id: int, platform: str, category: str, services: list, service: dict):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.platform = platform
        self.category = category
        self.services = services
        self.service = service

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("This panel isn't for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def go_back(self, interaction, button):
        # Refresh services list
        all_services = await db.smb_get_all_services()
        services = [s for s in all_services if s["platform"] == self.platform and s["category"] == self.category]
        view = OwnerServiceView(self.author_id, self.platform, self.category, services)
        enabled_count = sum(1 for s in services if s["enabled"])
        embed = make_embed(
            f"{self.platform} > {self.category[:50]}",
            f"{DIVIDER}\n\n**{len(services)}** services  •  🟢 {enabled_count} enabled  •  🔴 {len(services) - enabled_count} disabled\n\nSelect a service to view and edit."
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Edit Service", style=discord.ButtonStyle.primary)
    async def edit_service(self, interaction, button):
        await interaction.response.send_modal(OwnerEditModal(self.service, self))

    @discord.ui.button(label="Toggle On/Off", style=discord.ButtonStyle.secondary)
    async def toggle_service(self, interaction, button):
        new_state = not bool(self.service["enabled"])
        await db.smb_set_enabled(self.service["service_id"], new_state)
        self.service = await db.smb_get_service(self.service["service_id"])
        emoji = "🟢" if new_state else "🔴"
        await interaction.response.edit_message(
            embed=service_detail_embed(self.service),
            view=self
        )
        await interaction.followup.send(
            embed=success_embed(f"{emoji} **{self.service['name'][:60]}** {'enabled' if new_state else 'disabled'}."),
            ephemeral=True
        )


# ── STEP 5: Edit Modal ────────────────────────────────────────────────────────

class OwnerEditModal(discord.ui.Modal):
    def __init__(self, service: dict, parent_view: OwnerServiceDetailView):
        super().__init__(title=f"Edit — {service['name'][:35]}")
        self.service = service
        self.parent_view = parent_view

        self.name_input = discord.ui.TextInput(
            label="Service Name",
            default=service["name"][:100],
            style=discord.TextStyle.short,
            required=True,
            max_length=200,
        )
        self.rate_input = discord.ui.TextInput(
            label="Your Cost per 1,000 (hidden from buyers)",
            default=str(service["rate"]),
            style=discord.TextStyle.short,
            required=True,
            max_length=20,
        )
        self.buyer_rate_input = discord.ui.TextInput(
            label="Buyer Rate per 1,000 (shown to buyers)",
            default=str(service.get("buyer_rate") or ""),
            placeholder="e.g. 1.50 — leave blank to keep current",
            style=discord.TextStyle.short,
            required=False,
            max_length=20,
        )
        self.category_input = discord.ui.TextInput(
            label="Category",
            default=service["category"][:100],
            style=discord.TextStyle.short,
            required=True,
            max_length=200,
        )
        self.link_hint_input = discord.ui.TextInput(
            label="Link Hint (shown in order modal)",
            default=str(service.get("link_hint") or ""),
            placeholder="e.g. Spotify profile URL",
            style=discord.TextStyle.short,
            required=False,
            max_length=200,
        )
        self.add_item(self.name_input)
        self.add_item(self.rate_input)
        self.add_item(self.buyer_rate_input)
        self.add_item(self.category_input)
        self.add_item(self.link_hint_input)

    async def on_submit(self, interaction: discord.Interaction):
        # Validate rate fields
        try:
            float(self.rate_input.value.strip())
        except ValueError:
            return await interaction.response.send_message(embed=error_embed("Your cost must be a number (e.g. 0.90)."), ephemeral=True)

        buyer_rate = self.buyer_rate_input.value.strip()
        if buyer_rate:
            try:
                float(buyer_rate)
            except ValueError:
                return await interaction.response.send_message(embed=error_embed("Buyer rate must be a number (e.g. 1.50)."), ephemeral=True)

        updates = {
            "name": self.name_input.value.strip(),
            "rate": self.rate_input.value.strip(),
            "buyer_rate": buyer_rate,
            "category": self.category_input.value.strip(),
            "link_hint": self.link_hint_input.value.strip(),
        }
        await db.smb_edit_service(self.service["service_id"], **updates)
        updated = await db.smb_get_service(self.service["service_id"])
        self.parent_view.service = updated

        # Update the panel to show the refreshed service
        await interaction.response.edit_message(embed=service_detail_embed(updated), view=self.parent_view)
        await interaction.followup.send(
            embed=success_embed(f"**{updated['name'][:60]}** updated."),
            ephemeral=True
        )


# ── COG ───────────────────────────────────────────────────────────────────────

class SmbOwner(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="smbowner", description="Open the SMB service management panel (Admin)")
    async def smbowner(self, interaction: discord.Interaction):
        if not interaction.guild or not is_owner(interaction):
            return await interaction.response.send_message(
                embed=error_embed("This command is only available to the bot owner in the server."),
                ephemeral=True,
            )

        view = OwnerPlatformView(interaction.user.id)
        has_platforms = await view.build_select()

        if not has_platforms:
            return await interaction.response.send_message(
                embed=make_embed("SMB Owner Panel", "No services configured yet.\n\nRun `/smbsync` first to import services."),
                ephemeral=True,
            )

        embed = make_embed(
            "🛠️  SMB Owner Panel",
            f"{DIVIDER}\n\nBrowse and edit all your SMB services.\nSelect a platform to get started."
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(SmbOwner(bot), guild=guild)
