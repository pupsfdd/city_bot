import os
import sqlite3
import time
import random
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from dotenv import load_dotenv
from help import HelpSystem

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')

# Все здания включая магазины
BUILDINGS = {
    # Основные здания
    "house": {"name": "🏠 Дом", "cost": 100, "income": 5, "type": "basic"},
    "apartment": {"name": "🏢 Многоэтажка", "cost": 500, "income": 30, "type": "basic"},
    "mall": {"name": "🏬 Торговый центр", "cost": 2000, "income": 120, "type": "basic"},
    
    # Магазины и бизнесы
    "supermarket": {"name": "🛒 Супермаркет", "cost": 1500, "income": 80, "type": "shop"},
    "gas_station": {"name": "⛽ АЗС", "cost": 2000, "income": 100, "type": "shop"},
    "bank": {"name": "🏦 Банк", "cost": 5000, "income": 250, "type": "shop"},
    "casino": {"name": "🎰 Казино", "cost": 8000, "income": 400, "type": "shop", "risk": True},
    "market": {"name": "🛒 Рынок", "cost": 3000, "income": 150, "type": "shop"},
    "bazaar": {"name": "🏪 Базар", "cost": 2500, "income": 120, "type": "shop"},
    "hotel": {"name": "🏨 Отель", "cost": 6000, "income": 300, "type": "shop"},
    "airport": {"name": "✈️ Аэропорт", "cost": 10000, "income": 500, "type": "shop"},
    
    # Украшения (социальные объекты)
    "park": {"name": "🌳 Парк", "cost": 300, "income": 10, "type": "decoration", "happiness": 15},
    "school": {"name": "🏫 Школа", "cost": 800, "income": 25, "type": "decoration", "happiness": 20},
    "kindergarten": {"name": "🎪 Детский сад", "cost": 600, "income": 20, "type": "decoration", "happiness": 18},
    "hospital": {"name": "🏥 Больница", "cost": 1500, "income": 40, "type": "decoration", "happiness": 25},
    "police": {"name": "🚓 Полиция", "cost": 1000, "income": 35, "type": "decoration", "happiness": 22}
}

REFERRAL_BONUS = 100

class CityBot:
    def __init__(self):
        self.conn = sqlite3.connect('city.db', check_same_thread=False)
        self.create_tables()
        self.help_system = HelpSystem()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        # Игроки
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 1000,
                happiness INTEGER DEFAULT 50,
                total_earned INTEGER DEFAULT 0,
                net_worth INTEGER DEFAULT 1000,
                last_income_time INTEGER
            )
        ''')
        # Здания
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                building_type TEXT,
                build_time INTEGER
            )
        ''')
        # Переводы (история)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                from_username TEXT,
                to_user_id INTEGER,
                to_username TEXT,
                amount INTEGER,
                transfer_time INTEGER
            )
        ''')
        # Рынок (продажа зданий)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                seller_username TEXT,
                building_id INTEGER,
                building_type TEXT,
                price INTEGER,
                created_time INTEGER,
                is_sold BOOLEAN DEFAULT FALSE
            )
        ''')
        self.conn.commit()
    
    def get_player(self, user_id, username):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO players (user_id, username, balance, last_income_time) VALUES (?, ?, 1000, ?)',
            (user_id, username, int(time.time()))
        )
        cursor.execute('SELECT * FROM players WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def get_player_by_username(self, username):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM players WHERE username = ?', (username,))
        return cursor.fetchone()
    
    def update_balance(self, user_id, amount):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE players SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?',
            (amount, max(amount, 0), user_id)
        )
        self.conn.commit()
    
    def update_net_worth(self, user_id):
        cursor = self.conn.cursor()
        player = self.get_player(user_id, "")
        buildings = self.get_player_buildings(user_id)
        
        building_worth = 0
        for building in buildings:
            b_type = building[2]
            if b_type in BUILDINGS:
                building_worth += BUILDINGS[b_type]["cost"]
        
        net_worth = player[2] + building_worth
        cursor.execute('UPDATE players SET net_worth = ? WHERE user_id = ?', (net_worth, user_id))
        self.conn.commit()
    
    def update_happiness(self, user_id, amount):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE players SET happiness = happiness + ? WHERE user_id = ?', (amount, user_id))
        self.conn.commit()
    
    def add_building(self, user_id, building_type):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO buildings (user_id, building_type, build_time) VALUES (?, ?, ?)',
            (user_id, building_type, int(time.time()))
        )
        building_id = cursor.lastrowid
        self.conn.commit()
        self.update_net_worth(user_id)
        return building_id
    
    def get_player_buildings(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM buildings WHERE user_id = ?', (user_id,))
        return cursor.fetchall()
    
    def get_building_by_id(self, building_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM buildings WHERE id = ?', (building_id,))
        return cursor.fetchone()
    
    def remove_building(self, building_id):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM buildings WHERE id = ?', (building_id,))
        self.conn.commit()
    
    # === РЫНОК ===
    def add_to_market(self, seller_id, seller_username, building_id, building_type, price):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO market (seller_id, seller_username, building_id, building_type, price, created_time) VALUES (?, ?, ?, ?, ?, ?)',
            (seller_id, seller_username, building_id, building_type, price, int(time.time()))
        )
        self.conn.commit()
    
    def get_market_offers(self, limit=10):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM market 
            WHERE is_sold = FALSE 
            ORDER BY created_time DESC 
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
    
    def buy_from_market(self, offer_id, buyer_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM market WHERE id = ? AND is_sold = FALSE', (offer_id,))
        offer = cursor.fetchone()
        
        if not offer:
            return False, "Предложение не найдено или уже продано"
        
        buyer = self.get_player(buyer_id, "")
        if buyer[2] < offer[5]:  # price
            return False, "Недостаточно средств"
        
        # Переводим здание новому владельцу
        cursor.execute('UPDATE buildings SET user_id = ? WHERE id = ?', (buyer_id, offer[3]))
        # Помечаем как проданное
        cursor.execute('UPDATE market SET is_sold = TRUE WHERE id = ?', (offer_id,))
        # Переводим деньги продавцу
        self.update_balance(offer[1], offer[5])  # seller_id, price
        self.update_balance(buyer_id, -offer[5])  # buyer_id, -price
        
        self.conn.commit()
        return True, f"✅ Куплено {BUILDINGS[offer[4]]['name']} за {offer[5]}¢!"
    
    def get_player_market_offers(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM market WHERE seller_id = ? AND is_sold = FALSE', (user_id,))
        return cursor.fetchall()
    
    def cancel_market_offer(self, offer_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM market WHERE id = ? AND seller_id = ?', (offer_id, user_id))
        offer = cursor.fetchone()
        
        if not offer:
            return False, "Предложение не найдено"
        
        cursor.execute('DELETE FROM market WHERE id = ?', (offer_id,))
        self.conn.commit()
        return True, "✅ Предложение снято с рынка"
    
    # === ПЕРЕВОДЫ ===
    def transfer_money(self, from_user_id, to_username, amount):
        if amount <= 0:
            return False, "Сумма должна быть положительной"
        
        from_player = self.get_player(from_user_id, "")
        to_player = self.get_player_by_username(to_username)
        
        if not to_player:
            return False, f"Игрок @{to_username} не найден"
        
        if from_user_id == to_player[0]:
            return False, "Нельзя переводить самому себе"
        
        if from_player[2] < amount:
            return False, "Недостаточно средств для перевода"
        
        self.update_balance(from_user_id, -amount)
        self.update_balance(to_player[0], amount)
        
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO transfers (from_user_id, from_username, to_user_id, to_username, amount, transfer_time) VALUES (?, ?, ?, ?, ?, ?)',
            (from_user_id, from_player[1], to_player[0], to_username, amount, int(time.time()))
        )
        self.conn.commit()
        return True, f"✅ Перевод {amount}¢ игроку @{to_username} выполнен!"
    
    # === FORBES ===
    def get_forbes_top(self, limit=10, by_net_worth=True):
        cursor = self.conn.cursor()
        if by_net_worth:
            cursor.execute('''
                SELECT username, net_worth, total_earned 
                FROM players 
                WHERE username IS NOT NULL
                ORDER BY net_worth DESC LIMIT ?
            ''', (limit,))
        else:
            cursor.execute('''
                SELECT username, total_earned, net_worth
                FROM players 
                WHERE username IS NOT NULL
                ORDER BY total_earned DESC LIMIT ?
            ''', (limit,))
        return cursor.fetchall()
    
    def get_player_rank(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) + 1 FROM players WHERE net_worth > (SELECT net_worth FROM players WHERE user_id = ?)', (user_id,))
        net_worth_rank = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) + 1 FROM players WHERE total_earned > (SELECT total_earned FROM players WHERE user_id = ?)', (user_id,))
        earned_rank = cursor.fetchone()[0]
        return net_worth_rank, earned_rank

    def calculate_city_stats(self, user_id):
        buildings = self.get_player_buildings(user_id)
        player = self.get_player(user_id, "")
        
        total_income = 0
        total_happiness = 50
        decoration_count = 0
        
        for building in buildings:
            b_type = building[2]
            if b_type in BUILDINGS:
                building_data = BUILDINGS[b_type]
                total_income += building_data["income"]
                
                if building_data["type"] == "decoration":
                    total_happiness += building_data["happiness"]
                    decoration_count += 1
        
        happiness_bonus = 1.0 + (total_happiness / 200)
        final_income = int(total_income * happiness_bonus)
        
        if player[3] != total_happiness:
            self.update_happiness(user_id, total_happiness - player[3])
        
        return {
            "base_income": total_income,
            "final_income": final_income,
            "happiness": min(total_happiness, 100),
            "happiness_bonus": happiness_bonus,
            "decorations": decoration_count
        }

    # === МЕНЮ ===
    def get_main_menu(self):
        keyboard = [
            [KeyboardButton("👤 Профиль"), KeyboardButton("🏗️ Строить")],
            [KeyboardButton("🛍️ Магазины"), KeyboardButton("🎨 Украсить")],
            [KeyboardButton("💰 Рынок"), KeyboardButton("🏢 Мои здания")],
            [KeyboardButton("🌍 Онлайн"), KeyboardButton("🎁 Пригласить друга")],
            [KeyboardButton("❓ Помощь")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    def get_build_menu(self):
        keyboard = [
            [InlineKeyboardButton("🏠 Дом (100¢)", callback_data="build_house")],
            [InlineKeyboardButton("🏢 Многоэтажка (500¢)", callback_data="build_apartment")],
            [InlineKeyboardButton("🏬 Торговый центр (2000¢)", callback_data="build_mall")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_shops_menu(self):
        keyboard = [
            [InlineKeyboardButton("🛒 Супермаркет (1500¢)", callback_data="build_supermarket")],
            [InlineKeyboardButton("⛽ АЗС (2000¢)", callback_data="build_gas_station")],
            [InlineKeyboardButton("🏦 Банк (5000¢)", callback_data="build_bank")],
            [InlineKeyboardButton("🎰 Казино (8000¢)", callback_data="build_casino")],
            [InlineKeyboardButton("🛒 Рынок (3000¢)", callback_data="build_market")],
            [InlineKeyboardButton("🏪 Базар (2500¢)", callback_data="build_bazaar")],
            [InlineKeyboardButton("🏨 Отель (6000¢)", callback_data="build_hotel")],
            [InlineKeyboardButton("✈️ Аэропорт (10000¢)", callback_data="build_airport")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_decorate_menu(self):
        keyboard = [
            [InlineKeyboardButton("🌳 Парк (300¢)", callback_data="build_park")],
            [InlineKeyboardButton("🏫 Школа (800¢)", callback_data="build_school")],
            [InlineKeyboardButton("🎪 Детсад (600¢)", callback_data="build_kindergarten")],
            [InlineKeyboardButton("🏥 Больница (1500¢)", callback_data="build_hospital")],
            [InlineKeyboardButton("🚓 Полиция (1000¢)", callback_data="build_police")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_online_menu(self):
        keyboard = [
            [InlineKeyboardButton("🏆 Топ Forbes", callback_data="show_forbes")],
            [InlineKeyboardButton("💰 Перевести деньги", callback_data="transfer_money")],
            [InlineKeyboardButton("👀 Посмотреть игроков", callback_data="view_players")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_market_menu(self):
        keyboard = [
            [InlineKeyboardButton("🛒 Купить здание", callback_data="market_buy")],
            [InlineKeyboardButton("💰 Продать здание", callback_data="market_sell")],
            [InlineKeyboardButton("📊 Мои предложения", callback_data="market_my_offers")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_forbes_menu(self):
        keyboard = [
            [InlineKeyboardButton("💰 По состоянию", callback_data="forbes_net_worth")],
            [InlineKeyboardButton("💵 По заработку", callback_data="forbes_earned")],
            [InlineKeyboardButton("🔙 Назад", callback_data="online_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    # === ОБРАБОТЧИКИ ===
    async def start(self, update: Update, context):
        user = update.effective_user
        self.get_player(user.id, user.username)
        
        await update.message.reply_text(
            f"🏙️ Привет, мэр {user.first_name}!\n"
            "Строй город, открывай бизнесы, торгуй на рынке и соревнуйся с другими игроками!",
            reply_markup=self.get_main_menu()
        )
    
    async def help_command(self, update: Update, context):
        await update.message.reply_text(
            "❓ **Центр помощи для мэров**\n\n"
            "Здесь вы найдете всю информацию о игре!\n"
            "Выберите раздел, который вас интересует:",
            reply_markup=self.help_system.get_help_menu()
        )
    
    async def handle_message(self, update: Update, context):
        text = update.message.text
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        
        if text == "👤 Профиль":
            player = self.get_player(user_id, username)
            city_stats = self.calculate_city_stats(user_id)
            net_rank, earned_rank = self.get_player_rank(user_id)
            
            profile_text = f"""
👤 **Профиль мэра {username}**

💰 **Баланс:** {player[2]}¢
😊 **Счастье:** {city_stats['happiness']}%
🎨 **Украшений:** {city_stats['decorations']}

🏗️ **Всего зданий:** {len(self.get_player_buildings(user_id))}
📈 **Доход/час:** {city_stats['final_income']}¢
✨ **Бонус счастья:** +{int((city_stats['happiness_bonus'] - 1) * 100)}%

🏆 **Рейтинг Forbes:**
   • По состоянию: #{net_rank}
   • По заработку: #{earned_rank}
            """.strip()
            
            await update.message.reply_text(profile_text)
        
        elif text == "🏗️ Строить":
            await update.message.reply_text("🏗️ **Основные здания:**", reply_markup=self.get_build_menu())
        
        elif text == "🛍️ Магазины":
            await update.message.reply_text("🛍️ **Магазины и бизнесы:**\nВысокий доход, но требуют инвестиций!", reply_markup=self.get_shops_menu())
        
        elif text == "🎨 Украсить":
            await update.message.reply_text("🎨 **Украсьте город:**", reply_markup=self.get_decorate_menu())
        
        elif text == "💰 Рынок":
            await update.message.reply_text("💰 **Рынок недвижимости:**\nПокупайте и продавайте здания!", reply_markup=self.get_market_menu())
        
        elif text == "🏢 Мои здания":
            buildings = self.get_player_buildings(user_id)
            if not buildings:
                await update.message.reply_text("🚧 У тебя пока нет построек!")
                return
            
            basic_count = sum(1 for b in buildings if BUILDINGS[b[2]]["type"] == "basic")
            shop_count = sum(1 for b in buildings if BUILDINGS[b[2]]["type"] == "shop")
            decoration_count = sum(1 for b in buildings if BUILDINGS[b[2]]["type"] == "decoration")
            
            buildings_text = f"🏢 **Твои здания:** {len(buildings)}\n\n"
            buildings_text += f"🏗️ Основных: {basic_count}\n"
            buildings_text += f"🛍️ Магазинов: {shop_count}\n"
            buildings_text += f"🎨 Украшений: {decoration_count}"
            
            await update.message.reply_text(buildings_text)
        
        elif text == "🌍 Онлайн":
            await update.message.reply_text("🌍 **Онлайн функции:**", reply_markup=self.get_online_menu())
        
        elif text == "🎁 Пригласить друга":
            await update.message.reply_text(
                f"👥 **Пригласи друга и получи {REFERRAL_BONUS}¢!**\n\n"
                f"`https://t.me/{(await context.bot.get_me()).username}?start=ref_{user_id}`",
                parse_mode='Markdown'
            )
        
        elif text == "❓ Помощь":await self.help_command(update, context)
    
    async def handle_callback(self, update: Update, context):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        username = query.from_user.username or query.from_user.first_name
        
        # Строительство
        if data.startswith("build_"):
            building_type = data.replace("build_", "")
            cost = BUILDINGS[building_type]["cost"]
            
            player = self.get_player(user_id, username)
            if player[2] >= cost:
                self.update_balance(user_id, -cost)
                building_id = self.add_building(user_id, building_type)
                
                building_data = BUILDINGS[building_type]
                message = f"✅ Построено {building_data['name']}!"
                
                if building_data["type"] == "decoration":
                    message += f"\n✨ Счастье города +{building_data['happiness']}%!"
                elif building_data.get("risk"):
                    message += f"\n🎰 **Внимание!** Казино может приносить убытки!"
                
                await query.edit_message_text(message)
            else:
                await query.edit_message_text("❌ Недостаточно денег!")
        
        # Навигация
        elif data == "main_menu":
            await query.edit_message_text("🏙️ **Главное меню**", reply_markup=self.get_main_menu())
        elif data == "online_menu":
            await query.edit_message_text("🌍 **Онлайн функции:**", reply_markup=self.get_online_menu())
        
        # Forbes
        elif data == "show_forbes":
            await query.edit_message_text("🏆 **Рейтинг Forbes:**", reply_markup=self.get_forbes_menu())
        elif data == "forbes_net_worth":
            top_players = self.get_forbes_top(10, True)
            forbes_text = "🏆 **Forbes - Топ по состоянию**\n\n"
            for i, (player_username, net_worth, earned) in enumerate(top_players, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                forbes_text += f"{medal} @{player_username}\n💰 {net_worth:,}¢\n\n"
            net_rank, earned_rank = self.get_player_rank(user_id)
            forbes_text += f"📊 **Ваша позиция:** #{net_rank}"
            await query.edit_message_text(forbes_text, reply_markup=self.get_forbes_menu())
        elif data == "forbes_earned":
            top_players = self.get_forbes_top(10, False)
            forbes_text = "💰 **Forbes - Топ по заработку**\n\n"
            for i, (player_username, earned, net_worth) in enumerate(top_players, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                forbes_text += f"{medal} @{player_username}\n💵 {earned:,}¢\n\n"
            net_rank, earned_rank = self.get_player_rank(user_id)
            forbes_text += f"📊 **Ваша позиция:** #{earned_rank}"
            await query.edit_message_text(forbes_text, reply_markup=self.get_forbes_menu())
        
        # Рынок
        elif data == "market_buy":
            offers = self.get_market_offers(5)
            if not offers:
                await query.edit_message_text("🛒 **Рынок пуст**\nПока нет предложений о продаже.", reply_markup=self.get_market_menu())
                return
            
            market_text = "🛒 **Предложения на рынке:**\n\n"
            keyboard = []
            for offer in offers:
                building_data = BUILDINGS[offer[4]]
                market_text += f"🏠 {building_data['name']}\n"
                market_text += f"   💰 {offer[5]}¢ | Продавец: @{offer[2]}\n"
                market_text += f"   🆔 ID: {offer[0]}\n\n"
                
                keyboard.append([InlineKeyboardButton(f"Купить {building_data['name']} - {offer[5]}¢", callback_data=f"buy_{offer[0]}")])
            
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="market_menu")])
            await query.edit_message_text(market_text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data == "market_sell":
            buildings = self.get_player_buildings(user_id)
            if not buildings:
                await query.edit_message_text("❌ У вас нет зданий для продажи!", reply_markup=self.get_market_menu())
                return
            
            context.user_data['waiting_sell'] = True
            await query.edit_message_text(
                "💰 **Продажа здания**\n\n"
                "Введите ID здания и цену в формате:\n"
                "`ID_здания цена`\n\n"
                "Пример: `15 1000`\n\n"
                "📊 **Ваши здания:**\n" +
                "\n".join([f"🏠 {BUILDINGS[b[2]]['name']} (ID: {b[0]})" for b in buildings[:10]]) +
                "\n\n💡 **Совет:** Цена должна быть разумной!",
                parse_mode='Markdown'
            )
        
        elif data == "market_my_offers":
            offers = self.get_player_market_offers(user_id)
            if not offers:
                await query.edit_message_text("📊 У вас нет активных предложений на рынке.", reply_markup=self.get_market_menu())
                return
            
            offers_text = "📊 **Ваши предложения:**\n\n"
            keyboard = []
            for offer in offers:
                building_data = BUILDINGS[offer[4]]
                offers_text += f"🏠 {building_data['name']}\n"
                offers_text += f"   💰 {offer[5]}¢ | ID: {offer[0]}\n\n"
                keyboard.append([InlineKeyboardButton(f"❌ Снять {building_data['name']}", callback_data=f"cancel_{offer[0]}")])
            
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="market_menu")])
            await query.edit_message_text(offers_text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data == "market_menu":
            await query.edit_message_text("💰 **Рынок недвижимости:**", reply_markup=self.get_market_menu())
        
        elif data.startswith("buy_"):
            offer_id = int(data.replace("buy_", ""))
            success, message = self.buy_from_market(offer_id, user_id)
            await query.edit_message_text(message, reply_markup=self.get_market_menu())
        
        elif data.startswith("cancel_"):
            offer_id = int(data.replace("cancel_", ""))
            success, message = self.cancel_market_offer(offer_id, user_id)
            await query.edit_message_text(message, reply_markup=self.get_market_menu())
        
        # Переводы
        elif data == "transfer_money":
            context.user_data['waiting_transfer'] = True
            await query.edit_message_text(
                "💰 **Перевод денег**\n\n"
                "Введите username и сумму в формате:\n"
                "`@username сумма`\n\n"
                "Пример: `@ivanov 500`",
                parse_mode='Markdown'
            )
        
        # Просмотр игроков
        elif data == "view_players":
            top_players = self.get_forbes_top(5, True)
            players_text = "👥 **Топ игроков:**\n\n"
            for i, (player_username, net_worth, earned) in enumerate(top_players, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                players_text += f"{medal} @{player_username}\n💰 {net_worth:,}¢\n\n"
            await query.edit_message_text(players_text, reply_markup=self.get_online_menu())
        
        # Помощь
        elif data.startswith("help_"):
            help_text = self.help_system.get_help_section(data)
            await query.edit_message_text(help_text, reply_markup=self.help_system.get_help_menu(), parse_mode='Markdown')
    
    async def handle_transfer(self, update: Update, context):
        user_id = update.effective_user.id
        text = update.message.text
        
        # Обработка переводов
        if 'waiting_transfer' in context.user_data:
            try:
                parts = text.split()
                if len(parts) == 2 and parts[0].startswith('@'):
                    to_username = parts[0][1:]
                    amount = int(parts[1])
                    
                    success, message = self.transfer_money(user_id, to_username, amount)
                    await update.message.reply_text(message)
                    context.user_data.pop('waiting_transfer', None)
                else:
                    await update.message.reply_text("❌ Неверный формат. Используйте: `@username 100`", parse_mode='Markdown')
            except ValueError:
                await update.message.reply_text("❌ Сумма должна быть числом")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        
        # Обработка продажи на рынке
        elif 'waiting_sell' in context.user_data:
            try:
                parts = text.split()
                if len(parts) == 2:
                    building_id = int(parts[0])
                    price = int(parts[1])
                    
                    building = self.get_building_by_id(building_id)
                    if not building or building[1] != user_id:
                        await update.message.reply_text("❌ Здание не найдено или не принадлежит вам!")
                        return
                    
                    if price <= 0:
                        await update.message.reply_text("❌ Цена должна быть положительной!")
                        return
                    
                    self.add_to_market(user_id, update.effective_user.username, building_id, building[2], price)
                    await update.message.reply_text(f"✅ {BUILDINGS[building[2]]['name']} выставлен на рынок за {price}¢!")
                    context.user_data.pop('waiting_sell', None)
                else:
                    await update.message.reply_text("❌ Неверный формат. Используйте: `ID_здания цена`")
            except ValueError:
                await update.message.reply_text("❌ ID и цена должны быть числами")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    def run(self):
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_transfer))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        print("Бот запущен! 🏙️")
        application.run_polling()

if __name__ == "__main__":
    bot = CityBot()
    bot.run()