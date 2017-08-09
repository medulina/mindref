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
from bson.objectid import ObjectId

API_TOKEN = os.environ.get("API_TOKEN")

class TokenAuth(TokenAuth):
    def check_auth(self, token, allowed_roles, resource, method):
        return token == API_TOKEN

app = Eve(settings=settings, auth=TokenAuth)
app.register_blueprint(swagger, url_prefix='/docs/api')
app.add_url_rule('/docs/api', 'eve_swagger.index')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
roll_n = 5

def get_ave(x):
    if len(x) == 0:
        return 0
    total = 0.0
    for xi in x:
        total += xi
    return total/len(x)

def on_insert_mask(items):
    for i in items:
        # Convert encode string as json
        if isinstance(i['pic'], str):
            i['pic'] = json.loads(i['pic'])
        # For attempts on training data, update users training score
        if i['mode'] == 'try':
            # Find the user
            users = app.data.driver.db['user']
            a = users.find_one({'_id': ObjectId(i['user_id'])})

            if len(a['roll_scores']) <= roll_n:
                updt_rs = a['roll_scores'].copy()
            else:
                updt_rs = a['roll_scores'][1:].copy()
            updt_rs.append(a['score'])

            # TODO: Verify submission is novel
            users.update_one(
                {'_id': ObjectId(i['user_id'])},
                {'$inc': {'n_subs': 1, 'n_try': 1, 'total_score': i['score']},
                 '$set': {'ave_score':(a['total_score'] + i['score']) / (a['n_try'] + 1),
                          'roll_scores':updt_rs,
                          'roll_ave_score':get_ave(updt_rs)}}
            )
        # Increment user test counter
        if i['mode'] == 'test':
            users = app.data.driver.db['user']
            users.update_one(
                {'_id': ObjectId(i['user_id'])},
                {'$inc': {'n_subs': 1, 'n_test': 1}}
            )


app.on_insert_mask += on_insert_mask

# required. See http://swagger.io/specification/#infoObject for details.
app.config['SWAGGER_INFO'] = {
    'title': 'Medulina Web API',
    'version': 'v1'
}

if __name__ == '__main__':
    app.run(host='0.0.0.0')
