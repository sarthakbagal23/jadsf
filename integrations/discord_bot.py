"""Discord — talk to EDITH from Discord. Run:  python -m integrations.discord_bot

NOTE: PersonalJarvis ships Telegram + Slack surfaces, not Discord — so
this bot is built fresh on discord.py. Same pattern as their surfaces:
messages in, brain out.

Setup:
  1. discord.com/developers -> New Application -> Bot -> copy the token
     as DISCORD_BOT_TOKEN in .env.
  2. Same page -> Privileged Gateway Intents -> turn on MESSAGE CONTENT INTENT.
  3. OAuth2 -> URL Generator -> scopes: bot; permissions: Send Messages,
     Read Message History -> open the URL, add the bot to your server.
  4. Run this file. It answers DMs and @mentions.
"""
import discord

import memory
from brain import ask
from config import DISCORD_BOT_TOKEN

if not DISCORD_BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN not set in .env — see the module docstring.")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"EDITH is on Discord as {client.user}.")


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    is_dm = isinstance(message.channel, discord.DMChannel)
    mentioned = client.user in message.mentions
    if not (is_dm or mentioned):
        return
    text = message.content.replace(f"<@{client.user.id}>", "").strip()
    if not text:
        return
    history = memory.recent_history(10)
    messages = [{"role": r, "content": t} for r, t in history]
    messages.append({"role": "user", "content": text})
    reply = ask(messages)
    memory.log("user", text)
    memory.log("assistant", reply)
    await message.channel.send(reply[:2000])


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)
