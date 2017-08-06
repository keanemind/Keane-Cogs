"""A trivia cog that uses Open Trivia Database."""
import os
import html
import asyncio
import time
import datetime
import random

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

        self.playing_servers = {}
        self.timeout = 20
        self.game_tasks = []

        self.starter_task = bot.loop.create_task(self.start_loop())

    @commands.group(pass_context=True, no_pm=True)
    async def quiz(self, ctx):
        """Play a kahoot-like trivia game with questions from Open Trivia Database.

        In this game, you will compete with other players to correctly answer each
        question as quickly as you can. You have 10 seconds to type the answer
        choice before time runs out. The longer you take to say the right answer,
        the fewer points you get. If you get it wrong, you get no points.
        """
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @quiz.command(name="play", pass_context=True)
    async def quiz_play(self, ctx):
        """Create or join a quiz game."""
        server = ctx.message.server
        player = ctx.message.author
        if server.id not in self.playing_servers:
            self.playing_servers[server.id] = {"Start":datetime.datetime.utcnow(),
                                               "Started":False,
                                               "Players":{player.id:0},
                                               "Answers":{}
                                              }
            return await self.bot.say(player.display_name + " is starting a quiz game! "
                                      "It will start in 20 seconds. Use `{}quiz play` "
                                      "to join.".format(ctx.prefix))

        serverinfo = self.playing_servers[server.id]
        since_start = (datetime.datetime.utcnow() - serverinfo["Start"]).total_seconds()
        if player.id in serverinfo["Players"]:
            await self.bot.say("You are already in the game.")
        elif since_start > self.timeout:
            await self.bot.say("A quiz game is already underway.")
        else:
            serverinfo["Players"][player.id] = 0
            await self.bot.say(player.display_name + " joined the game.")

    async def start_loop(self):
        """Starts quiz games when the timeout period ends."""
        while True:
            await asyncio.sleep(1)
            for serverid in list(self.playing_servers):
                serverinfo = self.playing_servers[serverid]
                since_start = (datetime.datetime.utcnow() - serverinfo["Start"]).total_seconds()
                if since_start > self.timeout and not serverinfo["Started"]:
                    if len(serverinfo["Players"]) > 1:
                        server = self.bot.get_server(serverid)
                        self.game_tasks.append(self.bot.loop.create_task(self.game(server)))
                        serverinfo["Started"] = True
                    else:
                        await self.bot.send_message(self.bot.get_server(serverid),
                                                    "Nobody else joined the quiz game.")
                        self.playing_servers.pop(serverid)

                print("Started", serverinfo["Started"])
                for playerid in serverinfo["Players"]:
                    print(playerid, ":", serverinfo["Players"][playerid])
                print("\n")

    async def on_message(self, message):
        authorid = message.author.id
        serverid = message.server.id
        choice = message.content.lower()
        if serverid in self.playing_servers:
            serverinfo = self.playing_servers[serverid]
            if (authorid in serverinfo["Players"]
                    and authorid not in serverinfo["Answers"]
                    and choice in {"a", "b", "c", "d"}):
                serverinfo["Answers"][authorid] = {"Choice":choice,
                                                   "Time":time.perf_counter()}

    async def game(self, server):
        """Runs a quiz game on a server."""
        self.add_server(server)
        response = await self.get_questions(server, category=random.randint(9, 32))
        serverinfo = self.playing_servers[server.id]

        # Introduction
        intro = ("Welcome to the quiz game!\n"
                 "Remember to answer correctly as quickly as you can. "
                 "You have 10s per question.\n"
                 "The game will begin shortly.")
        await self.bot.send_message(server, intro)
        await asyncio.sleep(4)

        # Question and Answer
        for index, dictionary in enumerate(response["results"]):
            question = "**" + html.unescape(dictionary["question"]) + "**\n"
            answers = [dictionary["correct_answer"]] + dictionary["incorrect_answers"]

            # Display question and countdown
            if len(answers) == 2: # true/false question
                answers = ["True", "False", "", ""]
            else:
                answers = [html.unescape(answer) for answer in answers]
                random.shuffle(answers)

            question += "**A.** {}\n".format(answers[0])
            question += "**B.** {}\n".format(answers[1])
            question += "**C.** {}\n".format(answers[2])
            question += "**D.** {}\n".format(answers[3])

            serverinfo["Answers"].clear() # clear the previous question's answers
            message = await self.bot.send_message(server, question)
            await self.bot.add_reaction(message, "0⃣")
            start_time = time.perf_counter()
            numbers = ["1⃣", "2⃣", "3⃣", "4⃣", "5⃣", "6⃣", "7⃣", "8⃣", "9⃣", "🔟"]

            for i in range(10):
                if len(serverinfo["Answers"]) == len(serverinfo["Players"]):
                    break
                await asyncio.sleep(1)
                await self.bot.add_reaction(message, numbers[i])

            # Organize answers
            answerdict = {["a", "b", "c", "d"][num]: answers[num] for num in range(4)}
            print(answerdict)
            print(serverinfo["Answers"])

            # Assign scores
            for playerid in serverinfo["Answers"]:
                choice = serverinfo["Answers"][playerid]["Choice"]
                response_time = serverinfo["Answers"][playerid]["Time"]
                if answerdict[choice] == dictionary["correct_answer"]:
                    time_taken = response_time - start_time
                    if time_taken < 1:
                        serverinfo["Players"][playerid] += 1000 # need a time multiplier
                    else:
                        points = round(1000 * (1 - (time_taken / 20))) # the 20 is 2 * 10s (max answer time)
                        serverinfo["Players"][playerid] += points
            # answers said after this time are still added to the Answers dictionary,
            # but have no affect on scores or ranking and are effectively ignored

            # Find and display correct answer
            correct = ""
            for letter, answer in answerdict.items():
                if answer == html.unescape(dictionary["correct_answer"]):
                    correct = letter
                    break
            assert answerdict[correct] == html.unescape(dictionary["correct_answer"])
            await self.bot.send_message(server, "Correct answer: " +
                                        correct.upper() + ". " + answerdict[correct])

            # Display top 5 players and their points
            scoreboard = "```py\n"
            idlist = sorted(list(serverinfo["Players"]),
                            key=(lambda idnum: serverinfo["Players"][idnum]),
                            reverse=True)
            max_score = serverinfo["Players"][idlist[0]]
            end_len = len(str(max_score)) + 1
            rank = 1
            for playerid in idlist[:5]:
                player = server.get_member(playerid)
                if len(player.display_name) > 26 - end_len:
                    name = player.display_name[:23 - end_len] + "..."
                else:
                    name = player.display_name
                scoreboard += str(rank) + " " + name
                score_str = str(serverinfo["Players"][playerid])
                scoreboard += " " * (25 - len(str(rank)) - len(name) - len(score_str))
                scoreboard += score_str + "\n"
                rank += 1
            scoreboard += "```"
            await self.bot.send_message(server, "Scoreboard:\n" + scoreboard)

            await asyncio.sleep(4)
            if index < 19:
                await self.bot.send_message(server, "Next question...")
                await asyncio.sleep(1)

        # Ending and Results
        # non-linear credit earning .0002x^{2.9} where x is score/100
        # leaderboard with credits earned
        bank = self.bot.get_cog("Economy").bank
        leaderboard = "```py\n"
        idlist = sorted(list(serverinfo["Players"]),
                        key=(lambda idnum: serverinfo["Players"][idnum]),
                        reverse=True)
        max_credits = round(serverinfo["Players"][idlist[0]] / 100)
        end_len = len(str(max_credits)) + 1
        rank = 1
        for playerid in idlist:
            player = server.get_member(playerid)
            if len(player.display_name) > 26 - end_len:
                name = player.display_name[:23 - end_len] + "..."
            else:
                name = player.display_name
            leaderboard += str(rank) + " " + name
            creds = round(.0002 * (serverinfo["Players"][playerid] / 100)**2.9)
            bank.deposit_credits(player, creds)
            creds_str = str(creds)
            leaderboard += " " * (25 - len(str(rank)) - len(name) - len(creds_str))
            leaderboard += creds_str + "\n"
            rank += 1
        leaderboard += "```"
        await self.bot.send_message(server, "Credits earned:\n" + leaderboard)
        self.playing_servers.pop(server.id)

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
                elif (response_code == 1
                      or response_code == 2):
                    raise RuntimeError("Question retrieval unsuccessful. Response "
                                       "code from OTDB: {}".format(response_code))
                elif response_code == 3:
                    self.save_file["Servers"][server.id]["Token"] = ""
                    dataIO.save_json(SAVE_FILEPATH, self.save_file)
                elif response_code == 4:
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

        return

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
