# bot.py — Main entry point for Mango Bot.

import asyncio
import discord
from discord.ext import commands
import config as cfg
import database as db


class MangoBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.dm_messages = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await db.init_db()
        print("  ✅ Database initialized")

        cogs = [
            "cogs.admin",
            "cogs.products",
            "cogs.seller",
            "cogs.socials",
            "cogs.smb_admin",
        ]
        for cog in cogs:
            await self.load_extension(cog)
            print(f"  ✅ Loaded {cog}")

        guild = discord.Object(id=int(cfg.GUILD_ID))
        await self.tree.sync(guild=guild)
        await self.tree.sync()
        print("  ✅ Slash commands synced")

    async def on_ready(self):
        maint = await db.is_maintenance()
        print("")
        print("╔═══════════════════════════════════════╗")
        print("║          🥭  Mango Bot Online         ║")
        print(f"║  Logged in as {str(self.user).ljust(23)} ║")
        print(f"║  Serving {str(len(self.guilds)).ljust(3)} server(s)                ║")
        print("╚═══════════════════════════════════════╝")
        if maint:
            print("  ⚠️  MAINTENANCE MODE IS ON")
        print("")


async def main():
    bot = MangoBot()
    await bot.start(cfg.BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
