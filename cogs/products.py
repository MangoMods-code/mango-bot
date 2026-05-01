# cogs/products.py — Product & variant management (server-only, admin-only).

import json
import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
from helpers import (
    is_owner, mango_embed, error_embed, success_embed,
    server_only_error, DIVIDER, DIVIDER_SHORT,
    PaginatorView, paginate_items,
)


class Products(commands.Cog):

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

    # ── PRODUCTS ─────────────────────────────────────────────────────────────

    @app_commands.command(name="addproduct", description="Add a new product/cheat (Admin)")
    @app_commands.describe(name='Display name (e.g. "Free Fire")')
    async def addproduct(self, interaction: discord.Interaction, name: str):
        if await self._admin_check(interaction):
            return
        if await db.get_product_by_name(name):
            return await interaction.response.send_message(embed=error_embed(f"**{name}** already exists."), ephemeral=True)
        product = await db.add_product(name)
        embed = mango_embed("🥭  Product Added", f"**{name}** created!\n{DIVIDER}\n\n**Product ID:** `{product['id']}`\n\n⚠️ **Next:** Add variants with `/addvariant`")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removeproduct", description="Remove a product and ALL its variants/keys (Admin)")
    @app_commands.describe(product_id="Product ID to remove")
    async def removeproduct(self, interaction: discord.Interaction, product_id: int):
        if await self._admin_check(interaction):
            return
        product = await db.get_product(product_id)
        if not product:
            return await interaction.response.send_message(embed=error_embed("Product not found."), ephemeral=True)
        await db.remove_product(product_id)
        await interaction.response.send_message(embed=success_embed(f"**{product['display_name']}** and all variants/stock/keys removed."))

    @app_commands.command(name="toggleproduct", description="Enable or disable an entire product (Admin)")
    @app_commands.describe(product_id="Product ID", status="Enable or disable")
    @app_commands.choices(status=[
        app_commands.Choice(name="🟢 Enable", value="enable"),
        app_commands.Choice(name="🔴 Disable", value="disable"),
    ])
    async def toggleproduct(self, interaction: discord.Interaction, product_id: int, status: str):
        if await self._admin_check(interaction):
            return
        product = await db.get_product(product_id)
        if not product:
            return await interaction.response.send_message(embed=error_embed("Product not found."), ephemeral=True)
        await db.set_product_enabled(product_id, status == "enable")
        emoji = "🟢" if status == "enable" else "🔴"
        await interaction.response.send_message(embed=success_embed(f"{emoji} **{product['display_name']}** **{status}d**."))

    # ── VARIANTS ─────────────────────────────────────────────────────────────

    @app_commands.command(name="addvariant", description="Add a variant/tier to a product (Admin)")
    @app_commands.describe(product_id="Product ID", name='e.g. "3 Day", "Lifetime"', price="Balance cost", type="How keys are supplied")
    @app_commands.choices(type=[
        app_commands.Choice(name="📦 Stock — manually load keys", value="stock"),
        app_commands.Choice(name="🌐 API — keys from a URL", value="api"),
    ])
    async def addvariant(self, interaction: discord.Interaction, product_id: int, name: str, price: int, type: str):
        if await self._admin_check(interaction):
            return
        if price < 1:
            return await interaction.response.send_message(embed=error_embed("Price must be at least **1**."), ephemeral=True)
        product = await db.get_product(product_id)
        if not product:
            return await interaction.response.send_message(embed=error_embed("Product not found."), ephemeral=True)
        variant = await db.add_variant(product_id, name, price, type)
        next_step = f"`/setupapi variant_id:{variant['id']}`" if type == "api" else f"`/stock variant_id:{variant['id']}`"
        type_display = "🌐 API" if type == "api" else "📦 Stock"
        embed = mango_embed(
            "✨  Variant Added",
            f"**{product['display_name']}** — {name}\n{DIVIDER}\n\n"
            f"**Variant ID:** `{variant['id']}`\n"
            f"**Price:** {price} bal\n"
            f"**Type:** {type_display}\n\n"
            f"⚠️ **Next:** {next_step}"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removevariant", description="Remove a variant and its stock/keys (Admin)")
    @app_commands.describe(variant_id="Variant ID to remove")
    async def removevariant(self, interaction: discord.Interaction, variant_id: int):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        label = f"{variant['product_name']} — {variant['name']}"
        await db.remove_variant(variant_id)
        await interaction.response.send_message(embed=success_embed(f"**{label}** and all stock/keys removed."))

    @app_commands.command(name="togglevariant", description="Enable or disable a variant (Admin)")
    @app_commands.describe(variant_id="Variant ID", status="Enable or disable")
    @app_commands.choices(status=[
        app_commands.Choice(name="🟢 Enable", value="enable"),
        app_commands.Choice(name="🔴 Disable", value="disable"),
    ])
    async def togglevariant(self, interaction: discord.Interaction, variant_id: int, status: str):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        await db.set_variant_enabled(variant_id, status == "enable")
        emoji = "🟢" if status == "enable" else "🔴"
        label = f"{variant['product_name']} — {variant['name']}"
        await interaction.response.send_message(embed=success_embed(f"{emoji} **{label}** **{status}d**."))

    @app_commands.command(name="setprice", description="Set the price of a variant (Admin)")
    @app_commands.describe(variant_id="Variant ID", price="New price per key")
    async def setprice(self, interaction: discord.Interaction, variant_id: int, price: int):
        if await self._admin_check(interaction):
            return
        if price < 1:
            return await interaction.response.send_message(embed=error_embed("Price must be at least **1**."), ephemeral=True)
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        await db.set_variant_price(variant_id, price)
        label = f"{variant['product_name']} — {variant['name']}"
        await interaction.response.send_message(embed=success_embed(f"**{label}** → **{price}** bal per key"))

    # ── API CONFIG ────────────────────────────────────────────────────────────

    @app_commands.command(name="setupapi", description="Configure API for an api-type variant (Admin)")
    @app_commands.describe(
        variant_id="Variant ID", url="Full API URL", method="HTTP method",
        key_path='JSON path to key (e.g. "key" or "data.license")',
        headers="JSON headers", body="JSON body for POST",
    )
    @app_commands.choices(method=[
        app_commands.Choice(name="GET", value="GET"),
        app_commands.Choice(name="POST", value="POST"),
    ])
    async def setupapi(self, interaction: discord.Interaction, variant_id: int, url: str,
                       method: str, key_path: str, headers: str = "{}", body: str = "{}"):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        if variant["type"] != "api":
            return await interaction.response.send_message(embed=error_embed("This variant is **stock**, not API."), ephemeral=True)
        for label_name, val in [("headers", headers), ("body", body)]:
            try:
                json.loads(val)
            except json.JSONDecodeError:
                return await interaction.response.send_message(embed=error_embed(f"Invalid JSON in {label_name}."), ephemeral=True)
        await db.update_variant_api(variant_id, url, method, headers, body, key_path)
        label = f"{variant['product_name']} — {variant['name']}"
        embed = mango_embed("🌐  API Configured", f"**{label}**\n{DIVIDER_SHORT}\n\n**URL:** `{url}`\n**Method:** {method}\n**Key Path:** `{key_path}`")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── STOCK ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="stock", description="Add keys to a stock-type variant (Admin)")
    @app_commands.describe(variant_id="Variant ID to stock", keys="Keys separated by commas, semicolons, or newlines")
    async def stock(self, interaction: discord.Interaction, variant_id: int, keys: str):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        if variant["type"] != "stock":
            return await interaction.response.send_message(embed=error_embed("This variant uses **API**, not stock."), ephemeral=True)
        key_list = [k.strip() for k in keys.replace("\n", ",").replace(";", ",").split(",") if k.strip()]
        if not key_list:
            return await interaction.response.send_message(embed=error_embed("No valid keys found."), ephemeral=True)
        added = await db.add_stock_keys(variant_id, key_list)
        total = await db.get_stock_count(variant_id)
        label = f"{variant['product_name']} — {variant['name']}"
        await interaction.response.send_message(embed=success_embed(f"Added **{added}** key(s) to **{label}**\n{DIVIDER_SHORT}\n📦 Total stock: **{total}**"))

    @app_commands.command(name="stockcount", description="View stock levels for all variants (Admin)")
    async def stockcount(self, interaction: discord.Interaction):
        if await self._admin_check(interaction):
            return
        stocks = await db.get_all_stock_counts()
        if not stocks:
            return await interaction.response.send_message(embed=mango_embed("📦  Stock Levels", "No products/variants yet."), ephemeral=True)
        groups = {}
        for s in stocks:
            groups.setdefault(s["product_name"], []).append(s)
        lines = []
        for product_name, variants in groups.items():
            lines.append(f"**{product_name}**")
            for s in variants:
                t_icon = "🌐" if s["type"] == "api" else "📦"
                s_icon = "🟢" if s["enabled"] else "🔴"
                if s["type"] == "api":
                    stock_d = "∞ *(API)*"
                elif s["remaining"] == 0:
                    stock_d = "**0** 🔴"
                elif s["remaining"] <= 3:
                    stock_d = f"**{s['remaining']}** ⚠️"
                else:
                    stock_d = f"**{s['remaining']}**"
                lines.append(f"> {s_icon} {t_icon}  **{s['variant_name']}** — Stock: {stock_d}  •  {s['price']} bal  •  ID: `{s['id']}`")
            lines.append("")
        chunks = paginate_items(lines, 12)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n" + "\n".join(chunk)
            pages.append(mango_embed(f"📦  Stock Levels — Page {i}/{len(chunks)}", desc))
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True)


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(Products(bot), guild=guild)
