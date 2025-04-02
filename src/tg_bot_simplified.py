import asyncio
import json
from telegram.ext import Application, ContextTypes
import re
import subprocess
from datetime import datetime


# Конфигурация
BOT_TOKEN = "<your bot token>"
CHANNEL_ID = "<your channel id>"  # Или числовой ID канала (например, -100123456789)
JSON_FILE='/llm_bot/data/articles.json'
PARSER_SCRIPT = "/llm_bot/src/news_parser.py" 

async def run_parser():
    """Запускает скрипт парсера в отдельном процессе."""
    print(f"[{datetime.now()}] Запуск парсера: {PARSER_SCRIPT}")
    try:
        result = subprocess.run(
            ["python3", PARSER_SCRIPT],
            capture_output=True,
            text=True,
        )
        print(f"[{datetime.now()}] Парсер успешно выполнен:")
        print(result.stdout)
        if result.stderr:
            print(f"[{datetime.now()}] Ошибки парсера: {result.stderr}")
    except subprocess.CalledProcessError as e:
        print(f"[{datetime.now()}] Ошибка парсера: {e.stderr}")
    except Exception as e:
        print(f"[{datetime.now()}] Неожиданная ошибка в run_parser: {str(e)}")

async def send_single_message(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет одно сообщение в Telegram-канал."""
    print(f"[{datetime.now()}] Попытка отправки сообщения...")
    print(f"[{datetime.now()}] Используемый JSON-файл: {JSON_FILE}")
    print(f"[{datetime.now()}] Используемый CHANNEL_ID: {CHANNEL_ID}")
    try:
        with open(JSON_FILE, "r+", encoding="utf-8") as f:
            data = json.load(f)
            print(f"[{datetime.now()}] Загружено {len(data)} записей из {JSON_FILE}")
            updated = False

            for index, item in enumerate(data):
                if not item.get("flag", False):
                    print(f"[{datetime.now()}] Найдено неотправленное сообщение: {item.get('title', 'Без заголовка')}")
                    print(f"[{datetime.now()}] Текст: {item.get('llm_output', 'Нет текста')[:50]}...")
                    print(f"[{datetime.now()}] Фото: {item.get('image_url', 'Нет URL')}")
                    try:
                        clean_text = re.sub(r"</?br\s*/?>", "", item["llm_output"])
                        if len(clean_text) > 1024:
                            clean_text = clean_text[:1023]
                            print(f"[{datetime.now()}] Текст обрезан до 1024 символов")

                        for attempt in range(3):
                            try:
                                print(f"[{datetime.now()}] Отправка сообщения, попытка {attempt + 1}/3")
                                await asyncio.wait_for(
                                    context.bot.send_photo(
                                        chat_id=CHANNEL_ID,
                                        photo=item["image_url"],
                                        caption=clean_text,
                                        parse_mode="HTML",
                                    ),
                                    timeout=15,
                                )
                                data[index]["flag"] = True
                                updated = True
                                print(f"[{datetime.now()}] Успешно отправлено: {clean_text[:50]}...")
                                break
                            except asyncio.TimeoutError:
                                if attempt == 2:
                                    raise
                                print(f"[{datetime.now()}] Таймаут, попытка {attempt + 2}/3...")
                                await asyncio.sleep(5)
                        break
                    except Exception as e:
                        print(f"[{datetime.now()}] Ошибка в сообщении {index}: {str(e)}")
                        if "Message to send not found" not in str(e):
                            data[index]["flag"] = True
                            updated = True
                        continue

            if updated:
                f.seek(0)
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.truncate()
                print(f"[{datetime.now()}] JSON обновлен")
            else:
                print(f"[{datetime.now()}] Нет новых сообщений для отправки")

    except FileNotFoundError:
        print(f"[{datetime.now()}] Ошибка: Файл {JSON_FILE} не найден")
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] Ошибка: Неверный формат JSON в {JSON_FILE}")
    except Exception as e:
        print(f"[{datetime.now()}] Критическая ошибка в send_single_message: {str(e)}")

async def main():
    """Основная функция для запуска Telegram-бота."""
    print(f"[{datetime.now()}] Проверка переменных окружения:")
    print(f"[{datetime.now()}] BOT_TOKEN: {'Задан' if BOT_TOKEN else 'Не задан'}")
    print(f"[{datetime.now()}] CHANNEL_ID: {CHANNEL_ID}")
    print(f"[{datetime.now()}] PARSER_SCRIPT: {PARSER_SCRIPT}")
    print(f"[{datetime.now()}] JSON_FILE: {JSON_FILE}")

    if not BOT_TOKEN or not CHANNEL_ID:
        print(f"[{datetime.now()}] Ошибка: BOT_TOKEN или CHANNEL_ID не заданы")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка инициализации бота: {str(e)}")
        return

    # Планировщик для парсера (каждые 2 минуты)
    application.job_queue.run_repeating(
        callback=lambda ctx: asyncio.create_task(run_parser()),
        interval=1200,  # 20 минут
        first=60,
    )

    # Планировщик для отправки сообщений (каждые 5 минут)
    application.job_queue.run_repeating(
        callback=lambda ctx: asyncio.create_task(send_single_message(ctx)),
        interval=1800,  # 30 минут
        first=150,
    )

    await application.initialize()
    await application.start()
    print(f"[{datetime.now()}] Бот запущен. Для остановки Ctrl+C")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"[{datetime.now()}] Бот остановлен")
    except Exception as e:
        print(f"[{datetime.now()}] Неожиданная ошибка в main: {str(e)}")