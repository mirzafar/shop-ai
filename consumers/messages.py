import traceback
from typing import Optional

import aio_pika
import ujson
from aio_pika.abc import AbstractQueue, AbstractRobustChannel

from settings import settings


class MessageConsumer:
    loop = None

    queue_name: Optional[str] = 'messages'
    queue: Optional[AbstractQueue] = None

    async def initialize(self, loop):
        self.loop = loop

        connection = await aio_pika.connect_robust(
            settings['mq'], loop=loop, reconnect_interval=1
        )

        channel: AbstractRobustChannel = await connection.channel()

        self.queue = await channel.declare_queue(
            self.queue_name,
            durable=True
        )

        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:
                try:
                    async with message.process(requeue=False):
                        await self.on_message(ujson.loads(message.body))

                except (Exception,):
                    traceback.print_exc()

    async def on_message(self, data):
        print('on_message', data)
