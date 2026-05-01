# cogs/seller.py — Seller-facing commands (global / DMs).
# Owner can use these in server too.

import json
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
from helpers import (
    mango_embed, error_embed, dm_only_error, maintenance_embed,
    requires_dm, is_owner, DIVIDER, DIVIDER_SHORT,
    PaginatorView, DismissView, paginate_items,
    send_log, log_keygen,
)


def get_nested_value(obj, path):
    parts = path.split(".")
    current = obj
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


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
        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        seller_status = "✅  **Active Seller**" if user["is_seller"] else "❌  Not a seller"
        embed = mango_embed("💰  Your Balance", f"# {user['balance']}\n{DIVIDER_SHORT}\n{seller_status}")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=interaction.guild is not None)

    # ── MY KEYS (paginated) ──────────────────────────────────────────────────

    @app_commands.command(name="mykeys", description="View all keys you have generated")
    async def mykeys(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)
        await db.ensure_user(str(interaction.user.id), interaction.user.name)
        keys = await db.get_keys_by_user(str(interaction.user.id))
        if not keys:
            return await interaction.response.send_message(
                embed=mango_embed("🔑  Your Keys", "You haven't generated any keys yet.\n\nUse `/generatekey` to get started!"),
                ephemeral=interaction.guild is not None
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

    # ── PRODUCTS (paginated, works everywhere) ───────────────────────────────

    @app_commands.command(name="products", description="View all available products and variants")
    async def products(self, interaction: discord.Interaction):
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
                    t = "🌐" if v["type"] == "api" else "📦"
                    si = f"  •  Stock: **{await db.get_stock_count(v['id'])}**" if v["type"] == "stock" else ""
                    lines.append(f"> {v_s} {t}  **{v['name']}** — **{v['price']}** bal{si}  *(ID: `{v['id']}`)*")
            lines.append("")
        chunks = paginate_items(lines, 15)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n" + "\n".join(chunk)
            pages.append(mango_embed(f"🥭  Products — Page {i}/{len(chunks)}", desc))
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True)

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
            return await interaction.followup.send(embed=error_embed("🔒 You don't have seller permissions.\n\nAsk the bot owner to grant you access."))

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

        generated_keys = []

        for _ in range(amount):
            key_value = None
            if var["type"] == "stock":
                stock_key = await db.get_next_stock_key(variant)
                if not stock_key:
                    if generated_keys:
                        break
                    msg = "Use `/stock` to restock." if owner_mode else "Contact the owner."
                    return await interaction.followup.send(embed=error_embed(f"**{var['product_name']} — {var['name']}** is out of stock.\n\n{msg}"))
                key_value = stock_key["key_value"]
                await db.mark_stock_used(stock_key["id"])
            elif var["type"] == "api":
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
                                if generated_keys:
                                    break
                                return await interaction.followup.send(embed=error_embed(f"API error ({resp.status})."))
                            data = await resp.json()
                    key_value = get_nested_value(data, var["api_key_path"] or "key")
                    if not key_value:
                        if generated_keys:
                            break
                        return await interaction.followup.send(embed=error_embed("API didn't return a valid key."))
                    key_value = str(key_value)
                except Exception as e:
                    print(f"API error: {e}")
                    if generated_keys:
                        break
                    return await interaction.followup.send(embed=error_embed("Failed to reach the API."))

            await db.record_key(variant, key_value, str(interaction.user.id))
            if not owner_mode:
                await db.subtract_balance(str(interaction.user.id), var["price"])
            generated_keys.append(key_value)

        updated_user = await db.get_user(str(interaction.user.id))
        label = f"{var['product_name']} — {var['name']}"
        actual_cost = var["price"] * len(generated_keys)

        keys_display = f"```\n{generated_keys[0]}\n```" if len(generated_keys) == 1 else \
                       f"```\n" + "\n".join(f"{i+1}.  {k}" for i, k in enumerate(generated_keys)) + "\n```"

        balance_line = "💰 *Owner mode — no balance deducted*" if owner_mode else f"💰 Remaining balance: **{updated_user['balance']}**"

        embed = mango_embed("🔑  Your Generated Keys", f"**{label}** — {len(generated_keys)} key(s)\n{DIVIDER}\n{keys_display}\n{balance_line}")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

        if not owner_mode:
            receipt = mango_embed(
                "🧾  Receipt",
                f"**{label}**\n{DIVIDER_SHORT}\n\n"
                f"Keys generated: **{len(generated_keys)}**\n"
                f"Price per key: **{var['price']}** bal\n"
                f"Total deducted: **{actual_cost}** bal\n\n"
                f"Balance before: **{balance_before}**\n"
                f"Balance after: **{updated_user['balance']}**"
            )
            await interaction.followup.send(embed=receipt, view=DismissView(interaction.user.id), ephemeral=interaction.guild is not None)

        await send_log(self.bot, log_keygen(
            user=interaction.user,
            variant_label=label,
            count=len(generated_keys),
            price_each=var["price"],
            total_cost=actual_cost,
            balance_before=balance_before,
            balance_after=updated_user["balance"],
            keys=generated_keys,
            owner_mode=owner_mode,
        ))

    # ── HELP ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Show all available commands")
    async def help(self, interaction: discord.Interaction):
        embed = mango_embed("🥭  Mango Bot", f"License key reseller bot.\n{DIVIDER}")
        embed.add_field(
            name="📬  Seller Commands",
            value="`/generatekey` — Generate a license key\n`/balance` — View your balance\n`/mykeys` — View your generated keys\n`/products` — See products & variants\n`/help` — This message",
            inline=False,
        )
        if interaction.guild and is_owner(interaction):
            embed.add_field(name="🔧  Admin — Users", value="`/setseller` `/addbalance` `/setbalance` `/resetbalance` `/viewusers`", inline=False)
            embed.add_field(name="🔧  Admin — Products", value="`/addproduct` `/addvariant` `/removeproduct` `/removevariant`\n`/setprice` `/toggleproduct` `/togglevariant`\n`/setupapi` `/stock` `/stockcount`", inline=False)
            embed.add_field(name="🔧  Admin — System", value="`/bankey` `/unbankey` `/removekey`\n`/clearkeyhistory` `/maintenance`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Seller(bot))
