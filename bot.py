import telebot
from telebot import types
import requests
import sqlite3
from bs4 import BeautifulSoup
import spacy
from collections import defaultdict
import nltk
from collections import Counter
from transformers import pipeline
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

# Модель для NER
ner_model = pipeline("ner", model="dbmdz/bert-large-cased-finetuned-conll03-english", aggregation_strategy="simple")

# Модель для устойчивых фраз
sentence_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')


# Инициализация spaCy
nlp = spacy.load("en_core_web_sm")

# Токен вашего Telegram-бота
TELEGRAM_BOT_TOKEN = "7561029395:AAFbgLJALnlvTBaCBSPvud_vYyunA_5qGm4"
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Подключение к базе данных SQLite
conn = sqlite3.connect("user_data.db", check_same_thread=False)
cursor = conn.cursor()

# Создание таблицы для хранения данных пользователей
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    age INTEGER,
    gender TEXT,
    city TEXT
)
""")
conn.commit()
# Проверяем, существует ли колонка 'experience' в таблице users
cursor.execute("PRAGMA table_info(users)")
columns = [column[1] for column in cursor.fetchall()]

if "experience" not in columns:
    # Создаем новую таблицу с нужной структурой
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users_new (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        age INTEGER,
        gender TEXT,
        city TEXT,
        experience TEXT DEFAULT 'Без опыта'
    )
    """)

    # Копируем данные из старой таблицы users в новую таблицу users_new
    cursor.execute("""
    INSERT INTO users_new (user_id, username, age, gender, city)
    SELECT user_id, username, age, gender, city FROM users
    """)

    # Удаляем старую таблицу
    cursor.execute("DROP TABLE users")

    # Переименовываем новую таблицу в старое имя
    cursor.execute("ALTER TABLE users_new RENAME TO users")

    conn.commit()
    print("Таблица обновлена: добавлена колонка 'experience'.")
else:
    print("Колонка 'experience' уже существует.")



# Клиентские данные для HeadHunter API
CLIENT_ID = "I8TPIQGON8FPDC33IRSUVPJ025SEUNUN8VTD0MJ0CDO3619F15GEQHD4HH9P2C2V"
CLIENT_SECRET = "NJ79LIGC58K27VSC015JGMFTB0LQQ5P9AFCA9EFFNTRT3T31D2D2KL3BIS7SMGKT"

# Переменные для хранения токена и срока его действия
ACCESS_TOKEN = None
TOKEN_EXPIRES_AT = 0

def get_access_token(client_id, client_secret):
    global ACCESS_TOKEN, TOKEN_EXPIRES_AT

    # Проверяем, истёк ли срок действия токена
    current_time = time.time()
    if ACCESS_TOKEN and current_time < TOKEN_EXPIRES_AT:
        return ACCESS_TOKEN

    url = "https://hh.ru/oauth/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    response = requests.post(url, data=data)
    print(response.text)  # Для диагностики выводим тело ответа
    if response.status_code == 200:
        token_data = response.json()
        ACCESS_TOKEN = token_data["access_token"]
        # Устанавливаем срок действия токена, вычитая дополнительное время для безопасности
        TOKEN_EXPIRES_AT = current_time + token_data.get("expires_in", 3600) - 60  # 60 секунд для безопасности
        return ACCESS_TOKEN
    else:
        raise Exception(f"Ошибка получения токена: {response.status_code}, {response.text}")

try:
    ACCESS_TOKEN = get_access_token(CLIENT_ID, CLIENT_SECRET)
except Exception as e:
    print(f"Не удалось получить токен доступа: {e}")
    ACCESS_TOKEN = None

# Функции для работы с базой данных

def save_user_data(user_id, username, age, gender, city, experience="Без опыта"):
    cursor.execute(
        """
        INSERT INTO users (user_id, username, age, gender, city, experience)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            age=excluded.age,
            gender=excluded.gender,
            city=excluded.city,
            experience=excluded.experience
        """,
        (user_id, username, age, gender, city, experience)
    )
    conn.commit()


def get_user_data(user_id):
    """
    Получает данные пользователя из базы данных.
    """
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()  # Возвращает кортеж

def clean_text_with_bs4(text):
    """
    Очищает текст от HTML-тегов с использованием BeautifulSoup.
    """
    soup = BeautifulSoup(text, "html.parser")
    cleaned_text = soup.get_text()
    return " ".join(cleaned_text.split())  # Убираем лишние пробелы

def parse_key_skills_selenium(vacancy_url):
    """
    Парсит ключевые навыки со страницы вакансии на HeadHunter с использованием Selenium.
    """
    # Настройки для Chrome
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")  # Запуск в фоновом режиме (без открытия окна браузера)
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    # Используем ChromeDriver из PATH
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Загрузка страницы вакансии
        driver.get(vacancy_url)
        time.sleep(5)  # Ждем загрузки страницы (можно настроить точнее)

        # Поиск блока с ключевыми навыками
        skills_block = driver.find_elements(By.CLASS_NAME, "vacancy-skill-list--JsTYRZ5o6dsoavK7")
        if not skills_block:
            print("Ключевые навыки не найдены.")
            return []

        # Извлечение текста навыков
        skills = []
        for skill in skills_block[0].find_elements(By.CLASS_NAME, "magritte-tag__label___YHV-o_3-0-25"):
            skills.append(skill.text.strip())

        return skills

    except Exception as e:
        print(f"Ошибка при парсинге: {e}")
        return []

    finally:
        driver.quit()  # Закрываем браузер

def process_vacancy(vac):
    """
    Обрабатывает данные одной вакансии, возвращая очищенные обязанности и ключевые навыки.
    """
    snippet = vac.get("snippet", {})
    description = snippet.get("responsibility", None)

    if description is None:
        print(f"Вакансия без описания: {vac.get('name', 'Без названия')}")
        return "Описание не указано.", []

    # Удаление HTML-тегов и очистка текста
    description = clean_text_with_bs4(description).strip()

    # Проверка длины текста
    if not description or len(description) < 10:
        return "Требования не указаны.", []

    # Извлекаем ключевые навыки из API
    key_skills = vac.get("key_skills", [])
    if key_skills:
        key_skills_list = [skill["name"] for skill in key_skills]
    else:
        # Если ключевые навыки не указаны в API, используем Selenium для парсинга
        vacancy_url = vac.get("alternate_url", "")
        if vacancy_url:
            key_skills_list = parse_key_skills_selenium(vacancy_url)
        else:
            key_skills_list = []

    return description, key_skills_list  # Возвращаем очищенный текст и ключевые навыки

def extract_key_phrases(text):
    """
    Извлекает ключевые фразы из текста, исключая стоп-слова, предлоги и союзы.
    """
    doc = nlp(text)
    phrases = []

    for token in doc:
        # Условие для извлечения только осмысленных слов:
        # Существительные, прилагательные, глаголы и исключаем стоп-слова
        if not token.is_stop and token.is_alpha and token.pos_ in {"NOUN", "ADJ", "VERB"}:
            phrases.append(token.text.lower())  # Сохраняем слово в нижнем регистре

    # Частотный анализ для ключевых слов
    word_freq = Counter(phrases)
    # Оставляем только топ-10 наиболее частых слов
    most_common_phrases = [f"{word} ({freq} упоминаний)" for word, freq in word_freq.most_common(20)]

    return ", ".join(most_common_phrases)


def extract_key_skills(vac):
    """
    Извлекает ключевые навыки из данных вакансии с учётом структуры API.
    """
    # Ключевые навыки обычно находятся в поле key_skills
    key_skills = vac.get("key_skills", [])

    if isinstance(key_skills, list) and key_skills:
        # Извлекаем название каждого ключевого навыка
        return ", ".join(skill.get("name", "Неизвестный навык") for skill in key_skills if "name" in skill)

    # Если поле key_skills пустое
    return "Ключевые навыки не указаны."


def fetch_vacancies(query, access_token, area, per_page=5, page=0, experience=None):
    """
    Получает вакансии с учетом уровня опыта.
    """
    url = "https://api.hh.ru/vacancies"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    params = {
        "text": query,
        "area": area,
        "per_page": per_page,
        "page": page,
    }

    # Если указан уровень опыта, добавляем его в параметры
    if experience:
        params["experience"] = experience

    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Ошибка API hh.ru: {response.status_code}, {response.text}")

def create_keyboard(buttons, one_time_keyboard=True, include_back=False, include_main_menu=False):
    """
    Создает клавиатуру с заданными кнопками, кнопкой "Назад" и "Главное меню".
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=one_time_keyboard)

    # Добавляем основные кнопки
    for button in buttons:
        if button == "Изменить данные":
            markup.add(types.KeyboardButton("🛠️ Изменить данные"))
        elif button == "Поиск вакансий":
            markup.add(types.KeyboardButton("🔎 Поиск вакансий"))
        elif button == "Анализ вакансий":
            markup.add(types.KeyboardButton("📈 Анализ вакансий"))
        elif button == "Помощь":
            markup.add(types.KeyboardButton("🆘 Помощь"))
        else:
            markup.add(types.KeyboardButton(button))

    # Добавляем кнопку "Назад", если нужно
    if include_back:
        markup.add(types.KeyboardButton("🔙 Назад"))

    # Добавляем кнопку "Главное меню", если нужно
    if include_main_menu:
        markup.add(types.KeyboardButton("🏠 Главное меню"))

    return markup

prompts = {
    "age": "Введите ваш возраст:",
    "gender": "Выберите ваш пол:",
    "city": "Введите ваш город:",
    "experience": "Укажите ваш опыт работы (например, 'Без опыта', '1-3 года', 'Более 3 лет'):"
}

options_for_field = {
    "gender": ["Мужской", "Женский"],
    "experience": ["Нет опыта", "От 1 года до 3 лет", "От 3 до 6 лет", "Более 6 лет"]
}

field_order = ["age", "gender", "city", "experience"]

def get_next_field(current_field):
    """
    Возвращает следующее поле для ввода.
    """
    index = field_order.index(current_field)
    if index < len(field_order) - 1:
        return field_order[index + 1]
    return None

def get_experience_levels(user_experience):
    """
    Возвращает список уровней опыта, которые нужно учитывать при поиске вакансий.
    """
    if user_experience == "between3And6":
        return ["noExperience", "between1And3", "between3And6"]
    elif user_experience == "between1And3":
        return ["noExperience", "between1And3"]
    elif user_experience == "moreThan6":
        return ["noExperience", "between1And3", "between3And6", "moreThan6"]
    elif user_experience == "noExperience":
        return ["noExperience"]
    else:
        return None  # Если опыт "Не имеет значения", то не фильтруем

def find_city_id(city, areas):
    """
    Рекурсивно ищет ID города в данных областей.
    """
    for area in areas:
        if area["name"].strip().lower() == city.strip().lower():
            return area["id"]
        # Если есть вложенные регионы, продолжаем поиск
        if "areas" in area and area["areas"]:
            result = find_city_id(city, area["areas"])
            if result:
                return result
    return None


def get_region_id(city):
    """
    Получает ID региона (города) по названию.
    """
    url = "https://api.hh.ru/areas"
    response = requests.get(url)
    if response.status_code == 200:
        areas = response.json()
        city_id = find_city_id(city, areas)
        if city_id:
            print(f"Город найден: {city}, ID региона: {city_id}")
            return city_id
        else:
            print(f"Город '{city}' не найден в данных API. Возвращаем значение по умолчанию (Москва).")
    else:
        print(f"Ошибка получения данных о регионах: {response.status_code}, {response.text}")

    return 1261  # ID Москвы по умолчанию


@bot.message_handler(commands=["start"])
def start_handler(message):
    """
    Приветственное сообщение и вывод кнопок.
    """
    user_data_entry = get_user_data(message.chat.id)
    markup = create_keyboard(["🛠️ Изменить данные", "🔎 Поиск вакансий", "📈 Анализ вакансий", "🆘 Помощь"], include_main_menu=False)

    if user_data_entry:
        _, username, age, gender, city, experience = user_data_entry
        bot.send_message(
            message.chat.id,
            f"Привет снова, {username}! Ваши данные:\n"
            f"🎂 Возраст: {age}\n👫 Пол: {gender}\n🏙️ Город: {city}\n📅 Опыт работы: {experience}\n\nВыберите действие:",
            reply_markup=markup
        )
    else:
        bot.send_message(
            message.chat.id,
            f"Приветствую, {message.from_user.username}! Давайте начнем знакомство. Введите ваш возраст.",
            reply_markup=markup
        )
        # Убедимся, что ask_next_step вызывается только один раз
        ask_next_step(
            message,
            {"user_id": message.chat.id, "username": message.from_user.username},
            prompts["age"],
            "age"
        )

@bot.message_handler(func=lambda message: message.text == "🆘 Помощь")
def handle_help_button(message):
    """
    Обрабатывает нажатие кнопки "🆘 Помощь".
    """
    help_command(message)  # Вызываем функцию help_command

@bot.message_handler(func=lambda message: message.text == "Изменить данные")
def handle_edit_data(message):
    """
    Обрабатывает запрос на изменение данных пользователя.
    """
    bot.send_message(
        message.chat.id,
        "Давайте обновим ваши данные. Сначала укажите ваш возраст."
    )
    bot.register_next_step_handler(message, update_age)

def update_age(message):
    try:
        age = int(message.text)
        user_data = get_user_data(message.chat.id)
        if not user_data:
            bot.send_message(message.chat.id, "Данные о вас не найдены. Используйте команду /start для начала.")
            return

        user_id, username, _, gender, city = user_data
        save_user_data(user_id, username, age, gender, city)
        bot.send_message(message.chat.id, "Возраст обновлён. Теперь укажите ваш пол.")
        bot.register_next_step_handler(message, update_gender)
    except ValueError:
        ask_next_step(message, user_data, prompts["age"], "age")

def tuple_to_dict(user_data_tuple):
    """
    Преобразует кортеж с данными пользователя в словарь.
    """
    if isinstance(user_data_tuple, tuple):
        return {
            "user_id": user_data_tuple[0],
            "username": user_data_tuple[1],
            "age": user_data_tuple[2],
            "gender": user_data_tuple[3],
            "city": user_data_tuple[4],
            "experience": user_data_tuple[5] if len(user_data_tuple) > 5 else "Без опыта"
        }
    return user_data_tuple  # Если это уже словарь, возвращаем как есть

@bot.message_handler(func=lambda message: message.text == "Изменить данные")

@bot.message_handler(func=lambda message: message.text == "🏠 Главное меню")
def handle_main_menu(message):
    """
    Обрабатывает нажатие кнопки "Главное меню".
    """
    user_data_entry = get_user_data(message.chat.id)
    markup = create_keyboard(["🛠️ Изменить данные", "🔎 Поиск вакансий", "📈 Анализ вакансий"], include_main_menu=False)

    if user_data_entry:
        _, username, age, gender, city, experience = user_data_entry
        bot.send_message(
            message.chat.id,
            f"Вы вернулись в главное меню, {username}!\n"
            f"Ваши данные:\n"
            f"🎂 Возраст: {age}\n👫 Пол: {gender}\n🏙️ Город: {city}\n📅 Опыт работы: {experience}\n\nВыберите действие:",
            reply_markup=markup
        )
    else:
        bot.send_message(
            message.chat.id,
            "Вы вернулись в главное меню. Пожалуйста, начните с команды /start.",
            reply_markup=markup
        )

@bot.message_handler(func=lambda message: message.text == "🛠️ Изменить данные")
def handle_edit_data(message):
    """
    Обрабатывает запрос на изменение данных пользователя.
    """
    bot.send_message(
        message.chat.id,
        "Давайте обновим ваши данные. Сначала укажите ваш возраст."
    )
    # Убираем вызов ask_next_step, так как он уже вызывается в handle_user_input
    bot.register_next_step_handler(
        message,
        lambda msg: handle_user_input(msg, {"user_id": message.chat.id, "username": message.from_user.username}, "age")
    )

def update_age(message):
    try:
        age = int(message.text)
        user_data = get_user_data(message.chat.id)
        if not user_data:
            bot.send_message(message.chat.id, "Данные о вас не найдены. Используйте команду /start для начала.")
            return

        user_id, username, _, gender, city = user_data
        save_user_data(user_id, username, age, gender, city)
        bot.send_message(message.chat.id, "Возраст обновлён. Теперь укажите ваш пол.")
        bot.register_next_step_handler(message, update_gender)
    except ValueError:
        ask_next_step(message, user_data, prompts["age"], "age")


def ask_next_step(message, user_data, prompt, field_name, options=None):
    """
    Универсальный обработчик ввода данных с кнопками "Назад" и "Главное меню".
    """
    # Определяем, нужно ли добавлять кнопку "Назад"
    include_back = field_name != "age"  # Кнопка "Назад" не нужна на первом шаге (возраст)

    # Определяем, нужно ли добавлять кнопку "Главное меню"
    include_main_menu = field_name == "experience"  # Кнопка "Главное меню" только на последнем шаге

    # Создаем клавиатуру
    markup = create_keyboard(
        options if options else [],
        include_back=include_back,
        include_main_menu=include_main_menu
    )

    # Добавляем смайлики к подсказкам
    if field_name == "age":
        prompt = "🎂 " + prompt
    elif field_name == "gender":
        prompt = "👫 " + prompt
    elif field_name == "city":
        prompt = "🏙️ " + prompt
    elif field_name == "experience":
        prompt = "📅 " + prompt

    bot.send_message(message.chat.id, prompt, reply_markup=markup)

    # Регистрируем следующий шаг
    bot.register_next_step_handler(
        message,
        lambda msg: handle_user_input(msg, user_data, field_name, options)
    )
def handle_user_input(message, user_data, field_name, options=None):
    """
    Обрабатывает ввод пользователя, включая кнопки "Назад" и "Главное меню".
    """
    # Преобразуем user_data в словарь, если это кортеж
    user_data = tuple_to_dict(user_data)

    input_value = message.text.strip()

    # Если пользователь нажал "Назад"
    if input_value == "🔙 Назад":
        previous_field = get_previous_field(field_name)
        if previous_field:
            ask_next_step(
                message,
                user_data,
                prompts[previous_field],
                previous_field,
                options_for_field.get(previous_field)
            )
        else:
            bot.send_message(message.chat.id, "Вы в начале анкеты. Назад вернуться нельзя.")
        return

    # Если пользователь нажал "Главное меню" (только на последнем шаге)
    if input_value == "🏠 Главное меню" and field_name == "experience":
        handle_main_menu(message)
        return

    # Обработка ввода данных
    if options and input_value not in options:
        ask_next_step(
            message,
            user_data,
            f"Пожалуйста, выберите из предложенных вариантов: {', '.join(options)}.",
            field_name,
            options
        )
        return

    user_data[field_name] = input_value
    if field_name == "age":
        try:
            user_data["age"] = int(input_value)
        except ValueError:
            ask_next_step(message, user_data, "Возраст должен быть числом. Введите снова:", "age")
            return

    if field_name == "city":
        area_id = get_region_id(input_value)
        if not area_id:
            ask_next_step(message, user_data, "Город не найден. Попробуйте снова:", "city")
            return
        user_data["area_id"] = area_id

    # Переход к следующему этапу
    next_field = get_next_field(field_name)
    if next_field:
        ask_next_step(message, user_data, prompts[next_field], next_field, options_for_field.get(next_field))
    else:
        # Сохранение данных
        save_user_data(
            user_id=user_data["user_id"],
            username=user_data["username"],
            age=user_data["age"],
            gender=user_data["gender"],
            city=user_data["city"],
            experience=user_data.get("experience", "Без опыта")
        )
        bot.send_message(message.chat.id, "Ваши данные успешно сохранены!")
def get_previous_field(current_field):
    """
    Возвращает предыдущее поле для навигации.
    """
    index = field_order.index(current_field)
    if index > 0:
        return field_order[index - 1]
    return None
def update_gender(message):
    gender = message.text
    if gender not in ["Мужской", "Женский"]:
        bot.send_message(message.chat.id, "Пожалуйста, выберите пол из предложенных: Мужской или Женский.")
        bot.register_next_step_handler(message, update_gender)
        return

    user_data = get_user_data(message.chat.id)
    if not user_data:
        bot.send_message(message.chat.id, "Данные о вас не найдены. Используйте команду /start для начала.")
        return

    user_id, username, age, _, city = user_data
    save_user_data(user_id, username, age, gender, city)
    bot.send_message(message.chat.id, "Пол обновлён. Теперь укажите ваш город.")
    bot.register_next_step_handler(message, update_city)

def update_city(message):
    city = message.text
    user_data = get_user_data(message.chat.id)
    if not user_data:
        bot.send_message(message.chat.id, "Данные о вас не найдены. Используйте команду /start для начала.")
        return

    user_id, username, age, gender, _ = user_data
    save_user_data(user_id, username, age, gender, city)
    bot.send_message(
        message.chat.id,
        f"Данные обновлены: возраст {age}, пол {gender}, город {city}. Вы можете использовать поиск или анализ вакансий."
    )
def update_experience(message):
    experience = message.text.strip()
    user_data = get_user_data(message.chat.id)
    if not user_data:
        bot.send_message(message.chat.id, "Данные о вас не найдены. Используйте команду /start для начала.")
        return

    user_id, username, age, gender, city, _ = user_data
    save_user_data(user_id, username, age, gender, city, experience)
    bot.send_message(message.chat.id, "Ваш опыт работы обновлён.")

experience_mapping = {
    "Нет опыта": "noExperience",
    "От 1 года до 3 лет": "between1And3",
    "От 3 до 6 лет": "between3And6",
    "Более 6 лет": "moreThan6"
}


@bot.message_handler(func=lambda message: message.text == "🔎 Поиск вакансий")
def handle_search_button(message):
    """
    Обрабатывает нажатие кнопки "🔎 Поиск вакансий".
    """
    bot.send_message(message.chat.id, "Введите вакансию, которую хотите найти.")
    bot.register_next_step_handler(message, search_command_no_command)

def search_command_no_command(message):
    """
    Обрабатывает текст запроса для поиска вакансий.
    """
    global ACCESS_TOKEN

    try:
        ACCESS_TOKEN = get_access_token(CLIENT_ID, CLIENT_SECRET)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка доступа к API: {e}")
        return

    query = message.text.strip()
    if not query:
        bot.send_message(message.chat.id, "Запрос не должен быть пустым. Попробуйте снова.")
        bot.register_next_step_handler(message, search_command_no_command)
        return

    try:
        user_data_entry = get_user_data(message.chat.id)
        if not user_data_entry:
            bot.send_message(message.chat.id, "Данные о пользователе не найдены. Пожалуйста, начните с команды /start.")
            return

        # Распаковываем все значения
        user_id, username, age, gender, city, experience = user_data_entry
        area_id = get_region_id(city)  # Получаем ID региона на основе города пользователя

        bot.send_message(message.chat.id, f"Ищем вакансии для {username} в городе {city}...")

        # Получаем уровни опыта для поиска
        user_experience = experience_mapping[experience]
        experience_levels = get_experience_levels(user_experience)

        # Собираем все вакансии
        all_vacancies = []
        for exp in experience_levels:
            page = 0
            while True:
                vacancies_data = fetch_vacancies(
                    query,
                    ACCESS_TOKEN,
                    area=area_id,
                    per_page=100,  # Увеличиваем количество вакансий на странице
                    page=page,
                    experience=exp
                )
                if not vacancies_data.get("items"):
                    break  # Если вакансий больше нет, выходим из цикла

                all_vacancies.extend(vacancies_data["items"])
                page += 1

                # Ограничим количество страниц для примера (можно убрать)
                if page >= 10:  # Например, не более 10 страниц
                    break

                # Задержка между запросами
                time.sleep(1)

        # Отображаем общее количество вакансий
        total_found = len(all_vacancies)
        bot.send_message(message.chat.id, f"Всего найдено вакансий: {total_found}.")

        # Проверяем, есть ли вакансии
        if not all_vacancies:
            bot.send_message(message.chat.id, "Вакансии не найдены.")
            return

        # Ограничиваем вывод до 10 вакансий
        vacancies_to_show = all_vacancies[:10]
        shown_count = len(vacancies_to_show)  # Количество показанных вакансий

        # Отправляем вакансии
        for vacancy in vacancies_to_show:
            description, key_skills_list = process_vacancy(vacancy)  # Распаковываем кортеж

            # Формируем сообщение с описанием вакансии
            vacancy_message = (
                f"🔍 Название: {vacancy['name']}\n"
                f"🏢 Компания: {vacancy['employer']['name']}\n"
                f"📝 Обязанности: {description}\n"
            )

            # Добавляем ключевые навыки (даже если их нет)
            if key_skills_list:
                vacancy_message += f"🔑 Ключевые навыки: {', '.join(key_skills_list)}\n"
            else:
                vacancy_message += "🔑 Ключевые навыки: Не указаны\n"

            # Добавляем ссылку на вакансию
            vacancy_message += f"🔗 Ссылка: {vacancy['alternate_url']}"

            # Отправляем сообщение
            bot.send_message(message.chat.id, vacancy_message)

        # Сообщаем, сколько вакансий показано
        bot.send_message(
            message.chat.id,
            f"Показано {shown_count} вакансий из {total_found}."
        )

    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "📈 Анализ вакансий")
def handle_analyze_button(message):
    """
    Обрабатывает нажатие кнопки "Анализ вакансий".
    """
    bot.send_message(message.chat.id, "Введите запрос для анализа вакансий, например: 'Python разработчик'.")
    bot.register_next_step_handler(message, analyze_query)

@bot.message_handler(commands=["help"])
def help_command(message):
    """
    Выводит список доступных команд и их описание.
    """
    help_text = (
        "🤖 *Доступные команды и кнопки:*\n\n"
        "▶️ */start* — Начать работу с ботом. Запускает процесс ввода данных (возраст, пол, город, опыт).\n\n"
        "🔍 */search* — Поиск вакансий. Введите запрос, например: '/search Python разработчик'.\n\n"
        "📊 */analyze* — Анализ вакансий. Введите запрос, например: '/analyze Python разработчик'.\n\n"
        "🛠️ *Изменить данные* — Обновить ваши данные (возраст, пол, город, опыт).\n\n"
        "🔎 *Поиск вакансий* — Найти вакансии по вашему запросу.\n\n"
        "📈 *Анализ вакансий* — Провести анализ вакансий по вашему запросу.\n\n"
        "🏠 *Главное меню* — Вернуться в главное меню.\n\n"
        "🆘 *Помощь* — Показать сообщение с описанием команд."
    )

    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")



def analyze_query(message):
    """
    Обрабатывает ввод запроса для анализа вакансий.
    """
    global ACCESS_TOKEN

    query = message.text.strip()
    if not query:
        bot.send_message(message.chat.id, "Пожалуйста, укажите корректный запрос.")
        return

    try:
        ACCESS_TOKEN = get_access_token(CLIENT_ID, CLIENT_SECRET)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка доступа к API: {e}")
        return

    try:
        user_data_entry = get_user_data(message.chat.id)
        if not user_data_entry:
            bot.send_message(message.chat.id, "Данные о пользователе не найдены. Пожалуйста, начните с команды /start.")
            return

        # Распаковываем все значения
        user_id, username, age, gender, city, _ = user_data_entry  # Опыт работы больше не учитывается
        area_id = get_region_id(city)

        bot.send_message(message.chat.id, f"Проводим анализ вакансий для {username} в городе {city}.")

        # Получаем первую страницу вакансий
        vacancies_data = fetch_vacancies(
            query,
            ACCESS_TOKEN,
            area=area_id,
            per_page=50,  # Количество вакансий на странице
            page=0,  # Начинаем с первой страницы
        )

        if not vacancies_data.get("items"):
            bot.send_message(message.chat.id, "Вакансии не найдены для анализа.")
            return

        # Получаем общее количество вакансий
        total_found = vacancies_data.get("found", 0)
        bot.send_message(message.chat.id, f"Всего найдено вакансий: {total_found}.")

        # Собираем данные о зарплате со всех страниц
        salaries = []  # Список для хранения зарплат и ссылок на вакансии
        page = 0

        while True:
            # Получаем вакансии для текущей страницы
            vacancies_data = fetch_vacancies(
                query,
                ACCESS_TOKEN,
                area=area_id,
                per_page=50,  # Количество вакансий на странице
                page=page,  # Текущая страница
            )

            if not vacancies_data.get("items"):
                break  # Если вакансий больше нет, выходим из цикла

            # Обрабатываем вакансии на текущей странице
            for vacancy in vacancies_data["items"]:
                # Извлекаем зарплату, если она указана в рублях
                salary_data = vacancy.get("salary")
                if salary_data and salary_data.get("currency") == "RUR":
                    min_salary = salary_data.get("from")
                    max_salary = salary_data.get("to")

                    # Если указана только минимальная или максимальная зарплата, используем её
                    if min_salary is not None or max_salary is not None:
                        # Сохраняем зарплату и ссылку на вакансию
                        salaries.append({
                            "min_salary": min_salary,
                            "max_salary": max_salary,
                            "url": vacancy.get("alternate_url", "Ссылка не указана")
                        })

            # Переходим к следующей странице
            page += 1

            # Ограничим количество страниц для примера (можно убрать)
            if page >= 40:  # Например, не более 20 страниц
                break

            # Задержка между запросами (чтобы не перегружать API)
            time.sleep(1)

        # Анализ зарплат
        if salaries:
            # Находим вакансии с самой маленькой и самой высокой зарплатой
            min_salary_vacancy = min(salaries, key=lambda x: x["min_salary"] or x["max_salary"])
            max_salary_vacancy = max(salaries, key=lambda x: x["max_salary"] or x["min_salary"])

            # Вычисляем минимальную, максимальную и среднюю зарплату
            min_salary_all = min(s["min_salary"] or s["max_salary"] for s in salaries)
            max_salary_all = max(s["max_salary"] or s["min_salary"] for s in salaries)
            avg_salary = sum((s["min_salary"] or 0 + s["max_salary"] or 0) / 2 for s in salaries) / len(salaries)

            # Выводим зарплаты и ссылки на вакансии
            bot.send_message(
                message.chat.id,
                f"💵 Зарплаты по вакансиям:\n"
                f"❎ Минимальная: {int(min_salary_all)} руб. (Ссылка: {min_salary_vacancy['url']})\n"
                f"✅ Максимальная: {int(max_salary_all)} руб. (Ссылка: {max_salary_vacancy['url']})\n"
                f"💰 Средняя: {int(avg_salary)} руб."
            )
        else:
            bot.send_message(
                message.chat.id,
                "💵 Зарплаты по вакансиям:\n"
                "❎Минимальная: Не указана\n"
                "✅Максимальная: Не указана\n"
                "💰 Средняя: Не указана"
            )

    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")

def analyze_texts(texts):
    """
    Анализирует тексты, извлекая частотные слова.
    """
    doc = nlp(" ".join(texts))
    word_freq = Counter(
        token.text.lower()
        for token in doc
        if token.is_alpha and not token.is_stop
    )
    return word_freq.most_common(10)


@bot.message_handler(func=lambda message: message.text == "🔎 Поиск вакансий")
def handle_search_button(message):
    user_data_entry = get_user_data(message.chat.id)
    if user_data_entry:
        _, username, age, gender, city, experience = user_data_entry
        bot.send_message(
            message.chat.id,
            f"Ваши данные:\n"
            f"Возраст: {age}\nПол: {gender}\nГород: {city}\nОпыт работы: {experience}\n\nВведите вакансию, которую хотите найти."
        )
        bot.register_next_step_handler(message, search_command_no_command)
    else:
        bot.send_message(message.chat.id, "Данные о вас не найдены. Используйте команду /start для начала.")



def is_vacancy_suitable(vacancy_experience, user_experience):
    """
    Проверяет, подходит ли вакансия по опыту.
    """
    # Опыт пользователя и вакансии в виде числовых значений для сравнения
    experience_levels = {
        "noExperience": 0,  # Без опыта
        "between1And3": 1,  # 1-3 года
        "between3And6": 2,  # 3-6 лет
        "moreThan6": 3      # Более 6 лет
    }

    # Если опыт вакансии не указан, считаем, что она подходит
    if not vacancy_experience:
        return True

    # Получаем уровни опыта для пользователя и вакансии
    user_level = experience_levels.get(user_experience, 0)
    vacancy_level = experience_levels.get(vacancy_experience, 0)

    # Вакансия подходит, если её требуемый опыт меньше или равен опыту пользователя
    return vacancy_level <= user_level

def filter_vacancies_by_experience(vacancies, user_experience):
    """
    Фильтрует вакансии по опыту пользователя.
    """
    filtered_vacancies = []
    for vacancy in vacancies:
        vacancy_experience = vacancy.get("experience", {}).get("id", None)
        print(f"Вакансия: {vacancy['name']}, Опыт: {vacancy_experience}")  # Отладочная информация
        if is_vacancy_suitable(vacancy_experience, user_experience):
            filtered_vacancies.append(vacancy)
    return filtered_vacancies

@bot.message_handler(commands=["search"])
def search_command(message):
    """
    Обрабатывает запрос на поиск вакансий.
    """
    global ACCESS_TOKEN
    try:
        ACCESS_TOKEN = get_access_token(CLIENT_ID, CLIENT_SECRET)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка доступа к API: {e}")
        return

    query = message.text.replace("/search", "").strip()
    if not query:
        bot.send_message(message.chat.id,
                         "Пожалуйста, укажите запрос. Например: '/search Информационная безопасность'.")
        return

    try:
        user_data_entry = get_user_data(message.chat.id)
        if not user_data_entry:
            bot.send_message(message.chat.id, "Данные о пользователе не найдены. Пожалуйста, начните с команды /start.")
            return

        _, username, age, gender, city = user_data_entry
        area_id = get_region_id(city)  # Получаем ID региона на основе города пользователя

        bot.send_message(message.chat.id, f"Ищем вакансии для {username}, возраст {age}, пол {gender}, город {city}.")

        vacancies = fetch_vacancies(query, ACCESS_TOKEN, area=area_id)
        if not vacancies["items"]:
            bot.send_message(message.chat.id, "Вакансии не найдены.")
            return

        for vacancy in vacancies["items"]:
            description = process_vacancy(vacancy)
            key_skills = extract_key_skills(vacancy)
            bot.send_message(
                message.chat.id,
                f"Название: {vacancy['name']}\n"
                f"Компания: {vacancy['employer']['name']}\n"
                f"Обязанности: {description}\n"
                f"Ключевые навыки: {key_skills}\n"
                f"Ссылка: {vacancy['alternate_url']}"
            )

    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "📈 Анализ вакансий")
def handle_analyze_button(message):
    """
    Обрабатывает нажатие кнопки "📈 Анализ вакансий".
    """
    bot.send_message(message.chat.id, "Введите запрос для анализа вакансий, например: 'Python разработчик'.")
    bot.register_next_step_handler(message, analyze_query)

def analyze_vacancies(message):
    global ACCESS_TOKEN
    try:
        ACCESS_TOKEN = get_access_token(CLIENT_ID, CLIENT_SECRET)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка доступа к API: {e}")
        return

    query = message.text.strip()
    if not query:
        bot.send_message(message.chat.id, "Введите корректный запрос.")
        return

    try:
        user_data_entry = get_user_data(message.chat.id)
        if not user_data_entry:
            bot.send_message(message.chat.id, "Данные о пользователе не найдены. Пожалуйста, начните с команды /start.")
            return

        _, username, age, gender, city = user_data_entry
        area_id = get_region_id(city)

        bot.send_message(message.chat.id, f"Проводим анализ вакансий для {username} в городе {city}...")

        # Получаем данные первой страницы и общее количество вакансий
        first_page_data = fetch_vacancies(query, ACCESS_TOKEN, area=area_id, per_page=100, page=0)
        total_found = first_page_data.get("found", 0)  # Общее количество вакансий
        bot.send_message(message.chat.id, f"Всего найдено вакансий: {total_found}.")

        if not first_page_data["items"]:
            bot.send_message(message.chat.id, "Вакансии не найдены для анализа.")
            return

        # Переменные для анализа
        descriptions = []
        key_skills_list = []
        salaries = []

        # Перебор всех страниц (не более 50 страниц)
        page = 0
        while page * 100 < total_found and page < 500:
            vacancies_data = fetch_vacancies(query, ACCESS_TOKEN, area=area_id, per_page=100, page=page)
            if not vacancies_data["items"]:
                break

            for vacancy in vacancies_data["items"]:
                descriptions.append(process_vacancy(vacancy))

                # Извлекаем ключевые навыки
                key_skills = extract_key_skills(vacancy)
                if key_skills != "Ключевые навыки не указаны.":
                    key_skills_list.extend(key_skills.split(", "))

                # Извлекаем зарплату, если она указана
                salary = vacancy.get("salary")
                if salary and salary["from"] and salary["to"]:
                    avg_salary = (salary["from"] + salary["to"]) / 2
                    salaries.append(avg_salary)

            page += 1
            time.sleep(1)  # Задержка между запросами

        # Анализ текстов
        common_words = analyze_texts(descriptions)

        # Анализ ключевых навыков
        common_skills = Counter(key_skills_list).most_common(10)

        # Средняя зарплата
        if salaries:
            avg_salary_region = sum(salaries) / len(salaries)
            bot.send_message(message.chat.id, f"Средняя зарплата по вакансиям: {avg_salary_region:.2f} руб.")
        else:
            bot.send_message(message.chat.id, "Информация о зарплатах не найдена.")

        bot.send_message(message.chat.id, "Популярные фразы:")
        for word, freq in common_words:
            bot.send_message(message.chat.id, f"- {word} ({freq} упоминаний)")

    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")



def extract_named_entities(texts):
    """
    Извлекает именованные сущности из текстов.
    """
    combined_text = " ".join(texts)
    entities = ner_model(combined_text)

    # Фильтруем сущности по релевантным категориям
    relevant_entities = [entity["word"] for entity in entities if entity["entity_group"] in {"ORG", "MISC", "LOC"}]

    # Подсчитываем частоту упоминаний
    entity_freq = Counter(relevant_entities).most_common(10)
    return entity_freq

# Фильтрация ключевых фраз с учетом стоп-слов
stop_words = set([
    "и", "на", "в", "по", "с", "к", "из", "у", "о", "от", "до", "за", "под", "над",
    "без", "при", "об", "для", "как", "то", "это", "так", "а", "но", "же", "ли", "бы",
    "что", "чтобы", "если", "да", "нет", "их", "все", "ни", "мы", "вы", "он", "она",
    "они", "его", "ее", "их", "свой", "свои", "который", "уже", "только", "быть"
]) # Дополните список, если нужно

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    print("Загрузка стоп-слов...")
    nltk.download('stopwords')

from nltk.corpus import stopwords

# Расширенный список стоп-слов
custom_stop_words = set(stopwords.words('english') + stopwords.words('russian') + [
    "работа", "требования", "обязанности", "знание", "опыт", "навыки", "уметь", "необходимо", "требуется",
    "задачи", "разработка", "программирование", "использование", "возможность", "проект", "команда"
])

categories = {
    # Существующие категории
    "Python-стек": ["python", "django", "flask", "fastapi", "pandas", "numpy"],
    "JavaScript-стек": ["javascript", "typescript", "react", "angular", "vue", "node.js", "express"],
    "Java-стек": ["java", "spring", "hibernate", "maven", "gradle"],
    "C#/.NET": ["c#", ".net", "asp.net", "entity framework"],
    "PHP-стек": ["php", "laravel", "symfony", "wordpress"],
    "Базы данных": ["sql", "postgresql", "mysql", "mongodb", "redis", "oracle"],
    "DevOps": ["docker", "kubernetes", "jenkins", "ansible", "terraform", "ci/cd", "gitlab"],
    "Data Science": ["machine learning", "ai", "data analysis", "pandas", "numpy", "tensorflow", "pytorch"],
    "Mobile Development": ["android", "ios", "swift", "kotlin", "flutter", "react native"],
    "Cloud": ["aws", "azure", "google cloud", "gcp", "cloud computing"],
    "Frontend": ["html", "css", "sass", "less", "bootstrap", "webpack"],
    "Backend": ["rest api", "graphql", "microservices", "serverless"],
    "Testing": ["qa", "testing", "selenium", "junit", "testng", "automation"],
    "Project Management": ["agile", "scrum", "kanban", "jira", "confluence"],

    # Новая категория: Информационная безопасность
    "Информационная безопасность": [
        # Общие термины
        "кибербезопасность", "cybersecurity", "информационная безопасность", "infosec",
        "сетевой безопасность", "network security", "защита данных", "data protection",
        "аудит безопасности", "security audit", "политика безопасности", "security policy",
        "шифрование", "encryption", "криптография", "cryptography",
        "анализ угроз", "threat analysis", "управление рисками", "risk management",
        "защита от вредоносного ПО", "malware protection", "антивирусы", "antivirus",
        "защита от DDoS", "DDoS protection", "брандмауэр", "firewall",
        "VPN", "виртуальная частная сеть", "virtual private network",
        "SIEM", "security information and event management",
        "IDS/IPS", "intrusion detection system", "intrusion prevention system",
        "PKI", "инфраструктура открытых ключей", "public key infrastructure",
        "сетевой сканер", "network scanner", "nmap", "nessus",
        "анализ уязвимостей", "vulnerability assessment", "pentest", "penetration testing",
        "SOC", "security operations center", "мониторинг безопасности", "security monitoring",
        "GDPR", "General Data Protection Regulation", "законодательство", "compliance",
        "ISO 27001", "стандарты безопасности", "security standards",
        "OWASP", "Open Web Application Security Project",
        "защита веб-приложений", "web application security",
        "аутентификация", "authentication", "авторизация", "authorization",
        "двухфакторная аутентификация", "2FA", "two-factor authentication",
        "биометрия", "biometrics", "смарт-карты", "smart cards",
        "безопасность облачных технологий", "cloud security",
        "безопасность мобильных устройств", "mobile security",
        "безопасность IoT", "IoT security", "интернет вещей", "internet of things",
        "безопасность API", "API security", "защита API",
        "безопасность контейнеров", "container security", "docker security",
        "безопасность Kubernetes", "Kubernetes security",
        "безопасность баз данных", "database security",
        "безопасность операционных систем", "OS security", "Windows security", "Linux security",
        "безопасность сетей Wi-Fi", "Wi-Fi security", "WPA3", "WPA2",
        "безопасность электронной почты", "email security", "SPF", "DKIM", "DMARC",
        "безопасность DNS", "DNS security", "DNSSEC",
        "безопасность VoIP", "VoIP security",
        "безопасность блокчейна", "blockchain security",
        "безопасность искусственного интеллекта", "AI security",
        "безопасность больших данных", "big data security",
        "безопасность DevOps", "DevSecOps", "безопасность CI/CD",
        "безопасность конфиденциальных данных", "sensitive data protection",
        "безопасность платежных систем", "payment security", "PCI DSS",
        "безопасность медицинских данных", "healthcare security", "HIPAA",
        "безопасность финансовых данных", "financial security",
        "безопасность игровой индустрии", "gaming security",
        "безопасность социальных сетей", "social media security",
        "безопасность IoT-устройств", "IoT device security",
        "безопасность умного дома", "smart home security",
        "безопасность автомобилей", "car security", "автомобильная безопасность",
        "безопасность промышленных систем", "industrial security", "ICS security",
        "безопасность энергетических систем", "energy security",
        "безопасность телекоммуникаций", "telecom security",
        "безопасность государственных систем", "government security",
        "безопасность военных систем", "military security",

        # Нормативно-правовая база
        "ФСТЭК", "ФСБ", "Роскомнадзор", "152-ФЗ", "персональные данные",
        "требования ФСТЭК", "требования ФСБ", "лицензия ФСТЭК", "лицензия ФСБ",
        "сертификация ФСТЭК", "сертификация ФСБ", "СЗИ", "средства защиты информации",
        "КСЗИ", "комплексные средства защиты информации", "СОВ", "системы обнаружения вторжений",
        "СОК", "системы оперативного контроля", "СУИБ", "системы управления информационной безопасностью",
        "ГОСТ Р 57580", "ГОСТ Р 56939", "ГОСТ Р 50922", "ГОСТ Р 51583",
        "ISO/IEC 27001", "ISO/IEC 27002", "ISO/IEC 27005", "ISO/IEC 15408",
        "PCI DSS", "HIPAA", "GDPR", "NIST", "CIS Controls",

        # Методологии и стандарты
        "OWASP Top 10", "OWASP Testing Guide", "PTES", "MITRE ATT&CK",
        "Kill Chain", "Cyber Kill Chain", "STRIDE", "DREAD",
        "PASTA", "TARA", "FAIR", "NIST Cybersecurity Framework",

        # Инструменты для пентеста
        "Metasploit", "Burp Suite", "Nmap", "Wireshark", "Kali Linux",
        "Nessus", "OpenVAS", "Acunetix", "Nikto", "Sqlmap",
        "Aircrack-ng", "John the Ripper", "Hashcat", "Hydra", "Cobalt Strike",

        # Навыки и знания
        "анализ сетевого трафика", "network traffic analysis",
        "реверс-инжиниринг", "reverse engineering", "анализ вредоносного ПО", "malware analysis",
        "создание отчетов", "reporting", "документирование", "documentation",
        "навыки коммуникации", "communication skills", "работа в команде", "teamwork",
        "знание архитектуры сетей", "network architecture",
        "знание операционных систем", "OS knowledge", "Windows", "Linux",
        "знание протоколов", "protocol knowledge", "TCP/IP", "HTTP", "HTTPS", "DNS", "SMTP",
        "знание уязвимостей", "vulnerability knowledge", "CVE", "CVSS",
        "навыки программирования", "programming skills", "Python", "Bash", "PowerShell",
    ],

    # Другое
    "Другое": []  # Сюда попадут слова, которые не подходят ни под одну категорию
}



def extract_key_phrases(text):
    """
    Извлекает ключевые фразы из текста, исключая стоп-слова и группируя по категориям.
    """
    doc = nlp(text)
    phrases = []

    # Извлекаем существительные и прилагательные
    for token in doc:
        if (token.text.lower() not in custom_stop_words and  # Исключаем стоп-слова
                token.is_alpha and  # Оставляем только алфавитные символы
                token.pos_ in {"NOUN", "ADJ"}):  # Только существительные и прилагательные
            phrases.append(token.text.lower())

    # Частотный анализ для ключевых слов
    word_freq = Counter(phrases)

    # Группируем слова по категориям
    category_freq = defaultdict(int)
    for word, freq in word_freq.items():
        found_category = False
        for category, keywords in categories.items():
            if word in keywords:
                category_freq[category] += freq
                found_category = True
                break
        if not found_category:
            category_freq["Другое"] += freq  # Если слово не попало в категорию, добавляем в "Другое"

    # Сортируем по частоте
    sorted_categories = sorted(category_freq.items(), key=lambda x: x[1], reverse=True)

    return sorted_categories[:10]  # Возвращаем топ-10

sentence_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
ner_model = pipeline("ner", model="dbmdz/bert-large-cased-finetuned-conll03-english", aggregation_strategy="simple")

def extract_key_phrases_with_transformer(texts, top_n=10):
    """
    Использует SentenceTransformer для извлечения ключевых фраз.
    """
    combined_text = " ".join(texts)
    sentences = combined_text.split(".")  # Разделение на предложения

    # Создание эмбеддингов
    embeddings = sentence_model.encode(sentences)
    num_clusters = min(len(sentences), 5)

    # Кластеризация KMeans
    kmeans = KMeans(n_clusters=num_clusters, random_state=0)
    kmeans.fit(embeddings)
    cluster_labels = kmeans.labels_

    # Группируем предложения по кластерам
    clusters = {i: [] for i in range(num_clusters)}
    for idx, label in enumerate(cluster_labels):
        clusters[label].append(sentences[idx])

    # Выбираем топ фраз из каждого кластера
    key_phrases = []
    for cluster_sentences in clusters.values():
        if cluster_sentences:
            key_phrases.append(" ".join(cluster_sentences))

    return key_phrases[:top_n]

def extract_named_entities_with_ner(texts, top_n=10):
    """
    Использует NER для выделения сущностей из текста.
    """
    combined_text = " ".join(texts)
    entities = ner_model(combined_text)

    # Фильтруем сущности по категориям (например, организации, места, технологии)
    relevant_entities = [
        entity['word']
        for entity in entities
        if entity['entity_group'] in {"ORG", "LOC", "MISC"}
    ]

    # Подсчитываем частоту упоминаний сущностей
    entity_freq = Counter(relevant_entities)
    return entity_freq.most_common(top_n)

# Запуск бота
if __name__ == "__main__":
    bot.polling(none_stop=True)