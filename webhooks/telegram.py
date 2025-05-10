from sanic import response
from sanic.views import HTTPMethodView

from core.ai_client_v3 import on_messages


def validate_phone(value: str) -> str:
    response_text = ''
    value = value.strip()

    if len(value) == 10 or len(value) == 11:
        response_text = value

    if value.startswith('77') or value.startswith('87'):
        response_text = value

    return response_text


class TelegramWebhookView(HTTPMethodView):
    async def post(self, request):
        data = request.json or {}
        print(f'TelegramWebhookView.post: {data}')

        message = data.get('message')
        chat_member = data.get('my_chat_member')

        if message and message.get('chat', {}).get('type') == 'private':
            pass
        else:
            return response.json({})

        text, chat_id = None, None

        if message:
            chat_id = message.get('chat', {}).get('id')

        elif chat_member:
            chat_id = chat_member.get('chat', {}).get('id')

        if message and message.get('text') == '/start':
            pass

        if message and message.get('text'):
            text = message['text']

        elif message and message.get('caption'):
            text = message['caption']

        payload = {}

        if text:
            response_text = 'Здравствуйте! Чем могу помочь: хотите сделать покупку или вам нужна консультация по одежде?'
        else:
            response_text = 'Извините, но я не могу понять ваш запрос. Пожалуйста, уточните, вопрос'

        if text and chat_id:
            response_text = await on_messages(
                input_text=text,
                chat_id=chat_id
            )

        if response_text:
            payload = {
                'method': 'sendMessage',
                'chat_id': chat_id,
                'text': response_text
            }

        return response.json(payload)
