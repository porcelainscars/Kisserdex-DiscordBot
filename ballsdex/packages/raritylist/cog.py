import discord
import logging
import random
import re

from discord.utils import get
from discord import app_commands
from discord.ext import commands

from ballsdex.settings import settings
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.settings import settings
from ballsdex.core.models import Player, BallInstance, specials, balls 
from ballsdex.packages.countryballs.countryball import CountryBall
from ballsdex.core.utils.transformers import (
    BallTransform,
    EconomyTransform,
    RegimeTransform,
    SpecialTransform,
    BallEnabledTransform,
    BallInstanceTransform,
    SpecialEnabledTransform,
    TradeCommandType,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.raritylist")

class raritylist(commands.Cog):
    """
    Simple rarity commands.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
    
    @app_commands.command()
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def rarity_list(self, interaction: discord.Interaction, countryball: BallEnabledTransform | None = None):
        """
        Display the rarity of a kisser.

        Parameters
        ----------
        countryball: Ball | None
            The countryball whose rarity you would like to view. Shows entire list if not specified.
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
        list1 = []
        list2 = []
        for collectible in sorted_collectibles:
            name = f"{collectible.country}"
            emoji = self.bot.get_emoji(collectible.emoji_id)

            if emoji:
                emote = str(emoji)
            else:
                emote = "N/A"
            # if you want the Rarity to only show full numbers like 1 or 12 use the code part here:
            # rarity = int(collectible.rarity)
            # otherwise you want to display numbers like 1.5, 5.3, 76.9 use the normal part.
            r = collectible.rarity
            if r in list2:
                list1.append(list1[-1])
            else:
                list1.append(len(list1) + 1)
            rarity = list1[-1]
            list2.append(r)

            entry = (name, f"{emote} Rarity: {rarity}")
            entries.append(entry)
            if collectible == countryball:
                return await interaction.response.send_message(
                    f"**{name}**\n{emote} Rarity: {rarity}",
                    ephemeral=True,
                )
        # This is the number of countryballs who are displayed at one page,
        # you can change this, but keep in mind: discord has an embed size limit.
        per_page = 10

        source = FieldPageSource(entries, per_page=per_page, inline=False, clear_description=False)
        source.embed.description = (
            f"__**{settings.bot_name} rarity**__"
        )
        source.embed.colour = discord.Colour.blurple()
        source.embed.set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url
        )

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start(
            ephemeral=True,
        )
