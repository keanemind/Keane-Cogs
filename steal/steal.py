"""Finally, something for users to spend credits on!"""
import os
import asyncio

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
    "Active": "AS",
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

        # Add server
        if server.id not in servers:
            servers[server.id] = SERVER_DEFAULT

        # Add player, display newbie introduction
        if player.id not in servers[server.id]["Players"]:
            servers[server.id]["Players"][player.id] = PLAYER_DEFAULT
            message = ("Welcome to the world of crime!\n"
                       "There are three upgrade paths you can choose from. "
                       "You can upgrade in multiple paths at once, but only one "
                       "upgrade path can be active at once. Activating an upgrade "
                       "path means turning on the benefits that path provides "
                       "(and turning off the benefits your previous path provided).\n\n"
                       "Right now, your active path is Advanced Security. Learn more "
                       "about each path at ...")
            await self.bot.send_message(player, message)
            await asyncio.sleep(2)

        # Menu
        await self.main_menu(player, server)

    async def main_menu(self, player, server):
        """Display the main menu."""
        loop = True
        while True:
            message = ("What would you like to do?\n"
                       "1. Steal from someone\n"
                       "2. Buy an upgrade\n"
                       "3. Activate an upgrade path\n"
                       "Reply with the number of your choice, or with anything else to cancel.")
            d_message = await self.bot.send_message(player, message)

            response = await self.bot.wait_for_message(timeout=20,
                                                       author=player,
                                                       channel=d_message.channel)

            if response is None or response.content not in {"1", "2", "3"}:
                loop = False
            elif response.content == "1":
                loop = await self.steal_menu(response, server)
            elif response.content == "2":
                loop = await self.upgrade_menu(response, server)
            elif response.content == "3":
                loop = await self.activate_menu(response, server)

            if loop:
                await asyncio.sleep(2)
            else:
                break

        return await self.bot.send_message(player, "Goodbye!")

    async def steal_menu(self, response, server):
        """Steal from someone."""
        player = server.get_member(response.author.id)

        while True:
            message = ("Who do you want to steal from? The user must be on the "
                       "server you used `!steal` in. Enter a nickname, username, "
                       "or for best results, a full tag like Keane#8251.")
            await self.bot.send_message(player, message)

            response = await self.bot.wait_for_message(timeout=20,
                                                       author=player,
                                                       channel=response.channel)
            if response is None:
                return False

            target = server.get_member_named(response.content)

            if target is None:
                message = ("Target not found. Try again?\n"
                           "1. Yes\n")
                await self.bot.send_message(player, message)

                response = await self.bot.wait_for_message(timeout=20,
                                                           author=player,
                                                           channel=response.channel)
                if response is None:
                    return False
                elif response.content != "1":
                    await self.bot.send_message(player, "Steal cancelled.")
                    return True

            elif "#" not in response.content:
                message = ("Is {} the correct target?\n"
                           "1. Yes\n".format(target.mention))
                await self.bot.send_message(player, message)

                response = await self.bot.wait_for_message(timeout=20,
                                                           author=player,
                                                           channel=response.channel)
                if response is None:
                    return False
                elif response.content == "1":
                    break
            else:
                break

        # steal from target self.steal_credits(server.get_member(player.id), target)

        return True

    async def upgrade_menu(self, response, server):
        """Buy an upgrade."""
        player = server.get_member(response.author.id)
        bank = self.bot.get_cog("Economy").bank

        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        message = ("What would you like to upgrade? Reply with the number "
                   "of your choice, or with anything else to cancel.\n"
                   "1. Elite Raid (lvl {})\n"
                   "2. Advanced Security (lvl {})\n"
                   "3. Blackmarket Finances (lvl {})"
                   .format(playersave["ER"], playersave["AS"], playersave["BF"]))
        await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=20,
                                                   author=player,
                                                   channel=response.channel)
        if response is None:
            return False
        elif response.content not in {"1", "2", "3"}:
            await self.bot.send_message(player, "Upgrade cancelled.")
            return True

        paths = {"1":"ER", "2":"AS", "3":"BF"}
        path = paths[response.content]

        if playersave[path] == 99:
            await self.bot.send_message(player, "That path is already max level.")
            return True

        message = ("How many levels would you like to upgrade? Respond "
                   "with a non-number to cancel.")
        await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=20,
                                                   author=player,
                                                   channel=response.channel)
        if response is None:
            return False
        try:
            lvls = int(response.content)
        except ValueError:
            await self.bot.send_message(player, "Upgrade cancelled.")
            return True

        current_lvl = playersave[path]

        if current_lvl + lvls > 99:
            lvls = 99 - current_lvl
            cost = round((5 * 99**1.933) - (5 * current_lvl**1.933))
            await self.bot.send_message(player, "You cannot upgrade past lvl 99. You will only "
                                        "upgrade {} levels.".format(99 - current_lvl))
        else:
            cost = round((5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933))

        await self.bot.send_message(player, "This will cost {} credits. If you cannot afford the cost, "
                                    "the maximum number of levels you can afford will be upgraded. "
                                    "Reply with \"yes\" to confirm, or anything else to cancel.".format(cost))

        response = await self.bot.wait_for_message(timeout=20,
                                                   author=player,
                                                   channel=response.channel)
        if response is None or response.content.lower() != "yes":
            await self.bot.send_message(player, "Upgrade cancelled.")
            return True

        if not bank.can_spend(player, cost):
            balance = bank.get_balance(player)
            lvls = 1
            cost = round((5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933))
            while cost < balance:
                lvls += 1
                cost = round((5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933))

            if lvls == 1:
                await self.bot.send_message(player, "You cannot afford to upgrade this path at all.")
                return True
            else:
                lvls -= 1
                cost = round((5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933))

        bank.withdraw_credits(player, cost)
        playersave[path] += lvls
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

        await self.bot.send_message(player, "Upgrade complete.")

        return True

    async def activate_menu(self, response, server):
        """Activate an upgrade path."""
        player = server.get_member(response.author.id)

        return True

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
