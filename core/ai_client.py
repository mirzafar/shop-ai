import logging
import re
import traceback
from datetime import timedelta

import ujson
from openai import AsyncOpenAI

from core.cache import cache
from core.db import mongo
from settings import settings

client = AsyncOpenAI(
    api_key=settings['ai_api_key']
)

logger = logging.getLogger(__name__)

system_message = '''
Ты — помощник магазина женской одежды "Ерлан Ерке". Твоя задача — вежливо собрать ключевые данные о запросе клиента и сразу вывести итог в строгом формате.  

### Правила работы:  
1. **Определи намерение:**  
   - Покупка (оформление заказа)  
   - Проверка наличия  
   - Консультация  

2. **Уточни детали (задавай вопросы по порядку):**  
   - *Источник:* Kaspi/Instagram/магазин/другое (уточни)  
   - *Вид одежды:* платье, брюки, кофта и т.д.  
   - *Размер:* если клиент не знает — предложи таблицу размеров  
   - *Цвет:* если не определился — спроси предпочтения  
   - *Филиал (если актуально):*  
     • Ул. Александр Бараев, 19  
     • Пр. Мангилик Ел, 26Б  
     • Шоссе Алаш, 34/1  
     *Режим работы:* 9:00–21:00, без выходных  
   - *Ссылка на товар (если из Kaspi/Instagram):* попроси прислать ссылку  

3. **Как только все данные собраны — сразу выведи ИТОГ в строгом форматe:** 
ИТОГ:
- Намерение: [покупка/наличие/консультация]
- Источник: [Instagram/Kaspi/магазин/другое]
- Вид: [платье/брюки/кофта и т.д.]
- Размер: [S/M/L/другое]
- Цвет: [цвет или "не важен"]
- Филиал: [адрес или "не важен"]
- Ссылка: [ссылка или "нет"] 

**Важно:**  
- Если клиент спрашивает не по сценарию, Вежливо верни к теме одежды
- На вопросы про адреса/график — сразу давай информацию выше.  
'''


def clean_text(text: str) -> str:
    return text.strip().encode('utf-8', 'replace').decode('utf-8')


def close_chat(bot_response):
    logger.debug(f'bot_response: {bot_response}')
    summary_pattern = r"ИТОГ:(.*?)(?=\n\n|$)"
    match = re.search(summary_pattern, bot_response, re.DOTALL)
    if match:
        return clean_text(match.group(1).strip())
    return None


async def http_client(conversations: list) -> str:
    response = await client.chat.completions.create(
        model='gpt-3.5-turbo',
        messages=conversations,
        temperature=0.7,
    )

    return response.choices[0].message.content


async def on_messages(input_text: str, chat_id: str) -> str:
    input_text = clean_text(input_text)
    if input_text.lower() in ['/start', 'stoop']:
        return await cache.delete(f'chatbot:conversations:{chat_id}')

    conversations = await cache.get(f'chatbot:conversations:{chat_id}')
    if conversations:
        conversations = ujson.loads(conversations)
    else:
        conversations = [
            {'role': 'system', 'content': system_message}
        ]

    conversations.append({'role': 'user', 'content': input_text})
    response_text = await http_client(conversations)

    summary = close_chat(response_text)
    if summary:
        print()
        print(summary)
        print()
        try:
            result = {}
            for line in summary.strip().split('\n'):
                if line.startswith('- '):
                    key_value = line[2:].split(': ', 1)
                    if len(key_value) == 2:
                        key = key_value[0].strip()
                        value = key_value[1].strip()
                        result[key] = value

            await mongo.orders.insert_one(result)

        except (Exception,):
            traceback.print_exc()
        print()
        await cache.set(f'chatbot:number:{chat_id}', '1', ex=timedelta(hours=4))
        await cache.delete(f'chatbot:conversations:{chat_id}')
        return 'Для оформления заказа назовите, пожалуйста, номер телефона.'
    else:
        conversations.append({'role': 'assistant', 'content': response_text})
        await cache.set(f'chatbot:conversations:{chat_id}', ujson.dumps(conversations), ex=timedelta(hours=1))

    return response_text
