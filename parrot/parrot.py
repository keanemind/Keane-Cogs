"""A cog that requires server users to feed the bot in return for benefits."""
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

SERVER_DEFAULT = {"Parrot":{"Appetite":0, # the maximum number of pellets Parrot can be fed
                                          # (reset by starve_check)
                            "LoopsAlive":0, # the number of starve_loop loops so far
                            "UserWith":"", # ID of user Parrot is perched on
                                           # (reset by starve_check)
                            "Fullness":0, # the number of pellets Parrot has in his belly
                                          # (reset by starve_check)
                            "Cost":5, # the cost of feeding Parrot 1 pellet
                            "StarvedLoops":0 # tracks what phase of starvation Parrot is in
                           },
                  "Feeders":{} # contains user IDs as keys and dicts as values
                               # (reset by starve_check)
                 }

SAVE_FILEPATH = "data/KeaneCogs/parrot/parrot.json"

class Parrot:
    """Commands related to feeding the bot."""
    start_time = 0.0

    def __init__(self, bot):
        self.save_file = dataIO.load_json(SAVE_FILEPATH)
        self.bot = bot

        self.starve_time = copy.deepcopy(self.save_file["Global"]["StarveTime"])
        # this is the variable used by the starve_loop pauses
        # the current running starve_time is set only when the cog is first loaded.
        # reset the cog to apply a change to ["StarveTime"] saved by setstarvetime

        self.loop_task = bot.loop.create_task(self.starve_loop()) # remember to change __unload()
        self.loop_task2 = bot.loop.create_task(self.parrot_perch())

    @commands.command(pass_context=True, no_pm=True)
    async def feed(self, ctx, amount: int):
        """Feed the parrot! Use \"{prefix}help parrot\" for more information."""
        server = ctx.message.server

        # make sure the server is in the data file
        self.add_server(server)

        parrot = self.save_file["Servers"][server.id]["Parrot"]
        feeders = self.save_file["Servers"][server.id]["Feeders"]
        bank = self.bot.get_cog('Economy').bank

        # check if user has a bank account to withdraw credits from
        if not bank.account_exists(ctx.message.author):
            return await self.bot.say("You need to have a bank account with credits to feed me. "
                                      "Use `{}bank register` to open one.".format(ctx.prefix))

        # feeding negative pellets is not allowed
        if amount <= 0:
            return await self.bot.say("You can't feed me nothing!")

        # make sure parrot isn't full
        if parrot["Fullness"] == parrot["Appetite"]:
            return await self.bot.say("I'm full! I don't want to get fat.")

        # make sure parrot doesn't get overfed
        if parrot["Fullness"] + amount > parrot["Appetite"]:
            amount -= parrot["Fullness"] + amount - parrot["Appetite"]
            await self.bot.say("I don't want to be too full. I'll only eat {} pellets, "
                               "and you can keep the rest.".format(amount))

        usercost = amount * parrot["Cost"]

        # confirmation prompt
        await self.bot.say("You are about to spend {} credits to feed me {} pellets. "
                           "Reply \"yes\" to confirm.".format(usercost, amount))
        response = await self.bot.wait_for_message(author=ctx.message.author)
        if response.content.lower().strip() != "yes":
            return await self.bot.say("Okay then, but don't let me starve!")

        # deduct usercost from their credits account
        if bank.can_spend(ctx.message.author, usercost):
            bank.withdraw_credits(ctx.message.author, usercost)
        else:
            return await self.bot.say("You don't have enough credits to feed me that much.")

        # set up user's dict in the data file
        if ctx.message.author.id not in feeders:
            feeders[ctx.message.author.id] = {"PelletsFed":0}

        # record how much the user has fed for the day
        feeders[ctx.message.author.id]["PelletsFed"] += amount

        # change parrot's fullness level
        parrot["Fullness"] += amount

        dataIO.save_json(SAVE_FILEPATH, self.save_file)
        return await self.bot.say("Om nom nom. Thanks!")

    @commands.group(pass_context=True)
    async def parrot(self, ctx):
        """Parrot needs to be fed! Every day, Parrot has a different appetite value,
        which is how many food pellets he would like to be fed for the day.

        Spend your credits to feed Parrot pellets using the "{prefix}feed" command,
        and find out how full Parrot is or what his appetite is by using the "{prefix}parrot info" command.

        Every 20 minutes, Parrot perches on the shoulder of a random user who has fed him.
        The fraction of Parrot's appetite that you have fed is your chance of being perched on by Parrot.

        In return for providing your shoulder to him, Parrot will help you and give you powers.
        For example, he can assist you with Heists."""

        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @parrot.command(name="setstarvetime", pass_context=True) # no_pm=False
    @checks.is_owner()
    async def parrot_set_starve_time(self, ctx, seconds: int):
        """Change how long (in seconds) server members have to feed Parrot."""

        # confirmation prompt
        await self.bot.say("This is a global setting that affects all servers the bot is connected to. "
                           "Parrot periodically checks whether he has starved or not. "
                           "Are you sure you want Parrot to wait {} SECONDS between checks? "
                           "Reply \"yes\" to confirm.".format(seconds))
        response = await self.bot.wait_for_message(timeout=15, author=ctx.message.author)
        if response is None or response.content.lower().strip() != "yes":
            return await self.bot.say("Setting change cancelled.")

        if seconds > 0:
            self.save_file["Global"]["StarveTime"] = seconds
            dataIO.save_json(SAVE_FILEPATH, self.save_file) # IMPORTANT this does not affect
                                                            # the starve_loop function until
                                                            # the cog is reloaded. see __init__
            return await self.bot.say("Set period between starvation checks to {} seconds. "
                                      "This setting will not go into effect until the cog "
                                      "is reloaded.".format(seconds))
        else:
            return await self.bot.say("Must be at least 1 second.")

    @parrot.command(name="checknow", pass_context=True) # no_pm=False
    @checks.is_owner()
    async def parrot_check_now(self, ctx):
        """Execute a starve check immediately. This will move Parrot to the next
        appetite loop if he survives."""
        await self.starve_check()
        return await self.bot.send_message(ctx.message.author,
                                           "starve_check was executed.")

    @parrot.command(name="setcost", pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_server=True)
    async def parrot_set_cost(self, ctx, cost: int):
        """Change how much it costs to feed the parrot 1 pellet."""
        server = ctx.message.server
        self.add_server(server) # make sure the server is in the data file
        if cost >= 0:
            self.save_file["Servers"][server.id]["Parrot"]["Cost"] = cost
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            return await self.bot.say("Set cost of feeding to {} credits per pellet.".format(cost))
        else:
            return await self.bot.say("Cost must be at least 0.")

    @parrot.command(name="steal", pass_context=True, no_pm=True)
    async def parrot_steal(self, ctx, target: discord.Member):
        """Get Parrot to steal up to 1000 of someone's credits for you.
        One use per user; this limit resets with Parrot's fullness.
        Parrot will not steal from people who have fed him."""
        self.add_server(ctx.message.server) # make sure the server is in the data file

        feeders = self.save_file["Servers"][ctx.message.server.id]["Feeders"]
        parrot = self.save_file["Servers"][ctx.message.server.id]["Parrot"]
        bank = self.bot.get_cog('Economy').bank

        # checks
        error_msg = ""
        if ctx.message.author.id != parrot["UserWith"]:
            error_msg = ("Parrot needs to be perched on you to use this command. "
                         "Use `{}help parrot` for more information.".format(ctx.prefix))
        elif not feeders[ctx.message.author.id]["StealAvailable"]:
            error_msg = ("You have already used steal. You must wait until "
                         "Parrot's fullness resets, and be perched on by him again.")

        elif not bank.account_exists(target):
            error_msg = "Your target doesn't have a bank account to steal credits from."

        elif target.id in feeders:
            error_msg = ("Parrot refuses to steal from someone "
                         "who has fed him in the current fullness cycle.")

        if error_msg:
            return await self.bot.say(error_msg)

        await self.bot.say("Parrot flies off...")
        await asyncio.sleep(3)

        stolen = round(random.uniform(1, random.uniform(1, 1000)))
        target_balance = bank.get_balance(target)

        if stolen >= target_balance:
            bank.transfer_credits(target, ctx.message.author, target_balance)
            feeders[ctx.message.author.id]["StealAvailable"] = False
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            return await self.bot.say("Parrot stole every last credit ({} credits) from {}'s bank "
                                      "account and deposited it in your account!"
                                      .format(target_balance, target.mention))
        else:
            bank.transfer_credits(target, ctx.message.author, stolen)
            feeders[ctx.message.author.id]["StealAvailable"] = False
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            return await self.bot.say("Parrot stole {} credits from {}'s bank account and deposited "
                                      "it in your account!".format(stolen, target.mention))

    @parrot.command(name="airhorn", pass_context=True, no_pm=True)
    async def parrot_airhorn(self, ctx, channel: discord.Channel):
        """Plays an airhorn sound to the target voice channel."""
        # This is copy-pasted from audio.py's play() function and has
        # been modified to always play an airhorn.
        # Audio.py is a part of Red Bot, which is licensed under GPL v3
        # https://www.gnu.org/licenses/gpl-3.0.en.html
        # CHANGES:
        # The function has been renamed to parrot_airhorn, and takes a
        # channel instead of a URL as an argument now.
        # The URL is now hard-coded to be a YouTube link.
        # The try-except clause has been commented out. The calls for
        # functions within audio.py have been changed
        # Changes from self.function() to audio.function() .
        # Newly added lines are labeled with a comment "NEW".
        # No other changes were made.

        server = ctx.message.server
        self.add_server(server) # NEW

        if ctx.message.author.id != self.save_file["Servers"][server.id]["Parrot"]["UserWith"]: # NEW
            return await self.bot.say("Parrot needs to be perched on you to use this command. "
                                      "Use `{}help parrot` for more information.".format(ctx.prefix)) # NEW
        if self.save_file["Servers"][server.id]["Feeders"][ctx.message.author.id]["AirhornUses"] >= 3: # NEW
            return await self.bot.say("You have already used steal 3 times. You must wait until "
                                      "Parrot's fullness resets, and be perched on by him again.") # NEW

        audio = self.bot.get_cog('Audio') # NEW
        url = "https://www.youtube.com/watch?v=XDvuAYySJj0" # This line was changed to be a hard-coded
                                                            # YouTube link instead of being a URL argument.

        # Checking if playing in current server

        if audio.is_playing(server):
            await self.bot.say("Parrot is already playing music in a channel on this server.")
            return  # Default to queue

        # Checking already connected, will join if not

        # try:
        #     audio.has_connect_perm(target, server)
        # except AuthorNotConnected:
        #     await self.bot.say("You must join a voice channel before I can"
        #                        " play anything.")
        #     return
        # except UnauthorizedConnect:
        #     await self.bot.say("I don't have permissions to join your"
        #                        " voice channel.")
        #     return
        # except UnauthorizedSpeak:
        #     await self.bot.say("I don't have permissions to speak in your"
        #                        " voice channel.")
        #     return
        # except ChannelUserLimit:
        #     await self.bot.say("Your voice channel is full.")
        #     return

        if not audio.voice_connected(server):
            await audio._join_voice_channel(channel)
        else:  # We are connected but not to the right channel
            if audio.voice_client(server).channel != channel:
                await audio._stop_and_disconnect(server)
                await audio._join_voice_channel(channel)

        # If not playing, spawn a downloader if it doesn't exist and begin
        #   downloading the next song

        if audio.currently_downloading(server):
            await audio.bot.say("I'm already downloading a file!")
            return

        url = url.strip("<>")

        if audio._match_any_url(url):
            if not audio._valid_playable_url(url):
                await self.bot.say("That's not a valid URL.")
                return
        else:
            url = url.replace("/", "&#47")
            url = "[SEARCH:]" + url

        if "[SEARCH:]" not in url and "youtube" in url:
            url = url.split("&")[0]  # Temp fix for the &list issue

        audio._stop_player(server)
        audio._clear_queue(server)
        audio._add_to_queue(server, url)

        self.save_file["Servers"][server.id]["Feeders"][ctx.message.author.id]["AirhornUses"] += 1 # NEW
        dataIO.save_json(SAVE_FILEPATH, self.save_file) # NEW

    @parrot.command(name="info", pass_context=True, no_pm=True)
    async def parrot_info(self, ctx):
        """Information about the parrot."""
        server = ctx.message.server
        self.add_server(server) # make sure the server is in the data file

        parrot = self.save_file["Servers"][server.id]["Parrot"]

        fullness_str = "{} out of {} pellets".format(parrot["Fullness"], parrot["Appetite"])
        feed_cost_str = "{} credits per pellet".format(parrot["Cost"])
        days_living_str = "{} days".format((parrot["LoopsAlive"] * self.starve_time) // 86400)

        # status and time_until_starved
        if parrot["StarvedLoops"] == 0:
            status_str = "healthy"
            time_until_starved_str = "until Parrot begins\nstarving: "
        elif parrot["StarvedLoops"] == 1:
            status_str = "starving"
            time_until_starved_str = "until Parrot becomes\ndeathly hungry:\n"
        else:
            status_str = "deathbed\n(will die if not fed!)"
            time_until_starved_str = "until Parrot dies of\nstarvation: "

        if parrot["Fullness"] / parrot["Appetite"] >= 0.5:
            description_str = ("Parrot has been fed enough food that he won't starve for now. "
                               "Use `{}help parrot` for more information.".format(ctx.prefix))
            time_until_starved_str = "until fullness resets:\n"
            if parrot["StarvedLoops"] > 0:
                status_str = "recovering"
        else:
            description_str = ("If Parrot is not fed enough to be half full by the time "
                               "the timer reaches 0, he will enter the next phase of "
                               "starvation. Use `{}help parrot` for more information.".format(ctx.prefix))

        actual_start_time = Parrot.start_time + (self.starve_time * 0.2)
        time_since_started = time.time() - actual_start_time
        time_since_last_check = time_since_started % self.starve_time
        if parrot["LoopsAlive"] == 0:
            formatted_time = datetime.timedelta(seconds=round((self.starve_time * 2) - time_since_last_check))
        else:
            formatted_time = datetime.timedelta(seconds=round(self.starve_time - time_since_last_check))
        time_until_starved_str += str(formatted_time)
        # say you're checking every 60 seconds instead of self.starve_time seconds
        # (Parrot.start_time + (60 * 0.2)) is the actual start time of starve_loop
        # (time.time() - actual_start_time) is how long it's been since starve_loop started
        # (time_since_started % 60) resets to 0 every time it hits a multiple of 60
        # (60 - time_since_started_capped_at_60) is how long is left until the check runs again
        # if Parrot has been alive 0 days, it's (60*2 - time_since_started_capped_at_60)
        # datetime.timedelta formats this number of seconds into 0:00:00

        if parrot["UserWith"]:
            userwith_str = server.get_member(parrot["UserWith"]).mention
        else:
            userwith_str = "nobody"

        embed = discord.Embed(color=discord.Color.teal(), description=description_str)
        embed.title = "Parrot Information"
        embed.timestamp = datetime.datetime.utcfromtimestamp(time.time())
        embed.set_thumbnail(url="{}".format(self.bot.user.avatar_url if self.bot.user.avatar_url
                                            else self.bot.user.default_avatar_url))
        embed.set_footer(text="Made by Keane")
        embed.add_field(name="Fullness", value=fullness_str)
        embed.add_field(name="Cost to feed", value=feed_cost_str)
        embed.add_field(name="Age", value=days_living_str)
        embed.add_field(name="Status", value=status_str)
        embed.add_field(name="Perched on", value=userwith_str)
        embed.add_field(name="Countdown", value=time_until_starved_str)
        return await self.bot.say(embed=embed)

    @parrot.command(name="feeders", pass_context=True, no_pm=True)
    async def parrot_feeders(self, ctx):
        server = ctx.message.server
        output = "```py\n"
        feeders = self.save_file["Servers"][server.id]["Feeders"]
        idlist = sorted(list(feeders),
                        key=(lambda idnum: feeders[idnum]["PelletsFed"]),
                        reverse=True)
        for feederid in idlist:
            feeder = server.get_member(feederid)
            if len(feeder.display_name) > 22:
                name = feeder.display_name[:19] + "..."
            else:
                name = feeder.display_name
            output += name
            output += " " * (23 - len(name)) # output is 23 characters now
            pellets_str = str(feeders[feederid]["PelletsFed"])
            output += " " * (3 - (len(pellets_str)))
            output += pellets_str
            output += "\n"
        
        output += "```"
        return await self.bot.say(output)

    async def starve_loop(self):
        """Runs in a loop to periodically check whether Parrot has starved or not."""
        # check if starved. if starved, leave and wipe data
        # otherwise, reset settings except permanent ones (generate new appetite)
        # servers that use a Parrot command for the first time get added to the data file
        # and still follow the starvecheck schedule below

        # IMPORTANT: load Parrot at the time you want the starvation check to be every day

        Parrot.start_time = time.time() - (self.starve_time * 0.2) # subtract 20% of starve_time so that the
                                                                   # first sleep is for 80% not 100% of starve_time
        while True:
            # sleep for what's left of the time (approx. 80% of self.starve_time)
            await asyncio.sleep(self.starve_time - ((time.time() - Parrot.start_time) % self.starve_time))
            for serverid in self.save_file["Servers"]:
                parrot = self.save_file["Servers"][serverid]["Parrot"]
                if parrot["LoopsAlive"] > 0 and (parrot["Fullness"] / parrot["Appetite"]) < 0.5:
                    if parrot["StarvedLoops"] == 0:
                        await self.bot.send_message(
                            self.bot.get_server(serverid),
                            "I'm quite hungry...")
                    elif parrot["StarvedLoops"] == 1:
                        await self.bot.send_message(
                            self.bot.get_server(serverid),
                            "I'm so hungry I feel weak...")
                    else:
                        await self.bot.send_message(
                            self.bot.get_server(serverid),
                            "I'm going to die of starvation very soon if I don't get fed...")

            await asyncio.sleep(self.starve_time * 0.2)
            await self.starve_check()

    async def parrot_perch(self):
        """Runs in a loop to periodically set someone (or nobody) as the person Parrot is with."""
        start_time = time.time()
        while True:
            for serverid in self.save_file["Servers"]:
                feeders = self.save_file["Servers"][serverid]["Feeders"]
                parrot = self.save_file["Servers"][serverid]["Parrot"]

                weights = [(feeders[feederid]["PelletsFed"] / parrot["Appetite"]) * 100 for feederid in feeders]
                population = list(feeders)
                weights.append(100 - sum(weights))
                population.append("")
                # Randomly choose who Parrot is with. This could be nobody, represented by ""
                try:
                    parrot["UserWith"] = random.choices(population, weights)[0] #random.choices returns a list
                except AttributeError:
                    # DIY random.choices alternative for scrubs who don't have Python 3.6
                    total = 0
                    cum_weights = []
                    for num in weights:
                        total += num
                        cum_weights.append(total)

                    rand = random.uniform(0, 100)
                    for index, weight in enumerate(cum_weights):
                        if weight >= rand:
                            parrot["UserWith"] = population[index]
                            break

                if parrot["UserWith"]:
                    userwith = parrot["UserWith"] # this is an ID number
                    if "HeistBoostAvailable" not in feeders[userwith]:
                        feeders[userwith]["HeistBoostAvailable"] = True
                    if "StealAvailable" not in feeders[userwith]: # maybe unnecessary
                        feeders[userwith]["StealAvailable"] = True
                    if "AirhornUses" not in feeders[userwith]: # maybe unnecessary
                        feeders[userwith]["AirhornUses"] = 0

            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            await asyncio.sleep(1200 - ((time.time() - start_time) % 1200)) # 20 minutes

    async def starve_check(self):
        """Check if Parrot has starved or not.
        If Parrot has starved, leave the server. If he has survived,
        move on to the next loop."""
        for serverid in list(self.save_file["Servers"]): # generate a list because servers might
                                                            # be removed from the dict while iterating
            parrot = self.save_file["Servers"][serverid]["Parrot"] # maybe unnecessary

            # don't check on the first loop to give new servers a chance
            # in case they got added at an unlucky time (right before the check happens)
            if parrot["LoopsAlive"] == 0:
                parrot["LoopsAlive"] += 1
            elif parrot["Fullness"] / parrot["Appetite"] < 0.5:
                if parrot["StarvedLoops"] == 2:
                    await self.bot.send_message(
                        self.bot.get_server(serverid),
                        "Oh no! I've starved to death!\n"
                        "Goodbye, cruel world!")
                    await self.bot.leave_server(self.bot.get_server(serverid))
                    del self.save_file["Servers"][serverid]

                else:
                    # advance to the next stage of starvation
                    parrot["StarvedLoops"] += 1
                    parrot["LoopsAlive"] += 1
                    parrot["Appetite"] = round(random.normalvariate(50*(1.75**parrot["StarvedLoops"]), 6))
                    parrot["Fullness"] = 0
                    parrot["UserWith"] = ""
                    self.save_file["Servers"][serverid]["Feeders"].clear()
                    # https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python
            else:
                # healthy; reset for the next loop
                parrot["StarvedLoops"] = 0
                parrot["LoopsAlive"] += 1
                parrot["Appetite"] = round(random.normalvariate(50*(1.75**parrot["StarvedLoops"]), 6))
                parrot["Fullness"] = 0
                parrot["UserWith"] = ""
                self.save_file["Servers"][serverid]["Feeders"].clear()
                # https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python

        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    def add_server(self, server):
        """Adds the server to the file if it isn't already in it."""
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = copy.deepcopy(SERVER_DEFAULT)
            self.save_file["Servers"][server.id]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            print("{} New server \"{}\" found and added to Parrot data file!"
                  .format(datetime.datetime.now(), server.name))

        return

    def parrot_perched_on(self, server):
        """Returns the user ID of whoever Parrot is perched on.

        This is for Heist.py to use for heist boost."""
        self.add_server(server) # make sure the server is in the data file
        return self.save_file["Servers"][server.id]["Parrot"]["UserWith"]

    def heist_boost_available(self, server, user, availability=True):
        """Returns whether the user has a Heist boost available.
        Optionally set availability to False to set the user's HeistBoostAvailable to False.

        This is for Heist.py to use for heist boost."""
        self.add_server(server) # make sure the server is in the data file
        if availability is False:
            self.save_file["Servers"][server.id]["Feeders"][user.id]["HeistBoostAvailable"] = False
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
        return self.save_file["Servers"][server.id]["Feeders"][user.id]["HeistBoostAvailable"]

    def __unload(self):
        self.loop_task.cancel()
        self.loop_task2.cancel()

        actual_start_time = Parrot.start_time + (self.starve_time * 0.2)
        time_since_started = time.time() - actual_start_time
        time_since_last_check = time_since_started % self.starve_time
        if time_since_last_check / self.starve_time >= 0.8:
            message = ("You have unloaded Parrot very near the next starve check. "
                       "This means that a starve check that was about to happen will "
                       "not happen. You should consider using `{}parrot checknow` "
                       "when Parrot is loaded again.".format(self.bot.settings.prefixes[0]))
            ownerid = self.bot.settings.owner
            owner = discord.utils.get(self.bot.get_all_members(), id=ownerid)
            self.bot.loop.create_task(self.bot.send_message(owner, message))

def dir_check():
    """Creates a folder and save file for the cog if they don't exist."""
    if not os.path.exists("data/KeaneCogs/parrot"):
        print("Creating data/KeaneCogs/parrot folder...")
        os.makedirs("data/KeaneCogs/parrot")

    if not dataIO.is_valid_json(SAVE_FILEPATH):
        print("Creating default parrot.json...")
        dataIO.save_json(SAVE_FILEPATH, {"Servers": {}, "Global": {"StarveTime": 86400}})

def setup(bot):
    """Creates a Parrot object."""
    dir_check()
    bot.add_cog(Parrot(bot))
