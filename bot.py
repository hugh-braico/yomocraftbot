# General stuff
import os
import datetime as dt
import sys
import traceback
import aiohttp
import asyncio
import socket
import logging
import re
from dotenv import load_dotenv

# Discord stuff
import discord
from discord import User
from discord.ext import commands

################################################################################
#
### Initialization and globals

# lower the default socket timeout so commands are more responsive
socket.setdefaulttimeout(3)

# Load environment variables from .env
load_dotenv()

# Discord and bot output stuff
# Using UPPER_CASE as a convention for global variables
DISCORD_TOKEN   = os.getenv('DISCORD_TOKEN')
ADMIN           = int(os.getenv('ADMIN'))
ADMIN_NAME      = os.getenv('ADMIN_NAME')
PREFIX          = os.getenv('PREFIX')

# Emotes to add flavor to output messages
ERROR_EMOTE     = os.getenv('ERROR_EMOTE')
KILL_EMOTE      = os.getenv('KILL_EMOTE')
EC2_EMOTE       = os.getenv('EC2_EMOTE')
MINECRAFT_EMOTE = os.getenv('MINECRAFT_EMOTE')

# Dedicated error log channel
# Have to set this later, after the bot is ready (on_ready())
ERROR_LOG_CHANNEL = None

# The server URL is only used for display purposes in this file
RCON_URL = os.getenv('RCON_URL')

# Polling rate and timeout for stopping the server automatically
INACTIVITY_POLLING_RATE = int(os.getenv('INACTIVITY_POLLING_RATE'))
INACTIVITY_TIMEOUT      = int(os.getenv('INACTIVITY_TIMEOUT'))

# global flag to indicate that a stop is going to occur soon
# active during the wait between "stop MC server" and "stop EC2 instance"
# this is lazy programming, you shouldn't do this
EC2_WAITING_TO_STOP = False

# Import server management stuff (depends on dotenv)
from rcon_utils import get_rcon_status, get_player_list, submit_rcon_command
from ec2_utils import get_ec2_status, start_ec2_instance, stop_ec2_instance

# Initialize logging stuff - log to console, but also a file under logs/
log = logging.getLogger("bot")
log.setLevel(logging.DEBUG)
log_format = "%(asctime)s %(levelname)-8s %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(
    format=log_format,
    level=logging.INFO,
    datefmt=date_format
)
fh = logging.FileHandler("logs/" + dt.datetime.now().strftime(date_format) + ".log")
formatter = logging.Formatter(log_format, datefmt=date_format)
fh.setFormatter(formatter)
fh.setLevel(logging.DEBUG)
log.addHandler(fh)

# let the bot access discord Intents to do its thing
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

# finally, create the bot object 
bot = commands.Bot(command_prefix=PREFIX, intents=intents)


################################################################################
#
### Basic behavioral functions


# Startup function
@bot.event
async def on_ready():
    # Log the servers that the bot is connected to
    log.info(f'{bot.user} is connected to the following server(s):')
    for guild in bot.guilds:
        log.info(f'    {guild.name} (id: {guild.id})')
    # Get the log channel
    global ERROR_LOG_CHANNEL
    ERROR_LOG_CHANNEL = bot.get_channel(int(os.getenv('ERROR_LOG_CHANNEL')))
    # Kick off the server inactivity check
    await server_inactivity_check()


# Post a traceback to the dedicated error log channel
async def post_error_to_log_channel(ctx, error): 
    await ERROR_LOG_CHANNEL.send(
        f"<@{ADMIN}>\n" +
        f"Server: \"{ctx.guild.name}\"\n" + 
        f"Channel: #{ctx.channel.name}\n" + 
        f"Invoked by: {ctx.author.name}\n" + 
        f"```\n" +
        "".join(traceback.format_exception(type(error), error, error.__traceback__)) + 
        "\n```"
    )


# Error handling function
@bot.event
async def on_command_error(ctx, error):      
    # Prevents any commands with local handlers being handled here
    if hasattr(ctx.command, 'on_error'):
        return
    error = getattr(error, 'original', error)
    if isinstance(error, commands.DisabledCommand):
        await ctx.send(f"{ERROR_EMOTE} {ctx.command} has been disabled.")
    elif isinstance(error, commands.NoPrivateMessage):
        try:
            await ctx.author.send(f"{ctx.command} can not be used in Private Messages.")
        except discord.HTTPException:
            pass
    elif isinstance(error, commands.CommandNotFound):
        # ignore commands that don't start with a-zA-Z0-9
        # lets people post stuff like "~~strikethrough text~~" if your prefix is ~
        if re.match(r"[a-zA-Z0-9]", ctx.message.content[1]):
            await ctx.send(f"{ERROR_EMOTE} I don't recognise that command. Try `{PREFIX}help` for a list of all commands.")
    elif isinstance(error, commands.BadArgument):
        if ctx.command.qualified_name == 'tag list':
            await ctx.send(f"{ERROR_EMOTE} I could not find that member. Please try again.")
        else:
            await ctx.send(f"{ERROR_EMOTE} Invalid command arguments. Maybe try `{PREFIX}help <command>`.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"{ERROR_EMOTE} Not enough command arguments. Maybe try `{PREFIX}help <command>`.")
    elif isinstance(error, commands.ExpectedClosingQuoteError) or isinstance(error, commands.UnexpectedQuoteError):
        await ctx.send(f"{ERROR_EMOTE} Looks like you didn't close your double quotes properly.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(f"{ERROR_EMOTE} You don't have the right permissions to do that.")
    elif isinstance(error, aiohttp.client_exceptions.ClientConnectorError):
        log.info("DISCONNECT DETECTED - closing")
        await bot.close()
    else:
        await ctx.send(f"{ERROR_EMOTE} An unknown error occurred. <@{ADMIN}> should probably go check the server log.")
        print(f"Ignoring exception in command {ctx.command}:", file=sys.stderr)
        log.error("".join(traceback.format_exception(type(error), error, error.__traceback__)))
        await post_error_to_log_channel(ctx, error)


# continually poll the server status, and close it if it's inactive for too long
async def server_inactivity_check():
    global EC2_WAITING_TO_STOP
    last_active_time = dt.datetime.now()
    while True:
        await asyncio.sleep(60*INACTIVITY_POLLING_RATE)
        now = dt.datetime.now()
        log.info(f"server_inactivity_check: checking for inactivity...")
        if get_ec2_status() == "running":
            rcon_status = get_rcon_status()
            if not rcon_status or submit_rcon_command("list").startswith('There are 0'):
                inactivity_time = int((now - last_active_time).total_seconds())
                log.info(f"server_inactivity_check: inactivity detected (inactivity_time = {inactivity_time})")
                if not EC2_WAITING_TO_STOP and inactivity_time > (INACTIVITY_TIMEOUT * 60):
                    log.info(f"server_inactivity_check: TIMEOUT EXCEEDED")
                    EC2_WAITING_TO_STOP = True
                    try:
                        if rcon_status:
                            log.info(f"server_inactivity_check: stopping Minecraft server...")
                            submit_rcon_command(f"stop")
                            log.info(f"server_inactivity_check: allowing the server 120 seconds to exit cleanly before stopping EC2...")
                            await asyncio.sleep(120)
                            log.info(f"server_inactivity_check: stopping EC2...")
                        else:
                            log.info(f"server_inactivity_check: Minecraft server not responsive, skipping straight to stopping EC2...")
                        stop_ec2_instance()
                    finally:
                        EC2_WAITING_TO_STOP = False
                        last_active_time = now
            else:
                last_active_time = now
                log.info(f"server_inactivity_check: server is active")
        else:
            last_active_time = now
            log.info(f"server_inactivity_check: server not running.")


################################################################################
#
### Bot maintenance commands 


# simple ping test
@bot.command(name='ping', help='Test that this bot is alive')
async def ping(ctx):
    await ctx.send(f"🏓 approx. latency = {round(bot.latency, 3)}s")


# kill the bot
@bot.command(name='kill', aliases=['bang'], help=f"Kills the bot (admin only)")
async def killbot(ctx):
    if ctx.author.id == ADMIN: 
        await ctx.send(f"{KILL_EMOTE} Shutting down...")
        log.info(f"Shutting down (responding to {PREFIX}kill command)")
        await bot.close()
    else: 
        await ctx.send(f"{ERROR_EMOTE} Only {ADMIN_NAME} can do that.")


# print some information about this bot
@bot.command(name='about', help='Some info about this bot')
async def about(ctx):
    await ctx.send(
        f"👋 I am a small Python bot that administrates a Minecraft server. I'm hosted at {ADMIN_NAME}'s house.\n" +
        f"You can see the code here: <https://github.com/hugh-braico/yomocraftbot>\n\n" +
        f"**Libraries used:**\n" +
        f"• **discord.py** for general bot functionality: <https://discordpy.readthedocs.io/>\n" +
        f"• **boto3** for AWS administration: <https://github.com/boto/boto3>\n" +
        f"• **mcrcon** for Minecraft administration: <https://pypi.org/project/mcrcon/>\n" +
        f"\nThe Minecraft server itself ({RCON_URL}) is hosted on an AWS EC2 instance (instance type `t4g.large`). It has 2 ARM CPU cores and 8GB RAM.\n"
    )


################################################################################
#
### Minecraft server management

# Note: EC2 is called "Machine" in user-facing commands,
# and "EC2" in admin-only commands. 
# Output for admin commands is also more terse.


# Print the player list
@bot.command(name='ip', aliases=['url'], help='Get server IP/URL')
async def getip(ctx):
    await ctx.send(
        f"Connect to `{RCON_URL}` in your Minecraft client to play!\n" +
        f"Check server status with `{PREFIX}status`."
    )


# Print the player list
@bot.command(name='list', aliases=['l', 'players', 'playerlist', 'listplayers', 'playerslist'], help='List current players')
async def playerlist(ctx):
    log.info(f"playerlist: user {ctx.author.name} requested player list")
    if get_ec2_status() != "running": 
        await ctx.send(f"{EC2_EMOTE} 🛑 Machine is not currently running, try `{PREFIX}status`.")
    elif not get_rcon_status():
        await ctx.send(
            f"{MINECRAFT_EMOTE} ⚠️ Machine is running, but Minecraft server is not responsive.\n" +
            f"If the server was just started, wait about a minute for it to become ready.\n" +
            f"Use `{PREFIX}status` to get updates.\n" +
            f"Get {ADMIN_NAME} to investigate if it takes much longer."
        )
    else:
        await ctx.send(get_player_list())


# Minecraft daytime ticks to human-readable 12-hour time string
def ticks_to_time(ticks):
    aligned_ticks = (ticks + 6000) % 24000
    if aligned_ticks >= 12000:
        meridiam = "pm"
    else:
        meridiam = "am"
    if aligned_ticks >= 13000:
        aligned_ticks -= 12000
    total_minutes = int((aligned_ticks * 3) // 50)
    minutes = total_minutes % 60
    hours = (total_minutes - minutes) // 60
    if ticks < 1000 or ticks >= 23000:
        time_emoji = "🌅"
    elif ticks < 11000:
        time_emoji = "☀️"
    elif ticks < 13000:
        time_emoji = "🌇"
    else:
        time_emoji = "🌃"
    return f"{time_emoji} {hours:02d}:{minutes:02d}{meridiam}"


# returns the ingame time of the Minecraft server as a human-readable string
def get_ingame_time():
    resp = submit_rcon_command("time query daytime")
    ticks = int(re.search(r"\d+", resp).group(0))
    return f"The ingame time is **{ticks_to_time(ticks)}**"


# Print the player list
@bot.command(name='time', aliases=['t'], help='Get current ingame time')
async def gettime(ctx):
    log.info(f"playerlist: user {ctx.author.name} requested ingame time")
    if get_ec2_status() != "running": 
        await ctx.send(f"{EC2_EMOTE} 🛑 Machine is not currently running, try `{PREFIX}status`.")
    elif not get_rcon_status():
        await ctx.send(
            f"{MINECRAFT_EMOTE} ⚠️ Machine is running, but Minecraft server is not responsive.\n" +
            f"If the server was just started, wait about a minute for it to become ready.\n" +
            f"Use `{PREFIX}status` to get updates.\n" +
            f"Get {ADMIN_NAME} to investigate if it takes much longer."
        )
    else:
        await ctx.send(get_ingame_time())


# add someone to the Minecraft server whitelist
@bot.command(name='whitelist', help=f"Add someone to the whitelist (admin only)")
async def whitelist(ctx, name: str):    
    log.info(f"whitelist: user {ctx.author.name} requested {name} be added to whitelist")
    if ctx.author.id != ADMIN:
        await ctx.send(f"{ERROR_EMOTE} Only {ADMIN_NAME} can do that.")
    elif not re.fullmatch(r"^\w{3,16}$", name):
        await ctx.send(f"{ERROR_EMOTE} That's not a valid Minecraft username.")
    elif get_ec2_status() != "running": 
        await ctx.send(f"{EC2_EMOTE} 🛑 EC2 not running, try `{PREFIX}status`.")
    elif not get_rcon_status():
        await ctx.send(f"{MINECRAFT_EMOTE} ⚠️ EC2 running but server not responsive, try `{PREFIX}status`.\n")
    else:
        await ctx.send(f"Adding {name} to the whitelist...")
        resp = submit_rcon_command(f"whitelist add {name}")
        await ctx.send("`" + resp + "`")


# print the Minecraft server whitelist
@bot.command(name='printwhitelist', aliases=['getwhitelist', 'showwhitelist'], help=f"Print the current whitelist")
async def printwhitelist(ctx):    
    log.info(f"whitelist: user {ctx.author.name} requested to see the whitelist")
    if get_ec2_status() != "running": 
        await ctx.send(f"{EC2_EMOTE} 🛑 Machine is not currently running, try `{PREFIX}status`.")
    elif not get_rcon_status():
        await ctx.send(
            f"{MINECRAFT_EMOTE} ⚠️ Machine is running, but Minecraft server is not responsive.\n" +
            f"If the server was just started, wait about a minute for it to become ready.\n" +
            f"Use `{PREFIX}status` to get updates.\n" +
            f"Get {ADMIN_NAME} to investigate if it takes much longer."
        )
    else:
        resp = submit_rcon_command(f"whitelist list")
        await ctx.send("`" + resp + "`")


# send any command through RCON
@bot.command(name='rcon', help=f"Manual RCON command (admin only)")
async def whitelist(ctx, cmd: str):    
    log.info(f"whitelist: user {ctx.author.name} running RCON command \"{cmd}\"")
    if ctx.author.id != ADMIN:
        await ctx.send(f"{ERROR_EMOTE} Only {ADMIN_NAME} can do that.")
    elif get_ec2_status() != "running": 
        await ctx.send(f"{EC2_EMOTE} 🛑 EC2 not running, try `{PREFIX}status`.")
    elif not get_rcon_status():
        await ctx.send(f"{MINECRAFT_EMOTE} ⚠️ EC2 running but server not responsive, try `{PREFIX}status`.\n")
    else:
        resp = submit_rcon_command(cmd)
        await ctx.send("`" + resp + "`")


# manually stop both the minecraft server and the EC2 instance
# If there are players online, require a --force flag to boot them out
@bot.command(name='stop', help=f"Manually stop the server (admin only)")
async def stopserver(ctx, force: str=None):
    log.info(f"stopserver: user {ctx.author.name} requested a server stop")
    ec2_status = get_ec2_status()
    global EC2_WAITING_TO_STOP
    if ctx.author.id != ADMIN:
        await ctx.send(f"{ERROR_EMOTE} Only {ADMIN_NAME} can do that.")
    elif EC2_WAITING_TO_STOP:
        await ctx.send(f"{EC2_EMOTE} 🛑 ⏳ EC2 is already waiting to stop.")
    elif ec2_status == "stopping":
        await ctx.send(f"{EC2_EMOTE} 🛑 ⏳ EC2 is already stopping.")
    elif ec2_status == "stopped": 
        await ctx.send(f"{EC2_EMOTE} 🛑 EC2 is already stopped.")
    elif ec2_status == "pending": 
        await ctx.send(f"{EC2_EMOTE} ⏳ EC2 is currently starting.")
    elif ec2_status != "running": 
        await ctx.send(f"{EC2_EMOTE} ❓ Unrecognised EC2 status, try `{PREFIX}status`?")
    else:
        rcon_status = get_rcon_status()
        if rcon_status and not get_player_list().startswith("There are no") and force != "--force":
            await ctx.send(f"{MINECRAFT_EMOTE} ⚠️ Server not empty! Use `--force` to stop server anyway.")
            await ctx.send(get_player_list())
        else:
            try:
                if rcon_status:
                    EC2_WAITING_TO_STOP = True
                    await ctx.send(f"{MINECRAFT_EMOTE} 🛑 Stopping server...")
                    submit_rcon_command(f"stop")
                    await ctx.send(f"{MINECRAFT_EMOTE} 🛑 ⏳ Allowing server 120 seconds to exit cleanly before stopping EC2...")
                    await asyncio.sleep(120)
                    await ctx.send(f"{EC2_EMOTE} 🛑 Stopping EC2...")
                else:
                    await ctx.send(f"{MINECRAFT_EMOTE} ⚠️ Server not responding. Stopping EC2...")
                stop_ec2_instance()
                await ctx.send(f"{EC2_EMOTE} 🛑 ⏳ EC2 is stopping, should be stopped in about 1 minute.")
            finally:
                EC2_WAITING_TO_STOP = False


# Query the status of the server
@bot.command(name='status', aliases=['s', 'serverstatus', 'server'], help='Get server status')
async def serverstatus(ctx):
    log.info(f"serverstatus: user {ctx.author.name} requested a server status check")
    ec2_status = get_ec2_status()
    log.info(f"EC2 instance status = {ec2_status}")

    if ec2_status == 'pending':
        status_emoji = "⏳"
    elif ec2_status == 'running':
        status_emoji = "✅"
    elif ec2_status == 'stopping':
        status_emoji = "🛑 ⏳"
    elif ec2_status == 'stopped':
        status_emoji = "🛑"
    else:
        status_emoji = "❓"

    # start with this message, 
    # and we're going to add stuff onto it to send all as one message.
    status_message = f"{EC2_EMOTE} Machine status: {status_emoji} **{ec2_status}**\n"

    if EC2_WAITING_TO_STOP:
        status_message += "\n".join([
            f"{MINECRAFT_EMOTE} Minecraft server status: 🛑 ⏳ **stopping**",
            f"The server will automatically stop when inactive to save money.",
            f"Wait about 2 minutes for it to stop, then use `{PREFIX}start` to start the server again.",
            f"*(hint: you can DM the bot if you don't want people seeing you start the server at 4am.)*"
        ])
    elif ec2_status == 'pending':
        status_message += "\n".join([
            f"The machine is still starting.",
            f"Wait at least another minute for the server to become playable."
        ])
    elif ec2_status == 'stopped':
        status_message += "\n".join([
            f"The server will automatically stop when inactive to save money.",
            f"Use `{PREFIX}start` to start the server again.",
            f"*(hint: you can DM the bot if you don't want people seeing you start the server at 4am.)*"
        ])
    elif ec2_status == 'stopping':
        status_message += "\n".join([
            f"The server will automatically stop when inactive to save money.",
            f"Wait a minute for it to stop, then use `{PREFIX}start` to start the server again.",
            f"*(hint: you can DM the bot if you don't want people seeing you start the server at 4am.)*"
        ])
    elif ec2_status != "running":
        status_message += f"{ERROR_EMOTE} That seems bad, <@{ADMIN}> should probably investigate."
    else:
        log.info("Getting server status...")
        if get_rcon_status(): 
            log.info(f"Server status: running")
            status_message += "\n".join([
                f"{MINECRAFT_EMOTE} Minecraft server status: ✅ **running**",
                get_player_list(),
                get_ingame_time(),
                f"Connect to `{RCON_URL}` in your Minecraft client to play!"
            ])
        else:
            log.info(f"Server status: unresponsive")
            status_message += "\n".join([
                f"{MINECRAFT_EMOTE} Minecraft server status: ⚠️ **unresponsive**",
                f"If the server has just been started, wait a minute and try again.",
                f"Otherwise, consider asking {ADMIN_NAME} to investigate."
            ])
    await ctx.send(status_message)


# Start the EC2 instance
# A @reboot cronjob will automatically start the Minecraft server on boot
@bot.command(name='start', help=f"Start the Minecraft server")
async def startserver(ctx):
    log.info(f"startserver: user {ctx.author.name} requested a server start")
    ec2_status = get_ec2_status()
    if EC2_WAITING_TO_STOP:
        await ctx.send(
            f"{MINECRAFT_EMOTE} 🛑 ⏳ The server is already stopping.\n" +
            f"Wait a couple of minutes for it to come to a total stop before starting it again.\n" + 
            f"Use `{PREFIX}status` to get updates."
        )
    elif ec2_status == "stopping":
        await ctx.send(
            f"{EC2_EMOTE} 🛑 ⏳ Machine is already stopping.\n" +
            f"Wait a couple of minutes for it to come to a total stop before starting it again.\n" + 
            f"Use `{PREFIX}status` to get updates."
        )
    elif ec2_status == "pending":
        await ctx.send(
            f"{EC2_EMOTE} ⏳ Machine is already starting up.\n" +
            f"Give it about two minutes for the server to become playable.\n" +
            f"Use `{PREFIX}status` to get updates."
        )
    elif ec2_status == "running":
        if get_rcon_status():
            await ctx.send(
                f"{MINECRAFT_EMOTE} ✅ Minecraft server is already running.\n" +
                get_player_list()
            )
        else: 
            await ctx.send(
                f"{EC2_EMOTE} ✅ Machine is already running.\n" +
                f"{MINECRAFT_EMOTE} ⚠️ Minecraft server is not responsive.\n" +
                f"If the server was just started, wait about a minute for it to become ready.\n" +
                f"Use `{PREFIX}status` to get updates.\n" +
                f"Get {ADMIN_NAME} to investigate if it takes much longer."
            )
    elif ec2_status != "stopped":
        await ctx.send(
            f"{EC2_EMOTE} ⚠️ Unable to get the current state of the server!" + 
            f"<@{ADMIN}> should probably investigate."
        )
    else:
        await ctx.send(f"{EC2_EMOTE} {MINECRAFT_EMOTE} ⏳ Starting up the server...")
        start_ec2_instance()
        await ctx.send(
            f"{EC2_EMOTE} {MINECRAFT_EMOTE} ⏳ Server is starting! Give it about two minutes to become playable.\n" + 
            f"Use `{PREFIX}status` to get updates."
        )


################################################################################
#
### Main function

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
