# bot.py
import discord
from discord import app_commands
from discord.ext import commands
import datetime
import random
from io import BytesIO
import asyncio
import string
import os
from dotenv import load_dotenv

# Load token from .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# --- Configuration ---
GUILD_ID = 1491698389341962242
ROLE_ID = 1491698557672226928
WELCOME_CHANNEL_ID = 1491710027621339229

# --- Bot Setup ---
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        self.invite_cache = {}
        self.stats = {}

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"Slash commands synced to guild {GUILD_ID}")

bot = MyBot()

# --- Helpers ---
def get_ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def is_alt(member):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - member.created_at).days < 7

# --- Events ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            bot.invite_cache[guild.id] = {i.code: i.uses for i in await guild.invites()}
        except discord.Forbidden:
            print("Missing permissions to track invites.")

@bot.event
async def on_member_join(member):
    if member.guild.id != GUILD_ID:
        return

    guild = member.guild

    # Give role
    role = guild.get_role(ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"Role Error: {e}")

    # Invite tracking
    before_invites = bot.invite_cache.get(guild.id, {})
    after_invites = {i.code: i.uses for i in await guild.invites()}
    bot.invite_cache[guild.id] = after_invites

    inviter_text = "someone (link unknown)"
    for code, uses in after_invites.items():
        if code in before_invites and uses > before_invites[code]:
            current_invites = await guild.invites()
            for inv in current_invites:
                if inv.code == code:
                    inviter_text = inv.inviter.mention
                    bot.stats[inv.inviter.id] = bot.stats.get(inv.inviter.id, 0) + 1
                    break

    # Welcome message
    ordinal_count = get_ordinal(len(guild.members))
    channel = guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        alt_alert = " 🚩 **(Alt Detected)**" if is_alt(member) else ""
        await channel.send(
            f"Welcome {member.mention}, you have been invited by {inviter_text} "
            f"and you are the **{ordinal_count}** member!{alt_alert}"
        )

    # DM
    try:
        await member.send(f"Welcome to **{guild.name}**. We hope you're having a great time!")
    except:
        pass

# --- Slash Commands ---
@bot.tree.command(name="invites", description="Check invite count")
@app_commands.describe(member="The member to check")
async def invites(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    count = bot.stats.get(target.id, 0)
    await interaction.response.send_message(f"👤 **{target.name}** has invited **{count}** members!")

@bot.tree.command(name="leaderboard", description="Show top 10 inviters")
async def leaderboard(interaction: discord.Interaction):
    if not bot.stats:
        return await interaction.response.send_message("The leaderboard is empty!", ephemeral=True)

    sorted_stats = sorted(bot.stats.items(), key=lambda x: x[1], reverse=True)[:10]
    lb_content = "\n".join([f"**#{i+1}** <@{u_id}>: {c} invites" for i, (u_id, c) in enumerate(sorted_stats)])
    embed = discord.Embed(title="🏆 Invite Leaderboard", description=lb_content, color=0x7289DA)
    await interaction.response.send_message(embed=embed)

# --- Giveaways ---
active_giveaways = {}  # giveaway_id: {msg_id, channel_id, item, participants, requirement}

@bot.tree.command(name="giveaway", description="Create a giveaway (Admin only)")
@app_commands.describe(
    item="The item to give away",
    requirement="Requirement to join (informational only)",
    time="Duration in seconds",
    channel="Channel to host the giveaway"
)
async def giveaway(interaction: discord.Interaction, item: str, requirement: str, time: int, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need **Administrator** permissions to start a giveaway.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    giveaway_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    embed = discord.Embed(
        title="🎉 Giveaway!",
        description=f"Prize: **{item}**\nRequirement: {requirement}\nReact with 🎉 to join!\nID: `{giveaway_id}`",
        color=0xFFD700
    )
    embed.set_footer(text=f"Hosted by {interaction.user.name}")
    msg = await channel.send(embed=embed)
    await msg.add_reaction("🎉")

    participants = set()
    active_giveaways[giveaway_id] = {
        "msg_id": msg.id,
        "channel_id": channel.id,
        "item": item,
        "participants": participants,
        "requirement": requirement
    }

    def check_add(reaction, user):
        return reaction.message.id == msg.id and str(reaction.emoji) == "🎉" and not user.bot

    def check_remove(reaction, user):
        return reaction.message.id == msg.id and str(reaction.emoji) == "🎉" and not user.bot

    async def monitor_giveaway():
        end_time = asyncio.get_event_loop().time() + time
        while asyncio.get_event_loop().time() < end_time:
            try:
                reaction, user = await bot.wait_for("reaction_add", timeout=1.0, check=check_add)
                if user.id not in participants:
                    participants.add(user.id)
                    await user.send("🎉 You've joined the giveaway!")
            except asyncio.TimeoutError:
                pass
            try:
                reaction, user = await bot.wait_for("reaction_remove", timeout=1.0, check=check_remove)
                if user.id in participants:
                    participants.remove(user.id)
                    await user.send("❌ You left the giveaway!")
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0.1)

        if participants:
            winner_id = random.choice(list(participants))
            winner = interaction.guild.get_member(winner_id)
            await channel.send(f"🎉 Giveaway `{giveaway_id}` ended! Congratulations {winner.mention}, you won **{item}**!")
        else:
            await channel.send(f"Giveaway `{giveaway_id}` ended! No one joined 😢")
        del active_giveaways[giveaway_id]

    bot.loop.create_task(monitor_giveaway())
    await interaction.followup.send(f"Giveaway started in {channel.mention} with ID `{giveaway_id}`!", ephemeral=True)

# --- Reroll ---
@bot.tree.command(name="reroll", description="Reroll a giveaway winner (Admin only)")
@app_commands.describe(giveaway_id="The ID of the giveaway to reroll")
async def reroll(interaction: discord.Interaction, giveaway_id: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need **Administrator** permissions.", ephemeral=True)
        return

    if giveaway_id not in active_giveaways:
        await interaction.response.send_message("Giveaway ID not found or already ended.", ephemeral=True)
        return

    giveaway = active_giveaways[giveaway_id]
    participants = list(giveaway["participants"])
    if not participants:
        await interaction.response.send_message("No participants to choose from.", ephemeral=True)
        return

    new_winner_id = random.choice(participants)
    channel = interaction.guild.get_channel(giveaway["channel_id"])
    winner = interaction.guild.get_member(new_winner_id)
    await channel.send(f"🎉 Giveaway `{giveaway_id}` rerolled! New winner is {winner.mention}, congratulations!")
    await interaction.response.send_message("Reroll completed!", ephemeral=True)

# --- Run Bot ---
bot.run(TOKEN)
