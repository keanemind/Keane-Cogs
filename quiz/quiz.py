"""A trivia cog that uses Open Trivia Database."""
import os
import html
import asyncio
import time
import datetime
import random
import math

import aiohttp
import discord
from discord.ext import commands
from __main__ import send_cmd_help
from .utils import checks
from .utils.dataIO import dataIO

SAVE_FILEPATH = "data/KeaneCogs/quiz/quiz.json"

class Quiz:
    """Play a kahoot-like trivia game with questions from Open Trivia Database."""

    def __init__(self, bot):
        self.bot = bot
        self.save_file = dataIO.load_json(SAVE_FILEPATH)

        self.playing_channels = {}
        self.timeout = 20
        self.game_tasks = []

        self.starter_task = bot.loop.create_task(self.start_loop())

    @commands.group(pass_context=True, no_pm=True)
    async def quiz(self, ctx):
        """Play a kahoot-like trivia game with questions from Open Trivia Database.

        In this game, you will compete with other players to correctly answer each
        question as quickly as you can. You have 10 seconds to type the answer
        choice before time runs out. Only your first answer will be registered.
        The longer you take to say the right answer, the fewer points you get.
        If you get it wrong, you get no points.
        """
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @quiz.command(name="play", pass_context=True)
    async def quiz_play(self, ctx):
        """Create or join a quiz game."""
        channel = ctx.message.channel
        player = ctx.message.author
        if channel.id not in self.playing_channels:
            self.playing_channels[channel.id] = {"Start":datetime.datetime.utcnow(),
                                                 "Started":False,
                                                 "Players":{player.id:0},
                                                 "Answers":{}
                                                }
            return await self.bot.say("{} is starting a quiz game! It will start "
                                      "in 20 seconds. Use `{}quiz play` to join."
                                      .format(player.display_name, ctx.prefix))

        channelinfo = self.playing_channels[channel.id]
        if player.id in channelinfo["Players"]:
            await self.bot.say("You are already in the game.")
        elif channelinfo["Started"]:
            await self.bot.say("A quiz game is already underway.")
        else:
            channelinfo["Players"][player.id] = 0
            await self.bot.say("{} joined the game.".format(player.display_name))

    async def start_loop(self):
        """Starts quiz games when the timeout period ends."""
        while True:
            await asyncio.sleep(1)
            for channelid in list(self.playing_channels):
                channelinfo = self.playing_channels[channelid]
                since_start = (datetime.datetime.utcnow() - channelinfo["Start"]).total_seconds()
                if since_start > self.timeout and not channelinfo["Started"]:
                    if len(channelinfo["Players"]) > 1:
                        channel = self.bot.get_channel(channelid)
                        self.game_tasks.append(self.bot.loop.create_task(self.game(channel)))
                        channelinfo["Started"] = True
                    else:
                        await self.bot.send_message(self.bot.get_channel(channelid),
                                                    "Nobody else joined the quiz game.")
                        self.playing_channels.pop(channelid)

    async def on_message(self, message):
        authorid = message.author.id
        channelid = message.channel.id
        choice = message.content.lower()
        if channelid in self.playing_channels:
            channelinfo = self.playing_channels[channelid]
            if (authorid in channelinfo["Players"]
                    and authorid not in channelinfo["Answers"]
                    and choice in {"a", "b", "c", "d"}):
                channelinfo["Answers"][authorid] = {"Choice":choice,
                                                    "Time":time.perf_counter()}

    async def game(self, channel):
        """Runs a quiz game on a channel."""
        self.add_server(channel.server)

        try:
            category = await self.category_selector()
            category_name = await self.category_name(category)
            response = await self.get_questions(channel.server, category=category)
        except RuntimeError:
            await self.bot.send_message(channel, "An error occurred in retrieving questions. "
                                        "Please try again.")
            self.playing_channels.pop(channel.id)
            raise

        channelinfo = self.playing_channels[channel.id]

        # Introduction
        intro = ("Welcome to the quiz game! Your category is {}.\n"
                 "Remember to answer correctly as quickly as you can. "
                 "Only your first answer will be registered by the game. "
                 "You have 10 seconds per question.\n"
                 "The game will begin shortly.".format(category_name))
        await self.bot.send_message(channel, intro)
        await asyncio.sleep(4)

        # Question and Answer
        afk_questions = 0
        for index, dictionary in enumerate(response["results"]):
            answers = [dictionary["correct_answer"]] + dictionary["incorrect_answers"]

            # Display question and countdown
            if len(answers) == 2: # true/false question
                answers = ["True", "False", "", ""]
            else:
                answers = [html.unescape(answer) for answer in answers]
                random.shuffle(answers)

            message = "```\n"
            message += html.unescape(dictionary["question"]) + "\n"
            message += "A. {}\n".format(answers[0])
            message += "B. {}\n".format(answers[1])
            message += "C. {}\n".format(answers[2])
            message += "D. {}\n".format(answers[3])
            message += "```"

            message_obj = await self.bot.send_message(channel, message)
            await self.bot.add_reaction(message_obj, "0⃣")
            channelinfo["Answers"].clear() # clear the previous question's answers
            start_time = time.perf_counter()

            numbers = ["1⃣", "2⃣", "3⃣", "4⃣", "5⃣", "6⃣", "7⃣", "8⃣", "9⃣", "🔟"]
            for i in range(10):
                if len(channelinfo["Answers"]) == len(channelinfo["Players"]):
                    break
                await asyncio.sleep(1)
                await self.bot.add_reaction(message_obj, numbers[i])

            # Organize answers
            user_answers = channelinfo["Answers"] # snapshot channelinfo["Answers"] at this point in time
                                                  # to ignore new answers that are added to it
            answerdict = {["a", "b", "c", "d"][num]: answers[num] for num in range(4)}

            # Check for AFK
            if len(user_answers) < 2:
                afk_questions += 1
                if afk_questions == 3:
                    await self.bot.send_message(channel, "The game has been cancelled due "
                                                "to lack of participation.")
                    self.playing_channels.pop(channel.id)
                    return
            else:
                afk_questions = 0

            # Find and display correct answer
            correct_letter = ""
            for letter, answer in answerdict.items():
                if answer == html.unescape(dictionary["correct_answer"]):
                    correct_letter = letter
                    break
            assert answerdict[correct_letter] == html.unescape(dictionary["correct_answer"])
            message = "Correct answer:```{}. {}```".format(correct_letter.upper(),
                                                           answerdict[correct_letter])
            await self.bot.send_message(channel, message)

            # Assign scores
            for playerid in user_answers:
                if user_answers[playerid]["Choice"] == correct_letter:
                    time_taken = user_answers[playerid]["Time"] - start_time
                    assert time_taken > 0
                    if time_taken < 1:
                        channelinfo["Players"][playerid] += 1000
                    else:
                        # the 20 in the formula below is 2 * 10s (max answer time)
                        channelinfo["Players"][playerid] += round(1000 * (1 - (time_taken / 20)))

            # Display top 5 players and their points
            message = self.scoreboard(channel)
            await self.bot.send_message(channel, "Scoreboard:\n" + message)
            await asyncio.sleep(4)

            if index < 19:
                await self.bot.send_message(channel, "Next question...")
                await asyncio.sleep(1)

        # Ending and Results
        await self.end_game(channel)

    async def end_game(self, channel):
        """Ends a quiz game."""
        # non-linear credit earning .0002x^{2.9} where x is score/100
        # leaderboard with credits earned
        channelinfo = self.playing_channels[channel.id]
        idlist = sorted(list(channelinfo["Players"]),
                        key=(lambda idnum: channelinfo["Players"][idnum]),
                        reverse=True)

        winner = channel.server.get_member(idlist[0])
        await self.bot.send_message(channel, "Game over! {} won!".format(winner.mention))

        bank = self.bot.get_cog("Economy").bank
        leaderboard = "```py\n"
        max_credits = self.calculate_credits(channelinfo["Players"][idlist[0]])
        end_len = len(str(max_credits)) + 1 # the 1 is for a space between a max length name and the score
        rank_len = len(str(len(channelinfo["Players"])))
        rank = 1
        no_account = False
        for playerid in idlist:
            player = channel.server.get_member(playerid)
            account_exists = bank.account_exists(player) # how does this know what server it's called in???

            if account_exists:
                if len(player.display_name) > 25 - rank_len - end_len:
                    name = player.display_name[:22 - rank_len - end_len] + "..."
                else:
                    name = player.display_name
            else:
                if len(player.display_name) > 24 - rank_len - end_len:
                    name = player.display_name[:21 - rank_len - end_len] + "...*"
                else:
                    name = player.display_name + "*"

            leaderboard += str(rank)
            leaderboard += " " * (1 + rank_len - len(str(rank)))
            leaderboard += name
            creds = self.calculate_credits(channelinfo["Players"][playerid])
            creds_str = str(creds)
            leaderboard += " " * (26 - rank_len - 1 - len(name) - len(creds_str))
            leaderboard += creds_str + "\n"

            if account_exists:
                bank.deposit_credits(player, creds)
            else:
                no_account = True

            rank += 1

        if not no_account:
            leaderboard += "```"
        else:
            leaderboard += ("* because you do not have a bank account, "
                            "you did not get to keep the credits you won.```\n")

        await self.bot.send_message(channel, "Credits earned:\n" + leaderboard)
        self.playing_channels.pop(channel.id)

    def scoreboard(self, channel):
        """Returns a scoreboard string to be sent to the text channel."""
        channelinfo = self.playing_channels[channel.id]
        scoreboard = "```py\n"
        idlist = sorted(list(channelinfo["Players"]),
                        key=(lambda idnum: channelinfo["Players"][idnum]),
                        reverse=True)
        max_score = channelinfo["Players"][idlist[0]]
        end_len = len(str(max_score)) + 1
        rank = 1
        for playerid in idlist[:5]:
            player = channel.server.get_member(playerid)
            if len(player.display_name) > 24 - end_len:
                name = player.display_name[:21 - end_len] + "..."
            else:
                name = player.display_name
            scoreboard += str(rank) + " " + name
            score_str = str(channelinfo["Players"][playerid])
            scoreboard += " " * (24 - len(name) - len(score_str))
            scoreboard += score_str + "\n"
            rank += 1
        scoreboard += "```"
        return scoreboard

    def calculate_credits(self, score):
        """Calculates credits earned from a score."""
        adjusted = score / 100
        if adjusted < 156.591:
            result = .0002 * (adjusted**2.9)
        else:
            result = (.6625 * math.exp(.0411 * adjusted)) + 50

        return round(result)

# OpenTriviaDB API functions
    async def get_questions(self, server, category=None, difficulty=None):
        """Gets questions, resetting a token or getting a new one if necessary."""
        parameters = {"amount": 20}
        if category:
            parameters["category"] = category
        if difficulty:
            parameters["difficulty"] = difficulty
        for _ in range(3):
            parameters["token"] = await self.get_token(server)
            async with aiohttp.get("https://opentdb.com/api.php",
                                   params=parameters) as response:

                response_json = await response.json()
                response_code = response_json["response_code"]
                if response_code == 0:
                    return response_json
                elif response_code == 1:
                    raise RuntimeError("Question retrieval unsuccessful. Response "
                                       "code from OTDB: 1")
                elif response_code == 2:
                    raise RuntimeError("Question retrieval unsuccessful. Response "
                                       "code from OTDB: 2")
                elif response_code == 3:
                    # Token expired. Obtain new one.
                    print("Response code from OTDB: 3")
                    self.save_file["Servers"][server.id]["Token"] = ""
                    dataIO.save_json(SAVE_FILEPATH, self.save_file)
                elif response_code == 4:
                    # Token empty. Reset it.
                    print("Response code from OTDB: 4")
                    await self.reset_token(server)
        raise RuntimeError("Failed to retrieve questions.")

    async def get_token(self, server):
        """Gets the provided server's token, or generates
        and saves one if one doesn't exist."""
        if self.save_file["Servers"][server.id]["Token"]:
            token = self.save_file["Servers"][server.id]["Token"]
        else:
            async with aiohttp.get("https://opentdb.com/api_token.php",
                                   params={"command": "request"}) as response:
                response_json = await response.json()
                token = response_json["token"]
                self.save_file["Servers"][server.id]["Token"] = token
                dataIO.save_json(SAVE_FILEPATH, self.save_file)

        return token

    async def reset_token(self, server):
        """Resets the provided server's token."""
        token = self.save_file["Servers"][server.id]["Token"]
        async with aiohttp.get("https://opentdb.com/api_token.php",
                               params={"command": "reset", "token": token}) as response:
            response_code = (await response.json())["response_code"]
            if response_code != 0:
                raise RuntimeError("Token reset was unsuccessful. Response code from "
                                   "OTDB: {}".format(response_code))

    async def category_selector(self):
        """Chooses a random category that has enough questions."""
        for _ in range(10):
            category = random.randint(9, 32)
            async with aiohttp.get("https://opentdb.com/api_count.php",
                                   params={"category": category}) as response:
                response_json = await response.json()
                assert response_json["category_id"] == category
                if response_json["category_question_count"]["total_question_count"] > 39:
                    return category

        raise RuntimeError("Failed to select a category.")

    async def category_name(self, idnum):
        """Finds a category's name from its number."""
        async with aiohttp.get("https://opentdb.com/api_category.php") as response:
            response_json = await response.json()
            for cat_dict in response_json["trivia_categories"]:
                if cat_dict["id"] == idnum:
                    return cat_dict["name"]
        raise RuntimeError("Failed to find category's name.")

# Other functions
    def add_server(self, server):
        """Adds the server to the file if it isn't already in it."""
        if server.id not in self.save_file["Servers"]:
            self.save_file["Servers"][server.id] = {"Token": ""}
            dataIO.save_json(SAVE_FILEPATH, self.save_file)

        return

    def __unload(self):
        self.starter_task.cancel()
        for task in self.game_tasks:
            task.cancel()

def dir_check():
    """Creates a folder and save file for the cog if they don't exist."""
    if not os.path.exists("data/KeaneCogs/quiz"):
        print("Creating data/KeaneCogs/quiz folder...")
        os.makedirs("data/KeaneCogs/quiz")

    if not dataIO.is_valid_json(SAVE_FILEPATH):
        print("Creating default quiz.json...")
        dataIO.save_json(SAVE_FILEPATH, {"Servers": {}})

def setup(bot):
    """Creates a Quiz object."""
    dir_check()
    bot.add_cog(Quiz(bot))
