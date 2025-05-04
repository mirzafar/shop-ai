import json

from sanic import response
from sanic.views import HTTPMethodView


class CatalogView(HTTPMethodView):
    async def get(self, request):
        with open('catalog.json', 'r') as f:
            data = json.load(f)
        return response.json(data)
