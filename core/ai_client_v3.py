from datetime import timedelta
from typing import Optional, Any

import ujson
from openai import AsyncOpenAI

from core.cache import cache
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


async def func_sell(input_text: str, chat_id: str) -> tuple[bool, Any]:
    system_message_by_types = '''
        Ты — помощник магазина женской одежды "Ерлан Ерке". У нас есть филиалы:
            • Ул. Александр Бараев, 19 (9:00–21:00, без выходных)
            • Пр. Мангилик Ел, 26Б (9:00–21:00, без выходных)
            • Шоссе Алаш, 34/1 (9:00–18:00, без выходных)

        Твоя задача только определить:
            - категорию одежды (платье, брюки, блузка, верхняя одежда и т.д.)
            - размер (если клиент не знает — предложи таблицу размеров, Принимай любые форматы (европейские, американские), Примеры корректных размеров: 42, XL, 10, 38, M-L)
            - цвет (если не определился — спроси предпочтения)

        Как только соберешь детали заверши диалог и верни строго ответ:  
           `{"category": "категорию одежды", "size": "размер", "color": "цвет"}`

        Важно:
        - Диалог начни сразу с выбора одежды
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
            {'role': 'system', 'content': system_message_by_types}
        ]

    if input_text:
        conversations.append({'role': 'user', 'content': input_text})

    response_text = await http_client(conversations)
    if response_text:
        try:
            data = ujson.loads(response_text)
            return True, data
        except (Exception,):
            pass

    await cache.set(f'chatbot:{chat_id}:conversations', ujson.dumps(conversations), ex=timedelta(minutes=5))
    return False, response_text


async def func_refund(input_text: str) -> str:
    pass


async def on_messages(input_text: str, chat_id: str) -> str:
    if input_text in ['stoop']:
        await cache.delete(f'chatbot:{chat_id}:conversations', f'chatbot:{chat_id}:level', f'chatbot:{chat_id}:intent')
        return input_text

    level = await cache.get(f'chatbot:{chat_id}:level') or 1
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
            await cache.delete(f'chatbot:{chat_id}:conversations', f'chatbot:{chat_id}:level')
            return 'Что то не так пошел попробуйте занаво'

        input_text = None

    if level == 2:
        success, resp = await func_sell(input_text, chat_id)
        if success is False:
            return resp
        input_text = None
        await cache.set(f'chatbot:{chat_id}:configs', ujson.dumps(resp))

    if level == 3:
        await func_refund(input_text)

    await cache.set(f'chatbot:{chat_id}:level', level, ex=timedelta(minutes=5))
