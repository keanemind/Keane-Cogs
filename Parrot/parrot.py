import os
import random
import asyncio
import copy
import time
import datetime

import discord
from .utils import checks
from .utils.dataIO import dataIO
from discord.ext import commands
from __main__ import send_cmd_help

server_default = {"Parrot":{"Appetite":0, 
                            "LoopsAlive":0,
                            "UserWith":"", 
                            "Fullness":0, 
                            "Cost":5
                            },
                  "Feeders":{}
                  }

save_filepath = "data/KeaneCogs/parrot/parrot.json"

class Parrot:
    """Commands related to feeding the bot"""
    start_time = 0.0

    def __init__(self, bot): 
        self.save_file = dataIO.load_json(save_filepath)
        self.bot = bot

        self.starve_time = copy.deepcopy(self.save_file["Global"]["StarveTime"]) #the current running starve_time is set only when the cog is first loaded. reset the cog to apply a change to StarveTime

        self.loop_task = bot.loop.create_task(self.starve_check()) #remember to also change the unload function

    @commands.command(pass_context = True, no_pm = True)
    async def feed(self, ctx, amount: int):
        """Feed the parrot!"""
        bank = self.bot.get_cog('Economy').bank

        #check if user has a bank account to withdraw credits from
        if not bank.account_exists(ctx.message.author): 
            return await self.bot.say("You need to have a bank account to feed Parrot. Use !bank register to open one.")

        self.add_server(ctx.message.server) #make sure the server is in the database

        #negative not allowed
        if amount <= 0:
            return await self.bot.say("You must feed Parrot more than 0 pellets.")

        #make sure parrot isn't full
        if self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Fullness"] == self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Appetite"]:
            return await self.bot.say("Parrot is full! Don't make him fat.")

        #make sure parrot doesn't get overfed
        if self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Fullness"] + amount > self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Appetite"]:
            amount -= self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Fullness"] + amount - self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Appetite"]
            await self.bot.say("You cannot feed Parrot more than his appetite. You will only feed Parrot " + str(amount) + " pellets.")
        usercost = amount * self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Cost"]

        #confirmation prompt
        await self.bot.say("You are about to spend " + str(usercost) + " credits to feed Parrot " + str(amount) + " pellets. Reply \"yes\" to confirm.")
        response = await self.bot.wait_for_message(author = ctx.message.author)
        if response.content.lower().strip() != "yes":
            return await self.bot.say("Okay then, but don't let Parrot starve!")

        #deduct amount*cost from their credits account
        if bank.can_spend(ctx.message.author, usercost):
            bank.withdraw_credits(ctx.message.author, usercost)
        else:
            return await self.bot.say("You don't have enough credits to feed Parrot that much.") #end the function

        #record how much they have fed for the day
        if ctx.message.author.id not in self.save_file["Servers"][ctx.message.server.id]["Feeders"]: #first time feeding today, so set up user's dict in the database
            self.save_file["Servers"][ctx.message.server.id]["Feeders"][ctx.message.author.id] = amount
        else:
            self.save_file["Servers"][ctx.message.server.id]["Feeders"][ctx.message.author.id] += amount
        
        #change parrot's fullness level
        self.save_file["Servers"][ctx.message.server.id]["Parrot"]["Fullness"] += amount

        dataIO.save_json(save_filepath, self.save_file)
        return await self.bot.say("Om nom nom. Thanks!")
        
    #also plan the Parrot With function

    @commands.group(pass_context=True, no_pm=True)
    async def parrot(self, ctx): 
        """Parrot needs to be fed! Every day, Parrot has a different appetite value, which is how many food pellets he would like to be fed for the day. Spend your credits to feed Parrot pellets using the !feed command, and find out how full Parrot is or what his appetite is by using the !parrot info command."""

        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx) 

    @parrot.command(name="info", pass_context=True)
    async def parrotinfo(self, ctx):
        """Information about the parrot"""
        server = ctx.message.server
        self.add_server(server) #make sure the server is in the database

        fullness = "Fullness: " + str(self.save_file["Servers"][server.id]["Parrot"]["Fullness"]) + " out of " + str(self.save_file["Servers"][server.id]["Parrot"]["Appetite"])
        feed_cost = "Cost to feed: " + str(self.save_file["Servers"][server.id]["Parrot"]["Cost"])
        days_living = "Days living (age): " + str((self.save_file["Servers"][server.id]["Parrot"]["LoopsAlive"] * self.starve_time) // 86400) 
        
        if (self.save_file["Servers"][server.id]["Parrot"]["Fullness"] / self.save_file["Servers"][server.id]["Parrot"]["Appetite"]) >= 0.5:
            time_until_starved = "Time until starved: Parrot has been fed enough food that he won't starve today!"
        elif self.save_file["Servers"][server.id]["Parrot"]["LoopsAlive"] == 0:
            time_until_starved = "Time until starved: " + str(datetime.timedelta(seconds = round((self.starve_time * 2) - ((time.time() - (Parrot.start_time + (self.starve_time * 0.2))) % self.starve_time))))
        else:
            time_until_starved = "Time until starved: " + str(datetime.timedelta(seconds = round(self.starve_time - ((time.time() - (Parrot.start_time + (self.starve_time * 0.2))) % self.starve_time))))
        # say you're checking every 60 seconds instead of self.starve_time seconds
        # (Parrot.start_time + (60 * 0.2)) is the actual start time of starve_check
        # (time.time() - actual_start_time) is how long it's been (in seconds) since starve_check started
        # (time_since_started % 60) resets to 0 every time it hits a multiple of 60
        # (60 - time_since_started_capped_at_60) is how long is left until the check runs again
        # if Parrot has been alive 0 days, (60*2 - time_since_started_capped_at_60) is how long is left until he will starve
        # datetime.timedelta formats this number of seconds into 0:00:00 

        return await self.bot.say(fullness + "\n" + feed_cost + "\n" + days_living + "\n" + time_until_starved) #+ "\n" + eventually show who he's currently with

    @parrot.command(name="setcost", pass_context=True)
    @checks.admin_or_permissions(manage_server=True) #only admins can use this command
    async def parrot_set_cost(self, ctx, cost: int):
        """Change how much it costs to feed the parrot 1 pellet"""
        server = ctx.message.server
        self.add_server(server) #make sure the server is in the database
        if cost >= 0:
            self.save_file["Servers"][server.id]["Parrot"]["Cost"] = cost
            dataIO.save_json(save_filepath, self.save_file)
            return await self.bot.say("Set cost of feeding to " + str(cost) + " credits per pellet.")
        else:
            return await self.bot.say("Cost must be at least 0.")

    @parrot.command(name="setstarvetime", pass_context=True, no_pm=False)
    @checks.is_owner() #only the bot OWNER can use this command
    async def parrot_set_starve_time(self, ctx, seconds: int):
        """Change how long (in seconds) server members have to feed Parrot before he starves"""

        #confirmation prompt
        await self.bot.say("This is a global setting that affects all servers the bot is connected to. Parrot periodically checks whether he has starved or not. Are you sure you want Parrot to wait " + str(seconds) + " SECONDS between checks? Reply \"yes\" to confirm.")
        response = await self.bot.wait_for_message(author = ctx.message.author)
        if response.content.lower().strip() != "yes":
            return await self.bot.say("Setting change cancelled.")

        if seconds > 0:
            self.save_file["Global"]["StarveTime"] = seconds
            dataIO.save_json(save_filepath, self.save_file) #IMPORTANT this does not affect the starve_check function until the cog is reloaded. see __init__
            return await self.bot.say("Set period between starvation checks to " + str(seconds) + " seconds. This setting will not go into effect until the cog is reloaded.")
        else:
            return await self.bot.say("Must be at least 1 second.")

    async def starve_check(self): 
        #check if starved. if starved, leave and wipe data
        #otherwise, reset settings except permanent ones (generate new appetite)
        #servers that use a Parrot command for the first time get added to the database and still follow the starvecheck schedule below

        #IMPORTANT: make sure Parrot is loaded at the time you want the starvation check to be every day

        Parrot.start_time = time.time() - (self.starve_time * 0.2) 
        while True:
            await asyncio.sleep(self.starve_time - ((time.time() - Parrot.start_time) % self.starve_time)) #sleep for what's left of the time (approx. 80% of self.starve_time)
            for serverid in self.save_file["Servers"]:
                if (self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] > 0) and ((self.save_file["Servers"][serverid]["Parrot"]["Fullness"] / self.save_file["Servers"][serverid]["Parrot"]["Appetite"]) < 0.5):
                    await self.bot.send_message(self.bot.get_server(serverid), "I'm going to die of starvation soon...")

            await asyncio.sleep(self.starve_time * 0.2) #sleep for 20% of the time... since this is in a separate thread, so users can feed during this sleep
            for serverid in list(self.save_file["Servers"]): 
                #don't check on day 0 to give new servers a chance, and see if the server has starved Parrot (if he's less than halfway fed)
                if (self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] > 0) and ((self.save_file["Servers"][serverid]["Parrot"]["Fullness"] / self.save_file["Servers"][serverid]["Parrot"]["Appetite"]) < 0.5):
                    #die to starvation
                    await self.bot.send_message(self.bot.get_server(serverid), "Oh no! I've starved to death!\nGoodbye, cruel world!")
                    await self.bot.leave_server(self.bot.get_server(serverid)) #leave the server. disable when testing
                    
                    #delete server from database
                    del self.save_file["Servers"][serverid]

                else:
                    #if it didn't starve, continue living
                    self.save_file["Servers"][serverid]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))
                    self.save_file["Servers"][serverid]["Parrot"]["Fullness"] = 0
                    self.save_file["Servers"][serverid]["Parrot"]["UserWith"] = ""
                    self.save_file["Servers"][serverid]["Feeders"].clear() #https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python

            for serverid in self.save_file["Servers"]:
                self.save_file["Servers"][serverid]["Parrot"]["LoopsAlive"] += 1

            dataIO.save_json(save_filepath, self.save_file)
    
    def add_server(self, server): #adds the server that the command was run in into the database if necessary
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = copy.deepcopy(server_default)
            self.save_file["Servers"][server.id]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))    
            dataIO.save_json(save_filepath, self.save_file)
            print("New server \"" + server.name + "\" found and added to Parrot database!")
        
        return

    def __unload(self):
        self.loop_task.cancel()

def dir_check():
    if not os.path.exists("data/KeaneCogs/parrot"):
        print("Creating data/KeaneCogs/parrot folder...")
        os.makedirs("data/KeaneCogs/parrot")

    if not dataIO.is_valid_json(save_filepath):
        print("Creating default parrot.json...")
        dataIO.save_json(save_filepath, {"Servers": {}, "Global": {"StarveTime": 86400}})

def setup(bot): 
    dir_check()
    bot.add_cog(Parrot(bot))
