import functools
import traceback
from typing import Optional, Union

import aio_pika
import aioredis
import ujson
from aio_pika.abc import AbstractRobustChannel
from aioredis import Redis

from settings import settings


class Cache:

    def __init__(self):
        self.pool: Optional[Redis] = None
        self.connection = None
        self.channel: Optional[AbstractRobustChannel] = None

    async def initialize(self, loop):
        self.pool = await aioredis.from_url(
            settings['redis'],
            db=1
        )

        # self.connection = await aio_pika.connect_robust(
        #     settings['mq'],
        #     reconnect_interval=5,
        #     loop=loop
        # )
        #
        # self.channel = await self.connection.channel()

    async def queue(self, queue, **kwargs):
        if self.channel is None:
            return

        if self.channel.is_closed:
            await self.channel.reopen()

        try:
            await self.channel.default_exchange.publish(
                aio_pika.Message(
                    body=bytes(ujson.dumps(kwargs), 'utf-8')
                ),
                routing_key=queue
            )
        except (Exception,):
            traceback.print_exc()

    def __getattr__(self, attr):
        return functools.partial(getattr(self.pool, attr))


cache: Union[aioredis.Redis, Cache] = Cache()
