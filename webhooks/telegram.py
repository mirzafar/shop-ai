from sanic import response
from sanic.views import HTTPMethodView

from core.cache import cache


class TelegramWebhookView(HTTPMethodView):
    async def post(self, request):
        data = request.json or {}

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

        if text and chat_id:
            await cache.queue(
                queue='chatbot:messages',
                text=text,
                chat_id=chat_id
            )

        return response.json({
            'method': 'sendMessage',
            'chat_id': chat_id,
            'text': 'Введите текст'
        })
