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


async def http_client(conversations: list) -> str:
    response = await client.chat.completions.create(
        model='gpt-3.5-turbo',
        messages=conversations,
        temperature=0.7,
    )

    return response.choices[0].message.content


async def func_intention(input_text: str, chat_id: str) -> tuple[bool, str]:
    system_message = '''
    Ты — помощник магазина женской одежды "Ерлан Ерке". У нас есть филиалы:
        • Ул. Александр Бараев, 19 (9:00–21:00, без выходных)
        • Пр. Мангилик Ел, 26Б (9:00–21:00, без выходных)
        • Шоссе Алаш, 34/1 (9:00–18:00, без выходных)
    
    Твоя задача только определить намерение клиента: покупка, возврат.

    1. Если клиент хочет **купить товар или заказать тавар**, заверши диалог и верни строго ответ:  
       `{"intent": "покупка"}`
    
    2. Если клиент хочет **вернуть товар**, заверши диалог и верни строго ответ:  
       `{"intent": "возврат"}`
    
    Важно:
    - Не предлагай ничего, только узнай намерение клиента
    - Если клиент спрашивает не по сценарию, Вежливо верни к теме одежды.
    - На вопросы про адреса/график — сразу давай информацию выше.
    - Если клиент спрашивает про доставку домой ответ: "Извините,  к сожалению мы доставку по городу не делаем, но я могу вам скинуть фото отчёт при передаче товара курьеру. Курьера вы должны сами заказать ☺️"
    - Отвечай на русском или на казахском зависимо от языка клиента
    '''
    conversations = await cache.get(f'chatbot:{chat_id}:conversations')
    if conversations:
        conversations = ujson.loads(conversations)
    else:
        conversations = [
            {'role': 'system', 'content': system_message}
        ]

    conversations.append({'role': 'user', 'content': input_text})
    response_text = await http_client(conversations)
    if response_text:
        try:
            data = ujson.loads(response_text)
            if data.get('intent'):
                return True, data['intent']
        except (Exception,):
            pass

    await cache.set(f'chatbot:{chat_id}:conversations', ujson.dumps(conversations), ex=timedelta(minutes=5))
    return False, response_text


async def func_sell(input_text: str | None, chat_id: str):
    system_message = '''
        Ты — вежливый и лаконичный помощник интернет-магазина женской одежды "Ерлан Ерке". Твоя задача — помочь покупательнице выбрать товар, определив только три параметра:
        – вид одежды (например: платье, блузка, брюки и т.д.),
        – размер (если клиент не знает — предложи таблицу размеров, размер должен европейские, американские формате),
        – цвет.
        
        Когда три параметра получены — выведи только ответ в формате JSON, без лишних слов:
        `{"category": "категория одежды", "size": "размер", "color": "цвет"}`
        
        После вывода JSON — сразу заверши диалог, ничего больше не говори (никаких прощаний, вопросов или предложений помощи).
        
        Если клиент спрашивает какие цвета или размеры есть, сначала спроси её предпочтения

        Ответь только когда клиент спрашивает про филиалы:
        – Ул. Александр Бараев, 19 (9:00–21:00, без выходных)
        – Пр. Мангилик Ел, 26Б (9:00–21:00, без выходных)
        – Шоссе Алаш, 34/1 (9:00–18:00, без выходных)
        
        Ответь только когда клиент спрашивает про доставку, скажи:
        "Извините, к сожалению мы доставку по городу не делаем, но я могу вам скинуть фото отчёт при передаче товара курьеру. Курьера вы должны сами заказать ☺️"
        
        Диалог начни сразу с выбора одежды без приветствие, Не обсуждай другие темы, не предлагай ничего лишнего. Отвечай коротко, дружелюбно и по существу. Если не хватает одного или нескольких параметров — уточни.
        '''
    conversations = await cache.get(f'chatbot:{chat_id}:conversations')
    if conversations:
        conversations = ujson.loads(conversations)
    else:
        conversations = [
            {'role': 'system', 'content': system_message}
        ]

    if input_text:
        conversations.append({'role': 'user', 'content': input_text})

    response_text = await http_client(conversations)
    conversations.append({'role': 'assistant', 'content': response_text})
    await cache.set(f'chatbot:{chat_id}:conversations', ujson.dumps(conversations), ex=timedelta(minutes=5))

    try:
        data = ujson.loads(response_text)
        flag, _ids = await found_goods(data)
        if flag is False:
            conversations.append({'role': 'system', 'content': '''
            В базе с таким параметром ничего не найдено, вежливо скажи:
            "К сожалению, по этим параметрам ничего не найдено 😔 Давайте попробуем ещё раз. Уточните, пожалуйста: вид одежды, размер и цвет."
            
            Твоя задача пересобрать три параметра:
            – вид одежды (например: платье, блузка, брюки и т.д.),
            – размер (если клиент не знает — предложи таблицу размеров, размер должен европейские, американские формате),
            – цвет.
            
            После того как собраны все три параметра, выведи ответ в формате JSON:
            `{"category": "категория одежды", "size": "размер", "color": "цвет"}`
            '''})

            return await func_sell(None, chat_id)

        await mongo.orders.insert_one({
            'good_ids': _ids,
            **data
        })
        return True, data
    except (Exception,):
        pass

    return False, response_text


async def func_refund(input_text: str) -> str:
    pass


async def clear_chat(uid: str):
    await cache.delete(
        f'chatbot:{uid}:conversations',
        f'chatbot:{uid}:level',
        f'chatbot:{uid}:intent',
        f'chatbot:{uid}:configs'
    )


stemmer = SnowballStemmer("russian")


async def found_goods(configs: dict) -> tuple[bool, list]:
    tokens = word_tokenize(configs['category'])
    filters = []
    for word in tokens:
        filters.append({'words': stemmer.stem(word)})

    g_filter = {}
    if configs.get('size'):
        g_filter['size'] = configs['size']

    f_colors = []
    if configs.get('color'):
        t_colors = word_tokenize(configs['color'])
        for word in t_colors:
            f_colors.append({'f_colors': stemmer.stem(word)})

    g_filter.update({
        '$and': filters + f_colors,
        'size': configs['size']
    })

    good = await mongo.goods.find_one(g_filter)
    if good:
        return True, [str(good['_id'])]

    goods = await mongo.goods.find({'$and': filters}).to_list(length=None)
    if goods:
        return True, [str(x['_id']) for x in goods[:5]]
    else:
        return False, []


async def on_messages(input_text: str, chat_id: str) -> str:
    if input_text in ['stoop']:
        await clear_chat(chat_id)
        return input_text

    level = int(await cache.get(f'chatbot:{chat_id}:level') or 1)
    if level == 1:
        success, text = await func_intention(input_text, chat_id)
        if success is False:
            return text

        text = text.strip().lower()
        if text == 'возврат':
            level = 3
            await cache.set(f'chatbot:{chat_id}:intent', 'refund')
        elif text == 'покупка':
            level = 2
            await cache.set(f'chatbot:{chat_id}:intent', 'sell')
        else:
            await clear_chat(chat_id)
            return 'Что то не так пошел попробуйте занаво'

        await cache.delete(f'chatbot:{chat_id}:conversations')
        await cache.set(f'chatbot:{chat_id}:level', level, ex=timedelta(minutes=5))
        input_text = None

    if level == 2:
        success, resp = await func_sell(input_text, chat_id)
        if success is False:
            return resp

        await clear_chat(chat_id)
        await cache.set(f'chatbot:{chat_id}:configs', ujson.dumps(resp))
        return 'Ваш запрос принят, в ближайшее время оператор свяжется с вами.'

    if level == 3:
        await func_refund(input_text)
