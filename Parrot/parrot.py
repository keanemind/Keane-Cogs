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
        self.loop_task2 = bot.loop.create_task(self.parrot_shoulder())

    @commands.command(pass_context=True, no_pm=True)
    async def feed(self, ctx, amount: int):
        """Feed the parrot! Use \"!help parrot\" for more information."""
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
            self.save_file["Servers"][server.id]["Feeders"][ctx.message.author.id] = {"PelletsFed":0}

        self.save_file["Servers"][server.id]["Feeders"][ctx.message.author.id]["PelletsFed"] += amount

        # change parrot's fullness level
        self.save_file["Servers"][server.id]["Parrot"]["Fullness"] += amount

        dataIO.save_json(SAVE_FILEPATH, self.save_file)
        return await self.bot.say("Om nom nom. Thanks!")

    @commands.group(pass_context=True, no_pm=True)
    async def parrot(self, ctx):
        """Parrot needs to be fed! Every day, Parrot has a different appetite value,
        which is how many food pellets he would like to be fed for the day.
        Spend your credits to feed Parrot pellets using the !feed command,
        and find out how full Parrot is or what his appetite is by using the !parrot info command.
        Every 20 minutes, Parrot perches on the shoulder of a random user who has fed him.
        The fraction of Parrot's appetite that you have fed him is your chance of being perched on by Parrot.
        In return for providing your shoulder to him, Parrot will help you and give you powers.
        For example, he can assist you with Heists."""

        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @parrot.command(name="info", pass_context=True)
    async def parrot_info(self, ctx):
        """Information about the parrot"""
        server = ctx.message.server
        self.add_server(server) # make sure the server is in the data file

        fullness = str(self.save_file["Servers"][server.id]["Parrot"]["Fullness"]) + " out of " + str(self.save_file["Servers"][server.id]["Parrot"]["Appetite"]) + " pellets"
        feed_cost = str(self.save_file["Servers"][server.id]["Parrot"]["Cost"]) + " credits per pellet"
        days_living = str((self.save_file["Servers"][server.id]["Parrot"]["LoopsAlive"] * self.starve_time) // 86400) + " days" # displays actual days lived, not number of loops
        description = "If Parrot is not fed enough to be half full by the time the timer reaches 0, he will enter the next phase of starvation. Use \"!help parrot\" for more information."

        # status
        if self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"] == 0:
            status = "healthy"
        elif self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"] == 1:
            status = "starving"
        else:
            status = "deathbed (will die if not fed!)"

        # time_until_starved
        if self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"] == 0:
            time_until_starved = "Time until Parrot begins starving: \n"
        elif self.save_file["Servers"][server.id]["Parrot"]["StarvedLoops"] == 1:
            time_until_starved = "Time until Parrot becomes deathly hungry: \n"
        else:
            time_until_starved = "Time until Parrot dies of starvation: \n"

        # time_until_starved continued
        if (self.save_file["Servers"][server.id]["Parrot"]["Fullness"] / self.save_file["Servers"][server.id]["Parrot"]["Appetite"]) >= 0.5:
            time_until_starved = "time until fullness resets: \n" + str(datetime.timedelta(seconds=round(self.starve_time - ((time.time() - (Parrot.start_time + (self.starve_time * 0.2))) % self.starve_time))))
            status = "recovering"
            description = "Parrot has been fed enough food that he won't starve for now. Use \"!help parrot\" for more information."
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

        if self.save_file["Servers"][server.id]["Parrot"]["UserWith"] != "":
            userwith = (await self.bot.get_user_info(self.save_file["Servers"][server.id]["Parrot"]["UserWith"])).mention
        else:
            userwith = "nobody"

        embed = discord.Embed(color=discord.Color.teal(), description=description)
        embed.title = "Parrot Information"
        embed.timestamp = datetime.datetime.utcfromtimestamp(time.time())
        embed.set_thumbnail(url="{}".format(self.bot.user.avatar_url if self.bot.user.avatar_url != "" else self.bot.user.default_avatar_url))
        embed.set_footer(text="Made by Keane")
        embed.add_field(name="Fullness", value=fullness)
        embed.add_field(name="Cost to feed", value=feed_cost)
        embed.add_field(name="Age", value=days_living)
        embed.add_field(name="Status", value=status)
        embed.add_field(name="Perched on", value=userwith)
        embed.add_field(name="Timer", value=time_until_starved)
        return await self.bot.say(embed=embed)

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
        """Change how long (in seconds) server members have to feed Parrot"""

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

    @parrot.command(name="steal", pass_context=True)
    async def parrot_steal(self, ctx, target: discord.Member):
        """Get Parrot to steal up to 1000 of someone's credits for you (can only be used once per user; this limit resets with Parrot's fullness)"""
        if ctx.message.author.id != self.save_file["Servers"][ctx.message.server.id]["Parrot"]["UserWith"]:
            return await self.bot.say("Parrot needs to be perched on you to use this command.")
        if self.save_file["Servers"][ctx.message.server.id]["Feeders"][ctx.message.author.id]["StealAvailable"] is not True:
            return await self.bot.say("You have already used steal. You must wait until Parrot's fullness resets, and be perched on by him again.")

        bank = self.bot.get_cog('Economy').bank

        # check if users have bank accounts to withdraw credits from
        if not bank.account_exists(ctx.message.author):
            return await self.bot.say("You need to have a bank account with credits to store stolen credits. Use !bank register to open one.")
        if not bank.account_exists(target):
            return await self.bot.say("Your target doesn't have a bank account to steal credits from.")

        await self.bot.say("Parrot flies off...")
        await asyncio.sleep(3)

        stolen = round(random.uniform(1, random.uniform(1, 1000)))
        target_balance = bank.get_balance(target)

        if stolen >= target_balance:
            bank.transfer_credits(target, ctx.message.author, target_balance)
            self.save_file["Servers"][ctx.message.server.id]["Feeders"][ctx.message.author.id]["StealAvailable"] = False
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            return await self.bot.say("Parrot stole every last credit (" + str(target_balance) + " credits) from " + target.mention + "'s bank account and deposited it in your account!")
        else:
            bank.transfer_credits(target, ctx.message.author, stolen)
            self.save_file["Servers"][ctx.message.server.id]["Feeders"][ctx.message.author.id]["StealAvailable"] = False
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            return await self.bot.say("Parrot stole " + str(stolen) + " credits from " + target.mention + "'s bank account and deposited it in your account!")

    async def starve_check(self):
        """Runs in a loop to periodically check whether Parrot has starved or not"""
        # check if starved. if starved, leave and wipe data
        # otherwise, reset settings except permanent ones (generate new appetite)
        # servers that use a Parrot command for the first time get added to the data file and still follow the starvecheck schedule below

        # IMPORTANT: make sure Parrot is loaded at the time you want the starvation check to be every day

        Parrot.start_time = time.time() - (self.starve_time * 0.2) #subtract 20% of starve_time so that the first sleep is for 80% not 100% of starve_time
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
                        await self.bot.send_message(self.bot.get_server(serverid), "I'm going to die of starvation very soon if I don't get fed...")

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

    async def parrot_shoulder(self):
        """Runs in a loop to periodically set someone (or nobody) as the person Parrot is with"""
        start_time = time.time()
        while True:
            for serverid in self.save_file["Servers"]:
                # Randomly choose who Parrot is with. This could be nobody, represented by ""
                weights = [(self.save_file["Servers"][serverid]["Feeders"][feederid]["PelletsFed"] / self.save_file["Servers"][serverid]["Parrot"]["Appetite"])*100 for feederid in self.save_file["Servers"][serverid]["Feeders"]]
                population = [feederid for feederid in self.save_file["Servers"][serverid]["Feeders"]]
                weights.append(100 - sum(weights))
                population.append("")
                try:
                    self.save_file["Servers"][serverid]["Parrot"]["UserWith"] = random.choices(population, weights)[0] #random.choices returns a list
                except AttributeError:
                    # DIY random.choices alternative for scrubs who don't have Python 3.6
                    total = 0
                    cum_weights = []
                    for num in weights:
                        total += num
                        cum_weights.append(total)

                    rand = random.uniform(0, 100)
                    for index in range(len(cum_weights)): # apparently I'm supposed to use enumerate to be more Pythonic
                        if cum_weights[index] >= rand:
                            self.save_file["Servers"][serverid]["Parrot"]["UserWith"] = population[index]
                            break

                if self.save_file["Servers"][serverid]["Parrot"]["UserWith"] != "":
                    userwith = self.save_file["Servers"][serverid]["Parrot"]["UserWith"] # this is an ID number
                    if "HeistBoostAvailable" not in self.save_file["Servers"][serverid]["Feeders"][userwith]:
                        self.save_file["Servers"][serverid]["Feeders"][userwith]["HeistBoostAvailable"] = True # give the chosen user HeistBoost ability if they didn't have it before
                    if "StealAvailable" not in self.save_file["Servers"][serverid]["Feeders"][userwith]: # this is not necessary. the following line could go under the if statement above this
                        self.save_file["Servers"][serverid]["Feeders"][userwith]["StealAvailable"] = True # give the chosen user Steal ability if they didn't have it before

            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            await asyncio.sleep(1200 - ((time.time() - start_time) % 1200)) # 20 minutes between updates of who Parrot is with

    def add_server(self, server):
        """Adds the server to the file if it isn't already in it"""
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = copy.deepcopy(SERVER_DEFAULT)
            self.save_file["Servers"][server.id]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            print(str(datetime.datetime.now()) + "New server \"" + server.name + "\" found and added to Parrot data file!")

        return

    def parrot_shoulder_currentuser(self, server):
        """Returns the user ID of whoever Parrot is with"""
        return self.save_file["Servers"][server.id]["Parrot"]["UserWith"]

    def heist_boost_available(self, server, user, availability=True):
        """Returns whether the user has a Heist boost available"""
        if availability is False:
            self.save_file["Servers"][server.id]["Feeders"][user.id]["HeistBoostAvailable"] = False
        return self.save_file["Servers"][server.id]["Feeders"][user.id]["HeistBoostAvailable"]

    def __unload(self):
        self.loop_task.cancel()
        self.loop_task2.cancel()

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
