import os
import logging
import socket
from mcrcon import MCRcon

log = logging.getLogger("bot")

# get RCON credentials
RCON_URL      = os.getenv('RCON_URL')
RCON_PASSWORD = os.getenv('RCON_PASSWORD')


# check that the Minecraft server is responsive
def get_rcon_status():
	log.info(f"get_rcon_status: getting status...")
	try:
		return submit_rcon_command("list").startswith("There")
	except socket.timeout:
		log.info(f"get_rcon_status: Connection timed out, returning False")
		return False
	except ConnectionRefusedError:
		log.info(f"get_rcon_status: Connection refused, returning False")
		return False


# get player list
# Use get_rcon_status() to check server is available before using
def get_player_list():
    resp = submit_rcon_command("list")
    if resp.startswith('There are 0'): 
        return "There are no players currently playing."
    else:
        return resp.replace('_', '\_')


# submit a command to the server
# Use get_rcon_status() to check server is available before using
def submit_rcon_command(cmd: str):
	log.info(f"rcon_submit: submitting command {cmd} to url {RCON_URL}...")
	with MCRcon(RCON_URL, RCON_PASSWORD) as mcr:
		return mcr.command(cmd)