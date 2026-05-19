# cogs/products.py — Product & variant management (server-only, admin-only).

import json
import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
import aegis as aegis_api
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
            await interaction.response.send_message(
                embed=error_embed("🔒 Only the bot owner can use this command."), ephemeral=True
            )
            return True
        return False

    # ── Autocomplete helpers ──────────────────────────────────────────────────

    async def all_variants_autocomplete(self, interaction, current):
        """Shows ALL variants (enabled + disabled) for admin commands."""
        products = await db.get_all_products()
        choices = []
        for p in products:
            variants = await db.get_variants_for_product(p["id"])
            for v in variants:
                status = "🟢" if v["enabled"] else "🔴"
                label = f"{status} {p['display_name']} — {v['name']} ({v['price']} bal)"
                if current.lower() in label.lower():
                    choices.append(app_commands.Choice(name=label[:100], value=v["id"]))
                if len(choices) >= 25:
                    return choices
        return choices

    async def all_products_autocomplete(self, interaction, current):
        """Shows all products for admin commands."""
        products = await db.get_all_products()
        choices = []
        for p in products:
            label = f"{p['display_name']} (ID: {p['id']})"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=p["id"]))
            if len(choices) >= 25:
                return choices
        return choices

    # ── PRODUCTS ─────────────────────────────────────────────────────────────

    @app_commands.command(name="addproduct", description="Add a new product/cheat (Admin)")
    @app_commands.describe(name='Display name (e.g. "Free Fire", "Valorant")')
    async def addproduct(self, interaction: discord.Interaction, name: str):
        if await self._admin_check(interaction):
            return
        if await db.get_product_by_name(name):
            return await interaction.response.send_message(
                embed=error_embed(f"**{name}** already exists."), ephemeral=True
            )
        product = await db.add_product(name)
        embed = mango_embed(
            "🥭  Product Added",
            f"**{name}** created!\n{DIVIDER}\n\n"
            f"**Product ID:** `{product['id']}`\n\n"
            f"⚠️ **Next:** Add variants with `/addvariant`"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removeproduct", description="Remove a product and ALL its variants/keys (Admin)")
    @app_commands.describe(product_id="Product to remove")
    @app_commands.autocomplete(product_id=all_products_autocomplete)
    async def removeproduct(self, interaction: discord.Interaction, product_id: int):
        if await self._admin_check(interaction):
            return
        product = await db.get_product(product_id)
        if not product:
            return await interaction.response.send_message(embed=error_embed("Product not found."), ephemeral=True)
        await db.remove_product(product_id)
        await interaction.response.send_message(
            embed=success_embed(f"**{product['display_name']}** and all variants/stock/keys removed.")
        )

    @app_commands.command(name="toggleproduct", description="Enable or disable an entire product (Admin)")
    @app_commands.describe(product_id="Product to toggle", status="Enable or disable")
    @app_commands.autocomplete(product_id=all_products_autocomplete)
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
        await interaction.response.send_message(
            embed=success_embed(f"{emoji} **{product['display_name']}** **{status}d**.")
        )

    # ── VARIANTS ─────────────────────────────────────────────────────────────

    @app_commands.command(name="addvariant", description="Add a variant/tier to a product (Admin)")
    @app_commands.describe(
        product_id="Product to add this variant to",
        name='Variant name e.g. "3 Day", "7 Day", "Lifetime"',
        price="Your internal balance cost per key",
        type="How keys are supplied",
    )
    @app_commands.autocomplete(product_id=all_products_autocomplete)
    @app_commands.choices(type=[
        app_commands.Choice(name="📦 Stock — manually load keys", value="stock"),
        app_commands.Choice(name="🔑 Aegis — Aegis Online reseller API", value="aegis"),
        app_commands.Choice(name="🌐 API — generic external API", value="api"),
    ])
    async def addvariant(self, interaction: discord.Interaction, product_id: int,
                         name: str, price: int, type: str):
        if await self._admin_check(interaction):
            return
        if price < 1:
            return await interaction.response.send_message(
                embed=error_embed("Price must be at least **1**."), ephemeral=True
            )
        product = await db.get_product(product_id)
        if not product:
            return await interaction.response.send_message(embed=error_embed("Product not found."), ephemeral=True)

        variant = await db.add_variant(product_id, name, price, type)
        type_icons = {"stock": "📦 Stock", "aegis": "🔑 Aegis", "api": "🌐 Generic API"}
        type_display = type_icons.get(type, type)

        if type == "aegis":
            next_step = (
                f"1. Run `/aegisservices` to see available category and service IDs\n"
                f"2. Run `/setaegis` and pick this variant to link it"
            )
        elif type == "api":
            next_step = (
                f"1. Run `/setupapi` and pick this variant to configure key gen URL\n"
                f"2. Run `/setapibalance` to configure balance tracking"
            )
        else:
            next_step = f"Run `/stock variant_id:{variant['id']}` to load keys"

        embed = mango_embed(
            "✨  Variant Added",
            f"**{product['display_name']}** — {name}\n{DIVIDER}\n\n"
            f"**Variant ID:** `{variant['id']}`\n"
            f"**Price:** {price} bal\n"
            f"**Type:** {type_display}\n\n"
            f"⚠️ **Next steps:**\n{next_step}"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removevariant", description="Remove a variant and its stock/keys (Admin)")
    @app_commands.describe(variant_id="Variant to remove")
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
    async def removevariant(self, interaction: discord.Interaction, variant_id: int):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        label = f"{variant['product_name']} — {variant['name']}"
        await db.remove_variant(variant_id)
        await interaction.response.send_message(
            embed=success_embed(f"**{label}** and all stock/keys removed.")
        )

    @app_commands.command(name="togglevariant", description="Enable or disable a variant (Admin)")
    @app_commands.describe(variant_id="Variant to toggle", status="Enable or disable")
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
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
        await interaction.response.send_message(
            embed=success_embed(f"{emoji} **{label}** **{status}d**.")
        )

    @app_commands.command(name="setprice", description="Set the price of a variant (Admin)")
    @app_commands.describe(variant_id="Variant to update", price="New internal balance cost per key")
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
    async def setprice(self, interaction: discord.Interaction, variant_id: int, price: int):
        if await self._admin_check(interaction):
            return
        if price < 1:
            return await interaction.response.send_message(
                embed=error_embed("Price must be at least **1**."), ephemeral=True
            )
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        old_price = variant["price"]
        await db.set_variant_price(variant_id, price)
        label = f"{variant['product_name']} — {variant['name']}"
        await interaction.response.send_message(
            embed=success_embed(f"**{label}**\n{DIVIDER_SHORT}\n{old_price} bal → **{price}** bal per key")
        )

    # ── AEGIS SETUP ──────────────────────────────────────────────────────────

    @app_commands.command(name="setaegis", description="Link a variant to an Aegis category + service (Admin)")
    @app_commands.describe(
        variant_id="Aegis variant to configure",
        category="Aegis category ID (use /aegisservices to look up)",
        service="Aegis service ID (use /aegisservices to look up)",
    )
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
    async def setaegis(self, interaction: discord.Interaction, variant_id: int,
                       category: int, service: int):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        if variant["type"] != "aegis":
            return await interaction.response.send_message(
                embed=error_embed(
                    f"This variant is type **{variant['type']}**, not Aegis.\n"
                    f"Create a new variant with type 'Aegis' if needed."
                ),
                ephemeral=True,
            )
        await db.update_variant_aegis(variant_id, category, service)
        label = f"{variant['product_name']} — {variant['name']}"
        embed = mango_embed(
            "🔑  Aegis Variant Configured",
            f"**{label}** is ready.\n{DIVIDER_SHORT}\n\n"
            f"**Category ID:** `{category}`\n"
            f"**Service ID:** `{service}`\n\n"
            f"Sellers can now generate keys for this variant.\n"
            f"Balance before/after will be logged automatically on every gen."
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="aegisservices", description="List available services on the Aegis API (Admin)")
    async def aegisservices(self, interaction: discord.Interaction):
        if await self._admin_check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not cfg.AEGIS_API_KEY or not cfg.AEGIS_API_SECRET:
            return await interaction.followup.send(
                embed=error_embed(
                    "Aegis API credentials not set.\n\n"
                    "Add `AEGIS_API_KEY` and `AEGIS_API_SECRET` to your Railway environment variables."
                )
            )
        services = await aegis_api.list_services()
        if not services:
            return await interaction.followup.send(
                embed=error_embed("Could not fetch services from Aegis API.\n\nCheck your credentials or try again.")
            )
        lines = [f"{DIVIDER}\n"]
        for s in services:
            svc_id = s.get("id") or s.get("service_id") or "?"
            cat_id = s.get("category_id") or s.get("category") or "?"
            svc_name = s.get("name") or s.get("service_name") or "Unknown"
            price = s.get("price") or s.get("unit_price") or "?"
            lines.append(f"**{svc_name}**\n> Category: `{cat_id}`  •  Service: `{svc_id}`  •  Price: {price}\n")
        chunks = paginate_items(lines, 10)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            pages.append(mango_embed(f"🔑  Aegis Services — Page {i}/{len(chunks)}", "\n".join(chunk)))
        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0])
        else:
            await interaction.followup.send(embed=pages[0], view=PaginatorView(pages, interaction.user.id))

    # ── GENERIC API SETUP ────────────────────────────────────────────────────

    @app_commands.command(name="setupapi", description="Configure key gen URL for a generic API variant (Admin)")
    @app_commands.describe(
        variant_id="API variant to configure",
        url="Full API URL",
        method="HTTP method",
        key_path='JSON path to the key (e.g. "key" or "data.license")',
        headers="Optional JSON headers",
        body="Optional JSON body for POST",
    )
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
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
            return await interaction.response.send_message(
                embed=error_embed("This variant is not generic API type. Use `/setaegis` for Aegis variants."),
                ephemeral=True,
            )
        for label_name, val in [("headers", headers), ("body", body)]:
            try:
                json.loads(val)
            except json.JSONDecodeError:
                return await interaction.response.send_message(
                    embed=error_embed(f"Invalid JSON in {label_name}."), ephemeral=True
                )
        await db.update_variant_api(variant_id, url, method, headers, body, key_path)
        label = f"{variant['product_name']} — {variant['name']}"
        embed = mango_embed(
            "🌐  Key API Configured",
            f"**{label}**\n{DIVIDER_SHORT}\n\n"
            f"**URL:** `{url}`\n**Method:** {method}\n**Key Path:** `{key_path}`"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setapibalance", description="Configure balance check URL for a generic API variant (Admin)")
    @app_commands.describe(
        variant_id="API variant to configure",
        url="URL that returns your current external balance",
        balance_path='JSON path to balance (e.g. "balance" or "data.credits")',
    )
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
    async def setapibalance(self, interaction: discord.Interaction, variant_id: int,
                            url: str, balance_path: str = "balance"):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        if variant["type"] != "api":
            return await interaction.response.send_message(
                embed=error_embed("This is only for generic API variants. Aegis balance is tracked automatically."),
                ephemeral=True,
            )
        await db.update_variant_balance_check(variant_id, url, balance_path)
        label = f"{variant['product_name']} — {variant['name']}"
        embed = mango_embed(
            "💳  Balance Tracking Configured",
            f"**{label}**\n{DIVIDER_SHORT}\n\n"
            f"**Balance URL:** `{url}`\n**Balance Path:** `{balance_path}`"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── STOCK ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="stock", description="Add keys to a stock-type variant (Admin)")
    @app_commands.describe(variant_id="Stock variant to add keys to", keys="Keys separated by commas, semicolons, or newlines")
    @app_commands.autocomplete(variant_id=all_variants_autocomplete)
    async def stock(self, interaction: discord.Interaction, variant_id: int, keys: str):
        if await self._admin_check(interaction):
            return
        variant = await db.get_variant(variant_id)
        if not variant:
            return await interaction.response.send_message(embed=error_embed("Variant not found."), ephemeral=True)
        if variant["type"] != "stock":
            return await interaction.response.send_message(
                embed=error_embed("This variant doesn't use manual stock."), ephemeral=True
            )
        key_list = [k.strip() for k in keys.replace("\n", ",").replace(";", ",").split(",") if k.strip()]
        if not key_list:
            return await interaction.response.send_message(embed=error_embed("No valid keys found."), ephemeral=True)
        added = await db.add_stock_keys(variant_id, key_list)
        total = await db.get_stock_count(variant_id)
        label = f"{variant['product_name']} — {variant['name']}"
        await interaction.response.send_message(
            embed=success_embed(f"Added **{added}** key(s) to **{label}**\n{DIVIDER_SHORT}\n📦 Total stock: **{total}**")
        )

    @app_commands.command(name="stockcount", description="View stock levels for all variants (Admin)")
    async def stockcount(self, interaction: discord.Interaction):
        if await self._admin_check(interaction):
            return
        stocks = await db.get_all_stock_counts()
        if not stocks:
            return await interaction.response.send_message(
                embed=mango_embed("📦  Stock Levels", "No products/variants yet."), ephemeral=True
            )
        groups = {}
        for s in stocks:
            groups.setdefault(s["product_name"], []).append(s)
        lines = []
        for product_name, variants in groups.items():
            lines.append(f"**{product_name}**")
            for s in variants:
                icons = {"stock": "📦", "aegis": "🔑", "api": "🌐"}
                t_icon = icons.get(s["type"], "•")
                s_icon = "🟢" if s["enabled"] else "🔴"
                if s["type"] in ("aegis", "api"):
                    stock_d = "∞ *(Aegis)*" if s["type"] == "aegis" else "∞ *(API)*"
                elif s["remaining"] == 0:
                    stock_d = "**0** 🔴"
                elif s["remaining"] <= 3:
                    stock_d = f"**{s['remaining']}** ⚠️"
                else:
                    stock_d = f"**{s['remaining']}**"
                lines.append(
                    f"> {s_icon} {t_icon}  **{s['variant_name']}** — "
                    f"Stock: {stock_d}  •  {s['price']} bal  •  ID: `{s['id']}`"
                )
            lines.append("")
        chunks = paginate_items(lines, 12)
        pages = []
        for i, chunk in enumerate(chunks, 1):
            desc = f"{DIVIDER}\n\n" + "\n".join(chunk)
            pages.append(mango_embed(f"📦  Stock Levels — Page {i}/{len(chunks)}", desc))
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=pages[0], view=PaginatorView(pages, interaction.user.id), ephemeral=True
            )


async def setup(bot):
    guild = discord.Object(id=int(cfg.GUILD_ID))
    await bot.add_cog(Products(bot), guild=guild)

