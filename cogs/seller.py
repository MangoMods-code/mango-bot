# cogs/seller.py — Seller-facing commands (global / DMs).
# Every command requires seller status or owner.

import json
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
import aegis as aegis_api
from helpers import (
    mango_embed, error_embed, dm_only_error, maintenance_embed,
    requires_dm, is_owner, DIVIDER, DIVIDER_SHORT,
    PaginatorView, DismissView, paginate_items,
    send_log, log_keygen,
)

NO_ACCESS = "🔒 You need **seller permissions** to use this command.\n\nContact the owner to get access."


def get_nested_value(obj, path):
    parts = path.split(".")
    current = obj
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


async def fetch_generic_api_balance(variant: dict):
    if not variant.get("api_balance_url"):
        return None
    try:
        headers = json.loads(variant.get("api_headers") or "{}")
        async with aiohttp.ClientSession() as session:
            async with session.get(variant["api_balance_url"], headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        value = get_nested_value(data, variant.get("api_balance_path") or "balance")
        return str(value) if value is not None else None
    except Exception as e:
        print(f"[API Balance] Failed: {e}")
        return None


async def seller_check(interaction: discord.Interaction) -> bool:
    """Returns True if the user is a seller or the owner. False otherwise."""
    if is_owner(interaction):
        return True
    user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
    return bool(user["is_seller"])


class Seller(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def variant_autocomplete(self, interaction, current):
        variants = await db.get_all_enabled_variants()
        choices = []
        for v in variants:
            label = f"{v['product_name']} — {v['name']} ({v['price']} bal)"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=v["id"]))
            if len(choices) >= 25:
                break
        return choices

    # ── BALANCE ──────────────────────────────────────────────────────────────

    @app_commands.command(name="balance", description="View your current balance")
    async def balance(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)
        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        seller_status = "✅  **Active Seller**" if user["is_seller"] else "❌  Not a seller"
        embed = mango_embed("💰  Your Balance", f"# {user['balance']}\n{DIVIDER_SHORT}\n{seller_status}")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=interaction.guild is not None)

    # ── MY KEYS ──────────────────────────────────────────────────────────────

    @app_commands.command(name="mykeys", description="View all keys you have generated")
    async def mykeys(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)
        keys = await db.get_keys_by_user(str(interaction.user.id))
        if not keys:
            return await interaction.response.send_message(
                embed=mango_embed("🔑  Your Keys", "You haven't generated any keys yet.\n\nUse `/generatekey` to get started!"),
                ephemeral=interaction.guild is not None,
            )
        chunks = paginate_items(keys, 6)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n"
            for k in chunk:
                banned = "  🚫 *BANNED*" if k["is_banned"] else ""
                date_str = k["generated_at"][:10]
                desc += f"🔑  **{k['product_name']}** — {k['variant_name']}{banned}\n> `{k['key_value']}`\n> #{k['id']}  •  {date_str}\n\n"
            embed = mango_embed(f"🔑  Your Keys — Page {i}/{len(chunks)}", desc)
            embed.set_footer(text=f"🥭 {len(keys)} total keys  •  Page {i}/{len(chunks)}")
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            pages.append(embed)
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=interaction.guild is not None)
        else:
            await interaction.response.send_message(embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=interaction.guild is not None)

    # ── PRODUCTS ─────────────────────────────────────────────────────────────

    @app_commands.command(name="products", description="View all available products and variants")
    async def products(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)
        all_products = await db.get_all_products()
        if not all_products:
            return await interaction.response.send_message(embed=mango_embed("🥭  Products", "No products added yet."), ephemeral=True)
        lines = []
        for p in all_products:
            status = "🟢" if p["enabled"] else "🔴"
            lines.append(f"{status}  **{p['display_name']}**  *(ID: `{p['id']}`)*")
            variants = await db.get_variants_for_product(p["id"])
            if not variants:
                lines.append("> *No variants added yet*")
            else:
                for v in variants:
                    v_s = "🟢" if v["enabled"] else "🔴"
                    icons = {"stock": "📦", "aegis": "🔑", "api": "🌐"}
                    t = icons.get(v["type"], "•")
                    si = f"  •  Stock: **{await db.get_stock_count(v['id'])}**" if v["type"] == "stock" else ""
                    lines.append(f"> {v_s} {t}  **{v['name']}** — **{v['price']}** bal{si}  *(ID: `{v['id']}`)*")
            lines.append("")
        chunks = paginate_items(lines, 15)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            pages.append(mango_embed(f"🥭  Products — Page {i}/{len(chunks)}", f"{DIVIDER}\n\n" + "\n".join(chunk)))
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True)

    # ── BUYER GROUPS ─────────────────────────────────────────────────────────

    @app_commands.command(name="buyergroups", description="View buyer group links for your customers")
    async def buyergroups(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)
        groups = await db.get_all_buyer_groups()
        if not groups:
            return await interaction.response.send_message(embed=mango_embed("📲  Buyer Groups", "No buyer groups set up yet."), ephemeral=True)
        description = (
            f"⛔  **SELLER EYES ONLY — DO NOT SHARE THESE LINKS**\n"
            f"These links are for **your** buyer groups that you set up.\n"
            f"Do **NOT** send these directly to your customers.\n"
            f"You must create your own buyer group/tutorial for them.\n"
            f"{DIVIDER}\n\n"
        )
        for g in groups:
            description += f"**{g['name']}**\n> {g['link']}\n\n"
        description += f"{DIVIDER}\n⛔  **DO NOT SHARE — SELLER ONLY**"
        embed = discord.Embed(title="📲  Buyer Groups", description=description, color=discord.Colour.from_str("#FF3B3B"))
        embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── GENERATE KEY ─────────────────────────────────────────────────────────

    @app_commands.command(name="generatekey", description="Generate a license key (Sellers only)")
    @app_commands.describe(variant="Start typing a product name to see options", amount="How many keys (default 1, max 25)")
    @app_commands.autocomplete(variant=variant_autocomplete)
    async def generatekey(self, interaction: discord.Interaction, variant: int, amount: int = 1):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)
        if not is_owner(interaction) and await db.is_maintenance():
            return await interaction.response.send_message(embed=maintenance_embed(), ephemeral=True)

        await interaction.response.defer(ephemeral=interaction.guild is not None)

        amount = max(1, min(25, amount))
        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        owner_mode = is_owner(interaction)
        balance_before = user["balance"]

        if not user["is_seller"] and not owner_mode:
            return await interaction.followup.send(embed=error_embed(NO_ACCESS))

        if not owner_mode:
            try:
                guild = self.bot.get_guild(int(cfg.GUILD_ID)) or await self.bot.fetch_guild(int(cfg.GUILD_ID))
                try:
                    await guild.fetch_member(interaction.user.id)
                except discord.NotFound:
                    return await interaction.followup.send(embed=error_embed("You must be in the **official server** to generate keys."))
            except Exception:
                return await interaction.followup.send(embed=error_embed("Could not verify server membership."))

        var = await db.get_variant(variant)
        if not var:
            return await interaction.followup.send(embed=error_embed("Variant not found. Use `/products`."))
        if not var["enabled"]:
            return await interaction.followup.send(embed=error_embed(f"**{var['product_name']} — {var['name']}** is disabled."))
        product = await db.get_product(var["product_id"])
        if not product or not product["enabled"]:
            return await interaction.followup.send(embed=error_embed(f"**{var['product_name']}** is disabled."))

        total_cost = var["price"] * amount
        if not owner_mode and user["balance"] < total_cost:
            return await interaction.followup.send(embed=error_embed(
                f"**Not enough balance.**\n\nNeed: **{total_cost}**  •  Have: **{user['balance']}**\nPrice per key: **{var['price']}**"
            ))

        label = f"{var['product_name']} — {var['name']}"
        generated_keys = []
        api_balance_before = None
        api_balance_after = None

        if var["type"] == "aegis":
            if not var.get("aegis_category") or not var.get("aegis_service"):
                return await interaction.followup.send(embed=error_embed(f"**{label}** isn't configured yet. The owner needs to run `/setaegis`."))
            if not cfg.AEGIS_API_KEY or not cfg.AEGIS_API_SECRET:
                return await interaction.followup.send(embed=error_embed("Aegis API credentials are not set. Contact the owner."))
            try:
                result = await aegis_api.create_order(category=var["aegis_category"], service=var["aegis_service"], quantity=amount, buyer_name=interaction.user.name)
                data = result.get("data", {})
                generated_keys = data.get("keys", [])
                if not generated_keys:
                    return await interaction.followup.send(embed=error_embed("Aegis returned no keys. Contact the owner."))
                api_balance_before = data.get("balance_before")
                api_balance_after  = data.get("balance_after")
                for key_value in generated_keys:
                    await db.record_key(variant, str(key_value), str(interaction.user.id))
                    if not owner_mode:
                        await db.subtract_balance(str(interaction.user.id), var["price"])
            except Exception as e:
                return await interaction.followup.send(embed=error_embed(f"Aegis API error:\n{e}"))

        elif var["type"] == "stock":
            for _ in range(amount):
                stock_key = await db.get_next_stock_key(variant)
                if not stock_key:
                    if generated_keys:
                        break
                    return await interaction.followup.send(embed=error_embed(f"**{label}** is out of stock.\n\n{'Use `/stock` to restock.' if owner_mode else 'Contact the owner.'}"))
                await db.mark_stock_used(stock_key["id"])
                await db.record_key(variant, stock_key["key_value"], str(interaction.user.id))
                if not owner_mode:
                    await db.subtract_balance(str(interaction.user.id), var["price"])
                generated_keys.append(stock_key["key_value"])

        elif var["type"] == "api":
            api_balance_before = await fetch_generic_api_balance(var)
            for _ in range(amount):
                try:
                    headers = {"Content-Type": "application/json"}
                    headers.update(json.loads(var["api_headers"] or "{}"))
                    async with aiohttp.ClientSession() as session:
                        kwargs = {"headers": headers}
                        if var["api_method"] == "POST":
                            kwargs["json"] = json.loads(var["api_body"] or "{}")
                            req = session.post(var["api_url"], **kwargs)
                        else:
                            req = session.get(var["api_url"], **kwargs)
                        async with req as resp:
                            if resp.status != 200:
                                if generated_keys: break
                                return await interaction.followup.send(embed=error_embed(f"API error ({resp.status})."))
                            data = await resp.json(content_type=None)
                    key_value = get_nested_value(data, var["api_key_path"] or "key")
                    if not key_value:
                        if generated_keys: break
                        return await interaction.followup.send(embed=error_embed("API didn't return a valid key."))
                    await db.record_key(variant, str(key_value), str(interaction.user.id))
                    if not owner_mode:
                        await db.subtract_balance(str(interaction.user.id), var["price"])
                    generated_keys.append(str(key_value))
                except Exception as e:
                    print(f"API error: {e}")
                    if generated_keys: break
                    return await interaction.followup.send(embed=error_embed("Failed to reach the API. Try again."))
            if generated_keys:
                api_balance_after = await fetch_generic_api_balance(var)

        updated_user = await db.get_user(str(interaction.user.id))
        actual_cost = var["price"] * len(generated_keys)
        keys_display = f"```\n{generated_keys[0]}\n```" if len(generated_keys) == 1 else "```\n" + "\n".join(f"{i+1}.  {k}" for i, k in enumerate(generated_keys)) + "\n```"
        balance_line = "💰 *Owner mode — no balance deducted*" if owner_mode else f"💰 Remaining balance: **{updated_user['balance']}**"

        embed = mango_embed("🔑  Your Generated Keys", f"**{label}** — {len(generated_keys)} key(s)\n{DIVIDER}\n{keys_display}\n{balance_line}")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

        if not owner_mode:
            receipt = mango_embed("🧾  Receipt", f"**{label}**\n{DIVIDER_SHORT}\n\nKeys generated: **{len(generated_keys)}**\nPrice per key: **{var['price']}** bal\nTotal deducted: **{actual_cost}** bal\n\nBalance before: **{balance_before}**\nBalance after: **{updated_user['balance']}**")
            await interaction.followup.send(embed=receipt, view=DismissView(interaction.user.id), ephemeral=interaction.guild is not None)

        await send_log(self.bot, log_keygen(
            user=interaction.user, variant_label=label, count=len(generated_keys),
            price_each=var["price"], total_cost=actual_cost, balance_before=balance_before,
            balance_after=updated_user["balance"], keys=generated_keys, owner_mode=owner_mode,
            api_balance_before=api_balance_before, api_balance_after=api_balance_after,
        ))

    # ── SMB HELP ──────────────────────────────────────────────────────────────

    @app_commands.command(name="smbhelp", description="Show all social media panel commands")
    async def smbhelp(self, interaction: discord.Interaction):
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)
        embed = mango_embed("📱  Socials Panel", f"Social media growth services.\n{DIVIDER}")
        embed.add_field(
            name="📬  Your Commands",
            value=(
                "`/socials` — Open the order panel\n"
                "`/smborders` — View your past & active orders\n"
                "`/smbhelp` — This message"
            ),
            inline=False,
        )
        embed.add_field(
            name="💳  Balance",
            value="Your SMB balance is separate from your key reseller balance.\nContact the owner to top it up.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── SMB ORDERS ────────────────────────────────────────────────────────────

    @app_commands.command(name="smborders", description="View your past and active social media orders")
    async def smborders(self, interaction: discord.Interaction):
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)

        orders = await db.smb_get_user_orders(str(interaction.user.id))
        smb_bal = await db.smb_get_user_balance(str(interaction.user.id))

        if not orders:
            return await interaction.response.send_message(
                embed=mango_embed("📦  Your SMB Orders", f"💳 SMB Balance: **${smb_bal:.2f}**\n{DIVIDER_SHORT}\n\nNo orders yet. Use `/socials` to place one!"),
                ephemeral=True,
            )

        # Build dropdown with up to 25 most recent orders
        view = SmbOrdersView(interaction.user.id, orders[:25])
        embed = mango_embed(
            "📦  Your SMB Orders",
            f"💳 SMB Balance: **${smb_bal:.2f}**\n{DIVIDER_SHORT}\n\n"
            f"**{len(orders)}** total order(s).\nSelect one from the dropdown to see details."
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── HELP ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Show all available commands")
    async def help(self, interaction: discord.Interaction):
        if not await seller_check(interaction):
            return await interaction.response.send_message(embed=error_embed(NO_ACCESS), ephemeral=True)
        embed = mango_embed("🥭  Mango Bot", f"License key reseller bot.\n{DIVIDER}")
        embed.add_field(
            name="📬  Seller Commands",
            value=(
                "`/generatekey` — Generate a license key\n"
                "`/balance` — View your balance\n"
                "`/mykeys` — View your generated keys\n"
                "`/products` — See products & variants\n"
                "`/buyergroups` — Your buyer group links\n"
                "`/socials` — Social media order panel\n"
                "`/certgen` — Generate A Cert\n"
                "`/certplans` — View Certs Available For Gen\n"
                "`/certcheck` — Checks UDID For Active Certs\n"
                "`/mycerts` — View The Certs Youve Gened\n"
                "`/udidcheck` — Shows You How To Check Your UDID\n"
                "`/help` — This message"
            ),
            inline=False,
        )
        if interaction.guild and is_owner(interaction):
            embed.add_field(name="🔧  Admin — Users", value="`/setseller` `/addbalance` `/setbalance` `/resetbalance` `/viewusers`", inline=False)
            embed.add_field(
                name="🔧  Admin — Products",
                value="`/addproduct` `/addvariant` `/removeproduct` `/removevariant`\n`/setprice` `/toggleproduct` `/togglevariant`\n`/setaegis` `/aegisservices` — Aegis API\n`/setupapi` `/setapibalance` — Generic API\n`/stock` `/stockcount`",
                inline=False,
            )
            embed.add_field(
                name="🔧  Admin — System",
                value="`/bankey` `/unbankey` `/removekey`\n`/clearkeyhistory` `/maintenance`\n`/apibalance` `/dmannounce`\n`/setbuyergroup` `/removebuyergroup`\n`/smbmaintenance` `/smbbalance` `/smbservices`\n`/smbaddservice` `/smbremoveservice` `/smbtoggle`",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SmbOrdersView(discord.ui.View):
    def __init__(self, author_id, orders):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.orders = {str(o["smb_order_id"]): o for o in orders}
        options = []
        for o in orders:
            date = o["created_at"][:10]
            label = f"#{o['smb_order_id']} — {o['service_name'][:40]}"
            desc = f"{o['platform']}  •  {o['quantity']:,}  •  {date}"
            options.append(discord.SelectOption(label=label[:100], value=str(o["smb_order_id"]), description=desc[:100]))
        select = discord.ui.Select(placeholder="📦  Select an order to see details...", options=options)
        select.callback = self.on_order_select
        self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    async def on_order_select(self, interaction: discord.Interaction):
        order_id = interaction.data["values"][0]
        o = self.orders.get(order_id)
        if not o:
            return await interaction.response.send_message(embed=error_embed("Order not found."), ephemeral=True)

        # Fetch live status from SMB API
        live_status = o["status"]
        remains = "?"
        start_count = "?"
        try:
            import smb as smb_api
            status = await smb_api.get_order_status(int(order_id))
            live_status = status.get("status", live_status)
            remains = status.get("remains", "?")
            start_count = status.get("start_count", "?")
            await db.smb_update_order_status(order_id, live_status)
        except Exception:
            pass

        color_map = {
            "Completed": discord.Colour.green(), "In progress": discord.Colour.orange(),
            "Partial": discord.Colour.yellow(), "Processing": discord.Colour.blue(),
            "Canceled": discord.Colour.red(),
        }
        embed = discord.Embed(
            title=f"📦  Order #{order_id}",
            description=(
                f"**Service:** {o['service_name']}\n"
                f"**Platform:** {o['platform']}\n"
                f"**Link:** {o['link']}\n"
                f"**Quantity:** {o['quantity']:,}\n"
                f"**Cost:** ${o['buyer_cost']:.2f}\n"
                f"**Status:** {live_status}\n"
                f"**Start count:** {start_count}\n"
                f"**Remaining:** {remains}\n"
                f"**Placed:** {o['created_at'][:16]}"
            ),
            color=color_map.get(live_status, discord.Colour.greyple()),
        )
        embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Seller(bot))





