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
DEFAULT_MUTED_ROLE_NAME = "Muted"
COMMANDS_DATA_FILE = "commands_data.json"
TICKETS_DATA_FILE = "tickets_data.json"
CONFIG_FILE = "config.json"
TICKET_CATEGORY_NAME = "Tickets"
SUPPORT_ROLES_FILE = "support_roles.json"
VERIFY_ROLES_FILE = "verify_roles.json"

server_configs = {}

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

def get_server_config(guild_id: int):
    if guild_id not in server_configs:
        server_configs[guild_id] = {
            'features': {
                'info': True,
                'kick': True,
                'ban': True,
                'timeout': True,
                'cursing': True,
                'spamming': True,
                'dm': True,
                'warn': True
            },
            'spam_timeout_minutes': 10,
            'curse_timeout_minutes': 5
        }
    return server_configs[guild_id]

def load_data():
    global prompt_messages, ticket_counter, active_tickets, ticket_claims, support_roles, verify_roles, server_configs
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
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config_data = json.load(f)
            server_configs = {int(k): v for k, v in config_data.items()}
    except FileNotFoundError:
        print("No config file found. Starting fresh.")
    except Exception as e:
        print(f"Error loading config: {e}")

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
    
    try:
        config_data = {str(k): v for k, v in server_configs.items()}
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

def can_manage_tickets(member: discord.Member, guild_id: int) -> bool:
    if member.guild_permissions.administrator:
        return True
    
    if guild_id in support_roles:
        for role_id in support_roles[guild_id]:
            if member.get_role(role_id):
                return True
    
    return False

async def get_or_create_muted_role(guild: discord.Guild) -> discord.Role:
    muted_role = discord.utils.get(guild.roles, name=DEFAULT_MUTED_ROLE_NAME)
    
    if not muted_role:
        try:
            muted_role = await guild.create_role(
                name=DEFAULT_MUTED_ROLE_NAME,
                reason="Auto-created for mute command",
                color=discord.Color.dark_gray()
            )
            
            for channel in guild.channels:
                try:
                    await channel.set_permissions(
                        muted_role,
                        send_messages=False,
                        add_reactions=False,
                        speak=False
                    )
                except:
                    pass
        except Exception as e:
            print(f"Error creating muted role: {e}")
            return None
    
    return muted_role

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

    guild_id = message.guild.id if message.guild else None
    if not guild_id:
        return
    
    config = get_server_config(guild_id)

    if config['features'].get('cursing') and message.guild:
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

                curse_timeout_minutes = config.get('curse_timeout_minutes', 5)
                timeout_until = discord.utils.utcnow() + datetime.timedelta(minutes=curse_timeout_minutes)
                await message.author.timeout(timeout_until, reason="Using inappropriate language")

                dm_embed = discord.Embed(
                    title="🚫 Timeout Notice",
                    description=f"You have been timed out in **{message.guild.name}** for using inappropriate language.",
                    color=discord.Color.red()
                )
                dm_embed.add_field(
                    name="Duration",
                    value=f"{curse_timeout_minutes} minutes",
                    inline=False
                )
                try:
                    await message.author.send(embed=dm_embed)
                except:
                    pass
            except Exception as e:
                print(f"Error handling bad words: {e}")

    if config['features'].get('spamming') and message.guild:
        user_id = message.author.id
        current_time = datetime.datetime.now()

        if user_id not in user_messages:
            user_messages[user_id] = deque(maxlen=SPAM_THRESHOLD)

        user_messages[user_id].append(current_time)

        if len(user_messages[user_id]) == SPAM_THRESHOLD:
            time_diff = (current_time - user_messages[user_id][0]).total_seconds()

            if time_diff <= SPAM_COOLDOWN:
                try:
                    spam_timeout_minutes = config.get('spam_timeout_minutes', 10)
                    timeout_until = discord.utils.utcnow() + datetime.timedelta(minutes=spam_timeout_minutes)
                    await message.author.timeout(timeout_until, reason="Spamming messages")

                    embed = discord.Embed(
                        title="🚫 Anti-Spam Protection",
                        description=f"{message.author.mention} has been timed out for spamming.",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="Duration",
                        value=f"{spam_timeout_minutes} minutes",
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

@bot.tree.command(name="feature", description="Enable or disable bot features (Admin only)")
@app_commands.describe(
    feature="The feature to toggle",
    enabled="True to enable, False to disable"
)
@app_commands.choices(feature=[
    app_commands.Choice(name="Info Command", value="info"),
    app_commands.Choice(name="Kick Command", value="kick"),
    app_commands.Choice(name="Ban Command", value="ban"),
    app_commands.Choice(name="Timeout Command", value="timeout"),
    app_commands.Choice(name="Cursing Detection", value="cursing"),
    app_commands.Choice(name="Spam Detection", value="spamming"),
    app_commands.Choice(name="DM Commands", value="dm"),
    app_commands.Choice(name="Warn Command", value="warn"),
])
@app_commands.checks.has_permissions(administrator=True)
async def feature(interaction: discord.Interaction, feature: str, enabled: bool):
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    
    config['features'][feature] = enabled
    save_data()
    
    status = "enabled" if enabled else "disabled"
    emoji = "✅" if enabled else "❌"
    
    embed = discord.Embed(
        title=f"{emoji} Feature {status.capitalize()}",
        description=f"The **{feature}** feature has been **{status}**.",
        color=discord.Color.green() if enabled else discord.Color.red()
    )
    embed.set_footer(text=f"Changed by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="config", description="Configure bot settings (Admin only)")
@app_commands.describe(
    setting="The setting to configure",
    value="The value in minutes"
)
@app_commands.choices(setting=[
    app_commands.Choice(name="Spam Timeout Duration", value="spam_timeout"),
    app_commands.Choice(name="Curse Timeout Duration", value="curse_timeout"),
])
@app_commands.checks.has_permissions(administrator=True)
async def config(interaction: discord.Interaction, setting: str, value: int):
    if value < 1 or value > 10080:
        await interaction.response.send_message("❌ Value must be between 1 and 10080 minutes (1 week).", ephemeral=True)
        return
    
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    
    setting_name = "Unknown Setting"
    if setting == "spam_timeout":
        config['spam_timeout_minutes'] = value
        setting_name = "Spam Timeout Duration"
    elif setting == "curse_timeout":
        config['curse_timeout_minutes'] = value
        setting_name = "Curse Timeout Duration"
    
    save_data()
    
    embed = discord.Embed(
        title="⚙️ Configuration Updated",
        description=f"**{setting_name}** has been set to **{value} minutes**.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Changed by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="mute", description="Mute a member by assigning them the Muted role (Admin only)")
@app_commands.describe(
    member="The member to mute",
    duration="Duration in minutes (optional)",
    reason="Reason for the mute"
)
@app_commands.checks.has_permissions(administrator=True)
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", duration: int = 0):
    if member.guild_permissions.administrator:
        await interaction.response.send_message("❌ You cannot mute an administrator.", ephemeral=True)
        return
    
    muted_role = await get_or_create_muted_role(interaction.guild)
    
    if not muted_role:
        await interaction.response.send_message("❌ Failed to create or find the Muted role.", ephemeral=True)
        return
    
    if muted_role in member.roles:
        await interaction.response.send_message(f"❌ {member.mention} is already muted.", ephemeral=True)
        return
    
    try:
        await member.add_roles(muted_role, reason=reason)
        
        embed = discord.Embed(
            title="🔇 Member Muted",
            description=f"{member.mention} has been muted.",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        if duration and duration > 0:
            embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
        embed.set_footer(text=f"Muted by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
        
        dm_embed = discord.Embed(
            title="🔇 You Have Been Muted",
            description=f"You have been muted in **{interaction.guild.name}**.",
            color=discord.Color.red()
        )
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        if duration and duration > 0:
            dm_embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
        
        try:
            await member.send(embed=dm_embed)
        except:
            pass
        
        if duration and duration > 0:
            await asyncio.sleep(duration * 60)
            if muted_role in member.roles:
                await member.remove_roles(muted_role, reason="Mute duration expired")
                
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to mute {member.mention}: {e}", ephemeral=True)

@bot.tree.command(name="unmute", description="Unmute a member by removing the Muted role (Admin only)")
@app_commands.describe(
    member="The member to unmute"
)
@app_commands.checks.has_permissions(administrator=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    muted_role = discord.utils.get(interaction.guild.roles, name=DEFAULT_MUTED_ROLE_NAME)
    
    if not muted_role:
        await interaction.response.send_message("❌ Muted role not found.", ephemeral=True)
        return
    
    if muted_role not in member.roles:
        await interaction.response.send_message(f"❌ {member.mention} is not muted.", ephemeral=True)
        return
    
    try:
        await member.remove_roles(muted_role, reason=f"Unmuted by {interaction.user.display_name}")
        
        embed = discord.Embed(
            title="🔊 Member Unmuted",
            description=f"{member.mention} has been unmuted.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Unmuted by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
        
        dm_embed = discord.Embed(
            title="🔊 You Have Been Unmuted",
            description=f"You have been unmuted in **{interaction.guild.name}**.",
            color=discord.Color.green()
        )
        
        try:
            await member.send(embed=dm_embed)
        except:
            pass
            
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to unmute {member.mention}: {e}", ephemeral=True)

@bot.tree.command(name="untimeout", description="Remove timeout from a member (Admin only)")
@app_commands.describe(
    member="The member to remove timeout from"
)
@app_commands.checks.has_permissions(administrator=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    if not member.is_timed_out():
        await interaction.response.send_message(f"❌ {member.mention} is not timed out.", ephemeral=True)
        return
    
    try:
        await member.timeout(None, reason=f"Timeout removed by {interaction.user.display_name}")
        
        embed = discord.Embed(
            title="⏰ Timeout Removed",
            description=f"Timeout has been removed from {member.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Removed by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
        
        dm_embed = discord.Embed(
            title="⏰ Timeout Removed",
            description=f"Your timeout in **{interaction.guild.name}** has been removed.",
            color=discord.Color.green()
        )
        
        try:
            await member.send(embed=dm_embed)
        except:
            pass
            
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to remove timeout: {e}", ephemeral=True)

@bot.tree.command(name="unban", description="Unban a user from the server (Admin only)")
@app_commands.describe(
    user_id="The ID of the user to unban"
)
@app_commands.checks.has_permissions(administrator=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user_id_int = int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid user ID. Please provide a valid Discord user ID.", ephemeral=True)
        return
    
    try:
        user = await bot.fetch_user(user_id_int)
        
        await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user.display_name}")
        
        embed = discord.Embed(
            title="✅ User Unbanned",
            description=f"**{user.name}** (ID: {user.id}) has been unbanned from the server.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Unbanned by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
        
    except discord.NotFound:
        await interaction.response.send_message("❌ User not found or not banned.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unban users.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to unban user: {e}", ephemeral=True)

@bot.tree.command(name="info", description="Display bot information and available commands")
async def info(interaction: discord.Interaction):
    guild_id = interaction.guild.id if interaction.guild else None
    if guild_id:
        config = get_server_config(guild_id)
        if not config['features'].get('info'):
            await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
            return
    
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
            "`/unban` - Unban a user by ID\n"
            "`/timeout` - Temporarily timeout a member\n"
            "`/untimeout` - Remove timeout from a member\n"
            "`/mute` - Mute a member with the Muted role\n"
            "`/unmute` - Unmute a member\n"
            "`/warn` - Issue a warning to a user\n"
            "`/clearwarnings` - Clear all warnings for a user\n"
            "`/checkwarnings` - Check warnings for a user"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Configuration Commands",
        value=(
            "`/feature` - Enable/disable bot features\n"
            "`/config` - Configure timeout durations\n"
            "`/addsupportrole` - Add support role for tickets\n"
            "`/removesupportrole` - Remove support role\n"
            "`/listsupportroles` - List all support roles"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎫 Ticket System",
        value=(
            "`/ticketpanel` - Create ticket panel\n"
            "`/closeticket` - Close current ticket"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🤖 AI Commands",
        value=(
            "`/ask` - Ask AI a question\n"
            "`/generate` - Generate creative content\n"
            "`/prompt` - Custom AI prompt"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🔧 Utility Commands",
        value=(
            "`/verify` - Verify yourself\n"
            "`/dm` - Send DM to a member\n"
            "`/sync` - Sync slash commands"
        ),
        inline=False
    )
    
    embed.set_footer(text="Use /help <command> for detailed information about a command")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kick", description="Kick a member from the server (Admin only)")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    if not config['features'].get('kick'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return
    
    if member.guild_permissions.administrator:
        await interaction.response.send_message("❌ You cannot kick an administrator.", ephemeral=True)
        return
    
    try:
        dm_embed = discord.Embed(
            title="👢 You Have Been Kicked",
            description=f"You have been kicked from **{interaction.guild.name}**.",
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        
        try:
            await member.send(embed=dm_embed)
        except:
            pass
        
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
        await interaction.response.send_message(f"❌ Failed to kick {member.mention}: {e}", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member from the server (Admin only)")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    if not config['features'].get('ban'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return
    
    if member.guild_permissions.administrator:
        await interaction.response.send_message("❌ You cannot ban an administrator.", ephemeral=True)
        return
    
    try:
        dm_embed = discord.Embed(
            title="🔨 You Have Been Banned",
            description=f"You have been banned from **{interaction.guild.name}**.",
            color=discord.Color.red()
        )
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        
        try:
            await member.send(embed=dm_embed)
        except:
            pass
        
        await member.ban(reason=reason, delete_message_days=0)
        
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{member.mention} has been banned from the server.",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Banned by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to ban {member.mention}: {e}", ephemeral=True)

@bot.tree.command(name="timeout", description="Timeout a member (Admin only)")
@app_commands.describe(
    member="The member to timeout",
    duration="Duration in minutes",
    reason="Reason for the timeout"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, duration: int, reason: str = "No reason provided"):
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    if not config['features'].get('timeout'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return
    
    if member.guild_permissions.administrator:
        await interaction.response.send_message("❌ You cannot timeout an administrator.", ephemeral=True)
        return
    
    if duration < 1 or duration > 40320:
        await interaction.response.send_message("❌ Duration must be between 1 and 40320 minutes (28 days).", ephemeral=True)
        return
    
    try:
        timeout_until = discord.utils.utcnow() + datetime.timedelta(minutes=duration)
        await member.timeout(timeout_until, reason=reason)
        
        embed = discord.Embed(
            title="⏰ Member Timed Out",
            description=f"{member.mention} has been timed out.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Timed out by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
        
        dm_embed = discord.Embed(
            title="⏰ You Have Been Timed Out",
            description=f"You have been timed out in **{interaction.guild.name}**.",
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        
        try:
            await member.send(embed=dm_embed)
        except:
            pass
            
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to timeout {member.mention}: {e}", ephemeral=True)

@bot.tree.command(name="warn", description="Warn a user (Admin only)")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    if not config['features'].get('warn'):
        await interaction.response.send_message("❌ This feature is currently disabled.", ephemeral=True)
        return
    
    user_id = member.id
    
    if user_id not in user_warnings:
        user_warnings[user_id] = []
    
    warning_data = {
        'reason': reason,
        'moderator': interaction.user.display_name,
        'timestamp': datetime.datetime.now().isoformat(),
        'guild_id': guild_id
    }
    
    user_warnings[user_id].append(warning_data)
    warning_count = len(user_warnings[user_id])
    
    embed = discord.Embed(
        title="⚠️ User Warned",
        description=f"{member.mention} has been warned.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=str(warning_count), inline=True)
    embed.set_footer(text=f"Warned by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    dm_embed = discord.Embed(
        title="⚠️ Warning Received",
        description=f"You have received a warning in **{interaction.guild.name}**.",
        color=discord.Color.orange()
    )
    dm_embed.add_field(name="Reason", value=reason, inline=False)
    dm_embed.add_field(name="Total Warnings", value=str(warning_count), inline=True)
    
    try:
        await member.send(embed=dm_embed)
    except:
        pass

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user (Admin only)")
@app_commands.checks.has_permissions(moderate_members=True)
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    user_id = member.id
    
    if user_id not in user_warnings or not user_warnings[user_id]:
        await interaction.response.send_message(f"❌ {member.mention} has no warnings.", ephemeral=True)
        return
    
    warning_count = len(user_warnings[user_id])
    user_warnings[user_id] = []
    
    embed = discord.Embed(
        title="✅ Warnings Cleared",
        description=f"Cleared {warning_count} warning(s) for {member.mention}.",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Cleared by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="checkwarnings", description="Check warnings for a user")
async def checkwarnings(interaction: discord.Interaction, member: discord.Member):
    user_id = member.id
    
    if user_id not in user_warnings or not user_warnings[user_id]:
        await interaction.response.send_message(f"✅ {member.mention} has no warnings.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"⚠️ Warnings for {member.display_name}",
        description=f"Total warnings: {len(user_warnings[user_id])}",
        color=discord.Color.orange()
    )
    
    for i, warning in enumerate(user_warnings[user_id][:10], 1):
        timestamp = warning.get('timestamp', 'Unknown')
        moderator = warning.get('moderator', 'Unknown')
        reason = warning.get('reason', 'No reason')
        
        embed.add_field(
            name=f"Warning #{i}",
            value=f"**Reason:** {reason}\n**By:** {moderator}\n**Date:** {timestamp[:10]}",
            inline=False
        )
    
    if len(user_warnings[user_id]) > 10:
        embed.set_footer(text=f"Showing 10 of {len(user_warnings[user_id])} warnings")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ask", description="Ask AI a question")
async def ask(interaction: discord.Interaction, question: str):
    await _send_ai_response(interaction, question, 'ask', 500, 0.7)

@bot.tree.command(name="generate", description="Generate creative content with AI")
async def generate(interaction: discord.Interaction, prompt: str):
    await _send_ai_response(interaction, prompt, 'generate', 800, 0.9)

@bot.tree.command(name="prompt", description="Send a custom prompt to AI")
async def prompt(interaction: discord.Interaction, prompt: str, max_tokens: int = 500, temperature: float = 0.7):
    if max_tokens < 1 or max_tokens > 2000:
        await interaction.response.send_message("❌ max_tokens must be between 1 and 2000.", ephemeral=True)
        return
    
    if temperature < 0 or temperature > 2:
        await interaction.response.send_message("❌ temperature must be between 0 and 2.", ephemeral=True)
        return
    
    await _send_ai_response(interaction, prompt, 'prompt', max_tokens, temperature)

@bot.tree.command(name="setverifyrole", description="Set the verification role for this server (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setverifyrole(interaction: discord.Interaction, role: discord.Role):
    guild_id = interaction.guild.id
    verify_roles[guild_id] = role.id
    save_data()
    
    embed = discord.Embed(
        title="✅ Verification Role Set",
        description=f"Verification role set to {role.mention}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="verify", description="Verify yourself to gain access to the server")
async def verify(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if guild_id in verify_roles:
        role = interaction.guild.get_role(verify_roles[guild_id])
    else:
        role = discord.utils.get(interaction.guild.roles, name=DEFAULT_VERIFY_ROLE_NAME)
    
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
    guild_id = interaction.guild.id
    config = get_server_config(guild_id)
    if not config['features'].get('dm'):
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
