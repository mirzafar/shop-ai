import logging
import re
import traceback
from datetime import timedelta

import ujson
from nltk.stem.snowball import SnowballStemmer
from nltk.tokenize import word_tokenize
from openai import AsyncOpenAI

from core.cache import cache
from core.db import mongo
from settings import settings

client = AsyncOpenAI(
    api_key=settings['ai_api_key']
)

logger = logging.getLogger(__name__)

stemmer = SnowballStemmer("russian")

system_message = '''
Ты — помощник магазина женской одежды "Ерлан Ерке". Твоя задача — вежливо собрать ключевые данные о запросе клиента и сразу вывести итог в строгом формате.  

### Правила работы:  
1. **Определи намерение:**  
   - Покупка (оформление заказа)  
   - Проверка наличия  
   - Консультация
   - Возврат

2. **Уточни детали (задавай вопросы по порядку):**  
   - *Источник от куда узнал о нас:* Kaspi/Instagram/другое (обязательно)  
   - *Вид одежды:* платье, брюки, кофта и т.д. (обязательно)
   - *Размер:* если клиент не знает — предложи таблицу размеров  
   - *Цвет:* если не определился — спроси предпочтения
   - *Филиал (если актуально):*  
     • Ул. Александр Бараев, 19  
     • Пр. Мангилик Ел, 26Б  
     • Шоссе Алаш, 34/1  
     *Режим работы:* 9:00–21:00, без выходных  
   - *Ссылка на товар (если из Kaspi):* попроси прислать ссылку только если Источник каспи
   - *номер фискального чека (если намерение возврат):* попроси прислать номер

3. **Как только все данные собраны — сразу выведи ИТОГ в строгом форматe:** 
DATA:
- Намерение: [покупка/наличие/консультация/возврат]
- Источник: [Instagram/Kaspi/магазин/другое]
- Вид: [платье/брюки/кофта и т.д.]
- Размер: [S/M/L/другое]
- Цвет: [цвет]
- Филиал: [адрес]
- Ссылка: [ссылка]
- Номер чека: [номер фискального чека]

**Важно:**  
- Если клиент спрашивает не по сценарию, Вежливо верни к теме одежды
- На вопросы про адреса/график — сразу давай информацию выше.  
'''


def clean_text(text: str) -> str:
    return text.strip().encode('utf-8', 'replace').decode('utf-8')


def close_chat(bot_response):
    txt = bot_response.strip().replace('*', '')
    pattern = r'DATA:(.*?)(?=\n\n|$)'
    if match := re.search(pattern, txt, re.DOTALL):
        summary = clean_text(match.group(1).strip())
        result = {}
        for line in summary.strip().split('\n'):
            if line.startswith('- '):
                key_value = line[2:].split(': ', 1)
                if len(key_value) == 2:
                    key = key_value[0].strip()
                    value = key_value[1].strip()
                    result[key.lower().strip()] = value

        return result

    pattern = r'ИТОГ:(.*?)(?=\n\n|$)'
    if match := re.search(pattern, txt, re.DOTALL):
        summary = clean_text(match.group(1).strip())
        result = {}
        for line in summary.strip().split('\n'):
            if line.startswith('- '):
                key_value = line[2:].split(': ', 1)
                if len(key_value) == 2:
                    key = key_value[0].strip()
                    value = key_value[1].strip()
                    result[key.lower().strip()] = value

        return result

    lines = txt.split('\n')
    data = {}
    for line in lines:
        if line.startswith('-'):
            clean_line = line[1:].strip()
            if ':' in clean_line:
                key, value = clean_line.split(':', 1)
                key = key.strip()
                value = value.strip()
                if key in ['Намерение', 'Источник', 'Вид', 'Размер', 'Цвет', 'Филиал', 'Ссылка', 'Номер чека']:
                    data[key] = value

    if data:
        return data

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

    result = close_chat(response_text)
    if result:
        try:
            is_insert = False
            if result and result.get('намерение') and result['намерение'].lower().strip() in ['покупка', 'наличие']:
                if result.get('источник') and result['источник'].lower().strip() in ['kaspi', 'каспи']:
                    if result.get('ссылка'):
                        is_insert = True
                    else:
                        conversations.append({'role': 'system',
                                              'content': '''
                                              - Уточни ссылку на каспи.
                                              - Когда соберешь новые данные выведи новый ИТОГ в том же формате
                                              '''})
                        response_text = await http_client(conversations)
                else:
                    if result.get('вид'):
                        tokens = word_tokenize(result['вид'])
                        filters = []
                        for word in tokens:
                            filters.append({'words': stemmer.stem(word)})

                        goods = await mongo.goods.find({'$and': filters}).to_list(length=None)
                        if goods:
                            is_insert = True
                            result['good_ids'] = [str(x['_id']) for x in goods]
                        else:
                            conversations.append({
                                'role': 'system',
                                'content': '''
                                товара нет в наличии:
                                - не предлагай альтернативные размеры/цвета/филиал
                                - Сообщи: "К сожалению, этого товара сейчас нет в наличии. Хотите подобрать что-то похожее или уточнить наличие в другом филиале?"
                                - Нужно перейти на другую одежду если клиент хочет
                                - Если клиент согласен на другие одежды — собери данные заново вид/цвет/размеры/филиал
                                - Когда соберешь новые данные выведи новый ИТОГ в том же формате
                                '''})
                            response_text = await http_client(conversations)
                    else:
                        conversations.append({'role': 'system',
                                              'content': '''
                                                          - Уточни вид одежды.
                                                          - Когда соберешь новые данные выведи новый ИТОГ в том же формате
                                                          '''})
                        response_text = await http_client(conversations)
            else:
                is_insert = True

            if is_insert:
                await mongo.orders.insert_one(result)

        except (Exception,):
            traceback.print_exc()
            is_insert = True

        if is_insert:
            await cache.delete(f'chatbot:conversations:{chat_id}')
            return 'В ближайшее время оператор свяжется с вами.'
    else:
        conversations.append({'role': 'assistant', 'content': response_text})
        await cache.set(f'chatbot:conversations:{chat_id}', ujson.dumps(conversations), ex=timedelta(hours=1))

    return response_text
