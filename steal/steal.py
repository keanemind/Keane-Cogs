"""A cog allowing users to steal credits from each other."""
import os
import asyncio
import copy
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
    "Servers": {},
    "Global": {
        "CreditsGivenTime": "1970-01-01T00:00:00.0",
        "Version": "1.2",
    },
}

SERVER_DEFAULT = {
    "Players": {},
    "TheftCount": 0, # Reset daily by daily_report()
    "Thieves": [], # Reset daily by daily_report()
}

PLAYER_DEFAULT = {
    "Active": "Advanced Security",
    "Elite Raid": 0,
    "Advanced Security": 0,
    "Blackmarket Finances": 0,
    "StealTime": 0, # The time that the user last attempted to steal, assigned to dummy value
    "ActivateTime": 0, # The time that the users last activated an upgrade, assigned to dummy value
}

PRIMARY_UPGRADES = [
    "Elite Raid",
    "Advanced Security",
    "Blackmarket Finances",
]

class Steal:
    """Steal credits from other users and spend credits on upgrades."""

    def __init__(self, bot):
        self.save_file = dataIO.load_json(SAVE_FILEPATH)
        self.bot = bot

        self.update_version()

        self.menu_users = {}
        self.unloading = False

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
            servers[server.id] = copy.deepcopy(SERVER_DEFAULT)
            # doesn't need save_json() because it'll be saved when player is added below

        # Check for bank account
        if not bank.account_exists(player):
            return await self.bot.say("You don't have a bank account. "
                                      "Use `{0}bank register` to open one, "
                                      "then try `{0}steal` again.".format(ctx.prefix))

        # Check if main_menu is already running for them
        if player.id in self.menu_users:
            message = "The command is already running for you here."
            return await self.bot.send_message(player, message)

        # Add user to menu_users
        self.menu_users[player.id] = {
            "main_menu": {
                "prompt": "What would you like to do?",
                "choice_type": "multi",
                "choices": [
                    ("Steal from someone", self.generate_steal_menu, []),
                    ("Buy an upgrade", self.generate_upgrade_menu, []),
                    ("Activate an upgrade path", self.generate_activate_menu, []),
                    ("Quit", "done")
                ]
            },
            "target_not_found": {
                "prompt": "Target not found. Try again?",
                "choice_type": "multi",
                "choices": [
                    ("Yes", "steal_menu"),
                    ("No", "main_menu")
                ]
            },
            "done": {}
        }

        # Add player, display newbie introduction
        if player.id not in servers[server.id]["Players"]:
            d_message = await self.bot.say("Check for a direct message from me.")
            servers[server.id]["Players"][player.id] = copy.deepcopy(PLAYER_DEFAULT)
            dataIO.save_json(SAVE_FILEPATH, self.save_file)

            message = ("Welcome to the world of crime!\n"
                       "There are three upgrade paths you can choose from. "
                       "You can upgrade in multiple paths at once, but only one "
                       "upgrade path can be active at once. Activating an upgrade "
                       "path means turning on the benefits that path provides "
                       "(and turning off the benefits your previous path provided).\n\n"
                       "Right now, your active path is Advanced Security. Learn more "
                       "about each path at https://github.com/keanemind/Keane-Cogs/wiki/Commands#steal \n\n"
                       "**NOTICE: immediately deleting your `!steal` message "
                       "that invoked this command is recommended every time you "
                       "use steal. This will prevent other members of the server from "
                       "learning that you are using the command, possibly to steal from them.**")
            await self.bot.send_message(player, message)
            await asyncio.sleep(4)
            await self.bot.delete_message(d_message)

        # Menu
        current_menu = self.menu_users[player.id]["main_menu"]
        while current_menu and not self.unloading:
            if current_menu["choice_type"] == "multi":
                # Display prompt and choices
                message = current_menu["prompt"]
                for index, choice_tuple in enumerate(current_menu["choices"]):
                    message += "\n{}. {}".format(index + 1, choice_tuple[0])
                d_message = await self.bot.send_message(player, message)

                # Receive user's choice
                response = await self.bot.wait_for_message(timeout=60,
                                                           author=player,
                                                           channel=d_message.channel)

                if response is None:
                    current_menu = self.menu_users[player.id]["done"]
                    continue

                try:
                    user_choice = int(response.content)
                except ValueError:
                    await self.bot.send_message(player, "Please choose a number from the menu.")
                    continue

                if user_choice < 1 or user_choice > len(current_menu["choices"]):
                    await self.bot.send_message(player, "Please choose a number from the menu.")
                    continue

                # Move to next state based on their choice
                choice = current_menu["choices"][user_choice - 1]

                if len(choice) == 3: # a function needs to be called
                    next_menu = await choice[1](ctx, *choice[2])
                    current_menu = self.menu_users[player.id][next_menu]
                else:
                    current_menu = self.menu_users[player.id][choice[1]]

            elif current_menu["choice_type"] == "free": # all free choice menus have a function to call
                # Display prompt
                d_message = await self.bot.send_message(player, current_menu["prompt"])

                # Receive user's choice
                response = await self.bot.wait_for_message(timeout=30,
                                                           author=player,
                                                           channel=d_message.channel)

                if response is None:
                    current_menu = self.menu_users[player.id]["done"]
                    continue

                # Call function and move to next state based on the function's return
                next_menu = await current_menu["action"](ctx, response, *current_menu["args"])
                current_menu = self.menu_users[player.id][next_menu]

        await self.bot.send_message(player, "Goodbye!")

        del self.menu_users[player.id]

# Beginning of menu functions
    async def generate_steal_menu(self, ctx):
        """If off cooldown, create a steal menu dict and add it
        to the user's menus. Return the new menu's key."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        # Check cooldown
        since_steal = round(time.time() - playersave["StealTime"])
        if since_steal < 60 * 60:
            time_left = time_left_str(since_steal)
            message = "Steal is on cooldown. Time left: " + time_left
            await self.bot.send_message(player, message)
            return "main_menu"

        # Create menu
        self.menu_users[player.id]["steal_menu"] = {
            "prompt": ("Who do you want to steal from? The user must be on the "
                       "server you used `!steal` in. Enter a nickname, username, "
                       "or for best results, a full tag like Keane#8251."),
            "choice_type": "free",
            "action": self.get_target,
            "args": []
        }
        return "steal_menu"

    async def generate_upgrade_menu(self, ctx):
        """Create an upgrade menu dict and add it to the user's menus.
        Return the new menu's key."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        # Create menu
        self.menu_users[player.id]["upgrade_menu"] = {
            "prompt": "What would you like to upgrade? \*currently active",
            "choice_type": "multi",
            "choices": []
        }

        # Generate choices and add them to the list
        choices = self.menu_users[player.id]["upgrade_menu"]["choices"]
        for upgrade_name in PRIMARY_UPGRADES:
            option_text = "{} (lvl {})".format(upgrade_name, playersave[upgrade_name])
            if upgrade_name == playersave["Active"]:
                option_text += "*"
            choices.append((option_text, self.attempt_upgrade, [upgrade_name]))

        choices.append(("Go back", "main_menu"))

        return "upgrade_menu"

    async def generate_activate_menu(self, ctx):
        """If off cooldown, create an activate menu dict and add it
        to the user's menus. Return the new menu's key."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        # Check cooldown
        since_activate = round(time.time() - playersave["ActivateTime"])
        if since_activate < 60 * 60:
            time_left = time_left_str(since_activate)
            message = "Activate is on cooldown. Time left: " + time_left
            await self.bot.send_message(player, message)
            return "main_menu"

        # Create menu
        self.menu_users[player.id]["activate_menu"] = {
            "prompt": ("{} is active. What would you like to activate?"
                       .format(playersave["Active"])),
            "choice_type": "multi",
            "choices": []
        }

        # Generate choices and add them to the list
        choices = self.menu_users[player.id]["activate_menu"]["choices"]
        for upgrade_name in PRIMARY_UPGRADES:
            if upgrade_name != playersave["Active"]:
                option_text = "{} (lvl {})".format(upgrade_name, playersave[upgrade_name])
                choices.append((option_text, self.activate, [upgrade_name]))

        choices.append(("Go back", "main_menu"))

        return "activate_menu"

    async def get_target(self, ctx, response):
        """Convert the user's response to a target, then steal from the target."""
        server = ctx.message.server
        player = ctx.message.author
        target = server.get_member_named(response.content)

        if target is None:
            return "target_not_found"

        else:
            if "#" not in response.content:
                self.menu_users[player.id]["target_confirmation"] = {
                    "prompt": "Is {} the correct target?".format(target.mention),
                    "choice_type": "multi",
                    "choices": [
                        ("Yes", self.attempt_steal, [target]),
                        ("No", "steal_menu")
                    ]
                }
                return "target_confirmation"

            return await self.attempt_steal(ctx, target)

    async def attempt_steal(self, ctx, target):
        """Wrapper function with safety checks that steals and returns main_menu."""
        server = ctx.message.server
        player = ctx.message.author
        player_data = self.save_file["Servers"][server.id]["Players"]
        bank = self.bot.get_cog("Economy").bank

        if not bank.account_exists(target):
            await self.bot.send_message(player, "That person doesn't have a bank account.")
            return "main_menu"

        if target.id not in player_data:
            player_data[target.id] = copy.deepcopy(PLAYER_DEFAULT)
            dataIO.save_json(SAVE_FILEPATH, self.save_file)

        await self.steal_credits(ctx, target)
        player_data[player.id]["StealTime"] = time.time()
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

        return "main_menu"

    async def attempt_upgrade(self, ctx, upgrade_name):
        """Check if the path is already max level. Returns a menu key."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        if playersave[upgrade_name] >= 99:
            await self.bot.send_message(player, "That path is already max level.")
            return "upgrade_menu"

        self.menu_users[player.id]["num_levels_menu"] = {
            "prompt": ("How many levels would you like to upgrade? "
                       "Must be between 1 and {} inclusive. Reply with a non-number "
                       "to cancel.".format(99 - playersave[upgrade_name])),
            "choice_type": "free",
            "action": self.attempt_upgrade2,
            "args": [upgrade_name]
        }

        return "num_levels_menu"

    async def attempt_upgrade2(self, ctx, response, upgrade_name):
        """Check if the response is a valid number of levels to upgrade.
        Returns a menu key."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        # Check the user's response
        try:
            lvls = int(response.content)
        except ValueError:
            await self.bot.send_message(player, "Upgrade cancelled.")
            return "upgrade_menu"

        if lvls < 1 or lvls > 99 - playersave[upgrade_name]:
            await self.bot.send_message(player, "Please choose a number within the range.")
            return "num_levels_menu"

        # Check if the user can afford the upgrade
        current_lvl = playersave[upgrade_name]
        cost = (5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933)

        if playersave["Blackmarket Finances"] == 99:
            cost = round(cost / 2)
        else:
            cost = round(cost)

        self.menu_users[player.id]["upgrade_confirm_menu"] = {
            "prompt": "This will cost {} credits. If you cannot afford the cost, "
                      "the maximum number of levels you can afford will be upgraded."
                      .format(cost),
            "choice_type": "multi",
            "choices": [
                ("Continue", self.attempt_upgrade3, [upgrade_name, lvls, cost]),
                ("Cancel", "upgrade_menu")
            ]
        }

        return "upgrade_confirm_menu"

    async def attempt_upgrade3(self, ctx, upgrade_name, lvls, cost):
        """Try to upgrade the number of levels passed."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]
        bank = self.bot.get_cog("Economy").bank

        if not bank.can_spend(player, cost):
            balance = bank.get_balance(player)
            current_lvl = playersave[upgrade_name]

            # Find how many levels the user can afford to upgrade
            num = balance / 5
            if playersave["Blackmarket Finances"] == 99:
                num *= 2
            num += current_lvl**1.933
            num = num**(1/1.933) - current_lvl
            # num is the exact number of levels the user can afford to upgrade

            lvls = int(num) # round down

            if lvls == 0:
                message = "You cannot afford to upgrade this path at all."
                await self.bot.send_message(player, message)
                return "upgrade_menu"

            # Calculate reduced cost
            cost = (5 * (current_lvl + lvls)**1.933) - (5 * current_lvl**1.933)
            if playersave["Blackmarket Finances"] == 99:
                cost = round(cost / 2)
            else:
                cost = round(cost)

        bank.withdraw_credits(player, cost)
        playersave[upgrade_name] += lvls
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

        await self.bot.send_message(player, "Upgrade complete.")

        return "main_menu"

    async def activate(self, ctx, upgrade_name):
        """Activate an upgrade path."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]

        playersave["Active"] = upgrade_name
        playersave["ActivateTime"] = time.time()
        dataIO.save_json(SAVE_FILEPATH, self.save_file)

        await self.bot.send_message(player, "Activation complete.")
        return "main_menu"
# End of menu functions

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
            if (targetsave["Active"] == "Advanced Security"
                    and random.randint(1, 100) <= targetsave["Advanced Security"]):
                bank.deposit_credits(target, 1000)
            return
        else:
            await self.bot.send_message(player, "You're in!")
            await asyncio.sleep(1)

        # ATTACKER: ELITE RAID
        if playersave["Active"] == "Elite Raid":
            # Elite Raid v Elite Raid
            if targetsave["Active"] == "Elite Raid":
                if random.randint(1, 100) <= 66:
                    await self.er_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

            # Elite Raid v Advanced Security
            elif targetsave["Active"] == "Advanced Security":
                if targetsave["Advanced Security"] == 99:
                    success_chance = 33 / 2
                else:
                    success_chance = 33

                if random.randint(1, 100) <= success_chance:
                    await self.er_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                    if random.randint(1, 100) <= targetsave["Advanced Security"]:
                        bank.deposit_credits(target, 1000)

                    # Elite Raid is immune to Advanced Security's cameras

                if playersave["Elite Raid"] >= 66:
                    if random.randint(1, 100) <= 33:
                        if targetsave["Advanced Security"] > 5:
                            targetsave["Advanced Security"] -= 5
                        else:
                            targetsave["Advanced Security"] = 0

            # Elite Raid v Blackmarket Finances
            elif targetsave["Active"] == "Blackmarket Finances":
                if random.randint(1, 100) <= 66:
                    await self.er_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                if targetsave["Blackmarket Finances"] >= 66:
                    if random.randint(1, 100) <= 33:
                        if playersave["Elite Raid"] > 5:
                            playersave["Elite Raid"] -= 5
                        else:
                            playersave["Elite Raid"] = 0

        # ATTACKER: ADVANCED SECURITY
        elif playersave["Active"] == "Advanced Security":
            # Advanced Security v Elite Raid
            if targetsave["Active"] == "Elite Raid":
                if random.randint(1, 100) <= 33:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

            # Advanced Security v Advanced Security
            elif targetsave["Active"] == "Advanced Security":
                if targetsave["Advanced Security"] == 99:
                    success_chance = 33 / 2
                else:
                    success_chance = 33

                if random.randint(1, 100) <= success_chance:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                    if random.randint(1, 100) <= targetsave["Advanced Security"]:
                        bank.deposit_credits(target, 1000)

                    if targetsave["Advanced Security"] >= 33:
                        await self.reveal_attacker(ctx, target)

            # Advanced Security v Blackmarket Finances
            elif targetsave["Active"] == "Blackmarket Finances":
                if random.randint(1, 100) <= 33:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

        # ATTACKER: BLACKMARKET FINANCES
        elif playersave["Active"] == "Blackmarket Finances":
            # Blackmarket Finances v Elite Raid
            if targetsave["Active"] == "Elite Raid":
                if random.randint(1, 100) <= 50:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

            # Blackmarket Finances v Advanced Security
            elif targetsave["Active"] == "Advanced Security":
                if targetsave["Advanced Security"] == 99:
                    success_chance = 33 / 2
                else:
                    success_chance = 33

                if random.randint(1, 100) <= success_chance:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

                    if random.randint(1, 100) <= targetsave["Advanced Security"]:
                        bank.deposit_credits(target, 1000)

                    if targetsave["Advanced Security"] >= 33:
                        await self.reveal_attacker(ctx, target)

                if targetsave["Advanced Security"] >= 66:
                    if random.randint(1, 100) <= 33:
                        if playersave["Blackmarket Finances"] > 5:
                            playersave["Blackmarket Finances"] -= 5
                        else:
                            playersave["Blackmarket Finances"] = 0

            # Blackmarket Finances v Blackmarket Finances
            elif targetsave["Active"] == "Blackmarket Finances":
                if random.randint(1, 100) <= 50:
                    await self.regular_steal(ctx, target)
                else:
                    await self.steal_failure(ctx)

        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    async def er_steal(self, ctx, target):
        """Elite Raid steal."""
        player = ctx.message.author
        server = ctx.message.server
        playersave = self.save_file["Servers"][server.id]["Players"][player.id]
        bank = self.bot.get_cog("Economy").bank

        if playersave["Elite Raid"] == 99:
            # 1/10 chance to steal 110% of wealth, if steal successful in the first place
            if random.randint(1, 100) <= 10:
                amt_stolen = round(bank.get_balance(target) * 1.1)
                bank.set_credits(target, 0)
                bank.deposit_credits(player, amt_stolen)

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

        if random.randint(1, 100) <= playersave["Elite Raid"]:
            amt_stolen *= 2

        if playersave["Elite Raid"] >= 33:
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
            .format(player.mention, playersave["Active"])
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
        await self.bot.wait_until_ready()

        while True:
            now = datetime.datetime.utcnow()
            bank = self.bot.get_cog("Economy").bank
            last_given = datetime.datetime.strptime(self.save_file["Global"]["CreditsGivenTime"],
                                                    "%Y-%m-%dT%H:%M:%S.%f")
            if last_given.hour == now.hour and last_given.date() == now.date():
                next_time = now + datetime.timedelta(hours=1)
                next_time = next_time.replace(minute=random.randint(0, 59),
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
                    if (playersave["Active"] == "Blackmarket Finances"
                            and playersave["Blackmarket Finances"] > 0):
                        player = server.get_member(playerid)
                        bank.deposit_credits(player, playersave["Blackmarket Finances"])

            self.save_file["Global"]["CreditsGivenTime"] = datetime.datetime.utcnow().isoformat()
            dataIO.save_json(SAVE_FILEPATH, self.save_file)

    async def daily_report(self):
        """Loop to report theft every day."""
        await self.bot.wait_until_ready()

        now = datetime.datetime.utcnow()
        wake_time = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now.time() > wake_time.time():
            wake_time = wake_time + datetime.timedelta(days=1)

        while True:
            await asyncio.sleep((wake_time - datetime.datetime.utcnow()).total_seconds())
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

    def update_version(self):
        """Update the save file if necessary."""
        if "Version" not in self.save_file["Global"]: # if Version 1.0
            for serverid in self.save_file["Servers"]:
                for playerid in self.save_file["Servers"][serverid]["Players"]:
                    playersave = self.save_file["Servers"][serverid]["Players"][playerid]

                    playersave["StealTime"] = playersave["LatestSteal"]
                    del playersave["LatestSteal"]
                    playersave["ActivateTime"] = 0

            self.save_file["Global"]["Version"] = "1.1"

        if self.save_file["Global"]["Version"] == "1.1":
            for serverid in self.save_file["Servers"]:
                for playerid in self.save_file["Servers"][serverid]["Players"]:
                    playersave = self.save_file["Servers"][serverid]["Players"][playerid]

                    convert_dict = {
                        "AS": "Advanced Security",
                        "ER": "Elite Raid",
                        "BF": "Blackmarket Finances"
                    }
                    playersave["Active"] = convert_dict[playersave["Active"]]

                    for key, value in convert_dict.items():
                        playersave[value] = playersave[key]
                        del playersave[key]

            self.save_file["Global"]["Version"] = "1.2"

        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    def __unload(self):
        self.unloading = True
        self.loop_task.cancel()
        self.loop_task2.cancel()

def time_left_str(since_time):
    """Return a string with how much time is left until
    the 1 hour cooldown is over."""
    until_available = (60 * 60) - since_time
    minute, second = divmod(until_available, 60)
    hour, minute = divmod(minute, 60)
    return "{:d}:{:02d}:{:02d}".format(hour, minute, second)

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
