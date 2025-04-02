import os
import json
import requests
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import ollama



# Настройки
RSS_URL = 'https://<your_site>.ru/news/rss' # Замените на свой сайт с поддержкой rss
OUTPUT_JSON = '/llm_bot/data/articles.json'
MAX_ARTICLES = 20 # Максимальное количество просматриваемых статей

SELECTED_CATEGORIES = [
    "Окружающая среда",
    "окружающая среда",  # Пример категории
    "Искусственный интеллект, машинное обучение, нейросети",           # Добавьте нужные категории
    'Социальные сети',
    'на острие науки',
    'Операционные системы',
    'разработка и производство электроники',
    'Новости сети',
    'Шифрование и защита данных',
    'Приложения для Android',
    'сети и коммуникации',
    'Цифровые финансы',
    'носимая электроника'
]

SELECTED_CATEGORIES = [c.strip().lower() for c in SELECTED_CATEGORIES]


def normalize_paragraphs(text):
    """Нормализует переносы строк в тексте.

    Args:
        text (str): Исходный текст с потенциально неравномерными переносами строк.

    Returns:
        str: Текст с нормализованными переносами строк (двойные между абзацами).
    """
    # Заменяем все варианты \n, \\n, \r\n на одинарный \n
    text = re.sub(r"(\\n|\r\n|\n)", "\n", text)
    # Заменяем два или более символов новой строки на \n\n
    text = re.sub(r"\n{2,}", "\n\n", text)
    # Убираем лишние пробелы в начале и конце текста
    return text.strip()


def clean_content(text):
    """Удаляет блоки с указанием источников изображений из текста.

    Удаляет блоки, которые:
    - Обрамлены минимум тремя переносами строк с каждой стороны
    - Содержат фразу "источник изображения" в любом регистре

    Args:
        text (str): Исходный текст статьи.

    Returns:
        str: Очищенный текст без блоков источников изображений.
    """
    pattern = r"\n{3,}.*?источни[^\s]*\s+изображен[^\s]*:.*?\n{3,}"
    cleaned_text = re.sub(
        pattern=pattern,
        repl="\n",
        string=text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def get_rss_feed():
    """Получает RSS-ленту по заданному URL.

    Returns:
        BeautifulSoup | None: Объект BeautifulSoup с parsed RSS или None при ошибке.
    """
    try:
        response = requests.get(RSS_URL)
        response.raise_for_status()
        return BeautifulSoup(response.content, "lxml-xml")
    except Exception as e:
        print(f"Ошибка получения RSS: {str(e)}")
        return None


def parse_article_page(url):
    """Парсит страницу статьи и извлекает категорию и контент.

    Args:
        url (str): URL статьи для парсинга.

    Returns:
        dict | None: Словарь с категорией и контентом или None при ошибке.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Извлекаем категорию
        breadcrumbs = soup.find("span", class_="left nowrap")
        category = None
        if breadcrumbs:
            for link in breadcrumbs.find_all("a", class_="breadcrumb"):
                title = link.get("title", "").strip().lower()
                if title in SELECTED_CATEGORIES:
                    category = title
                    break

        # Извлекаем контент
        content_div = soup.find("div", class_="js-mediator-article")
        content = clean_content(content_div.text.strip()) if content_div else ""

        return {"category": category, "content": content}
    except Exception as e:
        print(f"Ошибка парсинга статьи: {str(e)}")
        return None


def get_new_articles():
    """Получает новые статьи из RSS-ленты, исключая уже существующие.

    Returns:
        list: Список словарей с данными новых статей.
    """
    soup = get_rss_feed()
    if not soup:
        return []

    existing = load_existing_articles()
    existing_ids = {a["id"] for a in existing}
    new_articles = []

    for item in soup.find_all("item")[:MAX_ARTICLES]:
        try:
            link = item.link.text.strip()
            guid = item.guid.text.strip()
            article_id = re.search(r"/(\d+)/", guid).group(1)

            if article_id in existing_ids:
                continue

            title = item.title.text.strip()
            pub_date = item.pubDate.text.strip() if item.pubDate else ""
            image_url = item.enclosure["url"] if item.enclosure else None

            article_data = parse_article_page(link)
            if not article_data or not article_data["category"]:
                continue

            new_articles.append(
                {
                    "id": article_id,
                    "title": title,
                    "content": article_data["content"],
                    "category": article_data["category"],
                    "original_url": link,
                    "image_url": image_url,
                    "pub_date": pub_date,
                    "parsed_time": datetime.now().isoformat(),
                    "llm_output": [],
                    "flag": False,
                }
            )
            time.sleep(1)

        except Exception as e:
            print(f"Ошибка обработки элемента RSS: {str(e)}")
            continue

    return new_articles


def load_existing_articles():
    """Загружает существующие статьи из JSON-файла.

    Returns:
        list: Список словарей с данными существующих статей.
    """
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_articles(articles):
    """Сохраняет статьи в JSON-файл, ограничивая их количество.

    Args:
        articles (list): Список словарей с данными статей.
    """
    articles = sorted(articles, key=lambda x: x.get("pub_date", ""), reverse=True)[:]
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def wait_for_ollama(client, retries=5, delay=5):
    """Ожидает, пока Ollama станет доступной, с повторными попытками.

    Args:
        client: Экземпляр ollama.Client.
        retries (int): Количество попыток подключения.
        delay (int): Задержка между попытками в секундах.

    Raises:
        Exception: Если Ollama не стала доступной после всех попыток.
    """
    for attempt in range(retries):
        try:
            client.generate(model="gemma3:4b-it-q8_0", prompt="ping")
            print("Ollama готова")
            return True
        except Exception as e:
            print(f"Ожидание Ollama (попытка {attempt + 1}/{retries}): {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise Exception("Ollama не стала доступной после всех попыток")

def main_loop():
    """Основной цикл программы для парсинга и обработки статей."""
    print(f"\n[{datetime.now()}] Начало парсинга...")
    existing = load_existing_articles()
    new_articles = get_new_articles()

    if new_articles:
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        client = ollama.Client(host=ollama_host)

        # Ожидаем готовности Ollama с повторными попытками
        try:
            wait_for_ollama(client)
        except Exception as e:
            print(f"Не удалось подключиться к Ollama: {str(e)}")
            return

        model = "gemma3:4b-it-q8_0"
        instruction = """Ты профессиональный редактор на новостном телеграм канале о высоких технологиях.  
            Создай пост для канала, кратко пересказав материал статьи. Четко следуй правилам, убедись что каждое условие выполняется. Если ты не будешь 
            точно следовать правилам, ты будешь платить штрафы. Правила:
            1. Нельзя писать посты, которые превышают 130 токенов (90 слов). 
            2. Писать весь текст строго НА РУССКОМ ЯЗЫКЕ, сохраняя технические термины.
            3. Не пиши ничего лишнего, сразу начинай писать пост.
            4. Заголовок эмоциональный.
            5. <b>Заголовки</b> и <b>Подзаголовки</b> выделяй по формату HTML (пример: <b>Ключевой тренд</b>).
            6. В конце поставь 1-3 релевантных хештега по теме поста (пример: #AI, #Nvidia, #ИИ).
            7. Сохрани все важные цифры и названия проектов.
            8. Все абзацы должны разделяться строго через \n\n. Не экранируй символы новой строки (не используй \\n\\n).
            9. Убедись, что текст легко читается и структурирован.
            10. Не используй обратные слэши (\) для экранирования символов новой строки.
            11. Проверь, что твой текст не длиннее 130 токенов (90 слов), если их больше, то вернись в самое начало инструкции и выполни задание заново,
            иначе нас с тобой оштрафуют.
            """
        
        # Выполняем запрос с обработкой ошибок
        try:
            response = client.generate(model=model, prompt=instruction)
            context = response.context
        except Exception as e:
            print(f"Ошибка при генерации инструкции: {str(e)}")
            return

        for data in new_articles:
            article = data["title"] + " \n" + data["content"]
            try:
                response = client.generate(model=model, prompt=article, context=context)
                data["llm_output"] = normalize_paragraphs(response.response)
            except Exception as e:
                print(f"Ошибка при обработке статьи {data['title']}: {str(e)}")
                continue

        updated = new_articles + existing
        save_articles(updated)
        print(f"Добавлено новых статей: {len(new_articles)}")
        print(f"Всего статей в файле: {len(updated[:MAX_ARTICLES])}")
    else:
        print("Новых статей не найдено")


if __name__ == "__main__":
    main_loop()