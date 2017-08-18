"""A cog that requires server users to feed the bot in return for benefits."""
import os
import random
import asyncio
import copy
import datetime

import discord
from discord.ext import commands
from __main__ import send_cmd_help
from .utils import checks
from .utils.dataIO import dataIO


SAVE_FILEPATH = "data/KeaneCogs/parrot/parrot.json"

SAVE_DEFAULT = {
    "Servers": {},
    "Global": {
        "StarveTime": [5, 0], # the hour and minute of the day that starve_check runs
        "PerchInterval": 20, # the number of minutes between perches
        "Version": "2.3"
    }
}

SERVER_DEFAULT = {
    "Parrot": {
        "Appetite": 0, # max number of pellets Parrot can be fed (reset by starve_check)

        "ChecksAlive": 0, # number of starve_checks survived

        "HoursAlive": 0, # number of hours Parrot has been alive in the server

        "UserWith": "", # ID of user Parrot is perched on (reset by starve_check)

        "Fullness": 0, # number of pellets Parrot has in his belly (reset by starve_check)

        "Cost": 5, # cost of feeding Parrot 1 pellet

        "StarvedLoops": 0, # phase of starvation Parrot is in

        "WarnedYet": False, # whether the server has been warned for the current self.checktime or not

        "StealAvailable": True # whether steal is available for the perched user (reset by perch_loop)
    },
    "Feeders": {} # contains user IDs as keys and dicts as values (reset by starve_check)
}

FEEDER_DEFAULT = {
    "PelletsFed": 0,
    "HeistBoostAvailable": True,
    "AirhornUses": 0,
    "StolenFrom": [],
    "CreditsCollected": 0.0
}

class Parrot:
    """Commands related to feeding the bot."""
    start_time = 0.0

    def __init__(self, bot):
        self.save_file = dataIO.load_json(SAVE_FILEPATH)
        self.bot = bot

        self.update_version()

        self.checktime = datetime.datetime.utcnow() # dummy value
        self.perchtime = datetime.datetime.utcnow() # dummy value
        self.update_looptimes(False) # change checktime to what it should be
                                     # without causing a new warning
        self.loop_task = bot.loop.create_task(self.loop()) # remember to change __unload()

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
            amount = parrot["Appetite"] - parrot["Fullness"]
            await self.bot.say("I don't want to be too full. I'll only eat {} pellets, "
                               "and you can keep the rest.".format(amount))

        usercost = amount * parrot["Cost"]

        # confirmation prompt
        await self.bot.say("You are about to spend {} credits to feed me {} pellets. "
                           "Reply \"yes\" to confirm.".format(usercost, amount))
        response = await self.bot.wait_for_message(timeout=15, author=ctx.message.author)
        if response is None or response.content.lower().strip() != "yes":
            return await self.bot.say("Okay then, but don't let me starve!")

        # deduct usercost from their credits account
        if bank.can_spend(ctx.message.author, usercost):
            bank.withdraw_credits(ctx.message.author, usercost)
        else:
            return await self.bot.say("You don't have enough credits to feed me that much.")

        # set up user's dict in the data file
        if ctx.message.author.id not in feeders:
            feeders[ctx.message.author.id] = copy.deepcopy(FEEDER_DEFAULT)

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

    @parrot.command(name="starvetime", pass_context=True) # no_pm=False
    @checks.is_owner()
    async def parrot_starve_time(self, ctx, hour: int = None, minute: int = 0):
        """View or change the time at which Parrot checks whether he has starved
        and resets his appetite. This command takes UTC time.
        (0 <= hour <= 23) (0 <= minute <= 59)"""

        if hour is None:
            cur_hour = self.save_file["Global"]["StarveTime"][0]
            cur_minute = self.save_file["Global"]["StarveTime"][1]
            cur_time = datetime.time(cur_hour, cur_minute)
            return await self.bot.say("Current setting: {} UTC".format(cur_time.strftime("%H:%M")))

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return await self.bot.say("Hour must be greater than -1 and less than 24. "
                                      "Minute must be greater than -1 and less than 60. "
                                      "Both numbers must be integers.")

        # confirmation prompt
        await self.bot.say("This is a global setting that affects all servers the bot is connected to. "
                           "Parrot checks whether he has starved or not every day at a certain time. "
                           "Parrot will check every day (including today if possible) at {} UTC. "
                           "Reply \"yes\" to confirm."
                           .format(datetime.time(hour, minute).strftime("%H:%M")))
        response = await self.bot.wait_for_message(timeout=15, author=ctx.message.author)
        if response is None or response.content.lower().strip() != "yes":
            return await self.bot.say("Setting change cancelled.")

        self.save_file["Global"]["StarveTime"] = [hour, minute]
        dataIO.save_json(SAVE_FILEPATH, self.save_file)
        self.update_looptimes()
        return await self.bot.say("Setting change successful.")

    @parrot.command(name="perchinterval", pass_context=True) # no_pm=False
    @checks.is_owner()
    async def parrot_perch_interval(self, ctx, minutes: int = None):
        """View or change how many minutes pass between perches."""
        if minutes is None:
            interval = self.save_file["Global"]["PerchInterval"]
            return await self.bot.say("Current setting: {} minutes".format(interval))
        if not 0 < minutes <= 1440:
            return await self.bot.say("The number of minutes must be greater than 0 "
                                      "and less than or equal to 1440.")
        if not (60 % minutes == 0 or minutes % 60 == 0):
            return await self.bot.say("The number of minutes must be a factor or "
                                      "multiple of 60.")

        # confirmation prompt
        await self.bot.say("This is a global setting that affects all servers the bot is connected to. "
                           "Every day, the first perch is at Parrot's starve time. For the rest of the day, "
                           "Parrot will wait {} minutes between perches. Reply \"yes\" "
                           "to confirm.".format(minutes))
        response = await self.bot.wait_for_message(timeout=15, author=ctx.message.author)
        if response is None or response.content.lower().strip() != "yes":
            return await self.bot.say("Setting change cancelled.")

        self.save_file["Global"]["PerchInterval"] = minutes
        dataIO.save_json(SAVE_FILEPATH, self.save_file)
        self.update_looptimes() # this updates self.perchtime with the new interval
        return await self.bot.say("Setting change successful.")

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
        One use per perch. Parrot will not steal from people who have
        fed him. Parrot will not steal from someone twice in a day."""
        self.add_server(ctx.message.server) # make sure the server is in the data file

        feeders = self.save_file["Servers"][ctx.message.server.id]["Feeders"]
        parrot = self.save_file["Servers"][ctx.message.server.id]["Parrot"]
        bank = self.bot.get_cog('Economy').bank

        # checks
        error_msg = ""
        if ctx.message.author.id != parrot["UserWith"]:
            error_msg = ("Parrot needs to be perched on you to use this command. "
                         "Use `{}help parrot` for more information.".format(ctx.prefix))
        elif not parrot["StealAvailable"]:
            error_msg = ("You have already used steal. You must wait until "
                         "the next time you are perched on.")

        elif not bank.account_exists(target):
            error_msg = "Your target doesn't have a bank account to steal credits from."

        elif target.id in feeders and feeders[target.id]["PelletsFed"] > 0:
            error_msg = ("Parrot refuses to steal from someone "
                         "who has fed him in the current fullness cycle.")
        elif target.id in feeders[ctx.message.author.id]["StolenFrom"]:
            error_msg = ("You have already stolen from this person today. "
                         "It is too risky to try a second time.")

        if error_msg:
            return await self.bot.say(error_msg)

        await self.bot.say("Parrot flies off...")
        await asyncio.sleep(3)

        stolen = round(random.uniform(1, random.uniform(1, 1000)))
        target_balance = bank.get_balance(target)

        if stolen >= target_balance:
            bank.transfer_credits(target, ctx.message.author, target_balance)
            msg = ("Parrot stole every last credit ({} credits) from "
                   "{}'s bank account and deposited it in your account!"
                   .format(target_balance, target.mention))
        else:
            bank.transfer_credits(target, ctx.message.author, stolen)
            msg = ("Parrot stole {} credits from {}'s bank account "
                   "and deposited it in your account!"
                   .format(stolen, target.mention))

        parrot["StealAvailable"] = False
        feeders[ctx.message.author.id]["StolenFrom"].append(target.id)
        dataIO.save_json(SAVE_FILEPATH, self.save_file)
        return await self.bot.say(msg)

    @parrot.command(name="airhorn", pass_context=True, no_pm=True)
    async def parrot_airhorn(self, ctx, channel: discord.Channel):
        """Play an airhorn sound to the target voice channel."""
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
            return await self.bot.say("You have already used airhorn 3 times. You must wait until "
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

    @parrot.command(name="info", pass_context=True, no_pm=True, aliases=["stats"])
    async def parrot_info(self, ctx):
        """Information about the parrot."""
        server = ctx.message.server
        self.add_server(server) # make sure the server is in the data file

        parrot = self.save_file["Servers"][server.id]["Parrot"]

        fullness_str = "{} out of {} pellets".format(parrot["Fullness"], parrot["Appetite"])
        feed_cost_str = "{} credits per pellet".format(parrot["Cost"])
        days_living_str = "{} days".format(round(parrot["HoursAlive"] / 24))

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

        if parrot["ChecksAlive"] == 0:
        # add an extra day because the first check won't starve or change Parrot's appetite
            until_starved = (self.checktime.replace(day=self.checktime.day + 1)
                             - datetime.datetime.utcnow())
        else:
            until_starved = self.checktime - datetime.datetime.utcnow()
        seconds = round(until_starved.total_seconds())
        time_until_starved_str += str(datetime.timedelta(seconds=seconds))

        if parrot["UserWith"]:
            userwith_str = server.get_member(parrot["UserWith"]).mention
        else:
            userwith_str = "nobody"

        embed = discord.Embed(color=discord.Color.teal(), description=description_str)
        embed.title = "Parrot Information"
        embed.timestamp = datetime.datetime.utcfromtimestamp(os.path.getmtime(os.path.abspath(__file__)))
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
        """Display a list of people who have fed Parrot in the current appetite
        loop, with the number of pellets they have fed and the percent chance
        they have of being perched on."""
        server = ctx.message.server

        self.add_server(server) # make sure the server is in the data file

        output = "```py\n"
        feeders = self.save_file["Servers"][server.id]["Feeders"]
        parrot = self.save_file["Servers"][server.id]["Parrot"]

        # The first perched user of the day is in feeders
        # but may not have fed any pellets. If so, ignore them.
        fedparrot = [feederid for feederid in feeders
                     if feeders[feederid]["PelletsFed"] > 0]

        if not fedparrot:
            return await self.bot.say("```Nobody has fed Parrot yet.```")

        idlist = sorted(fedparrot,
                        key=(lambda idnum: feeders[idnum]["PelletsFed"]),
                        reverse=True)

        max_chance = (feeders[idlist[0]]["PelletsFed"] / parrot["Appetite"]) * 100
        max_chance_len = len(str(round(max_chance)))

        max_pellets = feeders[idlist[0]]["PelletsFed"]
        max_pellets_len = len(str(max_pellets))

        # example: " 155/100%"
        max_end_len = 1 + max_pellets_len + 1 + max_chance_len + 1

        for feederid in idlist:
            feeder = server.get_member(feederid)

            chance = (feeders[feederid]["PelletsFed"] / parrot["Appetite"]) * 100
            chance_str = str(round(chance))

            if len(feeder.display_name) > 26 - max_end_len:
                # 26 - 3 to leave room for the ellipsis
                name = feeder.display_name[:23 - max_end_len] + "..."
            else:
                name = feeder.display_name

            output += name
            pellets_str = str(feeders[feederid]["PelletsFed"])

            # example: " 1/ 1%"
            end_len = 1 + len(pellets_str) + 1 + max_chance_len + 1

            output += " " * (26 - len(name) - end_len)
            # append the end
            output += " " + pellets_str + "|"
            output += " " * (max_chance_len - len(chance_str))
            output += chance_str + "%"
            output += "\n"

        output += "```"
        return await self.bot.say(output)

    async def loop(self):
        """Loop forever to do four tasks:

        Update HoursAlive, warn servers when Parrot is starving soon,
        perch on users at perchtime, and reset Parrot at checktime."""
        self.update_looptimes()
        current_hour = datetime.datetime.utcnow().hour
        while True:
            now = datetime.datetime.utcnow()

            # Update HoursAlive
            if current_hour != now.hour:
                current_hour = now.hour
                for serverid in self.save_file["Servers"]:
                    self.save_file["Servers"][serverid]["Parrot"]["HoursAlive"] += 1

                dataIO.save_json(SAVE_FILEPATH, self.save_file)

            # Send starvation warnings to each server (if they haven't been sent yet)
            stoptime = self.checktime + datetime.timedelta(hours=-4)
            if stoptime <= now:
                change = False
                for serverid in self.save_file["Servers"]:
                    parrot = self.save_file["Servers"][serverid]["Parrot"]
                    if (parrot["ChecksAlive"] > 0
                            and (parrot["Fullness"] / parrot["Appetite"]) < 0.5
                            and not parrot["WarnedYet"]):

                        if parrot["StarvedLoops"] == 0:
                            await self.bot.send_message(
                                self.bot.get_server(serverid),
                                "*I'm quite hungry...*")
                        elif parrot["StarvedLoops"] == 1:
                            await self.bot.send_message(
                                self.bot.get_server(serverid),
                                "*I'm so hungry I feel weak...*")
                        else:
                            await self.bot.send_message(
                                self.bot.get_server(serverid),
                                "*I'm going to* ***DIE*** *of starvation very "
                                "soon if I don't get fed!*")
                        parrot["WarnedYet"] = True
                        change = True
                if change:
                    dataIO.save_json(SAVE_FILEPATH, self.save_file)

            # Perch
            if self.perchtime <= now:
                # Choose perched user
                for serverid in self.save_file["Servers"]:
                    feeders = self.save_file["Servers"][serverid]["Feeders"]
                    parrot = self.save_file["Servers"][serverid]["Parrot"]

                    weights = [(feeders[feederid]["PelletsFed"] / parrot["Appetite"])
                               * 100 for feederid in feeders]
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

                # Reset at checktime (checktime is always on a perchtime)
                if self.checktime <= now:
                    await self.display_collected()
                    await self.starve_check()
                    self.update_looptimes() # checktime must be updated daily

                # Collect coins for perched user
                for serverid in self.save_file["Servers"]:
                    self.collect_credits(serverid)
                    self.save_file["Servers"][serverid]["Parrot"]["StealAvailable"] = True

                # Update perchtime
                interval = self.save_file["Global"]["PerchInterval"]
                self.perchtime = self.perchtime + datetime.timedelta(minutes=interval)

                dataIO.save_json(SAVE_FILEPATH, self.save_file)

            await asyncio.sleep(1)

    async def starve_check(self):
        """Check if Parrot has starved or not.
        If Parrot has starved, leave the server. If he has survived,
        reset for the next loop."""
        for serverid in list(self.save_file["Servers"]): # generate a list because servers might
                                                         # be removed from the dict while iterating
            parrot = self.save_file["Servers"][serverid]["Parrot"]
            feeders = self.save_file["Servers"][serverid]["Feeders"]

            # don't check on the first loop to give new servers a chance
            # in case they got added at an unlucky time (right before the check happens)
            reset = False
            if parrot["ChecksAlive"] == 0:
                parrot["ChecksAlive"] += 1
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
                    reset = True
            else:
                # healthy; reset for the next loop
                parrot["StarvedLoops"] = 0
                reset = True

            if reset:
                parrot["ChecksAlive"] += 1
                parrot["Appetite"] = round(random.normalvariate(50*(1.75**parrot["StarvedLoops"]), 6))
                parrot["Fullness"] = 0
                parrot["WarnedYet"] = False
                self.save_file["Servers"][serverid]["Feeders"].clear()
                # https://stackoverflow.com/questions/369898/difference-between-dict-clear-and-assigning-in-python
                if parrot["UserWith"]:
                    feeders[parrot["UserWith"]] = copy.deepcopy(FEEDER_DEFAULT)

        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    async def display_collected(self):
        """Display a leaderboard in each server with how many credits
        Parrot collected for users. Award CreditsCollected to each feeder."""
        bank = self.bot.get_cog('Economy').bank
        for serverid in self.save_file["Servers"]:
            server = self.bot.get_server(serverid)
            leaderboard = ("Here's how many credits I collected for "
                           "everyone I perched on today:\n\n")
            leaderboard += "```py\n"
            feeders = self.save_file["Servers"][serverid]["Feeders"]
            perched_users = [feederid for feederid in feeders
                             if round(feeders[feederid]["CreditsCollected"]) > 0]
            if not perched_users:
                continue # nobody gets credits, skip this server
            ranked = sorted(perched_users,
                            key=lambda idnum: feeders[idnum]["CreditsCollected"],
                            reverse=True)
            max_creds_len = len(str(round(feeders[ranked[0]]["CreditsCollected"])))
            for user_id in ranked:
                user = server.get_member(user_id)
                if len(user.display_name) > 26 - max_creds_len - 1:
                    name = user.display_name[22 - max_creds_len] + "..."
                else:
                    name = user.display_name
                leaderboard += name

                collected = round(feeders[user_id]["CreditsCollected"])
                bank.deposit_credits(user, collected)

                leaderboard += " " * (26 - len(name) - len(str(collected)))
                leaderboard += str(collected) + "\n"
            leaderboard += "```"
            await self.bot.send_message(server, leaderboard)

    def add_server(self, server):
        """Add the server to the file if it isn't already in it."""
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = copy.deepcopy(SERVER_DEFAULT)
            self.save_file["Servers"][server.id]["Parrot"]["Appetite"] = round(random.normalvariate(50, 6))
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
            print("{} New server \"{}\" found and added to Parrot data file!"
                  .format(datetime.datetime.now(), server.name))

    def update_looptimes(self, warn=True):
        """Update self.checktime for the latest StarveTime. If StarveTime
        has already passed today, self.checktime will be StarveTime tomorrow.
        Update self.perchtime for the latest StarveTime or PerchInterval."""
        # Update self.checktime
        starvetime = self.save_file["Global"]["StarveTime"]
        checktime = datetime.datetime.utcnow().replace(hour=starvetime[0],
                                                       minute=starvetime[1],
                                                       second=0,
                                                       microsecond=0)
        if datetime.datetime.utcnow().time() >= checktime.time():
            checktime = checktime.replace(day=datetime.datetime.utcnow().day + 1)

        if self.checktime != checktime: # if StarveTime changed (this will always be true
                                        # when Parrot is first loaded due to self.checktime's
                                        # initial value)
            self.checktime = checktime
            if warn:
                for serverid in self.save_file["Servers"]:
                    self.save_file["Servers"][serverid]["Parrot"]["WarnedYet"] = False
                dataIO.save_json(SAVE_FILEPATH, self.save_file)

        # Update self.perchtime
        interval = self.save_file["Global"]["PerchInterval"]
        self.perchtime = self.checktime + datetime.timedelta(days=-1)
        while self.perchtime < datetime.datetime.utcnow():
            self.perchtime = self.perchtime + datetime.timedelta(minutes=interval)

    def collect_credits(self, serverid):
        """Calculate how many credits Parrot will collect during the perch."""
        parrot = self.save_file["Servers"][serverid]["Parrot"]
        feeders = self.save_file["Servers"][serverid]["Feeders"]
        interval = self.save_file["Global"]["PerchInterval"]

        # Generate multiplier
        since_checktime = datetime.datetime.utcnow() - self.checktime
        current_minute = round(since_checktime.total_seconds() / 60)
        current_minute = current_minute % 1440
        multiplier = 0
        for i in range(current_minute, current_minute + interval):
            multiplier += 1.003**i
        multiplier = multiplier / 24568

        for feederid in feeders:
            pellets = feeders[feederid]["PelletsFed"]
            if pellets > 50: # Feeding more than 50 pellets (average healthy appetite) is ignored
                pellets = 50

            # 1.5 * parrot["Cost"] * pellets is exactly
            # how much the feeder would earn at the end of
            # the day if they fed right after checktime

            feeders[feederid]["CreditsCollected"] += 1.5 * parrot["Cost"] * pellets * multiplier

        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    def update_version(self):
        """Update the save file if necessary."""
        if "Version" not in self.save_file["Global"]: # if version == 1
            for serverid in self.save_file["Servers"]:
                parrot = self.save_file["Servers"][serverid]["Parrot"]
                starvetime = self.save_file["Global"]["StarveTime"]

                parrot["HoursAlive"] = round((starvetime * parrot["LoopsAlive"]) / 3600)
                parrot["ChecksAlive"] = parrot["LoopsAlive"]
                del parrot["LoopsAlive"]
                parrot["WarnedYet"] = False

            self.save_file["Global"]["StarveTime"] = [5, 0]
            self.save_file["Global"]["Version"] = "2"

        if self.save_file["Global"]["Version"] == "2":
            for serverid in self.save_file["Servers"]:
                parrot = self.save_file["Servers"][serverid]["Parrot"]
                feeders = self.save_file["Servers"][serverid]["Feeders"]

                for feederid in feeders:
                    if "StealAvailable" in feeders[feederid]:
                        feeders[feederid]["StolenFrom"] = []
                parrot["StealAvailable"] = True

            self.save_file["Global"]["Version"] = "2.1"

        if self.save_file["Global"]["Version"] == "2.1":
            for serverid in self.save_file["Servers"]:
                feeders = self.save_file["Servers"][serverid]["Feeders"]

                for feederid in feeders:
                    feeders[feederid]["CreditsCollected"] = 0
                    feeders[feederid]["StolenFrom"] = []
                    feeders[feederid]["AirhornUses"] = 0
                    feeders[feederid]["HeistBoostAvailable"] = True

            self.save_file["Global"]["Version"] = "2.2"

        if self.save_file["Global"]["Version"] == "2.2":
            self.save_file["Global"]["PerchInterval"] = 20
            self.save_file["Global"]["Version"] = "2.3"

        dataIO.save_json(SAVE_FILEPATH, self.save_file)

    def parrot_perched_on(self, server):
        """Return the user ID of whoever Parrot is perched on.

        This is for Heist.py to use for heist boost."""
        self.add_server(server) # make sure the server is in the data file
        return self.save_file["Servers"][server.id]["Parrot"]["UserWith"]

    def heist_boost_available(self, server, user, availability=True):
        """Return whether the user has a Heist boost available.
        Optionally set availability to False to set the user's HeistBoostAvailable to False.

        This is for Heist.py to use for heist boost."""
        self.add_server(server) # make sure the server is in the data file
        if availability is False:
            self.save_file["Servers"][server.id]["Feeders"][user.id]["HeistBoostAvailable"] = False
            dataIO.save_json(SAVE_FILEPATH, self.save_file)
        return self.save_file["Servers"][server.id]["Feeders"][user.id]["HeistBoostAvailable"]

    def __unload(self):
        self.loop_task.cancel()

def dir_check():
    """Create a folder and save file for the cog if they don't exist."""
    if not os.path.exists("data/KeaneCogs/parrot"):
        print("Creating data/KeaneCogs/parrot folder...")
        os.makedirs("data/KeaneCogs/parrot")

    if not dataIO.is_valid_json(SAVE_FILEPATH):
        print("Creating default parrot.json...")
        dataIO.save_json(SAVE_FILEPATH, SAVE_DEFAULT)

def setup(bot):
    """Create a Parrot object."""
    dir_check()
    bot.add_cog(Parrot(bot))
