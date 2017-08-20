"""Finally, something for users to spend credits on!"""
import os

import discord
from discord.ext import commands
from __main__ import send_cmd_help
from .utils import checks
from .utils.dataIO import dataIO

SAVE_FILEPATH = "data/KeaneCogs/steal/steal.json"

SAVE_DEFAULT = {
    "Servers": {}
}

SERVER_DEFAULT = {
    "Players": {}
}

PLAYER_DEFAULT = {
    "Active": "",
    "ER": 0,
    "AS": 0,
    "BF": 0,
}

class Steal:
    """Upgrade yourself!"""

    def __init__(self, bot):
        self.save_file = dataIO.load_json(SAVE_FILEPATH)
        self.bot = bot

    @commands.command(pass_context=True, no_pm=True)
    async def steal(self, ctx):
        """Steal's main menu. Everything you can do with this cog
        is accessed through this command."""
        server = ctx.message.server
        player = ctx.message.author
        servers = self.save_file["Servers"]
        bank = self.bot.get_cog("Economy").bank

        # Add server
        if server.id not in servers:
            servers[server.id] = SERVER_DEFAULT

        # Newbie introduction, add player
        if player.id not in servers[server.id]["Players"]:
            servers[server.id]["Players"][player.id] = PLAYER_DEFAULT
            message = ("Welcome to the world of crime!\n"
                       "There are three upgrade paths you can choose from. "
                       "You can upgrade in multiple paths at once, but only one "
                       "upgrade path can be active at once. Activating an upgrade "
                       "path means turning on the benefits that path provides. "
                       "Currently, you cannot steal or be stolen from. You can, "
                       "however, upgrade as you please. The first time you activate "
                       "a pathway, you will be able to steal and be stolen from. There "
                       "is no going back after that.")
            await self.bot.send_message(player, message)

        # Prompts
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        message = ("What would you like to upgrade? Reply with the number "
                   "of your choice, or with anything else to cancel.\n"
                   "1. Elite Raid (lvl {})\n"
                   "2. Advanced Security (lvl {})\n"
                   "3. Blackmarket Finances (lvl {})"
                   .format(playersave["ER"], playersave["AS"], playersave["BF"]))
        await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=15, author=player)
        if response is None or response.content not in {"1", "2", "3"}:
            return await self.bot.say("Upgrade cancelled.")

        paths = {"1":"ER", "2":"AS", "3":"BF"}
        path = paths[response.content]

        if playersave[path] == 99:
            return await self.bot.say("That path is already max level.")

        message = ("How many levels would you like to upgrade? Respond "
                   "with a non-number to cancel.")
        await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=15, author=player)
        if response is None:
            return await self.bot.say("Upgrade cancelled.")
        try:
            lvls = int(response.content)
        except ValueError:
            return await self.bot.say("Upgrade cancelled.")

        current_lvl = playersave[path]

        if current_lvl + lvls > 99:
            lvls = 99 - current_lvl
            cost = (5 * 99**1.933) - (5 * current_lvl**1.933)
            await self.bot.say("You cannot upgrade past lvl 99. You will only "
                               "upgrade {} levels.".format(99 - current_lvl))
        else:
            cost = (5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933)

        await self.bot.say("This will cost {} credits. If you cannot afford the cost, "
                           "the maximum number of levels you can afford will be upgraded. "
                           "Reply with \"yes\" to confirm, or anything else to cancel.".format(cost))

        if not bank.can_spend(player, cost):
            balance = bank.get_balance(player)
            lvls = 1
            cost = (5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933)
            while cost < balance:
                lvls += 1
                cost = (5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933)

            if lvls == 1:
                return await self.bot.say("You cannot afford to upgrade this path at all.")
            else:
                lvls -= 1
                cost = (5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933)

        bank.withdraw_credits(player, cost)
        playersave[path] += lvls

def dir_check():
    """Create a folder and save file for the cog if they don't exist."""
    if not os.path.exists("data/KeaneCogs/steal"):
        print("Creating data/KeaneCogs/steal folder...")
        os.makedirs("data/KeaneCogs/steal")

    if not dataIO.is_valid_json(SAVE_FILEPATH):
        print("Creating default steal.json...")
        dataIO.save_json(SAVE_FILEPATH, SAVE_DEFAULT)

def setup(bot):
    """Create a Steal object."""
    dir_check()
    bot.add_cog(Steal(bot))
