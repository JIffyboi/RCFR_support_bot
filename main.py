import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
from datetime import datetime
import json
import asyncio

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='a')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[handler, logging.StreamHandler()]
)
logger = logging.getLogger('RCFR_Bot')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

CONFIG = {
    'TICKET_CATEGORY': 'Support',
    'SUPPORT_ROLE': 'Administrator',
    'LOG_CHANNEL': 'ticket-logs',
    'RCFR_COLOR': 0xffffff,
    'TICKET_TYPES': {
        'member_report': {'label': 'Member Report', 'color': 0x95a5a6},
        'cmd_report': {'label': 'Command Report', 'color': 0xe74c3c},
        'asset': {'label': 'Asset Protection', 'color': 0xe67e22},
        'materials': {'label': 'Issues with Materials', 'color': 0xe67e22},
        'general': {'label': 'General Support', 'color': 0xe67e22},
    }
}

active_tickets = {}


class TicketLogger:
    @staticmethod
    def log_ticket_event(guild, event_type, ticket_channel, user, **kwargs):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        log_entry = {
            'timestamp': timestamp,
            'event': event_type,
            'user': str(user),
            'user_id': user.id,
            'channel': ticket_channel.name if ticket_channel else 'N/A',
            'channel_id': ticket_channel.id if ticket_channel else 'N/A',
            **kwargs
        }
        logger.info(f"Ticket Event: {json.dumps(log_entry)}")

        log_channel = discord.utils.get(guild.channels, name=CONFIG['LOG_CHANNEL'])
        if log_channel:
            embed = discord.Embed(
                title=f"Ticket {event_type}",
                color=CONFIG['RCFR_COLOR'],
                timestamp=datetime.now()
            )
            embed.add_field(name="User", value=f"{user.mention} ({user})", inline=True)
            if ticket_channel:
                embed.add_field(name="Channel", value=ticket_channel.mention, inline=True)

            for key, value in kwargs.items():
                embed.add_field(name=key.replace('_', ' ').title(), value=value, inline=False)

            embed.set_footer(text="RCFR Ticket System")
            bot.loop.create_task(log_channel.send(embed=embed))

    @staticmethod
    async def save_transcript(channel):
        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            messages.append(f"[{timestamp}] {msg.author}: {msg.content}")
            if msg.attachments:
                for att in msg.attachments:
                    messages.append(f"    └─ Attachment: {att.url}")

        transcript = '\n'.join(messages)
        filename = f"transcripts/ticket_{channel.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        os.makedirs('transcripts', exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"RCFR Ticket Transcript\n")
            f.write(f"Channel: {channel.name}\n")
            f.write(f"Created: {channel.created_at}\n")
            f.write(f"{'=' * 50}\n\n")
            f.write(transcript)

        return filename


@bot.event
async def on_ready():
    logger.info(f'✅ RCFR Bot logged in as {bot.user}')
    print(f'✅ RCFR Ticket Bot is ready!')
    print(f'   Logged in as: {bot.user}')
    print(f'   Bot ID: {bot.user.id}')


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    embed = discord.Embed(
        title="River City Fire Support\n",
        description=(
            "Select the type of support you need below.\n\n"
            
            "**Member Report** - Report any violations of our code of conduct here.\n"
            "**Command Report** - Report any command members here.\n"
            "**Asset Protection** - Think RCFR material has been stolen or taken without permission? Report it here.\n"
            "**Issues with Materials** - If any issues occur or you notice anything that needs to be added/removed, report that here.\n"
            "**General Support** - Support for any general matter that you cannot find in FAQ or in our general chat.\n\n"
            "Click a button to create your ticket."
        ),
        color=CONFIG['RCFR_COLOR']
    )
    embed.set_footer(text="Any general support questions may be asked in any chat channel, though if the question is urgent, you may make a general support ticket")
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)

    view = TicketView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for ticket_type, info in CONFIG['TICKET_TYPES'].items():
            button = discord.ui.Button(
                label=info['label'],
                style=discord.ButtonStyle.primary,
                custom_id=f"ticket_{ticket_type}"
            )
            button.callback = self.create_ticket_callback(ticket_type, info)
            self.add_item(button)

    def create_ticket_callback(self, ticket_type, info):
        async def callback(interaction: discord.Interaction):
            await self.create_ticket(interaction, ticket_type, info)

        return callback

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str, info: dict):
        user_id = interaction.user.id

        if user_id in active_tickets:
            channel = interaction.guild.get_channel(active_tickets[user_id])
            if channel:
                await interaction.response.send_message(
                    f"❌ You already have an open ticket: {channel.mention}",
                    ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True)

        try:
            category = discord.utils.get(
                interaction.guild.categories,
                name=CONFIG['TICKET_CATEGORY']
            )
            if not category:
                category = await interaction.guild.create_category(CONFIG['TICKET_CATEGORY'])

            support_role = discord.utils.get(interaction.guild.roles, name=CONFIG['SUPPORT_ROLE'])

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True
                )
            }

            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

            ticket_channel = await interaction.guild.create_text_channel(
                name=f"{ticket_type}-{interaction.user.name}",
                category=category,
                overwrites=overwrites
            )

            active_tickets[user_id] = ticket_channel.id

            embed = discord.Embed(
                title=f"{info['label']}",
                description=(
                    f"Hello {interaction.user.mention}!\n\n"
                    f"Thank you for contacting RCFR Support.\n"
                    f"Please describe your issue in detail and our support team will assist you shortly.\n\n"
                    f"**Ticket Type:** {info['label']}\n"
                    f"**Created:** {discord.utils.format_dt(datetime.now(), 'F')}"
                ),
                color=info['color']
            )
            embed.set_footer(text="RCFR Support • Use the button below to close this ticket")

            close_view = CloseTicketView()
            await ticket_channel.send(
                content=f"{interaction.user.mention} {support_role.mention if support_role else ''}",
                embed=embed,
                view=close_view
            )

            TicketLogger.log_ticket_event(
                interaction.guild,
                "Created",
                ticket_channel,
                interaction.user,
                ticket_type=info['label']
            )

            await interaction.followup.send(
                f"✅ Ticket created! {ticket_channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            await interaction.followup.send(
                "❌ Failed to create ticket. Please contact an administrator.",
                ephemeral=True
            )


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CloseReasonModal()
        await interaction.response.send_modal(modal)


class CloseReasonModal(discord.ui.Modal, title="Close Ticket"):
    reason = discord.ui.TextInput(
        label="Reason for closing (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the reason for closing this ticket...",
        required=False,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel

        if not any(channel.name.startswith(ticket_type) for ticket_type in CONFIG['TICKET_TYPES'].keys()):
            await interaction.response.send_message(
                "❌ This command can only be used in ticket channels!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        transcript_file = await TicketLogger.save_transcript(channel)

        ticket_owner = None
        for user_id, ch_id in active_tickets.items():
            if ch_id == channel.id:
                ticket_owner = interaction.guild.get_member(user_id)
                del active_tickets[user_id]
                break

        close_reason = self.reason.value or "No reason provided"
        TicketLogger.log_ticket_event(
            interaction.guild,
            "Closed",
            channel,
            interaction.user,
            closed_by=str(interaction.user),
            reason=close_reason,
            transcript=transcript_file
        )

        embed = discord.Embed(
            title="Ticket Closing",
            description=f"This ticket is being closed by {interaction.user.mention}\n\n**Reason:** {close_reason}",
            color=0xe74c3c,
            timestamp=datetime.now()
        )
        embed.set_footer(text="RCFR Support • Channel will be deleted in 5 seconds")

        await channel.send(embed=embed)

        log_channel = discord.utils.get(interaction.guild.channels, name=CONFIG['LOG_CHANNEL'])
        if log_channel and os.path.exists(transcript_file):
            try:
                await log_channel.send(
                    f"📄 Transcript for {channel.name}",
                    file=discord.File(transcript_file)
                )
            except:
                pass

        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {interaction.user}")


@bot.event
async def on_connect():
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())


if __name__ == "__main__":
    bot.run(token, log_handler=handler, log_level=logging.DEBUG)