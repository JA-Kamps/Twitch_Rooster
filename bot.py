# Description: A Discord bot that notifies a channel when a Twitch streamer goes live.
import discord
from discord.ext import commands, tasks
from discord import app_commands
from twitchAPI.twitch import Twitch
import asyncio
import json
import mysql.connector

# Define your variables here
TWITCH_CLIENT_ID = ''
TWITCH_CLIENT_SECRET = ''
DISCORD_BOT_TOKEN = ''

# Define intents
intents = discord.Intents.default()
intents.message_content = True  # Enable the message content intent

# Discord bot setup
bot = commands.Bot(command_prefix='!', intents=intents)

# Use the existing command tree
tree = bot.tree

# Twitch API setup
twitch = Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)

# Database connection details
DB_HOST = ''
DB_PORT = 
DB_USER = ''
DB_PASSWORD = ''
DB_NAME = ''

# Database setup
conn = mysql.connector.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME
)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS streamer_channels
             (streamer_name VARCHAR(255), channel_id VARCHAR(255))''')
conn.commit()

def save_streamer_data(streamer_name, channel_id):
    c.execute("INSERT INTO streamer_channels (streamer_name, channel_id) VALUES (%s, %s)", (streamer_name, channel_id))
    conn.commit()

def remove_streamer_data(streamer_name, channel_id):
    c.execute("DELETE FROM streamer_channels WHERE streamer_name = %s AND channel_id = %s", (streamer_name, channel_id))
    conn.commit()

def load_streamer_data():
    c.execute("SELECT * FROM streamer_channels")
    return c.fetchall()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await twitch.authenticate_app([])
    check_streamers.start()

@bot.command()
@commands.is_owner()
async def sync(ctx: commands.Context) -> None:
    """Sync commands"""
    synced = await ctx.bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} commands globally")

@tree.command(name="add_streamer", description="Add a streamer to the notification list")
async def add_streamer(interaction: discord.Interaction, streamer_name: str, channel_id: str):
    if interaction.user.guild_permissions.administrator:
        existing_entries = c.execute("SELECT * FROM streamer_channels WHERE streamer_name = %s AND channel_id = %s", (streamer_name, channel_id)).fetchall()
        if not existing_entries:
            save_streamer_data(streamer_name, channel_id)
            await interaction.response.send_message(f'Added {streamer_name} to notifications in channel {channel_id}')
        else:
            await interaction.response.send_message(f'{streamer_name} is already being checked for notifications in channel {channel_id}')
    else:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

@tree.command(name="remove_streamer", description="Remove a streamer from the notification list")
async def remove_streamer(interaction: discord.Interaction, streamer_name: str, channel_id: str):
    if interaction.user.guild_permissions.administrator:
        existing_entries = c.execute("SELECT * FROM streamer_channels WHERE streamer_name = %s AND channel_id = %s", (streamer_name, channel_id)).fetchall()
        if existing_entries:
            remove_streamer_data(streamer_name, channel_id)
            await interaction.response.send_message(f'Removed {streamer_name} from notifications in channel {channel_id}')
        else:
            await interaction.response.send_message(f'{streamer_name} is not in the notification list for channel {channel_id}')
    else:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

@tree.command(name="list_streamers", description="List all streamers being checked for notifications in this guild")
async def list_streamers(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        guild_id = interaction.guild_id
        response = "Streamers being checked for notifications in this guild:\n"
        found = False
        for entry in load_streamer_data():
            streamer_name, channel_id = entry
            channel = bot.get_channel(int(channel_id))
            if channel and channel.guild.id == guild_id:
                response += f"- {streamer_name} in channel <#{channel_id}>\n"
                found = True
        if not found:
            response = "No streamers are currently being checked for notifications in this guild."
        await interaction.response.send_message(response)
    else:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

@tasks.loop(minutes=1)
async def check_streamers():
    for entry in load_streamer_data():
        streamer, channel_id = entry
        user_info = twitch.get_users(logins=[streamer])
        async for user in user_info:
            user_id = user.id
            stream_info = twitch.get_streams(user_id=user_id)
            async for stream in stream_info:
                channel = bot.get_channel(int(channel_id))
                embed = discord.Embed(
                    title=f'{streamer} is now live!',
                    description=stream.title,
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=user.profile_image_url)
                message = await channel.send(embed=embed)
                await asyncio.sleep(60)  # Check every minute
                while await twitch.get_streams(user_id=user_id):
                    await asyncio.sleep(60)
                await message.delete()

bot.run(DISCORD_BOT_TOKEN)
