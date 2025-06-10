import discord
from discord.ext import commands
import os
from datetime import datetime
import asyncio
import hashlib
import asyncpg
import json

# Конфигурация
TOKEN = os.getenv('DISCORD_TOKEN')
REGISTRATION_CHANNEL_ID = 1378013945687838853
LOGS_CHANNEL_ID = 1378379841555922994
PASSWORD_LOGS_CHANNEL_ID = 1378380786410983656
REQUIRED_ROLE_IDS = [1382036523511320710, 1382038519626858658, 1382038794886447236]
GIF_URL = 'https://media.discordapp.net/attachments/1182720165645918289/1183684888147279872/4242342343123.gif?ex=68493c75&is=6847eaf5&hm=7a345ec08313a491247d6bfc34729ab3c3e90e789f159953d9735e9bd478563e&=&width=440&height=248'

# PostgreSQL настройки
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'utopia_bot')
DB_USER = os.getenv('DB_USER', 'botuser')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'your_secure_password')


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


class DatabaseManager:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )

        # Создание таблицы пользователей
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    discord_id BIGINT PRIMARY KEY,
                    discord_name TEXT NOT NULL,
                    nickname TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    registered_at TIMESTAMP NOT NULL,
                    password_changed_at TIMESTAMP
                )
            ''')

    async def get_user(self, discord_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM users WHERE discord_id = $1', discord_id)

    async def user_exists(self, discord_id):
        user = await self.get_user(discord_id)
        return user is not None

    async def nickname_exists(self, nickname):
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow('SELECT 1 FROM users WHERE LOWER(nickname) = LOWER($1)', nickname)
            return result is not None

    async def create_user(self, discord_id, discord_name, nickname, password_hash):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (discord_id, discord_name, nickname, password, registered_at)
                VALUES ($1, $2, $3, $4, $5)
            ''', discord_id, discord_name, nickname, password_hash, datetime.now())

    async def update_password(self, discord_id, new_password_hash):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE users SET password = $1, password_changed_at = $2
                WHERE discord_id = $3
            ''', new_password_hash, datetime.now(), discord_id)


# Глобальный экземпляр БД
db = DatabaseManager()


class RegistrationModal(discord.ui.Modal, title='Регистрация в Utopia Studio'):
    nickname = discord.ui.TextInput(
        label='ВАШ НИКНЕЙМ?',
        placeholder='Этот ник будет в вашем мире',
        required=True,
        min_length=3,
        max_length=16
    )

    password = discord.ui.TextInput(
        label='ПРИДУМАЙТЕ ПАРОЛЬ',
        placeholder='Минимум 6 символов',
        required=True,
        min_length=6,
        max_length=32,
        style=discord.TextStyle.short
    )

    password_confirm = discord.ui.TextInput(
        label='ПОДТВЕРДИТЕ ПАРОЛЬ',
        placeholder='Повторите пароль',
        required=True,
        min_length=6,
        max_length=32,
        style=discord.TextStyle.short
    )

    agree = discord.ui.TextInput(
        label='ВЫ СОГЛАСНЫ С ПРАВИЛАМИ? (ДА/НЕТ)',
        placeholder='Напишите ДА или НЕТ',
        required=True,
        min_length=2,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Проверка паролей
        if self.password.value != self.password_confirm.value:
            await interaction.response.send_message('❌ Пароли не совпадают!', ephemeral=True)
            return

        # Проверка согласия
        if self.agree.value.upper() != 'ДА':
            await interaction.response.send_message('❌ Необходимо согласиться с правилами!', ephemeral=True)
            return

        # Проверка роли
        member = interaction.guild.get_member(interaction.user.id)
        if not any(role.id in REQUIRED_ROLE_IDS for role in member.roles):
            await interaction.response.send_message('❌ У вас нет подписки Boosty!', ephemeral=True)
            return

        # Проверка никнейма
        if await db.nickname_exists(self.nickname.value):
            await interaction.response.send_message('❌ Этот никнейм уже занят!', ephemeral=True)
            return

        # Проверка регистрации
        if await db.user_exists(interaction.user.id):
            await interaction.response.send_message('❌ Вы уже зарегистрированы!', ephemeral=True)
            return

        # Регистрация
        await db.create_user(
            interaction.user.id,
            str(interaction.user),
            self.nickname.value,
            hash_password(self.password.value)
        )

        await interaction.response.send_message('✅ Регистрация успешна! Теперь вы можете скачать лаунчер.',
                                                ephemeral=True)

        # Отправка лога
        logs_channel = interaction.guild.get_channel(LOGS_CHANNEL_ID)
        if logs_channel:
            embed = discord.Embed(
                title='📝 Новая регистрация',
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name='Discord', value=f'{interaction.user.mention} ({interaction.user})', inline=False)
            embed.add_field(name='Discord ID', value=str(interaction.user.id), inline=True)
            embed.add_field(name='Никнейм', value=self.nickname.value, inline=True)
            embed.add_field(name='Пароль (хеш)', value=f'||{hash_password(self.password.value)[:16]}...||',
                            inline=False)
            embed.add_field(name='Согласие с правилами', value=self.agree.value, inline=True)
            embed.add_field(name='Дата регистрации', value=datetime.now().strftime('%d.%m.%Y %H:%M:%S'), inline=True)
            embed.set_footer(text='Utopia Studio Registration System')

            await logs_channel.send(embed=embed)


class ChangePasswordModal(discord.ui.Modal, title='Смена пароля'):
    old_password = discord.ui.TextInput(
        label='ТЕКУЩИЙ ПАРОЛЬ',
        placeholder='Введите ваш текущий пароль',
        required=True,
        style=discord.TextStyle.short
    )

    new_password = discord.ui.TextInput(
        label='НОВЫЙ ПАРОЛЬ',
        placeholder='Минимум 6 символов',
        required=True,
        min_length=6,
        max_length=32,
        style=discord.TextStyle.short
    )

    new_password_confirm = discord.ui.TextInput(
        label='ПОДТВЕРДИТЕ НОВЫЙ ПАРОЛЬ',
        placeholder='Повторите новый пароль',
        required=True,
        min_length=6,
        max_length=32,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        user = await db.get_user(interaction.user.id)

        if not user:
            await interaction.response.send_message('❌ Вы не зарегистрированы!', ephemeral=True)
            return

        # Проверка старого пароля
        if user['password'] != hash_password(self.old_password.value):
            await interaction.response.send_message('❌ Неверный текущий пароль!', ephemeral=True)
            return

        # Проверка новых паролей
        if self.new_password.value != self.new_password_confirm.value:
            await interaction.response.send_message('❌ Новые пароли не совпадают!', ephemeral=True)
            return

        # Смена пароля
        old_hash = user['password']
        new_hash = hash_password(self.new_password.value)
        await db.update_password(interaction.user.id, new_hash)

        await interaction.response.send_message('✅ Пароль успешно изменен!', ephemeral=True)

        # Отправка лога
        logs_channel = interaction.guild.get_channel(PASSWORD_LOGS_CHANNEL_ID)
        if logs_channel:
            embed = discord.Embed(
                title='🔐 Смена пароля',
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name='Пользователь', value=f'{interaction.user.mention} ({interaction.user})', inline=False)
            embed.add_field(name='Discord ID', value=str(interaction.user.id), inline=True)
            embed.add_field(name='Никнейм', value=user['nickname'], inline=True)
            embed.add_field(name='Старый пароль (хеш)', value=f'||{old_hash[:16]}...||', inline=False)
            embed.add_field(name='Новый пароль (хеш)', value=f'||{new_hash[:16]}...||', inline=False)
            embed.add_field(name='Дата смены пароля', value=datetime.now().strftime('%d.%m.%Y %H:%M:%S'), inline=False)
            embed.set_footer(text='Utopia Studio Password Change System')

            await logs_channel.send(embed=embed)


class RegistrationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Регистрация', style=discord.ButtonStyle.primary, custom_id='register')
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegistrationModal())

    @discord.ui.button(label='Профиль', style=discord.ButtonStyle.secondary, custom_id='profile')
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = await db.get_user(interaction.user.id)

        if not user:
            await interaction.response.send_message('❌ Вы не зарегистрированы!', ephemeral=True)
            return

        embed = discord.Embed(
            title='👤 Ваш профиль',
            color=discord.Color.blue()
        )
        embed.add_field(name='Никнейм', value=user['nickname'], inline=True)
        embed.add_field(name='Discord', value=interaction.user.mention, inline=True)
        embed.add_field(name='Дата регистрации', value=user['registered_at'].strftime('%d.%m.%Y %H:%M:%S'),
                        inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label='Скачать лаунчер', style=discord.ButtonStyle.success, custom_id='download')
    async def download(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await db.user_exists(interaction.user.id):
            await interaction.response.send_message('❌ Сначала нужно зарегистрироваться!', ephemeral=True)
            return

        await interaction.response.send_message('📥 Ссылка на скачивание: https://example.com/launcher.exe',
                                                ephemeral=True)

    @discord.ui.button(label='Правила', style=discord.ButtonStyle.danger, custom_id='rules')
    async def rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title='📜 Правила Utopia Studio',
            description='1. Запрещено распространять файлы сборки\n2. Один аккаунт = один игрок\n3. Запрещено использовать читы\n4. Соблюдайте правила сервера',
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label='Сменить пароль', style=discord.ButtonStyle.secondary, custom_id='change_password')
    async def change_password(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangePasswordModal())


# Бот
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'{bot.user} запущен!')
    await db.connect()
    print('База данных подключена!')
    bot.add_view(RegistrationView())


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """Команда для установки сообщения с регистрацией"""
    embed = discord.Embed(
        title='Добро пожаловать в Utopia Studio',
        description='Здесь вы можете зарегистрироваться и просмотреть свой профиль',
        color=discord.Color.blue()
    )

    # Добавляем гифку
    embed.set_image(url=GIF_URL)

    view = RegistrationView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()


# API для лаунчера
@bot.command()
@commands.has_permissions(administrator=True)
async def api_info(ctx):
    """Показывает информацию для подключения лаунчера"""
    embed = discord.Embed(
        title='API информация',
        description=f'База данных: PostgreSQL\nХост: {DB_HOST}\nПорт: 5432\nБаза: {DB_NAME}',
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, delete_after=30)


bot.run(TOKEN)
