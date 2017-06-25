import os
import random
import asyncio
import copy
import time
import datetime

import discord
from discord.ext import commands
from __main__ import send_cmd_help
from .utils import checks
from .utils.dataIO import dataIO

SERVER_DEFAULT = {"Parrot":{"Appetite":0, # the maximum number of pellets Parrot can be fed (resets every starve_check loop)
                            "LoopsAlive":0, # the number of starve_check loops the Parrot has gone through
                            "UserWith":"",
                            "Fullness":0, # the number of pellets Parrot has in his belly
                            "Cost":5, # the cost of feeding Parrot 1 pellet
                            "StarvedLoops":0 # tracks what phase of starvation Parrot is in
                           },
                  "Feeders":{} # contains user IDs as keys and the number of pellet's they've fed as the value (resets every starve_check loop)
                 }

SAVE_FILEPATH = "data/KeaneCogs/parrot/parrot.json"

PARROT_INFO_SAYINGS = ["healthy", "starving", "deathbed (will die if not fed!)"]

class Parrot:
    """Commands related to feeding the bot"""
    start_time = 0.0

    def __init__(self, bot):
        self.save_file = dataIO.load_json(SAVE_FILEPATH)
        self.bot = bot

        self.starve_time = copy.deepcopy(self.save_file["Global"]["StarveTime"])
        # this is the variable used by the starve_check pauses
        # the current running starve_time is set only when the cog is first loaded.
        # reset the cog to apply a change to ["StarveTime"] saved by setstarvetime

        self.loop_task = bot.loop.create_task(self.starve_check()) # remember to also change the unload function

    @commands.command(pass_context=True, no_pm=True)
    async def feed(self, ctx, amount: int):
        """Feed the parrot!"""
        bank = self.bot.get_cog('Economy').bank
        server = ctx.message.server

        # check if user has a bank account to withdraw credits from
        if not bank.account_exists(ctx.message.author):
            return await self.bot.say("You need to have a bank account with credits to feed me. Use !bank register to open one.")

        # make sure the server is in the data file
        self.add_server(server)

        # feeding negative pellets is not allowed
        if amount <= 0:
            return await self.bot.say("You can't feed me nothing!")

        # make sure parrot isn't full
        if self.save_file["Servers"][server.id]["Parrot"]["Fullness"] == self.save_file["Servers"][server.id]["Parrot"]["Appetite"]:
            return await self.bot.say("I'm full! I don't want to get fat.")

        # make sure parrot doesn't get overfed
        if self.save_file["Servers"][server.id]["Parrot"]["Fullness"] + amount > self.save_file["Servers"][server.id]["Parrot"]["Appetite"]:
            amount -= self.save_file["Servers"][server.id]["Parrot"]["Fullness"] + amount - self.save_file["Servers"][server.id]["Parrot"]["Appetite"]
            await self.bot.say("I don't want to be too full. I'll only eat " + str(amount) + " pellets, and you can keep the rest.")

        usercost = amount * self.save_file["Servers"][server.id]["Parrot"]["Cost"]

        # confirmation prompt
        await self.bot.say("You are about to spend " + str(usercost) + " credits to feed me " + str(amount) + " pellets. Reply \"yes\" to confirm.")
        response = await self.bot.wait_for_message(author=ctx.message.author)
        if response.content.lower().strip() != "yes":
            return await self.bot.say("Okay then, but don't let me starve!")

        # deduct usercost from their credits account
        if bank.can_spend(ctx.message.author, usercost):
            bank.withdraw_credits(ctx.message.author, usercost)
        else:
            return await self.bot.say("You don't have enough credits to feed me that much.")

        # record how much the user has fed for the day
        if ctx.message.author.id not in self.save_file["Servers"][server.id]["Feeders"]: # set up user's dict in the data file
            self.save_file["Servers"][server.id]["Feeders"][ctx.message.author.id] = amount
        else:
            self.save_file["Servers"][server.id]["Feeders"][ctx.message.author.id] += amount

        # change parrot's fullness level
        self.save_file["Servers"][server.id]["Parrot"]["Fullness"] += amount

        dataIO.save_json(SAVE_FILEPATH, self.save_file)
        return await self.bot.say("Om nom nom. Thanks!")

    @commands.group(pass_context=True, no_pm=True)
    async def parrot(self, ctx):
        """Parrot needs to be fed! Every day, Parrot has a different appetite value, which is how many food pellets he would like to be fed for the day. Spend your credits to feed Parrot pellets using the !feed command, and find out how full Parrot is or what his appetite is by using the !parrot info command."""

        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @parrot.command(name="info", pass_context=True)
    async def parrotinfo(self, ctx):
        """Information about the parrot"""
        server = ctx.message.server
        self.add_server(server) # make sure the server is in the data file

        fullness = "Fullness: " + str(self.save_file["Servers"][server.id]["Parrot"]["Fullness"]) + " out of " + str(self.save_file["Servers"][server.id]["Parrot"]["Appetite"]) + " pellets"
        feed_cost = "Cost to feed: " + str(self.save_file["Servers"][server.id]["Parrot"]["Cost"]) + " credits per pellet"
        days_living = "Age: " + str((self.save_file["Servers"][server.id]["Parrot"]["LoopsAlive"] * self.starve_time) // 86400) + " days" # displays actual days lived, not number of loops
        status = "Status: " + PARROT_INFO_SAYINGS[self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"]]

        if self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"] == 0:
            time_until_starved = "Time until Parrot begins starving: "
        elif self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"] == 1:
            time_until_starved = "Time until Parrot becomes deathly hungry: "
        else:
            time_until_starved = "Time until Parrot dies of starvation: "

        if (self.save_file["Servers"][server.id]["Parrot"]["Fullness"] / self.save_file["Servers"][server.id]["Parrot"]["Appetite"]) >= 0.5:
            time_until_starved += "Parrot has been fed enough food that he won't starve today!"
        elif self.save_file["Servers"][server.id]["Parrot"]["LoopsAlive"] == 0:
            time_until_starved += str(datetime.timedelta(seconds=round((self.starve_time * 2) - ((time.time() - (Parrot.start_time + (self.starve_time * 0.2))) % self.starve_time))))
        else:
            time_until_starved += str(datetime.timedelta(seconds=round(self.starve_time - ((time.time() - (Parrot.start_time + (self.starve_time * 0.2))) % self.starve_time))))
        # say you're checking every 60 seconds instead of self.starve_time seconds
        # (Parrot.start_time + (60 * 0.2)) is the actual start time of starve_check
        # (time.time() - actual_start_time) is how long it's been (in seconds) since starve_check started
        # (time_since_started % 60) resets to 0 every time it hits a multiple of 60
        # (60 - time_since_started_capped_at_60) is how long is left until the check runs again
        # if Parrot has been alive 0 days, (60*2 - time_since_started_capped_at_60) is how long is left until the next starve phase
        # datetime.timedelta formats this number of seconds into 0:00:00

        return await self.bot.say(fullness + "\n" + feed_cost + "\n" + days_living + "\n" + status + "\n" + time_until_starved)

    @parrot.command(name="setcost", pass_context=True)
    @checks.admin_or_permissions(manage_server=True) # only server admins can use this command
    async def parrot_set_cost(self, ctx, cost: int):
        """Change how much it costs to feed the parrot 1 pellet"""
        server = ctx.message.server
        self.add_server(server) # make sure the server is in the data file
        if cost >= 0:
            self.save_file["Servers"][server.id]["Parrot"]["Cost"] = cost
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            return await self.bot.say("Set cost of feeding to " + str(cost) + " credits per pellet.")
        else:
            return await self.bot.say("Cost must be at least 0.")

    @parrot.command(name="setstarvetime", pass_context=True, no_pm=False) # setstarvetime still cannot be used in PM?
    @checks.is_owner() # only the bot OWNER can use this command
    async def parrot_set_starve_time(self, ctx, seconds: int):
        """Change how long (in seconds) server members have to feed Parrot before he starves"""

        # confirmation prompt
        await self.bot.say("This is a global setting that affects all servers the bot is connected to. Parrot periodically checks whether he has starved or not. Are you sure you want Parrot to wait " + str(seconds) + " SECONDS between checks? Reply \"yes\" to confirm.")
        response = await self.bot.wait_for_message(author=ctx.message.author)
        if response.content.lower().strip() != "yes":
            return await self.bot.say("Setting change cancelled.")

        if seconds > 0:
            self.save_file["Global"]["StarveTime"] = seconds
            dataIO.save_json(SAVE_FILEPATH, self.save_file) # IMPORTANT this does not affect the starve_check function until the cog is reloaded. see __init__
            return await self.bot.say("Set period between starvation checks to " + str(seconds) + " seconds. This setting will not go into effect until the cog is reloaded.")
        else:
            return await self.bot.say("Must be at least 1 second.")

    async def starve_check(self):
        """Runs in a loop to periodically check whether Parrot has starved or not"""
        # check if starved. if starved, leave and wipe data
        # otherwise, reset settings except permanent ones (generate new appetite)
        # servers that use a Parrot command for the first time get added to the data file and still follow the starvecheck schedule below

        # IMPORTANT: make sure Parrot is loaded at the time you want the starvation check to be every day

        Parrot.start_time = time.time() - (self.starve_time * 0.2)
        while True:
            await asyncio.sleep(self.starve_time - ((time.time() - Parrot.start_time) % self.starve_time)) # sleep for what's left of the time (approx. 80% of self.starve_time)
            for serverid in self.save_file["Servers"]:
                if (self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] > 0) and ((self.save_file["Servers"][serverid]["Parrot"]["Fullness"] / self.save_file["Servers"][serverid]["Parrot"]["Appetite"]) < 0.5):
                    # different warnings depending on what stage of starvation Parrot is in
                    if self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"] == 0:
                        await self.bot.send_message(self.bot.get_server(serverid), "I'm quite hungry...")
                    elif self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"] == 1:
                        await self.bot.send_message(self.bot.get_server(serverid), "I'm so hungry I feel weak...")
                    else:
                        await self.bot.send_message(self.bot.get_server(serverid), "I'm going to die of starvation tonight if I don't get fed...")

            await asyncio.sleep(self.starve_time * 0.2) # sleep for 20% of the time
            for serverid in list(self.save_file["Servers"]):
                # don't check on the first loop to give new servers a chance in case they got added at an unlucky time (right before the check happens)
                if (self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] > 0) and ((self.save_file["Servers"][serverid]["Parrot"]["Fullness"] / self.save_file["Servers"][serverid]["Parrot"]["Appetite"]) < 0.5):
                    # if it's not the first loop AND the users have not fed Parrot halfway...
                    if self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"] == 2:
                        # if Parrot has been on stage 2 of starvation, stage 3 is death; die to starvation
                        await self.bot.send_message(self.bot.get_server(serverid), "Oh no! I've starved to death!\nGoodbye, cruel world!")
                        await self.bot.leave_server(self.bot.get_server(serverid)) # leave the server. disable when testing

                        # delete server from data file
                        del self.save_file["Servers"][serverid]

                    else:
                        # not dead yet, but dying; Parrot advances to the next stage of starvation
                        self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"] += 1
                        self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] += 1
                        self.save_file["Servers"][serverid]["Parrot"]["Appetite"] = round(random.normalvariate(50*(1.75**self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"]), 6))
                        self.save_file["Servers"][serverid]["Parrot"]["Fullness"] = 0
                        self.save_file["Servers"][serverid]["Parrot"]["UserWith"] = ""
                        self.save_file["Servers"][serverid]["Feeders"].clear() # https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python
                else:
                    # healthy; reset for the next loop
                    self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"] = 0 # reset StarvedLoops because Parrot is healthy now
                    self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] += 1
                    self.save_file["Servers"][serverid]["Parrot"]["Appetite"] = round(random.normalvariate(50*(1.75**self.save_file["Servers"][serverid]["Parrot"]["StarvedLoops"]), 6))
                    self.save_file["Servers"][serverid]["Parrot"]["Fullness"] = 0
                    self.save_file["Servers"][serverid]["Parrot"]["UserWith"] = ""
                    self.save_file["Servers"][serverid]["Feeders"].clear() # https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python

            dataIO.save_json(SAVE_FILEPATH, self.save_file)

    def add_server(self, server):
        """Adds the server to the file if it isn't already in it"""
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = copy.deepcopy(SERVER_DEFAULT)
            self.save_file["Servers"][server.id]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            print(str(datetime.datetime.now()) + "New server \"" + server.name + "\" found and added to Parrot data file!")

        return

    def __unload(self):
        self.loop_task.cancel()

def dir_check():
    """Creates a folder and save file for the cog if they don't exist"""
    if not os.path.exists("data/KeaneCogs/parrot"):
        print("Creating data/KeaneCogs/parrot folder...")
        os.makedirs("data/KeaneCogs/parrot")

    if not dataIO.is_valid_json(SAVE_FILEPATH):
        print("Creating default parrot.json...")
        dataIO.save_json(SAVE_FILEPATH, {"Servers": {}, "Global": {"StarveTime": 86400}})

def setup(bot):
    dir_check()
    bot.add_cog(Parrot(bot))
