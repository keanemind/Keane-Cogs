"""Finally, something for users to spend credits on!"""
import os
import asyncio
import random
import time
import datetime

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
    "Players": {},
    "TheftCount": 0, # Reset daily by daily_report()
    "Thieves": [], # Reset daily by daily_report()
}

PLAYER_DEFAULT = {
    "Active": "AS",
    "ER": 0,
    "AS": 0,
    "BF": 0,
    "LatestSteal": 0, # The time that the user last attempted to steal, assigned to dummy value
}

PRIMARY_UPGRADES = {
    "ER":"Elite Raid",
    "AS":"Advanced Security",
    "BF":"Blackmarket Finances",
}

class Steal:
    """Upgrade yourself!"""

    def __init__(self, bot):
        self.save_file = dataIO.load_json(SAVE_FILEPATH)
        self.bot = bot

        self.menu_users = [] # list is probably inefficient

        self.loop_task = bot.loop.create_task(self.give_credits())
        self.loop_task2 = bot.loop.create_task(self.daily_report())

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

        # Check for bank account
        if not bank.account_exists(player):
            return await self.bot.say("You don't have a bank account. "
                                      "Use `{0}bank register` to open one, "
                                      "then try `{0}steal` again.".format(ctx.prefix))

        # Check if main_menu is already running for them
        if player.id in self.menu_users:
            return await self.bot.say("The command is already running for you. "
                                      "Check your direct messages.")

        await self.bot.say("Check your direct messages.")
        self.menu_users.append(player.id)

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
        await self.main_menu(ctx)
        self.menu_users.remove(player.id)

    async def main_menu(self, ctx):
        """Display the main menu."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        loop = True
        while True:
            message = ("What would you like to do?\n"
                       "1. Steal from someone\n"
                       "2. Buy an upgrade\n"
                       "3. Activate an upgrade path\n"
                       "Reply with the number of your choice, or with anything else to cancel.")
            d_message = await self.bot.send_message(player, message)

            response = await self.bot.wait_for_message(timeout=60,
                                                       author=player,
                                                       channel=d_message.channel)

            if response is None or response.content not in {"1", "2", "3"}:
                loop = False
            elif response.content == "1":
                since_steal = round(time.time() - playersave["LatestSteal"])
                if since_steal > 20 * 60:
                    loop = await self.steal_menu(ctx)
                else:
                    until_available = (20 * 60) - since_steal
                    m, s = divmod(until_available, 60)
                    h, m = divmod(m, 60)
                    message = "Steal is on cooldown. Time left: {:d}:{:02d}:{:02d}".format(h, m, s)
                    await self.bot.send_message(player, message)
            elif response.content == "2":
                loop = await self.upgrade_menu(ctx)
            elif response.content == "3":
                loop = await self.activate_menu(ctx)

            if loop:
                await asyncio.sleep(2)
            else:
                break

        await self.bot.send_message(player, "Goodbye!")

    async def steal_menu(self, ctx):
        """Steal from someone."""
        player = ctx.message.author
        server = ctx.message.server
        bank = self.bot.get_cog("Economy").bank
        while True:
            message = ("Who do you want to steal from? The user must be on the "
                       "server you used `!steal` in. Enter a nickname, username, "
                       "or for best results, a full tag like Keane#8251.")
            d_message = await self.bot.send_message(player, message)

            response = await self.bot.wait_for_message(timeout=60,
                                                       author=player,
                                                       channel=d_message.channel)
            if response is None:
                return False

            target = server.get_member_named(response.content)

            if target is None:
                message = ("Target not found. Try again?\n"
                           "1. Yes\n")
                await self.bot.send_message(player, message)

                response = await self.bot.wait_for_message(timeout=20,
                                                           author=player,
                                                           channel=d_message.channel)
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
                                                           channel=d_message.channel)
                if response is None:
                    return False
                elif response.content == "1":
                    break
            else:
                break

        if not bank.account_exists(target):
            await self.bot.send_message(player, "That person doesn't have a bank account.")
            return True

        if target.id not in self.save_file["Servers"][server.id]["Players"]:
            self.save_file["Servers"][server.id]["Players"][target.id] = PLAYER_DEFAULT
            dataIO.save_json(SAVE_FILEPATH, self.save_file)

        await self.steal_credits(ctx, target)

        return True

    async def upgrade_menu(self, ctx):
        """Buy an upgrade."""
        player = ctx.message.author
        server = ctx.message.server
        bank = self.bot.get_cog("Economy").bank

        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        message = ("What would you like to upgrade? Reply with the number "
                   "of your choice, or with anything else to cancel.\n")

        zipped = zip(range(1, len(PRIMARY_UPGRADES) + 1), PRIMARY_UPGRADES)
        options = [(num, key) for num, key in zipped]

        for num, path in options:
            message += "{}. {} (lvl {})".format(num,
                                                PRIMARY_UPGRADES[path],
                                                playersave[path])
            if path == playersave["Active"]:
                message += " *"

            message += "\n"

        message += "* currently active"
        d_message = await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=60,
                                                   author=player,
                                                   channel=d_message.channel)
        if response is None:
            return False
        elif response.content not in {str(num) for num in range(1, len(PRIMARY_UPGRADES) + 1)}:
            await self.bot.send_message(player, "Upgrade cancelled.")
            return True

        paths = {str(num):path for num, path in options}
        path = paths[response.content]

        if playersave[path] == 99:
            await self.bot.send_message(player, "That path is already max level.")
            return True

        message = ("How many levels would you like to upgrade? Respond "
                   "with a non-number to cancel.")
        await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=20,
                                                   author=player,
                                                   channel=d_message.channel)
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
                                                   channel=d_message.channel)
        if response is None:
            return False
        elif response.content.lower() != "yes":
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

    async def activate_menu(self, ctx):
        """Activate an upgrade path."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        message = ("{} is currently active. Which path do you want to activate?\n"
                   .format(PRIMARY_UPGRADES[playersave["Active"]]))

        inactives = {key:PRIMARY_UPGRADES[key]
                     for key in PRIMARY_UPGRADES
                     if key != playersave["Active"]}
        zipped = zip(range(1, len(inactives) + 1), inactives)
        options = [(num, key) for num, key in zipped]

        for num, pathkey in options:
            message += "{}. {} (lvl {})\n".format(num,
                                                  inactives[pathkey],
                                                  playersave[pathkey])

        d_message = await self.bot.send_message(player, message)

        response = await self.bot.wait_for_message(timeout=60,
                                                   author=player,
                                                   channel=d_message.channel)
        if response is None:
            return False
        elif response.content not in {str(num) for num in range(1, len(inactives) + 1)}:
            await self.bot.send_message(player, "Activation cancelled.")
            return True

        paths = {str(num):pathkey for num, pathkey in options}
        playersave["Active"] = paths[response.content]
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

        await self.bot.send_message(player, "Activation complete.")
        return True

    async def steal_credits(self, ctx, target):
        """Steal credits. Contains all the matchup logic."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]
        targetsave = self.save_file["Servers"][server.id]["Players"][target.id]
        bank = self.bot.get_cog("Economy").bank

        # Helldivers-like code thing
        message = ("Quick! You have 15 seconds to unlock the "
                   "door's keypad to get inside! Type the code "
                   "below without the dashes. Keep trying until "
                   "you're in or time is up.\n")
        await self.bot.send_message(player, message)
        await asyncio.sleep(3)
        code = []
        for _ in range(13):
            code.append(str(random.randint(0, 9)))
        message = "-".join(code)
        d_message = await self.bot.send_message(player, message)
        response = await self.bot.wait_for_message(timeout=15,
                                                   author=player,
                                                   channel=d_message.channel,
                                                   content="".join(code))

        if response is None:
            await self.bot.send_message(player, "You failed!")
            if targetsave["Active"] == "AS" and random.randint(1, 100) <= targetsave["AS"]:
                bank.deposit_credits(target, 1000)
            return True
        else:
            await self.bot.send_message(player, "You're in!")
            await asyncio.sleep(1)

        # ATTACKER: ELITE RAID
        if playersave["Active"] == "ER":
            # Elite Raid v Elite Raid
            if targetsave["Active"] == "ER":
                if random.randint(1, 100) <= 66:
                    await self.er_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

            # Elite Raid v Advanced Security
            elif targetsave["Active"] == "AS":
                if targetsave["AS"] == 99:
                    success_chance = 33 / 2
                else:
                    success_chance = 33

                if random.randint(1, 100) <= success_chance:
                    await self.er_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                    if random.randint(1, 100) <= targetsave["AS"]:
                        bank.deposit_credits(target, 1000)

                    # Elite Raid is immune to Advanced Security's cameras

                if playersave["ER"] >= 66:
                    if random.randint(1, 100) <= 33:
                        if targetsave["AS"] > 5:
                            targetsave["AS"] -= 5
                        else:
                            targetsave["AS"] = 0

            # Elite Raid v Blackmarket Finances
            elif targetsave["Active"] == "BF":
                if random.randint(1, 100) <= 66:
                    await self.er_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                if targetsave["BF"] >= 66:
                    if random.randint(1, 100) <= 33:
                        if playersave["ER"] > 5:
                            playersave["ER"] -= 5
                        else:
                            playersave["ER"] = 0

        # ATTACKER: ADVANCED SECURITY
        elif playersave["Active"] == "AS":
            # Advanced Security v Elite Raid
            if targetsave["Active"] == "ER":
                if random.randint(1, 100) <= 33:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

            # Advanced Security v Advanced Security
            elif targetsave["Active"] == "AS":
                if targetsave["AS"] == 99:
                    success_chance = 33 / 2
                else:
                    success_chance = 33

                if random.randint(1, 100) <= success_chance:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                    if random.randint(1, 100) <= targetsave["AS"]:
                        bank.deposit_credits(target, 1000)

                    if targetsave["AS"] >= 33:
                        await self.reveal_attacker(ctx, target)

            # Advanced Security v Blackmarket Finances
            elif targetsave["Active"] == "BF":
                if random.randint(1, 100) <= 33:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

        # ATTACKER: BLACKMARKET FINANCES
        elif playersave["Active"] == "BF":
            # Blackmarket Finances v Elite Raid
            if targetsave["Active"] == "ER":
                if random.randint(1, 100) <= 50:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

            # Blackmarket Finances v Advanced Security
            elif targetsave["Active"] == "AS":
                if targetsave["AS"] == 99:
                    success_chance = 33 / 2
                else:
                    success_chance = 33

                if random.randint(1, 100) <= success_chance:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                    if random.randint(1, 100) <= targetsave["AS"]:
                        bank.deposit_credits(target, 1000)

                    if targetsave["AS"] >= 33:
                        await self.reveal_attacker(ctx, target)

                if targetsave["AS"] >= 66:
                    if random.randint(1, 100) <= 33:
                        if playersave["BF"] > 5:
                            playersave["BF"] -= 5
                        else:
                            playersave["BF"] = 0

            # Blackmarket Finances v Blackmarket Finances
            elif targetsave["Active"] == "BF":
                if random.randint(1, 100) <= 50:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

        playersave["LatestSteal"] = time.time()
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    async def er_steal(self, ctx, target):
        """Elite Raid steal."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]
        bank = self.bot.get_cog("Economy").bank

        if playersave["ER"] == 99:
            # 1/10 chance to steal 110% of wealth, if steal successful in the first place
            if random.randint(1, 100) <= 10:
                amt_stolen = round(bank.get_balance(target) * 1.1)
                bank.deposit_credits(player, amt_stolen)
                bank.set_credits(target, 0)

                message = ("You captured a good friend of {0}'s as hostage "
                           "and demanded ransom, which was promptly paid. "
                           "You graciously accepted every credit {0} had, "
                           "plus some that the poor soul took out on a loan "
                           "to meet your demands. All in all, you earned "
                           "yourself {1} credits."
                           .format(target.mention, amt_stolen))
                await self.bot.send_message(player, message)
                return

        amt_stolen = random.randint(1, random.randint(1, 2000))

        if random.randint(1, 100) <= playersave["ER"]:
            amt_stolen *= 2

        if playersave["ER"] >= 33:
            # steal a bonus 10% of target's wealth
            amt_stolen += round(bank.get_balance(target) * 0.1)

        if amt_stolen > bank.get_balance(target):
            amt_stolen = bank.get_balance(target)

        bank.transfer_credits(target, player, amt_stolen)

        message = ("Mission accomplished! You stole {} credits "
                   "from {}!".format(amt_stolen, target.mention))
        await self.bot.send_message(player, message)

        # Add to daily report data
        if player.id not in self.save_file["Servers"][server.id]["Thieves"]:
            self.save_file["Servers"][server.id]["Thieves"].append(player.id)

        self.save_file["Servers"][server.id]["TheftCount"] += 1
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    async def regular_steal(self, ctx, target):
        """Regular steal by classes other than Elite Raid."""
        player = ctx.message.author
        server = ctx.message.server

        bank = self.bot.get_cog("Economy").bank
        amt_stolen = random.randint(1, random.randint(1, 2000))
        if amt_stolen > bank.get_balance(target):
            amt_stolen = bank.get_balance(target)

        bank.transfer_credits(target, player, amt_stolen)

        message = ("Mission accomplished! You stole {} credits "
                   "from {}!".format(amt_stolen, target.mention))
        await self.bot.send_message(player, message)

        # Add to daily report data
        if player.id not in self.save_file["Servers"][server.id]["Thieves"]:
            self.save_file["Servers"][server.id]["Thieves"].append(player.id)

        self.save_file["Servers"][server.id]["TheftCount"] += 1
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    async def reveal_attacker(self, ctx, target):
        """Reveal to the defender who attacked them and what the
        attacker had active."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]
        message = (
            "{}, who had {} active, was spotted by your guard "
            "stealing credits from your bank safe! Your guard "
            "was unable to catch the fiend before they fled."
            .format(player.mention, PRIMARY_UPGRADES[playersave["Active"]])
        )
        await self.bot.send_message(target, message)

    async def steal_failure(self, ctx):
        """Send a steal failure message to the person who attempted it."""
        player = ctx.message.author
        messages = [
            ("Right as you're about to open the safe, you hear footsteps. "
             "You and your team flee the scene."),
            ("You pull hard on the door, making a loud clang, but it seems "
             "to be jammed. Maybe there's some kind of hidden mechanism, but "
             "guards may have heard you. You scram and and live to see another day."),
            ("Something about this operation smells fishy. It might be a trap. "
             "You call it off."),
            ("There's nothing in the safe! Maybe its owner knew you were coming?"),
            ("What in the world!? Two armed guards jump out at you. You and the "
             "team run like the wind and barely get out with your heads on your necks.")
        ]
        message = random.choice(messages) + "\n**Steal failed.**"
        await self.bot.send_message(player, message)

    async def give_credits(self):
        """Loop to give credits every hour at a random minute and second
        to Blackmarket Finances users."""
        while True:
            bank = self.bot.get_cog("Economy").bank
            now = datetime.datetime.utcnow()
            next_time = now.replace(hour=now.hour + 1,
                                    minute=random.randint(0, 59),
                                    second=random.randint(1, 59),
                                    microsecond=0)
            # If next_time is X:00:00 and the sleep below is slightly short,
            # the hour will still be the previous hour and credits could be given
            # twice in the same hour. To be safe, the minimum second is 1.
            await asyncio.sleep((next_time - now).total_seconds())

            for serverid in self.save_file["Servers"]:
                server = self.bot.get_server(serverid)
                for playerid in self.save_file["Servers"][serverid]["Players"]:
                    playersave = self.save_file["Servers"][serverid]["Players"][playerid]
                    if playersave["Active"] == "BF" and playersave["BF"] > 0:
                        player = server.get_member(playerid)
                        bank.deposit_credits(player, playersave["BF"])

    async def daily_report(self):
        """Loop to report theft every day."""
        now = datetime.datetime.now()
        wake_time = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if now.hour > wake_time.hour:
            wake_time = wake_time + datetime.timedelta(days=1)

        while True:
            await asyncio.sleep((wake_time - datetime.datetime.now()).total_seconds())
            wake_time = wake_time + datetime.timedelta(days=1)

            for serverid in self.save_file["Servers"]:
                serverdata = self.save_file["Servers"][serverid]
                message = ("Announcement from the Royal Navy: \n"
                           "Today there were {} counts of theft "
                           "perpetrated by {} members of this server. "
                           "The Royal Navy cautions all members to remain "
                           "vigilant in these lawless times."
                           .format(serverdata["TheftCount"], len(serverdata["Thieves"])))
                await self.bot.send_message(self.bot.get_server(serverid), message)
                serverdata["TheftCount"] = 0
                serverdata["Thieves"].clear()

            dataIO.save_json(SAVE_FILEPATH, self.save_file)

    def __unload(self):
        self.loop_task.cancel()
        self.loop_task2.cancel()

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
