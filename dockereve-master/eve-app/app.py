# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:

import os
import socket
import json
from eve import Eve
from eve.auth import TokenAuth
from eve_swagger import swagger
from settings import settings

API_TOKEN = os.environ.get("API_TOKEN")

class TokenAuth(TokenAuth):
    def check_auth(self, token, allowed_roles, resource, method):
        return token == API_TOKEN

app = Eve(settings=settings, auth=TokenAuth)
app.register_blueprint(swagger, url_prefix='/docs/api')
app.add_url_rule('/docs/api', 'eve_swagger.index')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

def on_insert_mask(items):
    for i in items:
        if isinstance(i['pic'],str):
            i['pic'] = json.loads(i['pic'])

app.on_insert_mask += on_insert_mask

# required. See http://swagger.io/specification/#infoObject for details.
app.config['SWAGGER_INFO'] = {
    'title': 'mindr Web API',
    'version': 'v1'
}

if __name__ == '__main__':
    app.run(host='0.0.0.0')
