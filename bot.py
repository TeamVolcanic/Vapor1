import discord
from discord import app_commands
from discord.ext import commands
import os
import datetime
import re
import asyncio
import json
from collections import deque
from dotenv import load_dotenv
from openai import AsyncOpenAI
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False
import io

load_dotenv()

DEFAULT_VERIFY_ROLE_NAME = "🧑︱Member"
COMMANDS_DATA_FILE = "commands_data.json"
TICKETS_DATA_FILE = "tickets_data.json"
TICKET_CATEGORY_NAME = "Tickets"
SUPPORT_ROLES_FILE = "support_roles.json"
VERIFY_ROLES_FILE = "verify_roles.json"

FEATURE_STATUS = {
    'info': True,
    'kick': True,
    'ban': True,
    'timeout': True,
    'cursing': True,
    'spamming': True,
    'dm': True,
    'warn': True
}

BAD_WORDS = [
    "fuck", "fucking", "fucked", "fucker", "fck", "f*ck",
    "shit", "shitty", "shitting", "bullshit", "horseshit",
    "bitch", "bitching", "bastard", "asshole",
    "ass","dick", "cock", "penis", "pussy",
    "vagina", "cunt", "whore", "slut", "hoe", "prostitute",
    "nigger", "nigga", "negro", "n*gger", "n*gga",
    "fag", "faggot", "f*ggot", "dyke", "retard", "retarded",
    "terrorist", "rape", "raping", "rapist",
    "kill yourself", "kys", "suicide", "cancer", "aids",
    "holocaust", "dork", "nazi", "hitler", "slave", "slavery"
]

SPAM_THRESHOLD = 5
SPAM_COOLDOWN = 6
SPAM_TIMEOUT_DURATION = datetime.timedelta(minutes=10)
CURSING_TIMEOUT_DURATION = datetime.timedelta(minutes=5)
TICKET_COOLDOWN_DURATION = 60
MAX_DM_PER_WARN = 5
DM_DELAY = 0.5
MAX_EMBED_LENGTH = 4096

user_messages = {}
active_dm_tasks = {}
user_warnings = {}
user_dm_limits = {}
prompt_messages = {}
ticket_counter = {}
active_tickets = {}
ticket_claims = {}
support_roles = {}
ticket_cooldowns = {}
verify_roles = {}

BAD_WORDS_PATTERN = re.compile(
    r'(' + '|'.join(re.escape(word) for word in BAD_WORDS) + r')',
    re.IGNORECASE
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        
    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced!")

bot = MyBot()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY and GENAI_AVAILABLE:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_client = True
else:
    gemini_client = None

def load_data():
    global prompt_messages, ticket_counter, active_tickets, ticket_claims, support_roles, verify_roles
    try:
        with open(COMMANDS_DATA_FILE, 'r') as f:
            data = json.load(f)
            prompt_messages = {int(k): {int(mk): mv for mk, mv in v.items()} for k, v in data.items()}
    except FileNotFoundError:
        print("No command data file found. Starting fresh.")
    except Exception as e:
        print(f"Error loading command data: {e}")
    
    try:
        with open(TICKETS_DATA_FILE, 'r') as f:
            tickets_data = json.load(f)
            ticket_counter = {int(k): v for k, v in tickets_data.get('counter', {}).items()}
            active_tickets = {int(k): v for k, v in tickets_data.get('active', {}).items()}
            ticket_claims = {int(k): v for k, v in tickets_data.get('claims', {}).items()}
    except FileNotFoundError:
        print("No tickets data file found. Starting fresh.")
    except Exception as e:
        print(f"Error loading tickets data: {e}")
    
    try:
        with open(SUPPORT_ROLES_FILE, 'r') as f:
            support_roles_data = json.load(f)
            support_roles = {int(k): v for k, v in support_roles_data.items()}
    except FileNotFoundError:
        print("No support roles file found. Starting fresh.")
    except Exception as e:
        print(f"Error loading support roles: {e}")
    
    try:
        with open(VERIFY_ROLES_FILE, 'r') as f:
            verify_roles_data = json.load(f)
            verify_roles = {int(k): v for k, v in verify_roles_data.items()}
    except FileNotFoundError:
        print("No verify roles file found. Starting fresh.")
    except Exception as e:
        print(f"Error loading verify roles: {e}")

def save_data():
    try:
        data_to_save = {str(k): {str(mk): mv for mk, mv in v.items()} for k, v in prompt_messages.items()}
        with open(COMMANDS_DATA_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e:
        print(f"Error saving command data: {e}")
    
    try:
        tickets_data = {
            'counter': {str(k): v for k, v in ticket_counter.items()},
            'active': {str(k): v for k, v in active_tickets.items()},
            'claims': {str(k): v for k, v in ticket_claims.items()}
        }
        with open(TICKETS_DATA_FILE, 'w') as f:
            json.dump(tickets_data, f, indent=4)
    except Exception as e:
        print(f"Error saving tickets data: {e}")
    
    try:
        support_roles_data = {str(k): v for k, v in support_roles.items()}
        with open(SUPPORT_ROLES_FILE, 'w') as f:
            json.dump(support_roles_data, f, indent=4)
    except Exception as e:
        print(f"Error saving support roles: {e}")
    
    try:
        verify_roles_data = {str(k): v for k, v in verify_roles.items()}
        with open(VERIFY_ROLES_FILE, 'w') as f:
            json.dump(verify_roles_data, f, indent=4)
    except Exception as e:
        print(f"Error saving verify roles: {e}")

def can_manage_tickets(member: discord.Member, guild_id: int) -> bool:
    if member.guild_permissions.administrator:
        return True
    
    if guild_id in support_roles:
        for role_id in support_roles[guild_id]:
            if member.get_role(role_id):
                return True
    
    return False

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.green, custom_id="create_ticket", emoji="🎫")
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        user = interaction.user
        user_id = user.id
        guild_id = guild.id
        current_time = datetime.datetime.now().timestamp()
        
        if user_id in ticket_cooldowns:
            time_since_last = current_time - ticket_cooldowns[user_id]
            if time_since_last < TICKET_COOLDOWN_DURATION:
                remaining = int(TICKET_COOLDOWN_DURATION - time_since_last)
                await interaction.followup.send(
                    f"⏱️ Please wait {remaining} seconds before creating another ticket.",
                    ephemeral=True
                )
                return
        
        for channel_id in active_tickets.get(guild_id, []):
            channel = guild.get_channel(channel_id)
            if channel and user.id in [m.id for m in channel.members]:
                await interaction.followup.send(
                    f"❌ You already have an open ticket: {channel.mention}",
                    ephemeral=True
                )
                return
        
        if guild_id not in ticket_counter:
            ticket_counter[guild_id] = 0
        
        ticket_counter[guild_id] += 1
        ticket_number = ticket_counter[guild_id]
        ticket_name = f"ticket-{ticket_number:04d}"
        
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        if not category:
            try:
                category = await guild.create_category(TICKET_CATEGORY_NAME)
            except Exception as e:
                ticket_counter[guild_id] -= 1
                await interaction.followup.send(
                    f"❌ Failed to create ticket category: {e}",
                    ephemeral=True
                )
                return
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True
            )
        }
        
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True
                )
        
        if guild_id in support_roles:
            for role_id in support_roles[guild_id]:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        manage_messages=True
                    )
        
        try:
            ticket_channel = await guild.create_text_channel(
                name=ticket_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket created by {user.display_name} ({user.id})"
            )
            
            if guild_id not in active_tickets:
                active_tickets[guild_id] = []
            active_tickets[guild_id].append(ticket_channel.id)
            
            ticket_cooldowns[user_id] = current_time
            
            save_data()
            
            embed = discord.Embed(
                title="🎫 Ticket Created",
                description=f"Welcome {user.mention}! Please describe your issue and a staff member will assist you shortly.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Ticket Number",
                value=f"#{ticket_number:04d}",
                inline=True
            )
            embed.add_field(
                name="Created By",
                value=user.mention,
                inline=True
            )
            embed.add_field(
                name="Status",
                value="⏳ Unclaimed",
                inline=True
            )
            embed.set_footer(text="Staff: Use the buttons below to manage this ticket")
            
            view = TicketControlsView()
            await ticket_channel.send(embed=embed, view=view)
            
            await interaction.followup.send(
                f"✅ Ticket created: {ticket_channel.mention}",
                ephemeral=True
            )
            
        except Exception as e:
            ticket_counter[guild_id] -= 1
            await interaction.followup.send(
                f"❌ Failed to create ticket: {e}",
                ephemeral=True
            )

class TicketControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, custom_id="claim_ticket", emoji="✋")
    async def claim_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        ticket_id = interaction.channel.id
        
        if not can_manage_tickets(interaction.user, guild_id):
            await interaction.response.send_message(
                "❌ You don't have permission to claim tickets.",
                ephemeral=True
            )
            return
        
        if ticket_id in ticket_claims and ticket_claims[ticket_id]:
            current_claimer = interaction.guild.get_member(ticket_claims[ticket_id])
            if current_claimer:
                await interaction.response.send_message(
                    f"❌ This ticket is already claimed by {current_claimer.mention}",
                    ephemeral=True
                )
                return
        
        ticket_claims[ticket_id] = interaction.user.id
        save_data()
        
        embed = discord.Embed(
            title="✅ Ticket Claimed",
            description=f"{interaction.user.mention} is now handling this ticket.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
        
        async for msg in interaction.channel.history(limit=10):
            if msg.embeds and "Ticket Created" in msg.embeds[0].title:
                new_embed = msg.embeds[0]
                for i, field in enumerate(new_embed.fields):
                    if field.name == "Status":
                        new_embed.set_field_at(i, name="Status", value=f"✅ Claimed by {interaction.user.mention}", inline=True)
                await msg.edit(embed=new_embed)
                break

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        
        if not can_manage_tickets(interaction.user, guild_id):
            await interaction.response.send_message(
                "❌ You don't have permission to close tickets.",
                ephemeral=True
            )
            return
        
        channel = interaction.channel
        
        if guild_id in active_tickets and channel.id in active_tickets[guild_id]:
            embed = discord.Embed(
                title="🔒 Closing Ticket",
                description="This ticket will be deleted in 5 seconds...",
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Closed by {interaction.user.display_name}")
            
            await interaction.response.send_message(embed=embed)
            
            active_tickets[guild_id].remove(channel.id)
            if channel.id in ticket_claims:
                del ticket_claims[channel.id]
            save_data()
            
            await asyncio.sleep(5)
            await channel.delete(reason=f"Ticket closed by {interaction.user.display_name}")
        else:
            await interaction.response.send_message("❌ This is not an active ticket channel.", ephemeral=True)

@bot.event
async def on_ready():
    bot.start_time = discord.utils.utcnow()
    print(f'Bot is ready. Logged in as: {bot.user}')
    print(f'Bot ID: {bot.user.id}')
    print(f'Connected to {len(bot.guilds)} guild(s)')
    if not openai_client:
        print("⚠️  Warning: OPENAI_API_KEY not found. AI commands will not work.")
    load_data()
    print("Command data loaded.")
    
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlsView())
    print("Ticket views registered.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if FEATURE_STATUS.get('cursing') and message.guild:
        if BAD_WORDS_PATTERN.search(message.content):
            try:
                await message.delete()
                embed = discord.Embed(
                    title="⚠️ Inappropriate Language Detected",
                    description=f"{message.author.mention}, please keep the chat clean and respectful.",
                    color=discord.Color.orange()
                )
                bot_name = bot.user.name if bot.user else "Bot"
                embed.set_footer(text=f"Message deleted by {bot_name}")
                await message.channel.send(embed=embed, delete_after=5)

                timeout_until = discord.utils.utcnow() + CURSING_TIMEOUT_DURATION
                await message.author.timeout(timeout_until, reason="Using inappropriate language")

                dm_embed = discord.Embed(
                    title="🚫 Timeout Notice",
                    description=f"You have been timed out in **{message.guild.name}** for using inappropriate language.",
                    color=discord.Color.red()
                )
                dm_embed.add_field(
                    name="Duration",
                    value=f"{CURSING_TIMEOUT_DURATION.seconds // 60} minutes",
                    inline=False
                )
                try:
                    await message.author.send(embed=dm_embed)
                except:
                    pass
            except Exception as e:
                print(f"Error handling bad words: {e}")

    if FEATURE_STATUS.get('spamming') and message.guild:
        user_id = message.author.id
        current_time = datetime.datetime.now()

        if user_id not in user_messages:
            user_messages[user_id] = deque(maxlen=SPAM_THRESHOLD)

        user_messages[user_id].append(current_time)

        if len(user_messages[user_id]) == SPAM_THRESHOLD:
            time_diff = (current_time - user_messages[user_id][0]).total_seconds()

            if time_diff <= SPAM_COOLDOWN:
                try:
                    timeout_until = discord.utils.utcnow() + SPAM_TIMEOUT_DURATION
                    await message.author.timeout(timeout_until, reason="Spamming messages")

                    embed = discord.Embed(
                        title="🚫 Anti-Spam Protection",
                        description=f"{message.author.mention} has been timed out for spamming.",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="Duration",
                        value=f"{SPAM_TIMEOUT_DURATION.seconds // 60} minutes",
                        inline=False
                    )
                    await message.channel.send(embed=embed, delete_after=10)

                    user_messages[user_id].clear()
                except Exception as e:
                    print(f"Error handling spam: {e}")

def _check_ai_config(interaction):
    if not openai_client and not gemini_client:
        return False
    return True

async def _send_ai_response(interaction: discord.Interaction, prompt: str, ai_type: str, max_tokens: int, temperature: float):
    if not _check_ai_config(interaction):
        embed = discord.Embed(
            title="❌ Configuration Error",
            description="Neither OpenAI nor Gemini API key is configured. Please contact the bot administrator.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    await interaction.response.defer()
    
    answer = None
    ai_provider = None

    if openai_client:
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            answer = response.choices[0].message.content or "No response generated"
            ai_provider = "OpenAI"
        except Exception as e:
            print(f"OpenAI API Error: {e}")
            if not gemini_client:
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"Failed to generate response with OpenAI: {str(e)}",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

    if not answer and gemini_client and GENAI_AVAILABLE:
        try:
            model = genai.GenerativeModel("gemini-pro")
            response = model.generate_content(prompt)
            answer = response.text or "No response generated"
            ai_provider = "Gemini"
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to generate response with Gemini: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            print(f"Gemini API Error: {e}")
            return

    if not answer:
        return

    was_truncated = False
    if len(answer) > MAX_EMBED_LENGTH - 100:
        answer = answer[:MAX_EMBED_LENGTH - 103] + "..."
        was_truncated = True

    if ai_type == 'ask':
        color = discord.Color.blue()
    elif ai_type == 'generate':
        color = discord.Color.purple()
    elif ai_type == 'prompt':
        color = discord.Color.green()
    else:
        color = discord.Color.default()

    embed = discord.Embed(
        description=answer,
        color=color
    )
    embed.set_footer(text=f"Prompted by {interaction.user.display_name} • {ai_provider}")

    if was_truncated:
        embed.add_field(
            name="⚠️ Note",
            value="Response was truncated due to length limit",
            inline=False
        )

    response_msg = await interaction.followup.send(embed=embed)

    channel_id = interaction.channel_id
    message_id = response_msg.id

    if channel_id not in prompt_messages:
        prompt_messages[channel_id] = {}

    prompt_messages[channel_id][message_id] = {
        'type': ai_type,
        'user_id': interaction.user.id,
        'prompt': prompt
    }
    save_data()

@bot.tree.command(name="info", description="Display bot information and available commands")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Server Management Bot",
        description="A comprehensive Discord bot designed to help you manage your server efficiently with moderation tools, ticket systems, AI features, and automated protection.",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🛡️ Moderation Commands",
        value=(
            "`/kick` - Remove a member from the server\n"
            "`/ban` - Ban a member from the server\n"
            "`/timeout` - Temporarily timeout a member\n"
            "`/warn` - Issue a warning to a user\n"
            "`/clearwarnings` - Clear all warnings for a user\n"
            "`/checkwarnings` - Check warnings for a user"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎫 Ticket System",
        value=(
            "`/ticketpanel` - Create an interactive ticket panel\n"
            "`/closeticket` - Close the current ticket\n"
            "`/addsupportrole` - Add a support role for tickets\n"
            "`/removesupportrole` - Remove a support role\n"
            "`/listsupportroles` - List all support roles"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🤖 AI Commands",
        value=(
            "`/ask` - Ask the AI a question\n"
            "`/generate` - Generate creative text with AI (Admin)\n"
            "`/prompt` - Get a structured AI response (Admin)"
        ),
        inline=False
    )
    
    embed.add_field(
        name="✉️ Direct Messaging",
        value=(
            "`/dm` - Send a private message to a member (Admin)\n"
            "`/dmeveryone` - Broadcast a message to all members (Admin)"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📝 Custom Commands",
        value=(
            "`/setcommand` - Create a custom command (Admin)\n"
            "`/deletecommand` - Delete a custom command (Admin)\n"
            "`/listcommands` - View all custom commands"
        ),
        inline=False
    )
    
    embed.add_field(
        name="✅ Verification System",
        value=(
            "`/setupverify` - Set up member verification (Admin)\n"
            "`/verify` - Verify yourself to gain access"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛡️ Auto-Moderation Features",
        value=(
            "**Cursing Detection** - Automatically removes inappropriate language and times out offenders (5 min)\n"
            "**Spam Protection** - Detects and times out users who spam messages (10 min)\n"
            "**Real-time Protection** - Keeps your server safe 24/7"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Server Management",
        value="`/sync` - Sync slash commands to the server (Admin)",
        inline=False
    )
    
    embed.set_footer(text="Commands marked with (Admin) require Administrator permissions")
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ask", description="Ask the AI a question")
async def ask(interaction: discord.Interaction, question: str):
    await _send_ai_response(interaction, question, 'ask', 500, 0.7)

@bot.tree.command(name="generate", description="Generate creative text with AI (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def generate(interaction: discord.Interaction, prompt: str):
    await _send_ai_response(interaction, prompt, 'generate', 800, 0.9)

@bot.tree.command(name="prompt", description="Get a structured AI response (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def prompt_cmd(interaction: discord.Interaction, user_prompt: str):
    await _send_ai_response(interaction, user_prompt, 'prompt', 600, 0.8)

@bot.tree.command(name="setcommand", description="Set a custom command response (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setcommand(interaction: discord.Interaction, command_name: str, response_text: str):
    channel_id = interaction.channel_id
    
    if channel_id not in prompt_messages:
        prompt_messages[channel_id] = {}
    
    prompt_messages[channel_id][command_name] = {
        'type': 'custom',
        'user_id': interaction.user.id,
        'prompt': response_text
    }
    save_data()
    
    embed = discord.Embed(
        title="✅ Custom Command Created",
        description=f"Command `{command_name}` has been set!",
        color=discord.Color.green()
    )
    embed.add_field(name="Response", value=response_text[:1024], inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="deletecommand", description="Delete a custom command (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def deletecommand(interaction: discord.Interaction, command_name: str):
    channel_id = interaction.channel_id
    
    if channel_id in prompt_messages and command_name in prompt_messages[channel_id]:
        del prompt_messages[channel_id][command_name]
        save_data()
        
        embed = discord.Embed(
            title="✅ Custom Command Deleted",
            description=f"Command `{command_name}` has been removed.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Command `{command_name}` not found.", ephemeral=True)

@bot.tree.command(name="listcommands", description="List all custom commands")
async def listcommands(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    
    if channel_id not in prompt_messages or not prompt_messages[channel_id]:
        await interaction.response.send_message("❌ No custom commands found in this channel.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📝 Custom Commands",
        description="Here are all the custom commands in this channel:",
        color=discord.Color.blue()
    )
    
    for cmd_name, cmd_data in prompt_messages[channel_id].items():
        if isinstance(cmd_name, str) and cmd_data.get('type') == 'custom':
            response = cmd_data.get('prompt', 'No response')
            embed.add_field(
                name=f"`{cmd_name}`",
                value=response[:100] + "..." if len(response) > 100 else response,
                inline=False
            )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kick", description="Kick a member from the server (Admin only)")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not FEATURE_STATUS.get('kick'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return

    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ You cannot kick this member (role hierarchy).", ephemeral=True)
        return

    try:
        await member.kick(reason=reason)
        embed = discord.Embed(
            title="👢 Member Kicked",
            description=f"{member.mention} has been kicked from the server.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Kicked by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to kick member: {e}", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member from the server (Admin only)")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not FEATURE_STATUS.get('ban'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return

    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ You cannot ban this member (role hierarchy).", ephemeral=True)
        return

    try:
        await member.ban(reason=reason)
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{member.mention} has been banned from the server.",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Banned by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to ban member: {e}", ephemeral=True)

@bot.tree.command(name="timeout", description="Timeout a member (Admin only)")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, duration: int, reason: str = "No reason provided"):
    if not FEATURE_STATUS.get('timeout'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return

    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ You cannot timeout this member (role hierarchy).", ephemeral=True)
        return

    try:
        timeout_until = discord.utils.utcnow() + datetime.timedelta(minutes=duration)
        await member.timeout(timeout_until, reason=reason)
        
        embed = discord.Embed(
            title="⏱️ Member Timed Out",
            description=f"{member.mention} has been timed out.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Duration", value=f"{duration} minutes", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Timed out by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to timeout member: {e}", ephemeral=True)

@bot.tree.command(name="warn", description="Warn a user (Admin only)")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not FEATURE_STATUS.get('warn'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return

    user_id = member.id
    
    if user_id not in user_warnings:
        user_warnings[user_id] = []
    
    warning_data = {
        'reason': reason,
        'moderator': interaction.user.id,
        'timestamp': datetime.datetime.now().isoformat(),
        'guild_id': interaction.guild.id
    }
    
    user_warnings[user_id].append(warning_data)
    warning_count = len(user_warnings[user_id])
    
    embed = discord.Embed(
        title="⚠️ Warning Issued",
        description=f"{member.mention} has been warned.",
        color=discord.Color.yellow()
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=str(warning_count), inline=True)
    embed.set_footer(text=f"Warned by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    try:
        dm_embed = discord.Embed(
            title="⚠️ You have been warned",
            description=f"You received a warning in **{interaction.guild.name}**",
            color=discord.Color.yellow()
        )
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_embed.add_field(name="Total Warnings", value=str(warning_count), inline=True)
        await member.send(embed=dm_embed)
    except:
        pass

@bot.tree.command(name="checkwarnings", description="Check warnings for a user")
async def checkwarnings(interaction: discord.Interaction, member: discord.Member):
    user_id = member.id
    
    if user_id not in user_warnings or not user_warnings[user_id]:
        await interaction.response.send_message(f"✅ {member.mention} has no warnings.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"⚠️ Warnings for {member.display_name}",
        description=f"Total warnings: {len(user_warnings[user_id])}",
        color=discord.Color.yellow()
    )
    
    for i, warning in enumerate(user_warnings[user_id][:10], 1):
        moderator = interaction.guild.get_member(warning['moderator'])
        mod_name = moderator.display_name if moderator else "Unknown"
        timestamp = warning.get('timestamp', 'Unknown time')
        
        embed.add_field(
            name=f"Warning {i}",
            value=f"**Reason:** {warning['reason']}\n**By:** {mod_name}\n**Date:** {timestamp[:10]}",
            inline=False
        )
    
    if len(user_warnings[user_id]) > 10:
        embed.set_footer(text=f"Showing 10 of {len(user_warnings[user_id])} warnings")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    user_id = member.id
    
    if user_id in user_warnings:
        del user_warnings[user_id]
        
        embed = discord.Embed(
            title="✅ Warnings Cleared",
            description=f"All warnings for {member.mention} have been cleared.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"✅ {member.mention} has no warnings to clear.", ephemeral=True)

@bot.tree.command(name="setupverify", description="Setup verification system (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setupverify(interaction: discord.Interaction, role: discord.Role = None):
    guild_id = interaction.guild.id
    
    if role:
        verify_roles[guild_id] = role.id
        role_name = role.name
    else:
        existing_role = discord.utils.get(interaction.guild.roles, name=DEFAULT_VERIFY_ROLE_NAME)
        if not existing_role:
            try:
                existing_role = await interaction.guild.create_role(
                    name=DEFAULT_VERIFY_ROLE_NAME,
                    reason="Verification system setup"
                )
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to create verification role: {e}", ephemeral=True)
                return
        
        verify_roles[guild_id] = existing_role.id
        role_name = existing_role.name
    
    save_data()
    
    embed = discord.Embed(
        title="✅ Verification System Setup",
        description=f"Verification role set to: **{role_name}**\n\nUsers can now use `/verify` to get this role.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="verify", description="Verify yourself to gain access to the server")
async def verify(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if guild_id not in verify_roles:
        await interaction.response.send_message("❌ Verification system is not set up on this server.", ephemeral=True)
        return
    
    role = interaction.guild.get_role(verify_roles[guild_id])
    
    if not role:
        await interaction.response.send_message("❌ Verification role not found. Please contact an administrator.", ephemeral=True)
        return
    
    if role in interaction.user.roles:
        await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
        return
    
    try:
        await interaction.user.add_roles(role, reason="User verified")
        
        embed = discord.Embed(
            title="✅ Verification Successful",
            description=f"Welcome! You have been verified and received the {role.mention} role.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to verify: {e}", ephemeral=True)

@bot.tree.command(name="dm", description="Send a DM to a specific member (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def dm(interaction: discord.Interaction, member: discord.Member, message: str):
    if not FEATURE_STATUS.get('dm'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return
    
    try:
        embed = discord.Embed(
            title=f"📩 Message from {interaction.guild.name}",
            description=message,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Sent by {interaction.user.display_name}")
        await member.send(embed=embed)
        await interaction.response.send_message(f"✅ DM sent to {member.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"❌ Cannot send DM to {member.mention}. They may have DMs disabled.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send DM: {e}", ephemeral=True)

@bot.tree.command(name="dmeveryone", description="Send a DM to all server members (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def dmeveryone(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    members = [m for m in guild.members if not m.bot]
    
    if not members:
        await interaction.followup.send("❌ No members to send DMs to.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"📢 Announcement from {guild.name}",
        description=message,
        color=discord.Color.purple()
    )
    embed.set_footer(text=f"Sent by {interaction.user.display_name}")
    
    success_count = 0
    failed_count = 0
    
    status_embed = discord.Embed(
        title="📨 Sending DMs...",
        description=f"Sending to {len(members)} members...",
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=status_embed, ephemeral=True)
    
    for member in members:
        try:
            await member.send(embed=embed)
            success_count += 1
        except discord.Forbidden:
            failed_count += 1
        except Exception as e:
            print(f"Error sending DM to {member}: {e}")
            failed_count += 1
        finally:
            await asyncio.sleep(0.5)
    
    result_embed = discord.Embed(
        title="✅ DM Broadcast Complete",
        description=f"**Sent:** {success_count}\n**Failed:** {failed_count}",
        color=discord.Color.green()
    )
    await interaction.edit_original_response(embed=result_embed)

@bot.tree.command(name="ticketpanel", description="Create a ticket panel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Support Ticket System",
        description="Need help? Click the button below to create a support ticket!\n\n"
                    "**How it works:**\n"
                    "• Click the 'Create Ticket' button\n"
                    "• A private channel will be created for you\n"
                    "• Only you and admins can see your ticket\n"
                    "• Staff will assist you as soon as possible",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Tickets are private and only visible to you and staff")
    
    view = TicketPanelView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Ticket panel created!", ephemeral=True)

@bot.tree.command(name="closeticket", description="Close a ticket channel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def closeticket(interaction: discord.Interaction):
    channel = interaction.channel
    guild_id = interaction.guild.id
    
    if guild_id in active_tickets and channel.id in active_tickets[guild_id]:
        embed = discord.Embed(
            title="🔒 Closing Ticket",
            description="This ticket will be deleted in 5 seconds...",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Closed by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
        
        active_tickets[guild_id].remove(channel.id)
        if channel.id in ticket_claims:
            del ticket_claims[channel.id]
        save_data()
        
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {interaction.user.display_name}")
    else:
        await interaction.response.send_message("❌ This is not an active ticket channel.", ephemeral=True)

@bot.tree.command(name="addsupportrole", description="Add a role that can manage tickets (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def addsupportrole(interaction: discord.Interaction, role: discord.Role):
    guild_id = interaction.guild.id
    
    if guild_id not in support_roles:
        support_roles[guild_id] = []
    
    if role.id in support_roles[guild_id]:
        await interaction.response.send_message(f"❌ {role.mention} is already a support role.", ephemeral=True)
        return
    
    support_roles[guild_id].append(role.id)
    save_data()
    
    embed = discord.Embed(
        title="✅ Support Role Added",
        description=f"{role.mention} can now manage tickets!",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="removesupportrole", description="Remove a support role (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def removesupportrole(interaction: discord.Interaction, role: discord.Role):
    guild_id = interaction.guild.id
    
    if guild_id not in support_roles or role.id not in support_roles[guild_id]:
        await interaction.response.send_message(f"❌ {role.mention} is not a support role.", ephemeral=True)
        return
    
    support_roles[guild_id].remove(role.id)
    save_data()
    
    embed = discord.Embed(
        title="✅ Support Role Removed",
        description=f"{role.mention} can no longer manage tickets.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="listsupportroles", description="List all support roles (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def listsupportroles(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if guild_id not in support_roles or not support_roles[guild_id]:
        await interaction.response.send_message("❌ No support roles configured.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎫 Support Roles",
        description="The following roles can manage tickets:",
        color=discord.Color.blue()
    )
    
    roles_list = []
    for role_id in support_roles[guild_id]:
        role = interaction.guild.get_role(role_id)
        if role:
            roles_list.append(role.mention)
    
    if roles_list:
        embed.add_field(name="Roles", value="\n".join(roles_list), inline=False)
    else:
        embed.add_field(name="Roles", value="None (all roles have been deleted)", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sync", description="Sync slash commands to this server (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def sync(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
        
        synced = await bot.tree.sync(guild=interaction.guild)
        
        embed = discord.Embed(
            title="✅ Commands Synced",
            description=f"Successfully synced {len(synced)} commands to this server!\n\nAll slash commands should now be visible immediately.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Synced by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands: {e}", ephemeral=True)

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    print("❌ Error: DISCORD_TOKEN not found in environment variables.")
    print("Please set your Discord bot token in the .env file or secrets.")
    exit(1)

bot.run(DISCORD_TOKEN)
