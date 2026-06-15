# cogs/certs.py — Seller-facing cert generation commands (global, DMs + server).
# Sellers run /certgen, pick a plan, enter their UDID, get a zip with .p12 + .mobileprovision + readme.

import io
import re
import base64
import zipfile
import discord
from discord import app_commands
from discord.ext import commands
import config as cfg
import database as db
import nekoo
from helpers import (
    mango_embed, error_embed, success_embed, is_owner,
    requires_dm, dm_only_error, DIVIDER, DIVIDER_SHORT,
    send_log,
)

CERT_TUTORIAL = cfg.CERT_TUTORIAL


def seconds_to_days(seconds: int) -> str:
    days = seconds // 86400
    return f"{days} day(s)"


def plan_shown_name(plan_row: dict) -> str:
    """Returns display_name if set, else plan_name."""
    return (plan_row.get("display_name") or "").strip() or plan_row["plan_name"]


def cert_maintenance_embed():
    embed = discord.Embed(
        title="🔧  Cert Gen — Unavailable",
        description="Certificate generation is temporarily unavailable.\n\nPlease check back later.",
        color=discord.Colour.from_str("#FFA500"),
    )
    embed.set_footer(text=f"🥭 {cfg.BOT_FOOTER}")
    return embed


def build_cert_zip(cert: dict, plan_display_name: str) -> io.BytesIO:
    """Build a zip file containing p12, mobileprovision, and readme.txt."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if cert.get("p12"):
            zf.writestr("certificate.p12", base64.b64decode(cert["p12"]))
        if cert.get("mobileprovision"):
            zf.writestr("profile.mobileprovision", base64.b64decode(cert["mobileprovision"]))
        if cert.get("devp12"):
            zf.writestr("dev_certificate.p12", base64.b64decode(cert["devp12"]))
        if cert.get("devmp"):
            zf.writestr("dev_profile.mobileprovision", base64.b64decode(cert["devmp"]))

        warranty_days = seconds_to_days(cert.get("warranty_remaining_seconds", 0))
        readme = (
            "==============================\n"
            "  MangoMods Certificate Files\n"
            "==============================\n\n"
            f"Plan:          {plan_display_name}\n"
            f"Certificate:   {cert.get('pname', 'N/A')}\n"
            f"UDID:          {cert.get('udid', 'N/A')}\n"
            f"Status:        {cert.get('status', 'N/A')}\n"
            f"Warranty left: {warranty_days}\n\n"
            "------------------------------\n"
            "  INSTALLATION\n"
            "------------------------------\n\n"
            f"P12 Password:  {cert.get('p12_password', '1')}\n\n"
            "For step-by-step installation instructions:\n"
            f"{CERT_TUTORIAL}\n\n"
            "------------------------------\n"
            "  FILES INCLUDED\n"
            "------------------------------\n\n"
            "  certificate.p12          - Main signing certificate\n"
            "  profile.mobileprovision  - Main provisioning profile\n"
        )
        if cert.get("devp12"):
            readme += "  dev_certificate.p12      - Dev certificate\n"
        if cert.get("devmp"):
            readme += "  dev_profile.mobileprovision - Dev provisioning profile\n"
        readme += (
            "\n------------------------------\n"
            "  SUPPORT\n"
            "------------------------------\n\n"
            "If you have any issues, contact your reseller.\n"
            f"Tutorial: {CERT_TUTORIAL}\n"
        )
        zf.writestr("README.txt", readme)

    buf.seek(0)
    return buf


def log_cert_gen(user, plan_name, udid, cert_id, seller_cost, already_registered, balance_before, balance_after):
    embed = discord.Embed(
        title="Cert Generated",
        color=discord.Colour.from_str("#00C49A"),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Seller", value=f"{user.mention} (`{user.name}`)", inline=True)
    embed.add_field(name="Plan", value=plan_name, inline=True)
    embed.add_field(name="UDID", value=f"`{udid}`", inline=False)
    embed.add_field(name="Cert ID", value=f"`{cert_id}`", inline=True)
    embed.add_field(name="Already registered", value="Yes (free)" if already_registered else "No", inline=True)
    embed.add_field(name="Cost", value=f"{seller_cost} bal", inline=True)
    embed.add_field(name="Balance", value=f"{balance_before} -> **{balance_after}**", inline=True)
    embed.set_footer(text=f"User ID: {user.id}")
    return embed


class Certs(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def plan_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            plans = await db.cert_get_enabled_plans()
            choices = []
            for p in plans:
                shown = plan_shown_name(p)
                label = f"{shown} -- {p['seller_price']} bal"
                if current.lower() in label.lower():
                    choices.append(app_commands.Choice(name=label[:100], value=p["plan_id"]))
            return choices[:25]
        except Exception:
            return []

    # ── CERT GEN ─────────────────────────────────────────────────────────────

    @app_commands.command(name="certgen", description="Generate an iOS certificate for a UDID (Sellers only)")
    @app_commands.describe(
        plan="Select a cert plan",
        udid="Device UDID (from your device settings or a UDID tool)",
    )
    @app_commands.autocomplete(plan=plan_autocomplete)
    async def certgen(self, interaction: discord.Interaction, plan: str, udid: str):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)

        owner_mode = is_owner(interaction)

        # Cert maintenance check (owner bypasses)
        if not owner_mode and await db.is_cert_maintenance():
            return await interaction.response.send_message(embed=cert_maintenance_embed(), ephemeral=True)

        await interaction.response.defer(ephemeral=interaction.guild is not None)

        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)

        if not user["is_seller"] and not owner_mode:
            return await interaction.followup.send(
                embed=error_embed("You need **seller permissions** to use this command.")
            )

        if not cfg.NEKOO_API_KEY:
            return await interaction.followup.send(
                embed=error_embed("Nekoo API key not configured. Contact the owner.")
            )

        plan_row = await db.cert_get_plan(plan)
        if not plan_row:
            return await interaction.followup.send(
                embed=error_embed("Plan not found. Use `/certplans` to see available plans.")
            )
        if not plan_row["enabled"]:
            return await interaction.followup.send(
                embed=error_embed(f"**{plan_shown_name(plan_row)}** is currently disabled.")
            )

        seller_cost = plan_row["seller_price"]
        balance_before = user["balance"]
        shown_name = plan_shown_name(plan_row)

        if not owner_mode and user["balance"] < seller_cost:
            return await interaction.followup.send(
                embed=error_embed(
                    f"**Not enough balance.**\n\n"
                    f"Need: **{seller_cost}**  Have: **{user['balance']}**"
                )
            )

        try:
            result = await nekoo.register(udid=udid.strip(), plan_id=plan)
        except Exception as e:
            err = str(e)
            if "insufficient_balance" in err:
                return await interaction.followup.send(embed=error_embed("Nekoo account is out of balance. Contact the owner."))
            if "invalid_udid" in err:
                return await interaction.followup.send(embed=error_embed(f"Invalid UDID format: `{udid.strip()}`\n\nMake sure you copied the full UDID correctly."))
            if "plan_locked" in err:
                return await interaction.followup.send(embed=error_embed("This plan is not available. Try a different one or contact the owner."))
            return await interaction.followup.send(embed=error_embed(f"Nekoo API error:\n`{err}`"))

        cert = result.get("certificate", {})
        already_registered = result.get("already_registered", False)
        cert_id = result.get("certificate_id", cert.get("id", "?"))
        nekoo_cost = result.get("cost", 0)

        actual_cost = 0 if already_registered else seller_cost
        if not owner_mode and not already_registered:
            await db.subtract_balance(str(interaction.user.id), seller_cost)

        updated_user = await db.get_user(str(interaction.user.id))
        balance_after = updated_user["balance"] if updated_user else balance_before

        await db.cert_record_order(
            user_id=str(interaction.user.id),
            udid=udid.strip(),
            certificate_id=str(cert_id),
            plan_id=plan,
            plan_name=shown_name,
            nekoo_cost=nekoo_cost,
            seller_cost=actual_cost,
            already_registered=already_registered,
        )

        zip_buf = build_cert_zip(cert, shown_name)
        zip_file = discord.File(zip_buf, filename=f"MangoMods_Cert_{udid.strip()[:8]}.zip")

        warranty_days = seconds_to_days(cert.get("warranty_remaining_seconds", 0))
        if already_registered:
            cost_line = "Already registered -- **no charge**"
        elif owner_mode:
            cost_line = "Owner mode -- **no charge**"
        else:
            cost_line = f"Cost: **{seller_cost}** bal  Remaining: **{balance_after}**"

        embed = mango_embed(
            "Certificate Ready",
            f"**{shown_name}**\n{DIVIDER}\n\n"
            f"**UDID:** `{udid.strip()}`\n"
            f"**Status:** {cert.get('status', 'N/A')}\n"
            f"**Warranty:** {warranty_days}\n"
            f"**P12 Password:** `{cert.get('p12_password', '1')}`\n\n"
            f"{cost_line}\n\n"
            f"Your cert files are in the zip below.\n"
            f"Tutorial: {CERT_TUTORIAL}"
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed, file=zip_file)

        await send_log(self.bot, log_cert_gen(
            user=interaction.user,
            plan_name=shown_name,
            udid=udid.strip(),
            cert_id=cert_id,
            seller_cost=actual_cost,
            already_registered=already_registered,
            balance_before=balance_before,
            balance_after=balance_after,
        ))

    # ── CERT CHECK ────────────────────────────────────────────────────────────

    @app_commands.command(name="certcheck", description="Check the status of a certificate by UDID")
    @app_commands.describe(udid="The device UDID to look up")
    async def certcheck(self, interaction: discord.Interaction, udid: str):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)

        owner_mode = is_owner(interaction)
        if not owner_mode and await db.is_cert_maintenance():
            return await interaction.response.send_message(embed=cert_maintenance_embed(), ephemeral=True)

        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        if not user["is_seller"] and not owner_mode:
            return await interaction.response.send_message(
                embed=error_embed("You need **seller permissions** to use this command."), ephemeral=True
            )

        if not cfg.NEKOO_API_KEY:
            return await interaction.response.send_message(
                embed=error_embed("Nekoo API key not configured."), ephemeral=True
            )

        await interaction.response.defer(ephemeral=interaction.guild is not None)

        try:
            result = await nekoo.get_certificate(udid=udid.strip())
        except Exception as e:
            err = str(e)
            if "not_found" in err:
                return await interaction.followup.send(
                    embed=mango_embed("No Certificate Found", f"No certificate found for UDID:\n`{udid.strip()}`")
                )
            return await interaction.followup.send(embed=error_embed(f"API error:\n`{err}`"))

        certs = result.get("certificates", [])
        if not certs:
            return await interaction.followup.send(
                embed=mango_embed("No Certificate Found", f"No certificates found for UDID:\n`{udid.strip()}`")
            )

        active = next((c for c in certs if c.get("status") == "signed" and c.get("provision_valid")), certs[0])
        status_icon = "🟢" if active.get("status") == "signed" and active.get("provision_valid") else "🔴"
        warranty_days = seconds_to_days(active.get("warranty_remaining_seconds", 0))

        embed = mango_embed(
            "Certificate Status",
            f"**UDID:** `{udid.strip()}`\n{DIVIDER}\n\n"
            f"**Status:** {status_icon} {active.get('status', 'N/A')}\n"
            f"**Valid:** {'Yes' if active.get('provision_valid') else 'No'}\n"
            f"**Expired:** {'Yes' if active.get('expired') else 'No'}\n"
            f"**Warranty left:** {warranty_days}\n"
            f"**Cert ID:** `{active.get('id', 'N/A')}`\n"
            f"**Plan:** {active.get('plan', 'N/A')}\n"
            f"**Cert name:** {active.get('pname', 'N/A')}"
        )
        if len(certs) > 1:
            embed.set_footer(text=f"🥭 {len(certs)} cert(s) found for this UDID -- showing most recent active")
        await interaction.followup.send(embed=embed)

    # ── CERT PLANS ────────────────────────────────────────────────────────────

    @app_commands.command(name="certplans", description="View available certificate plans and prices")
    async def certplans(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)

        owner_mode = is_owner(interaction)
        if not owner_mode and await db.is_cert_maintenance():
            return await interaction.response.send_message(embed=cert_maintenance_embed(), ephemeral=True)

        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        if not user["is_seller"] and not owner_mode:
            return await interaction.response.send_message(
                embed=error_embed("You need **seller permissions** to use this command."), ephemeral=True
            )

        plans = await db.cert_get_enabled_plans()
        if not plans:
            return await interaction.response.send_message(
                embed=mango_embed("Cert Plans", "No cert plans available right now."), ephemeral=True
            )

        desc = f"{DIVIDER}\n\n"
        for p in plans:
            desc += f"**{plan_shown_name(p)}**\n> Price: **{p['seller_price']}** bal\n\n"

        embed = mango_embed("Available Cert Plans", desc)
        embed.set_footer(text="Use /certgen to generate a certificate")
        await interaction.response.send_message(embed=embed, ephemeral=interaction.guild is not None)

    # ── MY CERTS ──────────────────────────────────────────────────────────────

    @app_commands.command(name="mycerts", description="View your cert generation history")
    async def mycerts(self, interaction: discord.Interaction):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)

        owner_mode = is_owner(interaction)
        if not owner_mode and await db.is_cert_maintenance():
            return await interaction.response.send_message(embed=cert_maintenance_embed(), ephemeral=True)

        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        if not user["is_seller"] and not owner_mode:
            return await interaction.response.send_message(
                embed=error_embed("You need **seller permissions** to use this command."), ephemeral=True
            )

        orders = await db.cert_get_user_orders(str(interaction.user.id))
        if not orders:
            return await interaction.response.send_message(
                embed=mango_embed("Your Certs", "No certs generated yet.\n\nUse `/certgen` to get started!"),
                ephemeral=interaction.guild is not None,
            )

        desc = f"{DIVIDER}\n\n"
        for o in orders[:15]:
            free = " *(free -- already registered)*" if o["already_registered"] else ""
            desc += (
                f"**{o['plan_name']}**{free}\n"
                f"> UDID: `{o['udid'][:20]}...`\n"
                f"> Cert ID: `{o['certificate_id']}`\n"
                f"> Cost: **{o['seller_cost']}** bal  {o['created_at'][:10]}\n\n"
            )

        embed = mango_embed(f"Your Certs ({len(orders)} total)", desc)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=interaction.guild is not None)


    # ── UDID CHECK ────────────────────────────────────────────────────────────

    @app_commands.command(name="udidcheck", description="Validate a UDID and check for existing certs")
    @app_commands.describe(udid="Your device UDID to validate (optional)")
    async def udidcheck(self, interaction: discord.Interaction, udid: str = None):
        if requires_dm(interaction):
            return await interaction.response.send_message(embed=dm_only_error(), ephemeral=True)

        user = await db.ensure_user(str(interaction.user.id), interaction.user.name)
        if not user["is_seller"] and not is_owner(interaction):
            return await interaction.response.send_message(
                embed=error_embed("You need **seller permissions** to use this command."), ephemeral=True
            )

        await interaction.response.defer(ephemeral=interaction.guild is not None)

        # UDID format patterns
        # Old style: 40 hex chars
        # New style: 8-16-hex format like 00008030-001A2B3C4D5E6F78
        UDID_OLD = re.compile(r'^[0-9a-fA-F]{40}
)
        UDID_NEW = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{16}
)

        # Pull custom steps from DB
        custom_steps = await db.get_setting("udid_steps", default="")
        default_steps = (
            "1. On your iPhone/iPad go to **Settings > General > VPN & Device Management**\n"
            "2. If no profile is there, visit **udid.tech** on Safari on your device\n"
            "3. Tap **Find My UDID** and install the profile when prompted\n"
            "4. Go back to Settings, tap the new profile, and copy the UDID shown\n"
            "5. Paste it into `/certgen` to generate your certificate"
        )
        steps = custom_steps if custom_steps else default_steps

        embed = mango_embed("UDID Check", "")

        # If UDID provided, validate it
        if udid:
            udid = udid.strip()
            valid_format = bool(UDID_OLD.match(udid) or UDID_NEW.match(udid))

            if not valid_format:
                embed.description = (
                    f"**UDID:** `{udid}`\n"
                    f"**Format:** INVALID\n\n"
                    f"A UDID should be either:\n"
                    f"> 40 hex characters: `a1b2c3d4e5f6...` (40 chars)\n"
                    f"> New format: `00008030-001A2B3C4D5E6F78`\n\n"
                    f"Double-check you copied the full UDID."
                )
                embed.color = discord.Colour.red()
                return await interaction.followup.send(embed=embed)

            # Format is valid — check Nekoo for existing cert
            cert_status = ""
            if cfg.NEKOO_API_KEY:
                try:
                    result = await nekoo.get_certificate(udid=udid)
                    certs = result.get("certificates", [])
                    active = next((c for c in certs if c.get("status") == "signed" and c.get("provision_valid")), None)
                    if active:
                        warranty = seconds_to_days(active.get("warranty_remaining_seconds", 0))
                        cert_status = (
                            f"\n{DIVIDER_SHORT}\n"
                            f"**Existing cert found:**\n"
                            f"> Status: Active\n"
                            f"> Warranty left: {warranty}\n"
                            f"> Plan: {active.get('plan', 'N/A')}\n"
                            f"> If you re-register this UDID it will be **free** (cert already exists)."
                        )
                    elif certs:
                        cert_status = f"\n{DIVIDER_SHORT}\nA cert exists for this UDID but may be expired or invalid."
                    else:
                        cert_status = f"\n{DIVIDER_SHORT}\nNo existing cert found — ready to register."
                except Exception as e:
                    if "not_found" in str(e):
                        cert_status = f"\n{DIVIDER_SHORT}\nNo existing cert found — ready to register."
                    else:
                        cert_status = f"\n{DIVIDER_SHORT}\nCould not check for existing cert."

            embed.description = (
                f"**UDID:** `{udid}`\n"
                f"**Format:** Valid\n"
                f"{cert_status}"
            )
            embed.color = discord.Colour.green()
        else:
            embed.description = "No UDID provided. Here's how to find yours:"
            embed.color = discord.Colour(int(cfg.EMBED_COLOR, 16))

        # Always show steps and link
        embed.add_field(
            name="How to find your UDID",
            value=steps,
            inline=False,
        )
        embed.add_field(
            name="UDID Tool",
            value="[udid.tech](https://udid.tech) — open this in **Safari on your device**",
            inline=False,
        )

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Certs(bot))
