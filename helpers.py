# helpers.py — Shared utilities, embed builders, pagination, and logging.

import discord
from discord.ui import View, Button
import config as cfg

EMBED_COLOR = discord.Colour(int(cfg.EMBED_COLOR, 16))
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
DIVIDER_SHORT = "━━━━━━━━━━━━━━━━"
ITEMS_PER_PAGE = 8


def is_owner(interaction: discord.Interaction) -> bool:
    return str(interaction.user.id) == str(cfg.OWNER_ID)

def requires_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    return not is_owner(interaction)

def mango_embed(title="", description=""):
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    embed.timestamp = discord.utils.utcnow()
    return embed

def error_embed(message):
    embed = discord.Embed(title="❌  Error", description=message, color=discord.Colour.from_str("#FF3B3B"))
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    embed.timestamp = discord.utils.utcnow()
    return embed

def success_embed(message):
    embed = discord.Embed(title="✅  Success", description=message, color=discord.Colour.from_str("#2ECC71"))
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    embed.timestamp = discord.utils.utcnow()
    return embed

def dm_only_error():
    return error_embed("This command only works in **DMs**.\n\nSend me a direct message and try again!")

def server_only_error():
    return error_embed("This command only works **in the server**.")

def maintenance_embed():
    embed = discord.Embed(
        title="🔧  Maintenance Mode",
        description="The bot is currently under maintenance.\nKey generation is temporarily disabled.\n\nPlease try again later.",
        color=discord.Colour.from_str("#FFA500"),
    )
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    embed.timestamp = discord.utils.utcnow()
    return embed


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

async def send_log(bot, embed):
    try:
        channel_id = cfg.LOG_CHANNEL_ID
        if not channel_id or not str(channel_id).isdigit():
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            channel = await bot.fetch_channel(int(channel_id))
        if channel:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"[LOG] Failed to send log: {e}")


def log_keygen(user, variant_label, count, price_each, total_cost,
               balance_before, balance_after, keys, owner_mode,
               api_balance_before=None, api_balance_after=None):
    keys_preview = ", ".join(f"`{k[:12]}…`" if len(k) > 12 else f"`{k}`" for k in keys[:5])
    if len(keys) > 5:
        keys_preview += f" *+{len(keys) - 5} more*"
    embed = discord.Embed(title="🔑  Key Generated", color=discord.Colour.from_str("#FF8C00"), timestamp=discord.utils.utcnow())
    embed.add_field(name="Seller", value=f"{user.mention} (`{user.name}`)", inline=True)
    embed.add_field(name="Product", value=variant_label, inline=True)
    embed.add_field(name="Keys", value=str(count), inline=True)
    if owner_mode:
        embed.add_field(name="Internal Cost", value="*Owner — free*", inline=True)
        embed.add_field(name="Internal Balance", value="N/A", inline=True)
    else:
        embed.add_field(name="Internal Cost", value=f"{price_each} × {count} = **{total_cost}**", inline=True)
        embed.add_field(name="Internal Balance", value=f"{balance_before} → **{balance_after}**", inline=True)
    if api_balance_before is not None or api_balance_after is not None:
        before_str = str(api_balance_before) if api_balance_before is not None else "N/A"
        after_str = str(api_balance_after) if api_balance_after is not None else "N/A"
        embed.add_field(name="🌐 API Balance (External)", value=f"{before_str} → **{after_str}**", inline=False)
    embed.add_field(name="Keys Preview", value=keys_preview, inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=f"User ID: {user.id}")
    return embed


def log_smb_order(user, service_name, platform, link, quantity,
                  order_id, estimated_cost, smb_balance_before, smb_balance_after):
    """Log a social media panel order to the log channel."""
    embed = discord.Embed(
        title="📱  Socials Order Placed",
        color=discord.Colour.from_str("#1DA1F2"),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Ordered by", value=f"{user.mention} (`{user.name}`)", inline=True)
    embed.add_field(name="Platform", value=platform, inline=True)
    embed.add_field(name="Service", value=service_name, inline=True)
    embed.add_field(name="Order ID", value=f"`{order_id}`", inline=True)
    embed.add_field(name="Quantity", value=f"{quantity:,}", inline=True)
    embed.add_field(name="Est. Cost", value=f"${estimated_cost:.5f}", inline=True)
    embed.add_field(name="Link", value=link, inline=False)
    # Always show your SMB balance in the log — this is private to the log channel
    if smb_balance_before or smb_balance_after:
        embed.add_field(
            name="💳 SMB Balance",
            value=f"{smb_balance_before or 'N/A'} → **{smb_balance_after or 'N/A'}**",
            inline=False,
        )
    embed.set_footer(text=f"User ID: {user.id}")
    return embed


def log_balance_change(admin, target, action, amount, new_balance):
    embed = discord.Embed(title="💰  Balance Changed", color=discord.Colour.from_str("#3498DB"), timestamp=discord.utils.utcnow())
    embed.add_field(name="Admin", value=f"{admin.mention}", inline=True)
    embed.add_field(name="Target", value=f"{target.mention} (`{target.name}`)", inline=True)
    embed.add_field(name="Action", value=action, inline=True)
    embed.add_field(name="Amount", value=str(amount), inline=True)
    embed.add_field(name="New Balance", value=f"**{new_balance}**", inline=True)
    embed.set_footer(text=f"Target ID: {target.id}")
    return embed

def log_seller_change(admin, target, granted):
    embed = discord.Embed(title="🏷️  Seller Updated", color=discord.Colour.from_str("#9B59B6"), timestamp=discord.utils.utcnow())
    embed.add_field(name="Admin", value=f"{admin.mention}", inline=True)
    embed.add_field(name="Target", value=f"{target.mention} (`{target.name}`)", inline=True)
    embed.add_field(name="Action", value="**Granted** ✅" if granted else "**Revoked** ❌", inline=True)
    embed.set_footer(text=f"Target ID: {target.id}")
    return embed

def log_maintenance(admin, enabled):
    embed = discord.Embed(
        title="🔧  Maintenance Toggled",
        description=f"Maintenance mode **{'ON' if enabled else 'OFF'}**",
        color=discord.Colour.from_str("#FFA500") if enabled else discord.Colour.from_str("#2ECC71"),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Admin", value=f"{admin.mention}", inline=True)
    embed.set_footer(text=f"Admin ID: {admin.id}")
    return embed

def log_clear_keys(admin, count):
    embed = discord.Embed(title="🗑️  Key History Cleared", description=f"**{count}** key record(s) deleted.", color=discord.Colour.from_str("#E74C3C"), timestamp=discord.utils.utcnow())
    embed.add_field(name="Admin", value=f"{admin.mention}", inline=True)
    embed.set_footer(text=f"Admin ID: {admin.id}")
    return embed

def log_announce(admin, message, sent, failed):
    embed = discord.Embed(title="📢  Announcement Sent", color=discord.Colour.from_str("#1ABC9C"), timestamp=discord.utils.utcnow())
    embed.add_field(name="Admin", value=f"{admin.mention}", inline=True)
    embed.add_field(name="Delivered", value=f"✅ {sent}", inline=True)
    embed.add_field(name="Failed", value=f"❌ {failed}", inline=True)
    embed.add_field(name="Message", value=message[:500], inline=False)
    embed.set_footer(text=f"Admin ID: {admin.id}")
    return embed


# ═══════════════════════════════════════════════════════════════════════════════
# PAGINATION
# ═══════════════════════════════════════════════════════════════════════════════

class PaginatorView(View):
    def __init__(self, pages, author_id, timeout=120):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.current = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("These buttons aren't for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction, button):
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction, button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class DismissView(View):
    def __init__(self, author_id, timeout=300):
        super().__init__(timeout=timeout)
        self.author_id = author_id

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.secondary, emoji="🗑️")
    async def dismiss(self, interaction, button):
        await interaction.message.delete()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


def paginate_items(items, per_page=ITEMS_PER_PAGE):
    return [items[i:i + per_page] for i in range(0, len(items), per_page)]


