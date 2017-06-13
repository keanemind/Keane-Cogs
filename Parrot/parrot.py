import os
import random
import asyncio
import copy

import discord
from .utils import checks
from .utils.dataIO import dataIO
from discord.ext import commands
from __main__ import send_cmd_help

server_default = {"Parrot":{"Appetite":0, 
                            "DaysAlive":0,
                            "UserWith":"", 
                            "Fullness":0, 
                            "Cost":5
                            },
                  "Feeders":{}
                  }

save_filepath = "data/KeaneCogs/parrot/parrot.json"

class Parrot:
    """learning stuff"""
    def __init__(self, bot): 
        self.save_file = dataIO.load_json(save_filepath)
        self.bot = bot

        self.loop_task = bot.loop.create_task(self.daily_check()) #remember to also change the unload function

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
        await self.bot.say("You are about to spend " + str(usercost) + " credits to feed Parrot " + str(amount) + " pellets. Reply with yes to confirm.")
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
        return await self.bot.say("You spent " + str(usercost) + " credits to feed Parrot " + str(amount) + " pellets.") #remove this after making confirmation prompt
        
    #also plan the Parrot With function

    @commands.group(pass_context=True, no_pm=True)
    async def parrot(self, ctx): #need a fix in here
        """Parrot needs to be fed! Every day, Parrot has a different appetite value, which is how many food pellets he would like to be fed for the day. Spend your credits to feed Parrot pellets using the !feed command, and find out how full Parrot is or what his appetite is by using the !parrot info command."""

        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx) #broken for some odd reason wtf

    @parrot.command(name="info", pass_context=True)
    async def parrotinfo(self, ctx):
        """Information about the parrot"""
        server = ctx.message.server
        self.add_server(server) #make sure the server is in the database

        await self.bot.say("Fullness: " + str(self.save_file["Servers"][server.id]["Parrot"]["Fullness"]) + " out of " + str(self.save_file["Servers"][server.id]["Parrot"]["Appetite"]) + "\n" + \
        "Cost to feed: " + str(self.save_file["Servers"][server.id]["Parrot"]["Cost"]) + "\n" \
        "Days living (age): " + str(self.save_file["Servers"][server.id]["Parrot"]["DaysAlive"])) #+ "\n" + eventually show who he's currently with

    @parrot.command(name="setcost", pass_context=True)
    @checks.admin_or_permissions(manage_server=True) #only admins can use this command
    async def parrotsetcost(self, ctx, cost: int):
        """Change how much it costs to feed the parrot 1 pellet"""
        server = ctx.message.server
        self.add_server(server) #make sure the server is in the database
        if cost >= 0:
            self.save_file["Servers"][server.id]["Parrot"]["Cost"] = cost
            dataIO.save_json(save_filepath, self.save_file)
            return await self.bot.say("Set cost of feeding to " + str(cost))
        else:
            return await self.bot.say("Cost must be at least 0")

    async def daily_check(self): 
        #check if starved, and leave if starved, saving certain data and deleting others
        #otherwise reset settings except permanent ones, generate new appetite
        while True:
            await asyncio.sleep(3600) #24 hours is 86400s            
            for serverid in list(self.save_file["Servers"]): #wont run when the database is empty

                #don't check on day 0 to give new servers a chance... see if the server has starved Parrot (he's less than halfway fed)
                if (self.save_file["Servers"][serverid]["Parrot"]["DaysAlive"] != 0) and ((self.save_file["Servers"][serverid]["Parrot"]["Fullness"] / self.save_file["Servers"][serverid]["Parrot"]["Appetite"]) < 0.5):
                    #die to starvation
                    for server in self.bot.servers:
                        if server.id == serverid:
                            await self.bot.send_message(server, "I starved to death!")

                            #leave the server
                            #await self.bot.leave_server(server) #DISABLED FOR TESTING

                            break

                    #delete server from database
                    del self.save_file["Servers"][serverid]

                else:
                    #if it didn't starve, continue living
                    self.save_file["Servers"][serverid]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))
                    self.save_file["Servers"][serverid]["Parrot"]["Fullness"] = 0
                    self.save_file["Servers"][serverid]["Parrot"]["UserWith"] = ""
                    self.save_file["Servers"][serverid]["Feeders"].clear() #https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python

            for serverid in self.save_file["Servers"]:
                self.save_file["Servers"][serverid]["Parrot"]["DaysAlive"] += 1

            dataIO.save_json(save_filepath, self.save_file)
    
    def add_server(self, server): #adds the server that the command was run in into the database if necessary
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = copy.deepcopy(server_default)
            self.save_file["Servers"][server.id]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))    
            dataIO.save_json(save_filepath, self.save_file)
            print("New server found and added to Parrot database!")
        
        return

    def __unload(self):
        self.loop_task.cancel()
        #save data here?

def dir_check():
    if not os.path.exists("data/KeaneCogs/parrot"):
        print("Creating data/KeaneCogs/parrot folder...")
        os.makedirs("data/KeaneCogs/parrot")

    if not dataIO.is_valid_json(save_filepath):
        print("Creating default parrot.json...")
        dataIO.save_json(save_filepath, {"Servers": {}})

def setup(bot): 
    dir_check()
    bot.add_cog(Parrot(bot))