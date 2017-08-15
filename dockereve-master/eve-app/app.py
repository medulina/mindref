# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:

import os
import socket
import json
from eve import Eve
from eve.auth import TokenAuth
from eve.auth import BasicAuth
from eve_swagger import swagger
from settings import settings
from bson.objectid import ObjectId
import requests
import re
from flask.json import jsonify
from flask_cors import CORS
import bcrypt

API_TOKEN = os.environ.get("API_TOKEN")

class TokenAuth(TokenAuth):
    def check_auth(self, token, allowed_roles, resource, method):
        return token == API_TOKEN

class UserAuth(BasicAuth):
    def check_auth(self, username, password, allowed_roles, resource, method):
        users = app.data.driver.db['user']
        user = users.find_one({'_id': ObjectId(username)})
        return user and user['token'] == password


settings['DOMAIN']['mask']['authentication'] = UserAuth
settings['DOMAIN']['mask']['public_methods'] = ['GET']
settings['DOMAIN']['mask']['public_item_methods'] = ['GET']
settings['DOMAIN']['mask']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['user']['resource_methods'] = ['GET']
settings['DOMAIN']['user']['item_methods'] = ['GET']

settings['DOMAIN']['image']['resource_methods'] = ['GET', 'POST']


app = Eve(settings=settings, auth=TokenAuth)
app.register_blueprint(swagger, url_prefix='/docs/api')
app.add_url_rule('/docs/api', 'eve_swagger.index')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['TOKEN_RE'] = re.compile('access_token=([a-zA-Z0-9]+)')
app.config.from_envvar('MINDR_CFG_PATH')
CORS(app)

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
            if 'roll_scores' not in a.keys():
                a['roll_scores'] = []
            if len(a['roll_scores']) < roll_n:
                updt_rs = a['roll_scores'].copy()
            else:
                updt_rs = a['roll_scores'][1:].copy()
            updt_rs.append(i['score'])

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

@app.route('/api/authenticate/<provider>/<code>')
def authenticate(provider, code):
    provider = provider.upper()
    data = {'client_id': app.config[provider+'_CLIENT_ID'],
            'client_secret': app.config[provider+'_CLIENT_SECRET'],
            'code': code}
    tr = requests.post(app.config[provider+'_ACCESS_TOKEN_URL'], data=data)
    print(tr.text)
    try:
        token = re.findall(app.config['TOKEN_RE'], tr.text)[0]
    except IndexError as e:
        return tr.text
    user_dat = get_profile(provider, token)
    token = bcrypt.hashpw(token, bcrypt.gensalt())
    user_dat['id'] = str(user_dat['id'])
    users = app.data.driver.db['user']
    if users.find_one({'username': user_dat['login'], 'oa_id': user_dat['id']}) is not None:
        users.update_one(
            {'username': user_dat['login'], 'oa_id': user_dat['id']},
            {'$set': {'token': token,
                      'avatar': user_dat['avatar_url']}},
            upsert=True
            )
    else:
        users.update_one(
            {'username': user_dat['login'], 'oa_id': user_dat['id']},
            {'$set': {'token': token,
                      'avatar': user_dat['avatar_url'],
                      'n_subs': 0,
                      'n_try': 0,
                      'n_test': 0,
                      'total_score': 0.0,
                      'ave_score': 0.0,
                      'roll_scores': [],
                      'roll_ave_score': 0.0}},
            upsert=True
            )
    return jsonify({'token': token})


def get_profile(provider, token):
    ur = requests.get(app.config[provider+'_USER_URL'],
                      headers={'authorization': 'token ' + token})
    print(ur.text)
    return ur.json()


if __name__ == '__main__':
    app.run(host='0.0.0.0')
