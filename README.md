# 🐸 yomocraftbot

`discord.py` bot that operates a Minecraft server running in AWS EC2.

Not really designed to be adopted by anyone else to be honest, but may offer
some examples of how to use `discord.py`, `boto3` and `mcrcon`.

Requires Python 3.6+.

## List of commands

```
  about     Some info about this bot
  help      Shows this message
  ip        Get server ip/url
  kill      Kills the bot (admin only)
  list      List current players on the Minecraft server
  ping      Test that this bot is alive
  start     Start the Minecraft server
  status    Get server status
  stop      Manually stop the server (admin only)
  time      Get current ingame time
  whitelist Add someone to the whitelist (admin only)
```

The bot also continuously monitors the server for inactivity, and stops it after
a certain number of minutes have passed without any players (as a cost-saving
measure).

## How to set up your own instance

This project isn't designed for ease of use by people who aren't me, but:

- Create an AWS EC2 instance and set up a Minecraft server on it.
  Make sure you can connect to it from the outside world with RCON. There are
  plenty of online tutorials on how to achieve this.
- Set up a `@reboot` cron job in your instance to automatically start the server
  on instance startup. I suggest starting it inside a `screen` session.
- Make an AWS IAM user that has permissions to manipulate your EC2 instance,
  and generate an access key for it.
- Create a Discord bot in the developer portal and invite it
  to your server with the appropriate permissions using OAuth. 
- Clone this repo to a Linux machine that you want to host this on (obviously
  don't put this on the same instance as the Minecraft server).
- Rename `env.template` to `.env` and edit it to fill out all its values.
- Change the 'about' command in `bot.py` to reflect your personal circumstances
  (or just remove it entirely).
- Run `./start.sh` to start the bot.

## 🤔 Is it a good idea to run a Minecraft server in EC2?

No, not really, there are cheaper and easier hosting platforms. This whole thing
is just for fun and practice.

If you do decide to use EC2 I suggest a `t4g.large` instance type, it's cheap
compared to other similarly-specced machines due to the ARM cores and it has
a very generous 8GB RAM.

## 🔒 Security concerns?

As far as I can tell, the worst thing people could do is message the bot to
start the EC2 instance a lot to cost you more money. If you're worried about
that you could use the `@commands.guild_only()` decorator on the start command
to make any invocation publicly viewable, or implement a whitelist by Discord
user id on who can invoke it.

(I don't accept any responsibility if anything goes wrong, as per MIT license)