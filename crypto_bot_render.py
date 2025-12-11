# crypto_bot_render.py
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, List
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import json
import sys

# Configure logging for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Bot configuration - Render will provide the token via environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")
    sys.exit(1)

API_URL = "https://api.coingecko.com/api/v3"

# Available cryptocurrencies with their IDs
CRYPTO_OPTIONS = {
    "Bitcoin": "bitcoin",
    "Ethereum": "ethereum",
    "Solana": "solana",
    "Cardano": "cardano",
    "Dogecoin": "dogecoin",
    "Polkadot": "polkadot",
    "Avalanche": "avalanche-2",
    "Chainlink": "chainlink",
    "Litecoin": "litecoin",
    "Ripple": "ripple",
    "Binance Coin": "binancecoin",
    "Polygon": "matic-network",
    "Cosmos": "cosmos",
    "Uniswap": "uniswap"
}

# Update intervals in minutes
INTERVAL_OPTIONS = {
    "15 minutes": 15,
    "30 minutes": 30,
    "1 hour": 60,
    "3 hours": 180,
    "6 hours": 360,
    "12 hours": 720,
    "24 hours": 1440
}

# States for conversation
class UserStates(StatesGroup):
    choosing_coins = State()
    choosing_interval = State()
    setting_time = State()

# User data storage
user_data = {}

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone="UTC")

# Function to get cryptocurrency prices
async def get_crypto_prices(coins: List[str]) -> Dict:
    """Fetch current prices for given cryptocurrencies"""
    try:
        async with aiohttp.ClientSession() as session:
            coin_ids = ",".join(coins)
            url = f"{API_URL}/simple/price?ids={coin_ids}&vs_currencies=usd&include_24hr_change=true"
            
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"API error: {response.status}")
                    return {}
    except Exception as e:
        logger.error(f"Error fetching prices: {e}")
        return {}

# Function to create coin selection keyboard
def create_coin_selection_keyboard(selected_coins: List[str] = None) -> InlineKeyboardMarkup:
    """Create inline keyboard for selecting cryptocurrencies"""
    if selected_coins is None:
        selected_coins = []
    
    keyboard = []
    rows = []
    
    for i, (name, coin_id) in enumerate(CRYPTO_OPTIONS.items()):
        emoji = "✅" if coin_id in selected_coins else "⬜"
        button = InlineKeyboardButton(
            text=f"{emoji} {name}",
            callback_data=f"coin_{coin_id}"
        )
        
        if i % 3 == 0:
            rows.append([])
        rows[-1].append(button)
    
    keyboard.extend(rows)
    
    keyboard.append([
        InlineKeyboardButton(text="📊 Selected: {}".format(len(selected_coins)), callback_data="selected_count")
    ])
    keyboard.append([
        InlineKeyboardButton(text="✅ Done", callback_data="coins_done"),
        InlineKeyboardButton(text="🔄 Select All", callback_data="select_all"),
        InlineKeyboardButton(text="🗑️ Clear All", callback_data="clear_all")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Function to create interval selection keyboard
def create_interval_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for selecting update intervals"""
    keyboard = []
    
    for name, minutes in INTERVAL_OPTIONS.items():
        keyboard.append([
            InlineKeyboardButton(text=name, callback_data=f"interval_{minutes}")
        ])
    
    keyboard.append([
        InlineKeyboardButton(text="⏰ Custom Time", callback_data="custom_time"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Function to send price updates
async def send_price_update(user_id: int):
    """Send price update to a specific user"""
    try:
        if user_id not in user_data:
            return
        
        user = user_data[user_id]
        if not user.get('subscribed_coins'):
            return
        
        prices = await get_crypto_prices(user['subscribed_coins'])
        
        if not prices:
            await bot.send_message(user_id, "⚠️ Could not fetch prices at the moment. Please try again later.")
            return
        
        message = "📊 **Crypto Price Update**\n"
        message += f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
        
        for coin_id in user['subscribed_coins']:
            if coin_id in prices:
                price_data = prices[coin_id]
                coin_name = [k for k, v in CRYPTO_OPTIONS.items() if v == coin_id][0]
                price = price_data.get('usd', 0)
                change_24h = price_data.get('usd_24h_change', 0)
                
                change_emoji = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"
                message += f"**{coin_name}**: ${price:,.2f}\n"
                message += f"   24h: {change_emoji} {change_24h:+.2f}%\n\n"
        
        message += "\nUse /settings to modify your preferences."
        
        await bot.send_message(user_id, message, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error sending update to {user_id}: {e}")

# Start command handler
@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Handle /start command"""
    welcome_text = """
    🤖 **Welcome to Crypto Price Tracker Bot!**
    
    **Features:**
    • Track multiple cryptocurrencies
    • Set custom update intervals
    • Get real-time price updates
    
    **Available Commands:**
    /subscribe - Subscribe to crypto updates
    /unsubscribe - Stop all updates
    /settings - Manage your preferences
    /prices - Get current prices
    /list - List your subscriptions
    /help - Show this help message
    
    Get started with /subscribe!
    """
    
    await message.answer(welcome_text, parse_mode="Markdown")

# Subscribe command handler
@dp.message(Command("subscribe"))
async def subscribe_command(message: types.Message, state: FSMContext):
    """Handle /subscribe command"""
    user_id = message.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            'subscribed_coins': [],
            'update_interval': 60,
            'is_subscribed': False,
            'job_id': None
        }
    
    if user_data[user_id].get('is_subscribed'):
        await message.answer("⚠️ You are already subscribed! Use /settings to modify your preferences.")
        return
    
    await state.set_state(UserStates.choosing_coins)
    await message.answer(
        "📈 **Select cryptocurrencies to track:**\n\n"
        "Click on coins to select/deselect them.\n"
        "Press '✅ Done' when finished.",
        reply_markup=create_coin_selection_keyboard(),
        parse_mode="Markdown"
    )

# Coin selection callback handler
@dp.callback_query(F.data.startswith("coin_"))
async def coin_selection_callback(callback: types.CallbackQuery, state: FSMContext):
    """Handle coin selection"""
    user_id = callback.from_user.id
    coin_id = callback.data.split("_")[1]
    
    if user_id not in user_data:
        user_data[user_id] = {
            'subscribed_coins': [],
            'update_interval': 60,
            'is_subscribed': False,
            'job_id': None
        }
    
    if coin_id in user_data[user_id]['subscribed_coins']:
        user_data[user_id]['subscribed_coins'].remove(coin_id)
    else:
        user_data[user_id]['subscribed_coins'].append(coin_id)
    
    await callback.message.edit_reply_markup(
        reply_markup=create_coin_selection_keyboard(user_data[user_id]['subscribed_coins'])
    )
    await callback.answer()

# Action callbacks for coin selection
@dp.callback_query(F.data.in_(["coins_done", "select_all", "clear_all", "selected_count"]))
async def coin_action_callback(callback: types.CallbackQuery, state: FSMContext):
    """Handle coin selection actions"""
    user_id = callback.from_user.id
    
    if callback.data == "select_all":
        user_data[user_id]['subscribed_coins'] = list(CRYPTO_OPTIONS.values())
    elif callback.data == "clear_all":
        user_data[user_id]['subscribed_coins'] = []
    elif callback.data == "coins_done":
        if not user_data[user_id]['subscribed_coins']:
            await callback.answer("Please select at least one cryptocurrency!", show_alert=True)
            return
        
        await state.set_state(UserStates.choosing_interval)
        await callback.message.edit_text(
            "⏰ **Select update interval:**",
            reply_markup=create_interval_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    await callback.message.edit_reply_markup(
        reply_markup=create_coin_selection_keyboard(user_data[user_id]['subscribed_coins'])
    )
    await callback.answer()

# Interval selection callback handler
@dp.callback_query(F.data.startswith("interval_"))
async def interval_selection_callback(callback: types.CallbackQuery, state: FSMContext):
    """Handle interval selection"""
    user_id = callback.from_user.id
    interval_minutes = int(callback.data.split("_")[1])
    
    user_data[user_id]['update_interval'] = interval_minutes
    
    job_id = f"user_{user_id}"
    
    if user_data[user_id]['job_id']:
        try:
            scheduler.remove_job(user_data[user_id]['job_id'])
        except:
            pass
    
    scheduler.add_job(
        send_price_update,
        'interval',
        minutes=interval_minutes,
        args=[user_id],
        id=job_id,
        replace_existing=True
    )
    
    user_data[user_id]['job_id'] = job_id
    user_data[user_id]['is_subscribed'] = True
    
    interval_name = [k for k, v in INTERVAL_OPTIONS.items() if v == interval_minutes][0]
    
    await callback.message.edit_text(
        f"✅ **Subscription Activated!**\n\n"
        f"📊 **Coins tracked:** {len(user_data[user_id]['subscribed_coins'])}\n"
        f"⏰ **Update interval:** {interval_name}\n\n"
        f"You will receive updates automatically.\n"
        f"Use /prices to get current prices anytime.\n"
        f"Use /settings to modify your preferences.",
        parse_mode="Markdown"
    )
    
    await send_price_update(user_id)
    await state.clear()

# Custom time callback
@dp.callback_query(F.data == "custom_time")
async def custom_time_callback(callback: types.CallbackQuery, state: FSMContext):
    """Handle custom time selection"""
    await state.set_state(UserStates.setting_time)
    await callback.message.edit_text(
        "⏰ **Enter custom schedule**\n\n"
        "Format examples:\n"
        "• 'every 30 minutes'\n"
        "• 'every 2 hours'\n"
        "• 'daily at 09:00'\n"
        "• 'at 14:30' (today)\n\n"
        "Or use /cancel to go back.",
        parse_mode="Markdown"
    )

# Process custom time input
@dp.message(UserStates.setting_time)
async def process_custom_time(message: types.Message, state: FSMContext):
    """Process custom time input"""
    user_id = message.from_user.id
    text = message.text.lower()
    
    try:
        if text.startswith('every '):
            if 'minute' in text:
                minutes = int(text.split()[1])
            elif 'hour' in text:
                minutes = int(text.split()[1]) * 60
            else:
                raise ValueError("Invalid format")
            
            if minutes < 1:
                raise ValueError("Interval must be at least 1 minute")
            
            user_data[user_id]['update_interval'] = minutes
            
            job_id = f"user_{user_id}"
            if user_data[user_id]['job_id']:
                try:
                    scheduler.remove_job(user_data[user_id]['job_id'])
                except:
                    pass
            
            scheduler.add_job(
                send_price_update,
                'interval',
                minutes=minutes,
                args=[user_id],
                id=job_id,
                replace_existing=True
            )
            
            user_data[user_id]['job_id'] = job_id
            user_data[user_id]['is_subscribed'] = True
            
            await message.answer(
                f"✅ **Scheduled!**\n"
                f"Updates every {minutes} minutes.\n\n"
                f"Sending first update now...",
                parse_mode="Markdown"
            )
            
            await send_price_update(user_id)
        
        elif 'at ' in text:
            time_str = text.split('at ')[1].strip()
            
            if ':' in time_str:
                hour, minute = map(int, time_str.split(':'))
            else:
                hour, minute = int(time_str), 0
            
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("Invalid time")
            
            job_id = f"user_{user_id}_daily"
            if user_data[user_id]['job_id']:
                try:
                    scheduler.remove_job(user_data[user_id]['job_id'])
                except:
                    pass
            
            scheduler.add_job(
                send_price_update,
                'cron',
                hour=hour,
                minute=minute,
                args=[user_id],
                id=job_id,
                replace_existing=True
            )
            
            user_data[user_id]['job_id'] = job_id
            user_data[user_id]['is_subscribed'] = True
            
            await message.answer(
                f"✅ **Scheduled!**\n"
                f"Updates daily at {hour:02d}:{minute:02d} UTC.\n\n"
                f"Sending first update now...",
                parse_mode="Markdown"
            )
            
            await send_price_update(user_id)
        
        else:
            raise ValueError("Invalid format. Please use examples provided.")
        
        await state.clear()
        
    except Exception as e:
        await message.answer(
            f"❌ **Error:** {str(e)}\n\n"
            "Please use one of these formats:\n"
            "• 'every 30 minutes'\n"
            "• 'every 2 hours'\n"
            "• 'daily at 09:00'\n"
            "• 'at 14:30'",
            parse_mode="Markdown"
        )

# Unsubscribe command handler
@dp.message(Command("unsubscribe"))
async def unsubscribe_command(message: types.Message):
    """Handle /unsubscribe command"""
    user_id = message.from_user.id
    
    if user_id not in user_data or not user_data[user_id].get('is_subscribed'):
        await message.answer("❌ You are not subscribed to any updates.")
        return
    
    if user_data[user_id]['job_id']:
        try:
            scheduler.remove_job(user_data[user_id]['job_id'])
        except:
            pass
    
    user_data[user_id]['is_subscribed'] = False
    user_data[user_id]['job_id'] = None
    
    await message.answer(
        "✅ **Unsubscribed!**\n"
        "You will no longer receive automatic updates.\n"
        "Use /subscribe to start again.",
        parse_mode="Markdown"
    )

# Settings command handler
@dp.message(Command("settings"))
async def settings_command(message: types.Message):
    """Handle /settings command"""
    user_id = message.from_user.id
    
    if user_id not in user_data or not user_data[user_id].get('is_subscribed'):
        await message.answer(
            "⚠️ You are not subscribed yet.\n"
            "Use /subscribe to get started!",
            parse_mode="Markdown"
        )
        return
    
    user = user_data[user_id]
    
    coin_names = []
    for coin_id in user['subscribed_coins']:
        coin_name = [k for k, v in CRYPTO_OPTIONS.items() if v == coin_id][0]
        coin_names.append(coin_name)
    
    interval_name = "Custom"
    for name, minutes in INTERVAL_OPTIONS.items():
        if minutes == user['update_interval']:
            interval_name = name
            break
    
    settings_text = f"""
    ⚙️ **Your Settings**
    
    📊 **Tracking:** {len(coin_names)} coins
    ⏰ **Interval:** {interval_name}
    ✅ **Status:** {'Active' if user['is_subscribed'] else 'Inactive'}
    
    **Tracked Coins:**
    {', '.join(coin_names[:5])}
    {f'... and {len(coin_names) - 5} more' if len(coin_names) > 5 else ''}
    
    **Actions:**
    • /subscribe - Modify subscription
    • /unsubscribe - Stop updates
    • /prices - Get current prices
    """
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/subscribe"), KeyboardButton(text="/unsubscribe")],
            [KeyboardButton(text="/prices"), KeyboardButton(text="/list")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer(settings_text, parse_mode="Markdown", reply_markup=keyboard)

# Get current prices command
@dp.message(Command("prices"))
async def prices_command(message: types.Message):
    """Handle /prices command"""
    user_id = message.from_user.id
    
    coins_to_check = []
    if user_id in user_data and user_data[user_id].get('subscribed_coins'):
        coins_to_check = user_data[user_id]['subscribed_coins']
    else:
        coins_to_check = ['bitcoin', 'ethereum', 'solana', 'cardano', 'dogecoin']
    
    prices = await get_crypto_prices(coins_to_check)
    
    if not prices:
        await message.answer("⚠️ Could not fetch prices at the moment. Please try again later.")
        return
    
    message_text = "📊 **Current Crypto Prices**\n\n"
    
    for coin_id in coins_to_check:
        if coin_id in prices:
            price_data = prices[coin_id]
            coin_name = [k for k, v in CRYPTO_OPTIONS.items() if v == coin_id][0]
            price = price_data.get('usd', 0)
            change_24h = price_data.get('usd_24h_change', 0)
            
            change_emoji = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"
            message_text += f"**{coin_name}**: ${price:,.2f}\n"
            message_text += f"   24h: {change_emoji} {change_24h:+.2f}%\n\n"
    
    if user_id not in user_data or not user_data[user_id].get('is_subscribed'):
        message_text += "\n💡 Use /subscribe to get automatic updates!"
    
    await message.answer(message_text, parse_mode="Markdown")

# List subscriptions command
@dp.message(Command("list"))
async def list_command(message: types.Message):
    """Handle /list command"""
    user_id = message.from_user.id
    
    if user_id not in user_data or not user_data[user_id].get('subscribed_coins'):
        await message.answer("❌ You are not tracking any cryptocurrencies.")
        return
    
    coin_names = []
    for coin_id in user_data[user_id]['subscribed_coins']:
        coin_name = [k for k, v in CRYPTO_OPTIONS.items() if v == coin_id][0]
        coin_names.append(coin_name)
    
    list_text = f"📋 **Your Tracked Cryptocurrencies** ({len(coin_names)})\n\n"
    
    for i in range(0, len(coin_names), 3):
        group = coin_names[i:i+3]
        list_text += " • " + " | ".join(group) + "\n"
    
    list_text += f"\nUse /prices to get current prices.\n"
    list_text += f"Use /settings to modify your preferences."
    
    await message.answer(list_text, parse_mode="Markdown")

# Help command handler
@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Handle /help command"""
    help_text = """
    🤖 **Crypto Price Tracker Bot - Help**
    
    **Available Commands:**
    /start - Start the bot
    /subscribe - Subscribe to crypto updates
    /unsubscribe - Stop all updates
    /settings - View and manage your settings
    /prices - Get current prices of tracked/default coins
    /list - List all your tracked cryptocurrencies
    /help - Show this help message
    
    **Features:**
    • Track up to 15 different cryptocurrencies
    • Set automatic updates from 15 minutes to 24 hours
    • Set custom schedules (e.g., "daily at 09:00")
    • Real-time price updates with 24h changes
    
    **How to Subscribe:**
    1. Use /subscribe
    2. Select cryptocurrencies
    3. Choose update interval
    4. Receive automatic updates!
    
    **Need Help?**
    If you encounter any issues, try /unsubscribe and then /subscribe again.
    """
    
    await message.answer(help_text, parse_mode="Markdown")

# Cancel command handler
@dp.message(Command("cancel"))
async def cancel_command(message: types.Message, state: FSMContext):
    """Handle /cancel command"""
    current_state = await state.get_state()
    if current_state is None:
        return
    
    await state.clear()
    await message.answer("❌ Operation cancelled.", reply_markup=types.ReplyKeyboardRemove())

# Health check endpoint for Render
from aiohttp import web

async def health_check(request):
    return web.Response(text="Bot is running!")

async def run_bot():
    """Run the bot with web server for health checks"""
    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started")
    
    # Load existing data
    try:
        if os.path.exists("user_data.json"):
            with open("user_data.json", "r") as f:
                loaded_data = json.load(f)
                user_data.update({int(k): v for k, v in loaded_data.items()})
            logger.info(f"Loaded user data for {len(user_data)} users")
    except Exception as e:
        logger.error(f"Error loading user data: {e}")
    
    # Save user data periodically
    async def save_user_data():
        try:
            with open("user_data.json", "w") as f:
                json.dump(user_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving user data: {e}")
    
    scheduler.add_job(save_user_data, 'interval', minutes=5)
    
    # Start web server for health checks
    app = web.Application()
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("Health check server started on port 8080")
    
    # Start bot polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Check for required environment variable
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN environment variable is not set!")
        print("Please set it in Render environment variables.")
        sys.exit(1)
    
    print("🤖 Crypto Price Tracker Bot starting on Render...")
    print(f"Bot token: {'*' * 10}{BOT_TOKEN[-5:]}")
    
    # Run the bot
    asyncio.run(run_bot())
