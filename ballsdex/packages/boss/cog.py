import discord
import time
import random
import string
import logging
import re

from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING, Optional, cast
from discord.ui import Button, View

from ballsdex.settings import settings
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.core.utils.transformers import BallEnabledTransform
from ballsdex.core.utils.transformers import SpecialTransform, BallTransform
from ballsdex.core.utils.transformers import SpecialEnabledTransform
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.logging import log_action
from ballsdex.settings import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.boss.cog")
FILENAME_RE = re.compile(r"^(.+)(\.\S+)$")

from ballsdex.core.models import (
    Ball,
    BallInstance,
    BlacklistedGuild,
    BlacklistedID,
    GuildConfig,
    Player,
    Trade,
    TradeObject,
    balls,
    specials,
)

# IMPORTANT NOTES, READ BEFORE USING
# 1. YOU MUST HAVE A SPECIAL CALLED "Boss" IN YOUR DEX, THIS IS FOR REWARDING THE WINNER.
#    MAKE IT SO THE SPECIAL'S END DATE IS 2124 OR SOMETHING. RARITY MUST BE 0
# 2. ONLY USE A COUNTRYBALL AS A BOSS in /boss start IF IT HAS BOTH THE COLLECTIBLE AND WILD CARDS STORED,
#    OTHERWISE THIS WILL RESULT TO AN ERROR.
#    Sometimes, you might create a non-spawnable ball using /admin balls create command, if that's the case
#    there's a chance you may have not selected a wild card as it isn't required.
#    Cards without wild cards do not work as a boss, as again, this will result in an error.
#    If you are using a ball made from the admin panel for the boss, then it's fine, since admin panel requires wild card.
# 3. You may change the shiny buffs below to suit your dex better it's defaulted at 1000 HP & ATK Bonus
# 4. Please report all bugs to user @moofficial on discord
# 5. Make sure to add "boss" to PACKAGES at ballsdex/core/bot.py (Usually around line 48)
# 6. Finally, add the boss to packages at config.yml file

# HOW TO PLAY
# Some commands can only be used by admins, these control the boss actions.
# 1. Start the boss using /boss admin start command. (ADMINS ONLY)
#    Choose a countryball to be the boss (required). Choose HP (Required)
# 2. Players can join using /boss join command.
# 3. Start a round using /boss admin defend or /boss admin attack.(ADMINS ONLY)
#    With /boss admin attack you can choose how much attack the boss deals (Optional, Defaulted to RNG from default 0 to 2000, can be changed below)
# 4. Players now choose an item to use against the boss using /boss select
# 5. /boss admin end_round ends the current round and displays user permformance about the round (ADMIN ONLY)
# 6. Step 3-5 is repeated until the boss' HP runs out, but you can end early with Step 7.
# 7. /boss admin conclude ends the boss battle and rewards the winner, but you can choose to have *no* winner (ADMIN ONLY)

SHINYBUFFS = [20000,20000] # Shiny Buffs
# ATK, HP
MAXSTATS = [154000,96701] # Max stats a card is limited to (before buffs)
# ATK, HP
DAMAGERNG = [10000,154000] # Damage a boss can deal IF attack_amount has NOT been inputted in /boss admin attack.
# Min Damage, Max Damage


@app_commands.guilds(*settings.admin_guild_ids)
class Boss(commands.GroupCog):
    """
    Boss commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.boss_enabled = False
        self.balls = []
        self.users = []
        self.usersdamage = []
        self.usersinround = []
        self.currentvalue = ("")
        self.bossHP = 0
        self.picking = False
        self.round = 0
        self.attack = False
        self.bossattack = 0
        self.bossball = None
        self.bosswild = None
        self.disqualified = []

    bossadmin = app_commands.Group(name="admin", description="admin commands for boss")

    @bossadmin.command(name="start")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def start(self, interaction: discord.Interaction, ball: BallTransform, hp_amount: int):
        """
        Start the boss
        """
        if self.boss_enabled == True:
            return await interaction.response.send_message(f"There is already an ongoing boss battle", ephemeral=True)
        self.bossHP = hp_amount
        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = ball.collection_card.split(".")[-1]
        file_location = "." + ball.collection_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.response.send_message(
            f"Boss successfully started", ephemeral=True
        )
        await interaction.channel.send((f"# The boss battle has begun! {self.bot.get_emoji(ball.emoji_id)}\n-# HP: {self.bossHP}"),file=discord.File(file_location, filename=file_name),)
        await interaction.channel.send("> Use `/boss join` to join the battle!")
        if ball != None:
            self.boss_enabled = True
            self.bossball = ball

            extension = ball.wild_card.split(".")[-1]
            file_location = "." + ball.wild_card
            file_name = f"nt_{generate_random_name()}.{extension}"
            self.bosswild = file=discord.File(file_location, filename=file_name)

    @bossadmin.command(name="attack")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def attack(self, interaction: discord.Interaction, attack_amount: int | None = None):
        """
        Start a round where the Boss Attacks
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if self.picking:
            return await interaction.response.send_message("There is already an ongoing round", ephemeral=True)
        if len(self.users) == 0:
            return await interaction.response.send_message("There are not enough users to start the round", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.response.send_message("The Boss is dead", ephemeral=True)
        self.round += 1

        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = self.bossball.wild_card.split(".")[-1]
        file_location = "." + self.bossball.wild_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.response.send_message(
            f"Round successfully started", ephemeral = True
        )
        await interaction.channel.send(
            (f"Round {self.round}\n# {self.bossball.country} is preparing to attack! {self.bot.get_emoji(self.bossball.emoji_id)}"),file=discord.File(file_location, filename=file_name)
        )
        await interaction.channel.send(f"> Use `/boss select` to select your defending {settings.collectible_name}.\n> Your selected {settings.collectible_name}'s HP will be used to defend.")
        self.picking = True
        self.attack = True
        self.bossattack = (attack_amount if attack_amount is not None else random.randrange(DAMAGERNG[0], DAMAGERNG[1], 100))

    @bossadmin.command(name="defend")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def defend(self, interaction: discord.Interaction):
        """
        Start a round where the Boss Defends
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if self.picking:
            return await interaction.response.send_message("There is already an ongoing round", ephemeral=True)
        if len(self.users) == 0:
            return await interaction.response.send_message("There are not enough users to start the round", ephemeral=True)
        if self.bossHP <= 0:
            return await interaction.response.send_message("The Boss is dead", ephemeral=True)
        self.round += 1

        def generate_random_name():
            source = string.ascii_uppercase + string.ascii_lowercase + string.ascii_letters
            return "".join(random.choices(source, k=15))
        extension = self.bossball.wild_card.split(".")[-1]
        file_location = "." + self.bossball.wild_card
        file_name = f"nt_{generate_random_name()}.{extension}"
        await interaction.response.send_message(
            f"Round successfully started", ephemeral=True
        )
        await interaction.channel.send(
            (f"Round {self.round}\n# {self.bossball.country} is preparing to defend! {self.bot.get_emoji(self.bossball.emoji_id)}"),file=discord.File(file_location, filename=file_name)
        )
        await interaction.channel.send(f"> Use `/boss select` to select your attacking {settings.collectible_name}.\n> Your selected {settings.collectible_name}'s ATK will be used to attack.")
        self.picking = True
        self.attack = False


    @bossadmin.command(name="end_round")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def end_round(self, interaction: discord.Interaction):
        """
        End the current round
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if not self.picking:
            return await interaction.response.send_message(
                f"There are no ongoing rounds, use `/boss attack` or `/boss defend` to start one", ephemeral=True
            )
        self.picking = False
        with open("roundstats.txt", "w") as file:
            file.write(f"{self.currentvalue}")
        await interaction.response.send_message(
            f"Round successfully ended", ephemeral=True
        )
        if not self.attack:
            if int(self.bossHP) <= 0:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThere is 0 HP remaining on the boss, the boss has been defeated!",
                )
            else:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThere is {self.bossHP} HP remaining on the boss",
                )
        else:
            snapshotusers = self.users.copy()
            for user in snapshotusers:
                user_id = user
                user = await self.bot.fetch_user(int(user))
                if str(user) not in self.currentvalue:
                    self.currentvalue += (str(user) + " has not selected on time and died!\n")
                    self.users.remove(user_id)
            with open("roundstats.txt","w") as file:
                file.write(f"{self.currentvalue}")
            if len(self.users) == 0:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has dealt {self.bossattack} damage!\nThe boss has won!",
                )
            else:
                await interaction.channel.send(
                    f"# Round {self.round} has ended {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has dealt {self.bossattack} damage!\n",
                )
        with open("roundstats.txt", "rb") as file:
            await interaction.channel.send(file=discord.File(file,"roundstats.txt"))
        self.currentvalue = ("")

    @bossadmin.command(name="stats")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def stats(self, interaction: discord.Interaction):
        """
        See current stats of the boss
        """
        with open("stats.txt","w") as file:
            file.write(f"Boss:{self.bossball}\nCurrentValue:{self.currentvalue}\nUsers:{self.users}\n\nUsersDamage:{self.usersdamage}\n\nBalls:{self.balls}\n\nUsersInRound:{self.usersinround}")
        with open("stats.txt","rb") as file:
            return await interaction.response.send_message(file=discord.File(file,"stats.txt"), ephemeral=True)

    @bossadmin.command(name="disqualify")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def disqualify(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        user_id : str | None = None,
        undisqualify : bool | None = False,
        ):
        """
        Disqualify a member from the boss
        """
        if (user and user_id) or (not user and not user_id):
            await interaction.response.send_message(
                "You must provide either `user` or `user_id`.", ephemeral=True
            )
            return

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))  # type: ignore
            except ValueError:
                await interaction.response.send_message(
                    "The user ID you gave is not valid.", ephemeral=True
                )
                return
            except discord.NotFound:
                await interaction.response.send_message(
                    "The given user ID could not be found.", ephemeral=True
                )
                return
        else:
            user_id = user.id
        if int(user_id) in self.disqualified:
            if undisqualify == True:
                self.disqualified.remove(int(user_id))
                await interaction.response.send_message(
                    f"{user} has been removed from disqualification.\nUse `/boss admin hackjoin` to join the user back.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"{user} has already been disqualified.\nSet `undisqualify` to `True` to remove a user from disqualification.", ephemeral=True
                )
        elif undisqualify == True:
            await interaction.response.send_message(
                f"{user} has **not** been disqualified yet.", ephemeral=True
            )
        elif self.boss_enabled != True:
            self.disqualified.append(int(user_id))
            await interaction.response.send_message(
                f"{user} will be disqualified from the next fight.", ephemeral=True
            )
        elif int(user_id) not in self.users:
            self.disqualified.append(int(user_id))
            await interaction.response.send_message(
                f"{user} has been disqualified successfully.", ephemeral=True
            )
            return
        else:
            self.users.remove(int(user_id))
            self.disqualified.append(int(user_id))
            await interaction.response.send_message(
                f"{user} has been disqualified successfully.", ephemeral=True
            )
            return


    @app_commands.command()
    async def select(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
        special: SpecialEnabledTransform | None = None,
        shiny: bool | None = None,
    ):
        """
        Select countryball to use against the boss.
        
        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to select
        special: Special
            Filter the results of autocompletion to a special event. Ignored afterwards.
        shiny: bool
            Filter the results of autocompletion to shinies. Ignored afterwards.
        """
        if [int(interaction.user.id),self.round] in self.usersinround:
            return await interaction.response.send_message(
                f"You have already selected an {settings.collectible_name}", ephemeral=True
            )
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if not self.picking:
            return await interaction.response.send_message(f"It is not yet time to select an {settings.collectible_name}", ephemeral=True)
        if interaction.user.id not in self.users:
            return await interaction.response.send_message(
                "You did not join, or you're dead/disqualified.", ephemeral=True
            )
        if not ball.is_tradeable:
            await interaction.response.send_message(
                f"You cannot use this {settings.collectible_name}.", ephemeral=True
            )
            return
        if ball in self.balls:
            return await interaction.response.send_message(
                f"You cannot select the same {settings.collectible_name} twice", ephemeral=True
            )
        if ball == None:
            return
        self.balls.append(ball)
        self.usersinround.append([int(interaction.user.id),self.round])
        if ball.attack > MAXSTATS[0]: #maximum and minimum atk and hp stats 
            ballattack = MAXSTATS[0]
        elif ball.attack < 0:
            ballattack = 0
        else:
            ballattack = ball.attack
        if ball.health > MAXSTATS[1]:
            ballhealth = MAXSTATS[1]
        elif ball.health < 0:
            ballhealth = 0
        else:
            ballhealth = ball.health
        messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack} ATK and {ballhealth} HP"
        if "✨" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+{SHINYBUFFS[0]} ATK and {ballhealth}+{SHINYBUFFS[1]} HP"
            ballhealth += SHINYBUFFS[1]
            ballattack += SHINYBUFFS[0]
        elif "🍬" in messageforuser or "❄" in messageforuser or "❄️" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+15000 ATK and {ballhealth}+15000 HP"
            ballhealth += 15000
            ballattack += 15000
        elif "💘" in messageforuser or "🏳️‍🌈" in messageforuser or "🍁" in messageforuser or "🎁" in messageforuser or "🐬" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+5000 ATK and {ballhealth}+5000 HP"
            ballhealth += 5000
            ballattack += 5000
        elif "🎃" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+7500 ATK and {ballhealth}+7500 HP"
            ballhealth += 7500
            ballattack += 7500
        elif "🍭" in messageforuser or "🎊" in messageforuser or "🎉" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+10000 ATK and {ballhealth}+10000 HP"
            ballhealth += 10000
            ballattack += 10000
        elif "🦄" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+50000 ATK and {ballhealth}+50000 HP"
            ballhealth += 50000
            ballattack += 50000
        elif "⚔️" in messageforuser:
            messageforuser = f"{ball.description(short=True, include_emoji=True, bot=self.bot)} has been selected for this round, with {ballattack}+100000 ATK and {ballhealth}+100000 HP"
            ballhealth += 100000
            ballattack += 100000
        else:
            pass

        if not self.attack:
            self.bossHP -= ballattack
            self.usersdamage.append([int(interaction.user.id),ballattack,ball.description(short=True, include_emoji=True, bot=self.bot)])
            self.currentvalue += (str(interaction.user)+"'s "+str(ball.description(short=True, bot=self.bot))+" has dealt "+(str(ballattack))+" damage!\n")
        else:
            if self.bossattack >= ballhealth:
                self.users.remove(interaction.user.id)
                self.currentvalue += (str(interaction.user)+"'s "+str(ball.description(short=True, bot=self.bot))+" had "+(str(ballhealth))+"HP and died!\n")
            else:
                self.currentvalue += (str(interaction.user)+"'s "+str(ball.description(short=True, bot=self.bot)) + " had " + (str(ballhealth)) + "HP and survived!\n")

        await interaction.response.send_message(
            messageforuser, ephemeral=True
        )
        await log_action(
            f"-# Round {self.round}\n{interaction.user}'s {messageforuser}\n-# -------",
            self.bot,
        )

    @app_commands.command()
    async def ongoing(self, interaction: discord.Interaction):
        """
        Show your damage to the boss in the current fight.
        """
        snapshotdamage = self.usersdamage.copy()
        ongoingvalue = ("")
        ongoingfull = 0
        ongoingdead = False
        for i in range(len(snapshotdamage)):
            if snapshotdamage[i][0] == interaction.user.id:
                ongoingvalue += f"{snapshotdamage[i][2]}: {snapshotdamage[i][1]}\n\n"
                ongoingfull += snapshotdamage[i][1]
        if ongoingfull == 0:
            if interaction.user.id in self.users:
                await interaction.response.send_message("You have not dealt any damage.",ephemeral=True)
            elif interaction.user.id in self.disqualified:
                await interaction.response.send_message("You have been disqualified.",ephemeral=True)
            else:
                await interaction.response.send_message("You have not joined the battle, or you have died.",ephemeral=True)
        else:
            if interaction.user.id in self.users:
                await interaction.response.send_message(f"You have dealt {ongoingfull} damage.\n{ongoingvalue}",ephemeral=True)
            elif interaction.user.id in self.disqualified:
                await interaction.response.send_message(f"You have dealt {ongoingfull} damage and have been disqualified.\n{ongoingvalue}",ephemeral=True)
            else:
                await interaction.response.send_message(f"You have dealt {ongoingfull} damage and you are now dead.\n{ongoingvalue}",ephemeral=True)


    @bossadmin.command(name="conclude")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    @app_commands.choices(
        winner=[
            app_commands.Choice(name="Random", value="RNG"),
            app_commands.Choice(name="Most Damage", value="DMG"),
            app_commands.Choice(name="No Winner", value="None"),
        ]
    )
    async def conclude(self, interaction: discord.Interaction, winner: str):
        """
        Finish the boss, conclude the Winner
        """
        self.picking = False
        self.boss_enabled = False
        test = self.usersdamage
        test2 = []
        total = ("")
        total2 = ("")
        totalnum = []
        for i in range(len(test)):
            if test[i][0] not in test2:
                temp = 0
                tempvalue = test[i][0]
                test2.append(tempvalue)
                for j in range(len(test)):
                    if test[j][0] == tempvalue:
                        temp += test[j][1]
                if test[i][0] in self.users:
                    user = await self.bot.fetch_user(int(tempvalue))
                    total += (f"{user} has dealt a total of " + str(temp) + " damage!\n")
                    totalnum.append([tempvalue, temp])
                else:
                    user = await self.bot.fetch_user(int(tempvalue))
                    total2 += (f"[Dead/Disqualified] {user} has dealt a total of " + str(temp) + " damage!\n")

        bosswinner = 0
        highest = 0
        if winner == "DMG":
            for k in range(len(totalnum)):
                if totalnum[k][1] > highest:
                    highest = totalnum[k][1]
                    bosswinner = totalnum[k][0]
        else:
            if len(totalnum) != 0:
                bosswinner = totalnum[random.randint(0,len(totalnum)-1)][0]
        if bosswinner == 0:
            await interaction.response.send_message(
                f"Boss successfully concluded", ephemeral=True
            )
            await interaction.channel.send(f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has won the Boss Battle!")
            with open("totalstats.txt", "w") as file:
                file.write(f"{total}{total2}")
            with open("totalstats.txt", "rb") as file:
                await interaction.channel.send(file=discord.File(file, "totalstats.txt"))
            self.round = 0
            self.balls = []
            self.users = []
            self.currentvalue = ("")
            self.usersdamage = []
            self.usersinround = []
            self.bossHP = 0
            self.round = 0
            self.attack = False
            self.bossattack = 0
            self.bossball = None
            self.bosswild = None
            self.disqualified = []
            return
        if winner != "None":
            player, created = await Player.get_or_create(discord_id=bosswinner)
            special = special = [x for x in specials.values() if x.name == "Boss"][0]
            instance = await BallInstance.create(
                ball=self.bossball,
                player=player,
                shiny=False,
                special=special,
                attack_bonus=random.randint(-100,1000),
                health_bonus=random.randint(-100,1000),
            )
            await interaction.response.send_message(
                f"Boss successfully concluded", ephemeral=True
            )
            await interaction.channel.send(
                f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}\n<@{bosswinner}> has won the Boss Battle!\n\n"
                f"`Boss` `{self.bossball}` {settings.collectible_name} was successfully given.\n"
            )
            bosswinner_user = await self.bot.fetch_user(int(bosswinner))

            await log_action(
                f"`Kisserdex` gave {settings.collectible_name} {self.bossball.country} to {bosswinner_user}.",
                self.bot,
            )
        else:
            await interaction.channel.send(f"# Boss has concluded {self.bot.get_emoji(self.bossball.emoji_id)}\nThe boss has been defeated!")
        with open("totalstats.txt", "w") as file:
            file.write(f"{total}{total2}")
        with open("totalstats.txt", "rb") as file:
            await interaction.channel.send(file=discord.File(file, "totalstats.txt"))
        self.round = 0
        self.balls = []
        self.users = []
        self.currentvalue = ("")
        self.usersdamage = []
        self.usersinround = []
        self.bossHP = 0
        self.round = 0
        self.attack = False
        self.bossattack = 0
        self.bossball = None
        self.bosswild = None
        self.disqualified = []

    @app_commands.command()
    async def join(self, interaction: discord.Interaction):
        """
        Join the boss battle!.
        """
        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if int(interaction.user.id) in self.disqualified:
            return await interaction.response.send_message("You have been disqualified", ephemeral=True)
        if [int(interaction.user.id),self.round] in self.usersinround:
            return await interaction.response.send_message("You have already joined the boss", ephemeral=True)
        if self.round != 0 and interaction.user.id not in self.users:
            return await interaction.response.send_message(
                "It is too late to join the boss, or you have died", ephemeral=True
            )
        if interaction.user.id in self.users:
            return await interaction.response.send_message(
                "You have already joined the boss", ephemeral=True
            )
        self.users.append(interaction.user.id)
        await interaction.response.send_message(
            "You have joined the Boss Battle!", ephemeral=True
        )
        await log_action(
            f"{interaction.user} has joined the `{self.bossball}` Boss Battle.",
            self.bot,
        )

    @bossadmin.command(name="hackjoin")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def hackjoin(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        user_id : str | None = None,
        ):
        """
        Join a user to the boss battle.
        """
        if (user and user_id) or (not user and not user_id):
            await interaction.response.send_message(
                "You must provide either `user` or `user_id`.", ephemeral=True
            )
            return

        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))  # type: ignore
            except ValueError:
                await interaction.response.send_message(
                    "The user ID you gave is not valid.", ephemeral=True
                )
                return
            except discord.NotFound:
                await interaction.response.send_message(
                    "The given user ID could not be found.", ephemeral=True
                )
                return
        else:
            user_id = user.id

        if not self.boss_enabled:
            return await interaction.response.send_message("Boss is disabled", ephemeral=True)
        if [int(user_id), self.round] in self.usersinround:
            return await interaction.response.send_message("This user is already in the boss battle.", ephemeral=True)
        if int(user_id) in self.users:
            return await interaction.response.send_message(
                "This user is already in the boss battle.", ephemeral=True
            )
        self.users.append(user_id)
        if user_id in self.disqualified:
            self.disqualified.remove(user_id)
        await interaction.response.send_message(
            f"{user} has been hackjoined into the Boss Battle.", ephemeral=True
        )
        await log_action(
            f"{user} has joined the `{self.bossball}` Boss Battle. [hackjoin by {await self.bot.fetch_user(int(interaction.user.id))}]",
            self.bot,
        )


