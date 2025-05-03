import re
from datetime import timedelta

import ujson
from openai import AsyncOpenAI

from core.cache import cache
from settings import settings

client = AsyncOpenAI(
    api_key=settings['ai_api_key']
)

system_message = '''
Ты - бот-продавец и консультант магазина женской одежды "Ерлан Ерке". 
Наши филиалы в Астане:
1. Улица Александр Бараев 19
2. Проспект Мангилик Ел 26Б
3. Шоссе Алаш 34/1
Режим работы всех филиалов: с 9:00 до 21:00.

Твоя задача - собирать информацию о намерениях клиента:
1. Для покупок:
   - Уточни тип запроса (покупка/консультация)
   - Источник информации (Инстаграм, Каспи, магазин)
   - Для Каспи: получи ссылку и ЗАВЕРШИ диалог
   - Для других источников: собери все теги (вид, размер, цвет, филиал)
   - После сбора всех данных - ЗАВЕРШИ диалог

2. Для консультаций:
   - Уточни тему консультации
   - Ответь на вопрос
   - Предложи дополнительную помощь
   - Если вопрос исчерпан - заверши диалог

3. При отклонении от темы:
   - Вежливо верни к теме одежды

Строгий формат завершения диалога:
ИТОГ:
- Намерение: [покупка/консультация]
- Источник: [Инстаграм/Каспи/магазин]
- вид: [вид]
- размер: [размер]
- цвет: [цвет]
- филиал: [филиал]
- ссылка: [ссылка на каспи]
'''


def clean_text(text: str) -> str:
    return text.encode('utf-8', 'replace').decode('utf-8')


def close_chat(bot_response):
    summary_pattern = r"ИТОГ:(.*?)(?=\n\n|$)"
    match = re.search(summary_pattern, bot_response, re.DOTALL)
    if match:
        return clean_text(match.group(1).strip())
    return None


def clear_text(text: str) -> str:
    return text.strip().encode('ascii', errors='replace').decode('ascii')


async def http_client(conversations: list) -> str:
    response = await client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=conversations,
        temperature=0.7,
    )

    return response.choices[0].message.content


async def on_messages(input_text: str, chat_id: str) -> str:
    print('123')
    input_text = clear_text(input_text)
    if input_text.lower() in ['/start', 'stoop']:
        return await cache.delete(f'chatbot:conversations:{chat_id}')

    print('1234')
    conversations = await cache.get(f'chatbot:conversations:{chat_id}')
    print()
    print(f'on_messages() -> conversations: {conversations}')
    print()
    if conversations:
        conversations = ujson.loads(conversations)
    else:
        conversations = [
            {'role': 'system', 'content': system_message}
        ]

    conversations.append({'role': 'user', 'content': input_text})
    response_text = await http_client(conversations)
    print('1235')
    print(response_text)

    summary = close_chat(response_text)
    if summary:
        print()
        print(summary)
        print()
        await cache.set(f'chatbot:number:{chat_id}', ex=timedelta(hours=4))
        await cache.delete(f'chatbot:conversations:{chat_id}')
        return 'Для оформления заказа назовите, пожалуйста, номер телефона.'
    else:
        conversations.append({'role': 'assistant', 'content': response_text})
        await cache.set(f'chatbot:conversations:{chat_id}', ujson.dumps(conversations), ex=timedelta(hours=1))

    return response_text
