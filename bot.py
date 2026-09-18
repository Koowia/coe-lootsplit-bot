import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import re
import os
from datetime import datetime

TOKEN = os.environ['TOKEN']
GOOGLE_SCRIPT_URL = os.environ['GOOGLE_SCRIPT_URL']
OFFICER_ROLE_IDS = [
    1531315951235240087,
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

nick_cache = set()


async def post_to_sheet(data, retries=3):
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    GOOGLE_SCRIPT_URL,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as response:
                    return await response.text()

        except asyncio.TimeoutError:
            if attempt < retries - 1:
                print(f"⏱️ Таймаут (попытка {attempt + 1}/{retries}), повторяю через 2 сек...")
                await asyncio.sleep(2)
            else:
                print("❌ Таймаут после 3 попыток")
                return "ERROR: Timeout"

        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            return f"ERROR: {e}"


async def update_cache():
    global nick_cache

    result = await post_to_sheet({"action": "get_all_nicks"})

    if result.startswith("ERROR"):
        print(f"⚠️ Ошибка загрузки кэша: {result}")
        return False

    data = json.loads(result)
    nicks = data.get("nicks", [])

    if not nicks:
        print("⚠️ Таблица вернула пустой список ников")
        return False

    nick_cache = set(n.lower() for n in nicks if n)
    print(f"✅ Кэш загружен")
    return True


def clean_nick(discord_nick: str) -> str:
    nick = re.sub(r'^\[.*?\]\s*', '', discord_nick)
    nick = re.sub(r'^!+\s*', '', nick)
    return nick.strip()


def is_officer(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True
    user_role_ids = [role.id for role in member.roles]
    return any(role_id in user_role_ids for role_id in OFFICER_ROLE_IDS)


@bot.event
async def on_ready():
    print(f"✅ Бот {bot.user} запущен!")
    await update_cache()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❌ Неизвестная команда",
            description=f"Команда `{ctx.message.content.split()[0]}` не существует",
            color=discord.Color.red()
        )
        embed.add_field(name="Что делать", value="Напиши `!help` чтобы увидеть список команд", inline=False)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Не хватает аргумента: `{error.param.name}`\nПример: `!split 30м @ник1, @ник2`")
    else:
        print(f"⚠️ Ошибка: {error}")


@bot.command(name="split")
async def split(ctx, amount: str, *, players: str):
    if not is_officer(ctx.author):
        embed = discord.Embed(
            title="🚫 Доступ запрещён",
            description="У вас нет доступа для данной команды",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    amount = amount.lower().replace('м', 'm')
    if 'm' in amount:
        total_amount = float(amount.replace('m', '')) * 1000000
    else:
        total_amount = float(amount)

    players = re.sub(r'<@!?(\d+)>', r'\1', players)
    nicks = list(dict.fromkeys([n.strip() for n in re.split(r'[,\s]+', players) if n.strip()]))

    if not nicks:
        await ctx.send("❌ Укажи участников! Пример: `!split 30м @ник1, @ник2`")
        return

    if not nick_cache:
        await update_cache()

    not_found = [n for n in nicks if n.lower() not in nick_cache]
    if not_found:
        embed = discord.Embed(
            title="❌ Операция отменена",
            description=f"Не найдены в таблице: {', '.join(not_found)}",
            color=discord.Color.red()
        )
        embed.add_field(name="Что делать", value="Проверь написание или добавь в таблицу. После добавления напиши `!reload`", inline=False)
        await ctx.send(embed=embed)
        return

    count = len(nicks)
    per_person = int(total_amount / count)

    msg = await ctx.send(f"⏳ Начисляю {count} игрокам...")

    players_data = [{"nick": n, "amount": per_person} for n in nicks]

    result = await post_to_sheet({
        "action": "add_batch",
        "players": players_data,
        "date": datetime.now().strftime("%d.%m.%Y"),
        "caller": ctx.author.name
    })

    if result == "OK":
        embed = discord.Embed(
            title="✅ Лут распределен!",
            description=f"**{ctx.author.display_name}** провел сплит",
            color=discord.Color.gold()
        )
        embed.add_field(name="Сумма к распределению", value=f"{total_amount:,.0f} 💰", inline=False)
        embed.add_field(name="На человека", value=f"**{per_person:,.0f}** 💵", inline=False)
        embed.add_field(name="Участников", value=f"{count} чел.", inline=True)
        embed.set_footer(text=f"CoE LootSplit • {datetime.now().strftime('%d.%m.%Y')}")
        await msg.edit(content="", embed=embed)
    else:
        await msg.edit(content=f"❌ Ошибка записи: {result}")


@bot.command(name="balance")
async def balance(ctx, *, nick: str = None):
    if nick is None:
        nick = clean_nick(ctx.author.display_name)

    nick = nick.replace("@", "").strip()

    if not nick_cache:
        await update_cache()

    if nick.lower() not in nick_cache:
        embed = discord.Embed(
            title="❌ Игрок не найден",
            description=f"Ник **{nick}** отсутствует в таблице",
            color=discord.Color.red()
        )
        embed.add_field(name="Возможные причины", value="• Опечатка в нике\n• Игрок не добавлен в таблицу\n• Другой ник в игре и Discord", inline=False)
        await ctx.send(embed=embed)
        return

    msg = await ctx.send("🔍 Запрашиваю баланс...")

    result = await post_to_sheet({"action": "get_balance", "nick": nick})

    if result.startswith("ERROR"):
        await msg.edit(content="❌ Ошибка связи с таблицей")
        return

    try:
        data = json.loads(result)
        if data.get("status") == "found":
            embed = discord.Embed(
                title=f"💼 Баланс: {data['nick']}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Текущий баланс", value=f"**{data['balance']:,.0f}** 💰", inline=False)
            await msg.edit(content="", embed=embed)
        else:
            await msg.edit(content=f"❌ Игрок **{nick}** не найден в таблице")
    except Exception:
        await msg.edit(content="❌ Ошибка обработки данных")


@bot.command(name="reload")
async def reload_cache(ctx):
    if not is_officer(ctx.author):
        return

    success = await update_cache()
    if success:
        await ctx.send("✅ Кэш обновлён")
    else:
        await ctx.send("❌ Не удалось обновить кэш")


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="📖 CoE LootSplit — Команды",
        color=discord.Color.dark_gold()
    )
    embed.add_field(
        name="💼 Баланс",
        value="`!balance [ник]` - для просмотра чужого баланса\n`!balance` - для просмотра своего баланса",
        inline=False
    )

    if is_officer(ctx.author):
        embed.add_field(
            name="💰 Распределить лут (только для офицеров)",
            value="`!split <сумма> <ники>`\nПримеры:\n`!split 24м @Artem, @Ivan`\n`!split 15000000 ник1 ник2`",
            inline=False
        )
        embed.add_field(
            name="🔄 Обновить кэш",
            value="`!reload` - обновить список ников из таблицы",
            inline=False
        )
        embed.color = discord.Color.gold()
        embed.set_footer(text="CoE LootSplit • Crown of Eteriy • Режим: Офицер")
    else:
        embed.set_footer(text="CoE LootSplit • Crown of Eteriy")

    await ctx.send(embed=embed)


bot.run(TOKEN)