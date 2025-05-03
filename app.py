from sanic import Sanic

from consumers.messages import MessageConsumer
from core.cache import cache
from webhooks import TelegramWebhookView

app = Sanic(name='chat-bot')


@app.before_server_start
async def before_server_start(_app, _loop):
    await cache.initialize()
    _loop.create_task(MessageConsumer().initialize(_loop))


app.add_route(TelegramWebhookView.as_view(), '/webhooks/telegram/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
