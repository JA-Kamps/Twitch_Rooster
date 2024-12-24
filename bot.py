# Description: A Discord bot that notifies a channel when a Twitch streamer goes live.
import discord
from discord.ext import commands, tasks
from discord import app_commands
from twitchAPI.twitch import Twitch
import asyncio
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
             (streamer_name VARCHAR(255), channel_id VARCHAR(255), role_id VARCHAR(255))''')
conn.commit()

def save_streamer_data(streamer_name, channel_id, role_id):
    c.execute("INSERT INTO streamer_channels (streamer_name, channel_id, role_id) VALUES (%s, %s, %s)", (streamer_name, channel_id, role_id))
    conn.commit()

def remove_streamer_data(streamer_name, guild_id):
    c.execute("DELETE FROM streamer_channels WHERE streamer_name = %s AND guild_id = %s", (streamer_name, guild_id))
    conn.commit()

def load_streamer_data():
    c.execute("SELECT streamer_name, channel_id, role_id FROM streamer_channels")
    return c.fetchall()

# Dictionary to keep track of live stream messages per channel and streamer
live_stream_messages = {}
live_status = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await twitch.authenticate_app([])
    check_streamers.start()
    check_channel_access.start()

@bot.command()
@commands.is_owner()
async def sync(ctx: commands.Context) -> None:
    """Sync commands"""
    synced = await ctx.bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} commands globally")

@tree.command(name="add_streamer", description="Add a streamer to the notification list")
async def add_streamer(interaction: discord.Interaction, streamer_name: str, channel_id: str = None, role_id: str = None):
    if interaction.user.guild_permissions.administrator:
        if channel_id is None:
            channel_id = str(interaction.channel_id)
        channel = bot.get_channel(int(channel_id))
        if channel and channel.guild.id == interaction.guild_id:
            c.execute("SELECT * FROM streamer_channels WHERE streamer_name = %s AND channel_id = %s", (streamer_name, channel_id))
            existing_entries = c.fetchall()
            if not existing_entries:
                save_streamer_data(streamer_name, channel_id, role_id)
                await interaction.response.send_message(f'Added {streamer_name} to notifications in channel <#{channel_id}>', ephemeral=True)
            else:
                await interaction.response.send_message(f'{streamer_name} is already being checked for notifications in channel <#{channel_id}>', ephemeral=True)
        else:
            await interaction.response.send_message("The specified channel is not in this guild.", ephemeral=True)
    else:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

@tree.command(name="remove_streamer", description="Remove a streamer from the notification list")
async def remove_streamer(interaction: discord.Interaction, streamer_name: str, channel_id: str = None):
    if channel_id is None:
            channel_id = str(interaction.channel_id)
    if interaction.user.guild_permissions.administrator:
        guild_id = str(interaction.guild_id)
        c.execute("DELETE FROM streamer_channels WHERE streamer_name = %s AND channel_id = %s", (streamer_name, channel_id))
        conn.commit()
        await interaction.response.send_message(f'Removed {streamer_name} from notifications in all channels of this guild.', ephemeral=True)
    else:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

@tree.command(name="list_streamers", description="List all streamers being checked for notifications in this guild")
async def list_streamers(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        guild_id = interaction.guild_id
        response = "Streamers being checked for notifications in this guild:\n"
        found = False
        for entry in load_streamer_data():
            streamer_name, channel_id, role_id = entry
            channel = bot.get_channel(int(channel_id))
            if channel and channel.guild.id == guild_id:
                role_mention = f'<@&{role_id}>' if role_id else 'No role assigned'
                response += f"- {streamer_name} in channel <#{channel_id}> (Role: {role_mention})\n"
                found = True
        if not found:
            response = "No streamers are currently being checked for notifications in this guild."
        await interaction.response.send_message(response, ephemeral=True)
    else:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

@tasks.loop(minutes=1)
async def check_streamers():
    for entry in load_streamer_data():
        streamer, channel_id, role_id = entry
        channel = bot.get_channel(int(channel_id))
        if channel:
            try:
                user_info = twitch.get_users(logins=[streamer])
                async for user in user_info:
                    user_id = user.id
                    stream_info = twitch.get_streams(user_id=user_id)
                    async for stream in stream_info:
                        thumbnail_url = stream.thumbnail_url.replace("{width}", "1280").replace("{height}", "720")
                        #tags = ', '.join(stream.tags)
                        embed = discord.Embed(
                            title=stream.title,
                            #description=tags,
                            color=discord.Color.green()
                        )
                        embed.set_thumbnail(url=user.profile_image_url)
                        embed.add_field(name="Game", value=stream.game_name, inline=True)
                        embed.add_field(name="Viewers", value=stream.viewer_count, inline=True)
                        embed.set_image(url=thumbnail_url)
                        embed.url = f'https://www.twitch.tv/{streamer}'
                        role_mention = f'<@&{role_id}>' if role_id else ''
                        message_content = f'{streamer} is now live! {role_mention}'
                        if (streamer, channel_id) not in live_status or not live_status[(streamer, channel_id)]:
                            message = await channel.send(content=message_content, embed=embed)
                            live_stream_messages[(streamer, channel_id)] = message.id
                            live_status[(streamer, channel_id)] = True
                        else:
                            message = await channel.fetch_message(live_stream_messages[(streamer, channel_id)])
                            await message.edit(content=message_content, embed=embed)
                    if (streamer, channel_id) in live_status and live_status[(streamer, channel_id)]:
                        stream_info = twitch.get_streams(user_id=user_id)
                        async for _ in stream_info:
                            break
                        else:
                            message = await channel.fetch_message(live_stream_messages[(streamer, channel_id)])
                            await message.delete()
                            del live_stream_messages[(streamer, channel_id)]
                            live_status[(streamer, channel_id)] = False
            except discord.errors.Forbidden:
                print(f"Missing access to send messages in channel {channel_id}")

@tasks.loop(hours=24)
async def check_channel_access():
    for entry in load_streamer_data():
        streamer_name, channel_id, role_id = entry
        channel = bot.get_channel(int(channel_id))
        if not channel:
            remove_streamer_data(streamer_name, channel_id)
            print(f"Removed {streamer_name} from channel {channel_id} due to missing access")

bot.run(DISCORD_BOT_TOKEN)
