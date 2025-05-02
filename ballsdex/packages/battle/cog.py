import logging
import time
import random
import sys
from typing import TYPE_CHECKING, Dict
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

import asyncio
import io

from ballsdex.core.models import (
    Ball,
    BallInstance,
    Player
)
from ballsdex.core.models import balls as countryballs
from ballsdex.settings import settings

from ballsdex.core.utils.transformers import (
    BallInstanceTransform,
    BallTransform,
    BallEnabledTransform,
    SpecialEnabledTransform,
)

from ballsdex.packages.battle.xe_battle_lib import (
    BattleBall,
    BattleInstance,
    gen_battle,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")

battles = []

@dataclass
class GuildBattle:
    interaction: discord.Interaction

    author: discord.Member
    opponent: discord.Member

    author_ready: bool = False
    opponent_ready: bool = False

    battle: BattleInstance = field(default_factory=BattleInstance)


def gen_deck(balls) -> str:
    """Generates a text representation of the player's deck."""
    if not balls:
        return "Empty"

    deck_lines = [
        f"- {ball.emoji} {ball.name} (HP: {ball.health} | DMG: {ball.attack})"
        for ball in balls
    ]

    deck = "\n".join(deck_lines)

    if len(deck) <= 1024:
        return deck

    total_suffix = f"\nTotal: {len(balls)}"
    suffix_length = len(total_suffix)
    max_deck_length = 1024 - suffix_length
    truncated_deck = ""
    current_length = 0
    
    for line in deck_lines:
        line_length = len(line) + (1 if truncated_deck else 0) 
        if current_length + line_length > max_deck_length:
            break
        truncated_deck += ("\n" if truncated_deck else "") + line
        current_length += line_length
    
    return truncated_deck + total_suffix

def update_embed(
    author_balls, opponent_balls, author, opponent, author_ready, opponent_ready, maxallowed
) -> discord.Embed:
    """Creates an embed for the battle setup phase."""
    if maxallowed == 0:
        maxallowed = "Unlimited"
    embed = discord.Embed(
        title=f"{settings.plural_collectible_name.title()} Battle Plan",
        description=(
            f"Add or remove {settings.plural_collectible_name} you want to propose to the other player using the "
            "/battle add and /battle remove commands. Once you've finished, "
            f"click the tick button to start the battle.\nMax amount: {maxallowed}"
        ),
        color=discord.Colour.blurple(),
    )

    author_emoji = ":white_check_mark:" if author_ready else ""
    opponent_emoji = ":white_check_mark:" if opponent_ready else ""

    embed.add_field(
        name=f"{author_emoji} {author}'s deck:",
        value=gen_deck(author_balls),
        inline=True,
    )
    embed.add_field(
        name=f"{opponent_emoji} {opponent}'s deck:",
        value=gen_deck(opponent_balls),
        inline=True,
    )
    return embed


def create_disabled_buttons() -> discord.ui.View:
    """Creates a view with disabled start and cancel buttons."""
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.success, emoji="✔", label="Ready", disabled=True
        )
    )
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.danger, emoji="✖", label="Cancel", disabled=True
        )
    )


def fetch_battle(user: discord.User | discord.Member):
    """
    Fetches a battle based on the user provided.

    Parameters
    ----------
    user: discord.User | discord.Member
        The user you want to fetch the battle from.
    """
    found_battle = None

    for battle in battles:
        if user not in (battle.author, battle.opponent):
            continue

        found_battle = battle
        break

    return found_battle


class Battle(commands.GroupCog):
    """
    Battle your countryballs!
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.battlerounds = []

    bulk = app_commands.Group(
        name='bulk', description='Bulk commands for battle'
    )

    admin = app_commands.Group(
        name='admin', description='Admin commands for battle'
    )
    
    async def start_battle(self, interaction: discord.Interaction):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't a part of this battle.", ephemeral=True
            )
            return
        
        # Set the player's readiness status

        if interaction.user == guild_battle.author:
            guild_battle.author_ready = True
        elif interaction.user == guild_battle.opponent:
            guild_battle.opponent_ready = True
        # If both players are ready, start the battle

        if guild_battle.author_ready and guild_battle.opponent_ready:
            if not (guild_battle.battle.p1_balls and guild_battle.battle.p2_balls):
                await interaction.response.send_message(
                    f"Both players must add {settings.plural_collectible_name}!"
                )
                return
            new_view = create_disabled_buttons()
            battle_log = "\n".join(gen_battle(guild_battle.battle))
            embed = discord.Embed(
                title=f"{settings.plural_collectible_name.title()} Battle Plan",
                description=f"Battle between {guild_battle.author.mention} and {guild_battle.opponent.mention}",
                color=discord.Color.green(),
            )
            embed.add_field(
                name=f"{guild_battle.author}'s deck:",
                value=gen_deck(guild_battle.battle.p1_balls),
                inline=True,
            )
            embed.add_field(
                name=f"{guild_battle.opponent}'s deck:",
                value=gen_deck(guild_battle.battle.p2_balls),
                inline=True,
            )
            embed.add_field(
                name="Winner:",
                value=f"{guild_battle.battle.winner} - Turn: {guild_battle.battle.turns}",
                inline=False,
            )
            embed.set_footer(text="Battle log is attached.")

            await interaction.response.defer()
            await interaction.message.edit(
                content=f"{guild_battle.author.mention} vs {guild_battle.opponent.mention}",
                embed=embed,
                view=new_view,
                attachments=[
                    discord.File(io.StringIO(battle_log), filename="battle-log.txt")
                ],
            )
            battles.pop(battles.index(guild_battle))
            for bround in self.battlerounds:
                if interaction.user.id in bround:
                    self.battlerounds.remove(bround)
                    break
        else:
            # One player is ready, waiting for the other player

            await interaction.response.send_message(
                f"Done! Waiting for the other player to press 'Ready'.", ephemeral=True
            )

            author_emoji = (
                ":white_check_mark:" if interaction.user == guild_battle.author else ""
            )
            opponent_emoji = (
                ":white_check_mark:"
                if interaction.user == guild_battle.opponent
                else ""
            )
            for bround in self.battlerounds:
                if interaction.user.id in bround:
                    maxallowed = bround[2]
                    break
            if maxallowed == 0:
                maxallowed = "Unlimited"
            embed = discord.Embed(
                title=f"{settings.plural_collectible_name.title()} Battle Plan",
                description=(
                    f"Add or remove {settings.plural_collectible_name} you want to propose to the other player using the "
                    "/battle add and /battle remove commands. Once you've finished, "
                    f"click the tick button to start the battle.\nMax amount: {maxallowed}"
                ),
                color=discord.Colour.blurple(),
            )

            embed.add_field(
                name=f"{author_emoji} {guild_battle.author.name}'s deck:",
                value=gen_deck(guild_battle.battle.p1_balls),
                inline=True,
            )
            embed.add_field(
                name=f"{opponent_emoji} {guild_battle.opponent.name}'s deck:",
                value=gen_deck(guild_battle.battle.p2_balls),
                inline=True,
            )

            await guild_battle.interaction.edit_original_response(embed=embed)

    async def cancel_battle(self, interaction: discord.Interaction):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't a part of this battle!", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{settings.plural_collectible_name.title()} Battle Plan",
            description="The battle has been cancelled.",
            color=discord.Color.red(),
        )
        embed.add_field(
            name=f":no_entry_sign: {guild_battle.author}'s deck:",
            value=gen_deck(guild_battle.battle.p1_balls),
            inline=True,
        )
        embed.add_field(
            name=f":no_entry_sign: {guild_battle.opponent}'s deck:",
            value=gen_deck(guild_battle.battle.p2_balls),
            inline=True,
        )

        try:
            await interaction.response.defer()
        except discord.errors.InteractionResponded:
            pass

        await interaction.message.edit(embed=embed, view=create_disabled_buttons())
        battles.pop(battles.index(guild_battle))
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                self.battlerounds.remove(bround)
                break

    @app_commands.command()
    async def start(self, interaction: discord.Interaction, opponent: discord.Member, max_amount: int | None = 0):
        """
        Starts a battle with a chosen user.

        Parameters
        ----------
        opponent: discord.Member
            The user you want to battle.

        max_amount: int | None = 0
            The maximum amount of kissers allowed each.
        """
        if opponent.bot:
            await interaction.response.send_message(
                "You can't battle against bots.", ephemeral=True,
            )
            return
        
        if opponent.id == interaction.user.id:
            await interaction.response.send_message(
                "You can't battle against yourself.", ephemeral=True,
            )
            return

        if fetch_battle(opponent) is not None:
            await interaction.response.send_message(
                "That user is already in a battle. They may use `/battle cancel` to cancel it.", ephemeral=True,
            )
            return

        if fetch_battle(interaction.user) is not None:
            await interaction.response.send_message(
                "You are already in a battle. You may use `/battle cancel` to cancel it.", ephemeral=True,
            )
            return
        
        battles.append(GuildBattle(interaction, interaction.user, opponent))
        if max_amount < 0:
            max_amount = 0
        self.battlerounds.append([interaction.user.id,opponent.id,max_amount])
        
        embed = update_embed([], [], interaction.user.name, opponent.name, False, False, max_amount)

        start_button = discord.ui.Button(
            style=discord.ButtonStyle.success, emoji="✔", label="Ready"
        )
        cancel_button = discord.ui.Button(
            style=discord.ButtonStyle.danger, emoji="✖", label="Cancel"
        )

        # Set callbacks

        start_button.callback = self.start_battle
        cancel_button.callback = self.cancel_battle

        view = discord.ui.View(timeout=None)

        view.add_item(start_button)
        view.add_item(cancel_button)

        await interaction.response.send_message(
            f"Hey, {opponent.mention}, {interaction.user.name} is proposing a battle with you!",
            embed=embed,
            view=view,
        )

    async def add_balls(self, interaction: discord.Interaction, countryballs):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't a part of a battle!", ephemeral=True
            )
            return
        
        if interaction.guild_id != guild_battle.interaction.guild_id:
            await interaction.response.send_message(
                "You must be in the same server as your battle to use commands.", ephemeral=True
            )
            return

        # Check if the user is already ready

        if (interaction.user == guild_battle.author and guild_battle.author_ready) or (
            interaction.user == guild_battle.opponent and guild_battle.opponent_ready
        ):
            await interaction.response.send_message(
                f"You cannot change your {settings.plural_collectible_name} as you are already ready.", ephemeral=True
            )
            return
        # Determine if the user is the author or opponent and get the appropriate ball list

        user_balls = (
            guild_battle.battle.p1_balls
            if interaction.user == guild_battle.author
            else guild_battle.battle.p2_balls
        )

        for bround in self.battlerounds:
            if interaction.user.id in bround:
                maxallowed = bround[2]
                break
        if len(user_balls) == maxallowed and maxallowed != 0:
            await interaction.response.send_message(
                f"You cannot add anymore {settings.plural_collectible_name} as you have already reached the max amount limit!", ephemeral=True
            )
            return
        # Create the BattleBall instance
        maxvalue = 300000
        for countryball in countryballs:
            battlespecial = await countryball.special
            battlespecial = (f"{battlespecial}")
            if battlespecial == "Valentine 2024" or battlespecial == "Pride 2024" or battlespecial == "Autumn 2024" or battlespecial == "Kissmas 2024" or battlespecial == "Symphony":
                buff = 5000
            elif battlespecial == "Halloween 2024":
                buff = 7500
            elif battlespecial == "Birthday 2024" or battlespecial == "Afterparty 2024" or battlespecial == "Treat" or battlespecial == "Lunar New Year 2025" or battlespecial == "Valentine's Day 2025" or battlespecial == "April Fools 2025" or battlespecial == "Easter 2025":
                buff = 10000
            elif battlespecial == "Halloween 2023" or battlespecial == "Kissmas 2023":
                buff = 15000
            elif battlespecial == "Shiny":
                buff = 20000
            elif battlespecial == "Fabled":
                buff = 50000
            elif battlespecial == "Boss":
                buff = 100000
            else:
                buff = 0
            if countryball.health < 0:
                countryballhealth = 0
            elif countryball.health > maxvalue:
                countryballhealth = maxvalue
            else:
                countryballhealth = countryball.health
            if countryball.attack < 0:
                countryballattack = 0
            elif countryball.attack > maxvalue:
                countryballattack = maxvalue
            else:
                countryballattack = countryball.attack
            ball = BattleBall(
                countryball.description(short=True, include_emoji=False, bot=self.bot),
                interaction.user.name,
                (countryballhealth + buff),
                (countryballattack + buff),
                self.bot.get_emoji(countryball.countryball.emoji_id),
            )

            # Check if ball has already been added

            if ball in user_balls:
                yield True
                continue
            
            user_balls.append(ball)
            yield False

        # Update the battle embed for both players
        await guild_battle.interaction.edit_original_response(
            embed=update_embed(
                guild_battle.battle.p1_balls,
                guild_battle.battle.p2_balls,
                guild_battle.author.name,
                guild_battle.opponent.name,
                guild_battle.author_ready,
                guild_battle.opponent_ready,
                maxallowed,
            )
        )

    async def remove_balls(self, interaction: discord.Interaction, countryballs):
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't a part of a battle!", ephemeral=True
            )
            return
        
        if interaction.guild_id != guild_battle.interaction.guild_id:
            await interaction.response.send_message(
                "You must be in the same server as your battle to use commands.", ephemeral=True
            )
            return

        # Check if the user is already ready

        if (interaction.user == guild_battle.author and guild_battle.author_ready) or (
            interaction.user == guild_battle.opponent and guild_battle.opponent_ready
        ):
            await interaction.response.send_message(
                "You cannot change your balls as you are already ready.", ephemeral=True
            )
            return
        # Determine if the user is the author or opponent and get the appropriate ball list

        user_balls = (
            guild_battle.battle.p1_balls
            if interaction.user == guild_battle.author
            else guild_battle.battle.p2_balls
        )
        # Create the BattleBall instance

        maxvalue = 300000
        for countryball in countryballs:
            battlespecial = await countryball.special
            battlespecial = (f"{battlespecial}")
            if battlespecial == "Valentine 2024" or battlespecial == "Pride 2024" or battlespecial == "Autumn 2024" or battlespecial == "Kissmas 2024" or battlespecial == "Symphony":
                buff = 5000
            elif battlespecial == "Halloween 2024":
                buff = 7500
            elif battlespecial == "Birthday 2024" or battlespecial == "Afterparty 2024" or battlespecial == "Treat" or battlespecial == "Lunar New Year 2025" or battlespecial == "Valentine's Day 2025" or battlespecial == "April Fools 2025" or battlespecial == "Easter 2025":
                buff = 10000
            elif battlespecial == "Halloween 2023" or battlespecial == "Kissmas 2023":
                buff = 15000
            elif battlespecial == "Shiny":
                buff = 20000
            elif battlespecial == "Fabled":
                buff = 50000
            elif battlespecial == "Boss":
                buff = 100000
            else:
                buff = 0
            if countryball.health < 0:
                countryballhealth = 0
            elif countryball.health > maxvalue:
                countryballhealth = maxvalue
            else:
                countryballhealth = countryball.health
            if countryball.attack < 0:
                countryballattack = 0
            elif countryball.attack > maxvalue:
                countryballattack = maxvalue
            else:
                countryballattack = countryball.attack
            ball = BattleBall(
                countryball.description(short=True, include_emoji=False, bot=self.bot),
                interaction.user.name,
                (countryballhealth + buff),
                (countryballattack + buff),
                self.bot.get_emoji(countryball.countryball.emoji_id),
            )

            # Check if ball has already been added

            if ball not in user_balls:
                yield True
                continue
            
            user_balls.remove(ball)
            yield False

        # Update the battle embed for both players
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                maxallowed = bround[2]
                break
        await guild_battle.interaction.edit_original_response(
            embed=update_embed(
                guild_battle.battle.p1_balls,
                guild_battle.battle.p2_balls,
                guild_battle.author.name,
                guild_battle.opponent.name,
                guild_battle.author_ready,
                guild_battle.opponent_ready,
                maxallowed,
            )
        )

    @app_commands.command()
    async def add(
        self, interaction: discord.Interaction, countryball: BallInstanceTransform, special: SpecialEnabledTransform | None = None,
    ):
        """
        Adds a countryball to a battle.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to add.
        """
        if not (await countryball.ball).tradeable:
            await interaction.response.send_message(
                f"You cannot use this {settings.collectible_name}.", ephemeral=True
            )
            return
        async for dupe in self.add_balls(interaction, [countryball]):
            if dupe:
                await interaction.response.send_message(
                    f"You cannot add the same {settings.collectible_name} twice!", ephemeral=True
                )
                return

        # Construct the message
        attack = "{:+}".format(countryball.attack_bonus)
        health = "{:+}".format(countryball.health_bonus)

        try:
            await interaction.response.send_message(
                f"Added `{countryball.description(short=True, include_emoji=False, bot=self.bot)} ({attack}%/{health}%)`!",
                ephemeral=True,
            )
        except:
            return

    @app_commands.command()
    async def remove(
        self, interaction: discord.Interaction, countryball: BallInstanceTransform, special: SpecialEnabledTransform | None = None,
    ):
        """
        Removes a countryball from battle.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        async for not_in_battle in self.remove_balls(interaction, [countryball]):
            if not_in_battle:
                await interaction.response.send_message(
                    f"You cannot remove a {settings.collectible_name} that is not in your deck!", ephemeral=True
                )
                return

        attack = "{:+}".format(countryball.attack_bonus)
        health = "{:+}".format(countryball.health_bonus)

        try:
            await interaction.response.send_message(
                f"Removed `{countryball.description(short=True, include_emoji=False, bot=self.bot)} ({attack}%/{health}%)`!",
                ephemeral=True,
            )
        except:
            return
    
    @bulk.command(name="add")
    async def bulk_add(
        self, interaction: discord.Interaction, countryball: BallEnabledTransform | None = None,
    ):
        """
        Adds countryballs to a battle in bulk.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to add.
        """
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            for bround in self.battlerounds:
                if interaction.user.id in bround:
                    maxallowed = bround[2]
                    break
            if maxallowed != 0:
                return await interaction.followup.send("Bulk adding is not available when there is a max amount limit!",ephemeral=True)
            player, _ = await Player.get_or_create(discord_id=interaction.user.id)
            filters = {}
            filters["player__discord_id"] = interaction.user.id
            filters["ball__tradeable"] = True
            if countryball:
                balls = await countryball.ballinstances.filter(player=player)
            else:
                balls = await BallInstance.filter(**filters)

            count = 0
            async for dupe in self.add_balls(interaction, balls):
                if not dupe:
                    count += 1
            if countryball:
                await interaction.followup.send(
                    f'Added {count} {countryball.country}{"s" if count != 1 else ""}!',
                    ephemeral=True,
                )
            else:
                name = settings.plural_collectible_name if count != 1 else settings.collectible_name
                await interaction.followup.send(f"Added {count} {name}!", ephemeral=True)
        except:
            await interaction.followup.send(f"An error occured, please make sure you're in an active battle and try again.",ephemeral=True)

    @bulk.command(name="remove")
    async def bulk_remove(
        self, interaction: discord.Interaction, countryball: BallEnabledTransform | None = None,
    ):
        """
        Removes countryballs from a battle in bulk.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            player, _ = await Player.get_or_create(discord_id=interaction.user.id)
            if countryball:
                balls = await countryball.ballinstances.filter(player=player)
            else:
                balls = await BallInstance.filter(player=player)
                
            count = 0
            async for not_in_battle in self.remove_balls(interaction, balls):
                if not not_in_battle:
                    count += 1
            if countryball:
                await interaction.followup.send(
                    f'Removed {count} {countryball.country}{"s" if count != 1 else ""}!',
                    ephemeral=True,
                )
            else:
                name = settings.plural_collectible_name if count != 1 else settings.collectible_name
                await interaction.followup.send(f"Removed {count} {name}!", ephemeral=True)
        except:
            await interaction.followup.send(f"An error occured, please make sure you're in an active battle and try again.",ephemeral=True)

    @app_commands.command()
    async def cancel(
        self, interaction: discord.Interaction
    ):
        """
        Cancels the battle you are in.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        guild_battle = fetch_battle(interaction.user)

        if guild_battle is None:
            await interaction.response.send_message(
                "You aren't a part of a battle!", ephemeral=True
            )
            return

        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.InteractionResponded:
            pass

        battles.pop(battles.index(guild_battle))
        for bround in self.battlerounds:
            if interaction.user.id in bround:
                self.battlerounds.remove(bround)
                break

        await interaction.followup.send(f"Your current battle has been frozen and cancelled.",ephemeral=True)

    @admin.command(name="clear")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def clear(
        self, interaction: discord.Interaction
    ):
        """
        Cancels all battles.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to remove.
        """
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.InteractionResponded:
            pass

        battles.clear()
        self.battlerounds = []

        await interaction.followup.send(f"All battle have been reset.",ephemeral=True)
        
