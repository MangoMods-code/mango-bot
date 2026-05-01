# 🥭 Mango Bot — Setup Guide

A Discord bot for reselling license keys, written in Python.
Sellers DM the bot to generate keys. Admin commands run in your server.

---

## Step 1: Create a Discord Bot Application

1. Go to https://discord.com/developers/applications
2. Click **"New Application"** → name it **Mango Bot** → click **Create**
3. On the left sidebar, click **"Bot"**
4. Click **"Reset Token"** → copy the token
5. Enable **Server Members Intent** (the bot needs this to check membership)
6. Click **Save Changes**

## Step 2: Invite the Bot to Your Server

1. On the left sidebar, click **"OAuth2"**
2. Under **Scopes**, check:
   - ✅ `bot`
   - ✅ `applications.commands`
3. Under **Bot Permissions**, check:
   - ✅ Send Messages
   - ✅ Embed Links
4. Copy the generated URL → open in browser → pick your server → authorize

## Step 3: Get Your IDs

Enable **Developer Mode** first: Discord Settings → Advanced → Developer Mode ON

| What          | How to get it                                              |
|---------------|------------------------------------------------------------|
| **BOT_TOKEN** | Developer Portal → Bot → Reset Token → copy               |
| **OWNER_ID**  | Right-click your name → Copy User ID                      |
| **GUILD_ID**  | Right-click your server name → Copy Server ID             |

## Step 4: Edit config.json

```json
{
  "BOT_TOKEN": "your-bot-token-here",
  "OWNER_ID": "your-user-id-here",
  "GUILD_ID": "your-server-id-here",
  "EMBED_COLOR": "FF8C00",
  "BOT_NAME": "Mango Bot",
  "BOT_FOOTER": "Mango Bot • Key Reseller"
}
```

## Step 5: Install & Run

```bash
cd ~/Desktop/reseller-bot
pip3 install -r requirements.txt
python3 bot.py
```

---

## How It Works

**Sellers DM the bot** to generate keys. They never need to type
commands in your server — everything happens in private DMs.

**You (the admin)** run management commands in your server.

### First-Time Setup:

1. **Add a product** (in your server):
   `/addproduct name:Free Fire price:1 type:Stock`

2. **Load keys** (stock type):
   `/stock product_id:1 keys:KEY-AAA,KEY-BBB,KEY-CCC`

3. **Or configure API** (api type):
   `/addproduct name:Fortnite price:2 type:API`
   `/setupapi product_id:2 url:https://api.site.com/gen?token=abc method:GET key_path:license`

4. **Make someone a seller** (in your server):
   `/setseller user:@someone action:Grant`

5. **Give them balance** (in your server):
   `/addbalance user:@someone amount:10`

6. **They DM the bot**:
   `/generatekey product_id:1`
   → Key delivered right in the DM!

---

## All Commands

### 📬 Seller Commands (DMs only)
| Command        | What it does                    |
|----------------|---------------------------------|
| `/generatekey` | Generate a key (costs balance)  |
| `/balance`     | Check your balance              |
| `/mykeys`      | See your generated keys         |
| `/products`    | See available products          |
| `/help`        | Show all commands               |

### 🔧 Admin — Users (Server only)
| Command          | What it does                   |
|------------------|--------------------------------|
| `/setseller`     | Grant/revoke seller            |
| `/addbalance`    | Add balance                    |
| `/setbalance`    | Set exact balance              |
| `/resetbalance`  | Reset to 0                     |
| `/viewusers`     | View all users & stats         |

### 🔧 Admin — Products (Server only)
| Command           | What it does                  |
|-------------------|-------------------------------|
| `/addproduct`     | Add a new product             |
| `/removeproduct`  | Remove a product              |
| `/setprice`       | Change price                  |
| `/toggleproduct`  | Enable/disable                |
| `/setupapi`       | Configure API endpoint        |
| `/stock`          | Load keys (stock type)        |
| `/stockcount`     | View stock levels             |

### 🔧 Admin — Keys (Server only)
| Command        | What it does                    |
|----------------|---------------------------------|
| `/bankey`      | Ban a key                       |
| `/unbankey`    | Unban a key                     |
| `/removekey`   | Permanently delete a key        |

---

## File Structure

```
reseller-bot/
├── bot.py              ← Run this to start
├── config.json         ← Your bot token & IDs
├── database.py         ← All database logic
├── helpers.py          ← Embed builders & utilities
├── requirements.txt    ← Python packages
├── SETUP.md            ← This file
├── cogs/
│   ├── admin.py        ← Admin commands (server-only)
│   ├── products.py     ← Product management (server-only)
│   └── seller.py       ← Seller commands (DMs)
└── data/
    └── bot.db          ← Auto-created on first run
```

---

## Keeping It Running

```bash
# Option A: screen
screen -S mangobot
python3 bot.py
# Ctrl+A then D to detach, screen -r mangobot to reattach

# Option B: background
nohup python3 bot.py > bot.log 2>&1 &
```

---

## Troubleshooting

- **Commands not showing** → Wait a few seconds after starting, global sync can take a minute
- **"This command only works in DMs"** → Seller commands must be used by DMing the bot
- **"Not in server"** → Seller must be a member of your GUILD_ID server
- **API keys failing** → Double-check `/setupapi` URL and key_path
- **ModuleNotFoundError** → Run `pip3 install -r requirements.txt`
