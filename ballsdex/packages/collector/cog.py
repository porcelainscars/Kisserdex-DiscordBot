import logging

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, button
from tortoise.exceptions import DoesNotExist

from typing import TYPE_CHECKING, Optional, cast

from ballsdex.core.models import BallInstance
from ballsdex.core.models import Player
from ballsdex.core.models import specials
from ballsdex.core.models import balls
from ballsdex.core.utils.transformers import BallEnabledTransform
from ballsdex.core.utils.transformers import BallTransform
from ballsdex.core.utils.transformers import SpecialEnabledTransform
from ballsdex.core.utils.transformers import SpecialTransform
from ballsdex.core.utils.buttons import ConfirmChoiceView
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.sorting import SortingChoices, sort_balls
from ballsdex.settings import settings
from ballsdex.core.utils.logging import log_action

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

# You must have a special called "Collector" and "Diamond" for this to work.
# You must be have version 2.22.0 Ballsdex or diamond will not work.

# AMOUNT NEEDED FOR TOP 1 CC BALL e.g. reichtangle
T1Req = 70

# RARITY OF TOP 1 BALL e.g. reichtangle
# (If not originally inputted as 1 into admin panel or /admin balls create)
T1Rarity = 0.01

# AMOUNT NEEDED FOR **MOST** COMMON CC BALL e.g. djibouti
CommonReq = 750

# RARITY OF MOST COMMON BALL e.g. djibouti
# (Which was originally inputted into admin panel or /admin balls create)
CommonRarity = 0.121

# ROUNDING OPTION FOR AMOUNTS NEEDED, WHAT YOU WOULD LIKE EVERYTHING TO ROUNDED TO
# e.g. Putting 10 makes everything round to the nearest 10, cc reqs would look something like:(100,110,120,130,140,150 etc)
# e.g. Putting 5 looks like: (100,105,110,115,120 etc)
# e.g. Putting 20 looks like: (100,120,140,160,180,200 etc)
# 1 is no rounding and looks like: (100,106,112,119,127 etc)
# however you are not limited to these numbers, I think Ballsdex does 50
RoundingOption = 10
# WARNINGS:
# if T1Req/CommonReq is not divisible by RoundingOption they will be affected.
# if T1Req is less than RoundingOption it will be rounded down to 0, (That's just how integer conversions work in python unfortunately)

#Same thing but for diamond
dT1Req = 3
dT1Rarity = 0.01 # this must be the same as T1Rarity, dont make it different unless you know what you're doing
dCommonReq = 12
dCommonRarity = 0.121 # this must be the same as CommonRarity, dont make it different unless you know what you're doing
dRoundingOption = 1


log = logging.getLogger("ballsdex.packages.collector.cog")

gradient = (CommonReq-T1Req)/(CommonRarity-T1Rarity)
dgradient = (dCommonReq-dT1Req)/(dCommonRarity-dT1Rarity)

class Collector(commands.GroupCog):
    """
    Collector commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    ccadmin = app_commands.Group(name="admin", description="admin commands for collector")
    
    @app_commands.command()
    async def card(
        self,
        interaction: discord.Interaction,
        countryball: BallEnabledTransform,
        diamond: bool | None = False
        ):
        """
        Create a collector card.

        Parameters
        ----------
        countryball: Ball
            The countryball for which you want to obtain the collector card.
        """
          
        if interaction.response.is_done():
            return
        assert interaction.guild
        filters = {}
        checkfilter = {}
        if countryball:
            filters["ball"] = countryball
        await interaction.response.defer(ephemeral=True, thinking=True)
        if diamond:
            special = [x for x in specials.values() if x.name == "Diamond"][0]
        else:
            special = [x for x in specials.values() if x.name == "Collector"][0]
        checkfilter["special"] = special
        checkfilter["player__discord_id"] = interaction.user.id
        checkfilter["ball"] = countryball
        checkcounter = await BallInstance.filter(**checkfilter).count()
        if checkcounter >= 1:
            if diamond:
                return await interaction.followup.send(
                    f"You already have a {countryball.country} diamond card."
                )
            else:
                return await interaction.followup.send(
                    f"You already have a {countryball.country} collector card."
                )
        filters["player__discord_id"] = interaction.user.id
        if diamond:
            shiny = [x for x in specials.values() if x.name == "Shiny"][0]
            filters["special"] = shiny
        balls = await BallInstance.filter(**filters).count()

        if diamond:
            collector_number = int(int((dgradient*(countryball.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
        else:
            collector_number = int(int((gradient*(countryball.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)

        country = f"{countryball.country}"
        player, created = await Player.get_or_create(discord_id=interaction.user.id)
        if balls >= collector_number:
            if diamond:
                diamondtext = " diamond"
            else:
                diamondtext = ""
            await interaction.followup.send(
                f"Congratulations! You are now a {country}{diamondtext} collector.", 
                ephemeral=True
            )
            await BallInstance.create(
            ball=countryball,
            player=player,
            attack_bonus=0,
            health_bonus=0,
            special=special,
            )
        else:
            if diamond:
                text0 = "diamond"
                shinytext = " Shiny"
            else:
                text0 = "collector"
                shinytext = ""
            await interaction.followup.send(
                f"You need {collector_number}{shinytext} {country} to create a {text0} card. You currently have {balls}."
            )

    @app_commands.command()
    async def list(self, interaction: discord.Interaction["BallsDexBot"], diamond: bool | None = False):
        # DO NOT CHANGE THE CREDITS TO THE AUTHOR HERE!
        """
        Display the collector card requirements for each kisser.
        """
        # Filter enabled collectibles
        enabled_collectibles = [x for x in balls.values() if x.enabled]

        if not enabled_collectibles:
            await interaction.response.send_message(
                f"There are no collectibles registered in {settings.bot_name} yet.",
                ephemeral=True,
            )
            return

        # Sort collectibles by rarity in ascending order
        sorted_collectibles = sorted(enabled_collectibles, key=lambda x: x.rarity)

        entries = []
        if diamond:
            text0 = "Diamond"
            shinytext = " Shiny"
        else:
            text0 = "Collector"
            shinytext = ""
        for collectible in sorted_collectibles:
            name = f"{collectible.country}"
            emoji = self.bot.get_emoji(collectible.emoji_id)

            if emoji:
                emote = str(emoji)
            else:
                emote = "N/A"
            if diamond:
                rarity1 = int(int((dgradient*(collectible.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
            else:
                rarity1 = int(int((gradient*(collectible.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)
            
            entry = (name, f"{emote}{shinytext} Amount required: {rarity1}")
            entries.append(entry)
        # This is the number of countryballs which are displayed at one page,
        # you can change this, but keep in mind: discord has an embed size limit.
        per_page = 10

        source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
        source.embed.description = (
            f"__**{settings.bot_name} {text0} Card List**__"
        )
        source.embed.colour = discord.Colour.from_rgb(190,100,190)
        source.embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start(
            ephemeral=True,
        )

    @ccadmin.command(name="check")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    @app_commands.choices(
        option=[
            app_commands.Choice(name="Show all CCs", value="ALL"),
            app_commands.Choice(name="Show only unmet CCs", value="UNMET"),
            app_commands.Choice(name="Delete all unmet CCs", value="DELETE"), # must have full admin perm
        ]
    )
    async def check(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        option: str,
        countryball: BallTransform | None = None,
        user: discord.User | None = None,
        diamond: bool | None = False,
    ):
        """
        Check for unmet Collector Cards
        
        Parameters
        ----------
        option: option
        countryball: Ball | None
        user: discord.User | None
        """
        if option == "DELETE":
            fullperm = False
            for i in settings.root_role_ids:
                if interaction.guild.get_role(i) in interaction.user.roles:
                    fullperm = True
            if fullperm == False:
                return await interaction.response.send_message(f"You do not have permission to delete {settings.plural_collectible_name}", ephemeral=True)
                
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        if diamond:
            collectorspecial = [x for x in specials.values() if x.name == "Diamond"][0]
        else:
            collectorspecial = [x for x in specials.values() if x.name == "Collector"][0]
            
        filters = {}
        filters["special"] = collectorspecial
        if countryball:
            filters["ball"] = countryball
        if user:
            filters["player__discord_id"] = user.id
        entries = []
        unmetlist = []
        
        balls = await BallInstance.filter(**filters).prefetch_related(
                        "player","special","ball"
                    )
        for ball in balls:
            player = await self.bot.fetch_user(int(f"{ball.player}"))
            checkfilter = {}
            checkfilter["player__discord_id"] = int(f"{ball.player}")
            checkfilter["ball"] = ball.ball
            
            if diamond:
                checkfilter["special"] = [x for x in specials.values() if x.name == "Shiny"][0]
                shinytext = " Shiny"
            else:
                shinytext = ""
                
            checkballs = await BallInstance.filter(**checkfilter).count()
            if checkballs == 1:
                collectiblename = settings.collectible_name
            else:
                collectiblename = settings.plural_collectible_name
            meetcheck = (f"{player} has **{checkballs}**{shinytext} {ball.ball} {collectiblename}")
            
            if diamond:
                rarity2 = int(int((dgradient*(ball.ball.rarity-dT1Rarity) + dT1Req)/dRoundingOption)*dRoundingOption)
            else:
                rarity2 = int(int((gradient*(ball.ball.rarity-T1Rarity) + T1Req)/RoundingOption)*RoundingOption)
                
            if checkballs >= rarity2:
                meet = (f"**Enough to maintain ✅**\n---")
                if option == "ALL":
                    entry = (ball.description(short=True, include_emoji=True, bot=self.bot), f"{player}({ball.player})\n{meetcheck}\n{meet}")
                    entries.append(entry)
            else:
                meet = (f"**Not enough to maintain** ⚠️\n---")
                entry = (ball.description(short=True, include_emoji=True, bot=self.bot), f"{player}({ball.player})\n{meetcheck}\n{meet}")
                entries.append(entry)
                unmetlist.append(ball)
                
        if diamond:
            text0 = "diamond"
            shiny0 = " shiny"
        else:
            text0 = "collector"
            shiny0 = ""
            
        if len(entries) == 0:
            if countryball:
                ctext = (f" {countryball}")
            else:
                ctext = ("")
            if option == "ALL":
                utext = ("")
            else:
                utext = (" unmet")
            if user == None:
                return await interaction.followup.send(f"There are no{utext}{ctext} {text0} cards!")
            else:
                return await interaction.followup.send(f"{user} has no{utext}{ctext} {text0} cards!")
        if option == "DELETE":
            unmetballs = ""
            for b in unmetlist:
                player = await self.bot.fetch_user(int(f"{b.player}"))
                unmetballs+=(f"{player}'s {b}\n")
            with open("unmetccs.txt", "w") as file:
                file.write(unmetballs)
            with open("unmetccs.txt", "rb") as file:
                await interaction.followup.send(f"The following {text0} cards will be deleted for no longer having enough{shiny0} {settings.plural_collectible_name} each to maintain them:",file=discord.File(file, "unmetccs.txt"),ephemeral=True)
            view = ConfirmChoiceView(
                interaction,
                accept_message=f"Confirmed, deleting...",
                cancel_message="Request cancelled.",
            )
            unmetcount = len(unmetlist)
            await interaction.followup.send(f"Are you sure you want to delete {unmetcount} {text0} card(s)?\nThis cannot be undone.",view=view,ephemeral=True)
            await view.wait()
            if not view.value:
                return
            for b in unmetlist:
                await b.delete()
            if unmetcount == 1:
                collectiblename1 = settings.collectible_name
            else:
                collectiblename1 = settings.plural_collectible_name
            await interaction.followup.send(f"{unmetcount} {text0} card {collectiblename1} has been deleted successfully.",ephemeral=True)
            await log_action(
                f"{interaction.user} has deleted {unmetcount} {text0} card {collectiblename1} for no longer having enough{shiny0} {settings.plural_collectible_name} each to maintain them.",
                self.bot,
            )
            return
            
        else:
            per_page = 10

            source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
            if diamond:
                source.embed.description = (
                    f"__**{settings.bot_name} Diamond Card Check**__"
                )
            else:
                source.embed.description = (
                    f"__**{settings.bot_name} Collector Card Check**__"
                )
            source.embed.colour = discord.Colour.from_rgb(190,100,190)

            pages = Pages(source=source, interaction=interaction, compact=True)
            await pages.start(ephemeral=True)
