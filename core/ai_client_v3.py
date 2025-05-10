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
    
    Твоя задача — определить намерение клиента: покупка, возврат или консультация.  

    1. Если клиент хочет **купить товар**, заверши диалог и верни строго ответ:  
       `{"intent": "покупка"}`
    
    2. Если клиент хочет **вернуть товар**, заверши диалог и верни строго ответ:  
       `{"intent": "возврат"}`
    
    3. Если клиент хочет **консультацию** (узнать о товаре, размерах, наличии, доставке и т. д.), дай подробный и вежливый ответ.
    
    Важно:
    - Если клиент спрашивает не по сценарию, Вежливо верни к теме одежды.
    - На вопросы про адреса/график — сразу давай информацию выше.
    - Если клиент спрашивает про доставку ответ: "Извините,  к сожалению мы доставку по городу не делаем, но я могу вам скинуть фото отчёт при передаче товара курьеру. Курьера вы должны сами заказать ☺️"
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
                await cache.delete(f'chatbot:{chat_id}:conversations')
                return True, data['intent']
        except (Exception,):
            pass

    await cache.set(f'chatbot:{chat_id}:conversations', ujson.dumps(conversations))
    return False, response_text


async def func_sell(input_text: str) -> str:
    pass


async def func_refund(input_text: str) -> str:
    pass


async def on_messages(input_text: str, chat_id: str) -> str:
    level = await cache.get(f'chatbot:{chat_id}:level') or 1
    if level == 1:
        success, text = await func_intention(input_text, chat_id)
        if success is True:
            await cache.set(f'chatbot:{chat_id}:level', level + 1)
            await cache.set(f'chatbot:{chat_id}:intent', text)
        else:
            return text

    elif level == 2:
        return await func_sell(input_text)

    elif level == 3:
        return await func_refund(input_text)
