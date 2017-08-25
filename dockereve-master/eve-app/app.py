# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:

import os
import sys
import socket
import json
import re
import requests
import pandas as pd
import base64
from io import BytesIO
from copy import deepcopy
from eve import Eve
from eve.auth import TokenAuth
from eve.auth import BasicAuth
from eve_swagger import swagger
from settings import settings
from bson.objectid import ObjectId
from flask.json import jsonify
from flask_cors import CORS
import bcrypt
from numpy.random import randint
from PIL import Image

API_TOKEN = os.environ.get("API_TOKEN")

class TokenAuth(TokenAuth):
    def check_auth(self, token, allowed_roles, resource, method):
        return token == API_TOKEN

class UserAuth(BasicAuth):
    def check_auth(self, username, password, allowed_roles, resource, method):
        users = app.data.driver.db['user']
        user = users.find_one({'_id': ObjectId(username)})
        return user and user['token'] == password


#settings['DOMAIN']['mask']['authentication'] = UserAuth
settings['DOMAIN']['mask']['public_methods'] = ['GET']
settings['DOMAIN']['mask']['public_item_methods'] = ['GET']
settings['DOMAIN']['mask']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['user']['resource_methods'] = ['GET']
settings['DOMAIN']['user']['item_methods'] = ['GET']

settings['DOMAIN']['image']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['project']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['researcher']['resource_methods'] = ['GET']
settings['DOMAIN']['researcher']['item_methods'] = ['GET']


app = Eve(settings=settings, auth=TokenAuth)
app.register_blueprint(swagger, url_prefix='/docs/api')
app.add_url_rule('/docs/api', 'eve_swagger.index')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['TOKEN_RE'] = re.compile('access_token=([a-zA-Z0-9]+)')
app.config['TASK_RE'] = re.compile('"task":"(.*?)"')
app.config.from_envvar('MINDR_CFG_PATH')
CORS(app)

roll_n = app.config['ROLL_N']

# variables for image selection
test_thresh = app.config['TEST_THRESH']
test_per_train = app.config['TEST_PER_TRAIN']
train_repeat = app.config['TRAIN_REPEAT']

def get_ave(x):
    if len(x) == 0:
        return 0
    total = 0.0
    for xi in x:
        total += xi
    return total/len(x)

def get_cfx_mat(truth, attempt, totaln):
    x = deepcopy(truth)
    y = deepcopy(attempt)
    cm = {}
    rt = 0
    # Run through truth and add to confusion matrix
    for ik, iv in x.items():
        while len(iv) > 0:
            jk, jv = iv.popitem()
            rt += 1
            try:
                yjv = y[ik].pop(jk)
            except KeyError:
                # Change this once we're getting sent the complete try masks
                yjv = jv
            try:
                cm[jv][yjv] += 1
            except KeyError:
                try:
                    cm[jv][yjv] = 1
                except KeyError:
                    cm[jv] = {}
                    cm[jv][yjv] = 1
    # Run through remaining items in attempt and update confusion matrix
    for ik, iv in y.items():
        while len(iv) > 0:
            jk, yjv = iv.popitem()
            rt += 1
            try:
                cm[0][yjv] += 1
            except KeyError:
                try:
                    cm[0][yjv] = 1
                except KeyError:
                    cm[0] = {}
                    cm[0][yjv] = 1
    cm[0][0] = totaln-rt
    return cm


def get_dice(cm):
    """Given a confusion matrix in dictionary form, return dice coefficient"""
    tp = cm[1][1]
    fp = cm[0][1]
    fn = cm[1][0]
    return (2 * tp)/(2 * tp + fp + fn)


def get_totaln(image_id):
    images = app.data.driver.db['image']
    img = images.find_one({'_id': ObjectId('image_id')})
    img = Image.open(BytesIO(base64.b64decode(img['pic'])))
    return img.height * img.width

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
                 '$set': {'ave_score': (a['total_score'] + i['score']) / (a['n_try'] + 1),
                          'roll_scores': updt_rs,
                          'roll_ave_score': get_ave(updt_rs)}}
            )
        # Increment user test counter
        if i['mode'] == 'test':
            users = app.data.driver.db['user']
            users.update_one(
                {'_id': ObjectId(i['user_id'])},
                {'$inc': {'n_subs': 1, 'n_test': 1}}
            )


def get_seen_images(user_id, mode, task):
    masks = app.data.driver.db['mask']
    pipeline = [{'$match': {'user_id': ObjectId(user_id),
                            'mode': mode,
                            'task': task}},
                {'$group': {'_id': '$image_id', 'count': {'$sum': 1}}}]

    seen_images = pd.DataFrame([r for r in masks.aggregate(pipeline)], columns=['_id', 'count'])
    seen_ids = list(seen_images['_id'].values)
    return seen_images, seen_ids




def pre_image_get_callback(request, lookup):
    """Decide if the user will get a train or test image
    if train, decide if user will get a repeated image,
    if not repeated, try to give the user a novel training image"""

    try:
        user_id = request.args['user_id']
        token = request.args['token']
        try:
            task = re.findall(app.config['TASK_RE'], request.args['where'])[0]
        except IndexError as e:
            raise type(e)(str(e)+request.args['where'])
    except KeyError:
        # raise type(e)(str(e)+request.args['where'])
        return None

    users = app.data.driver.db['user']
    images = app.data.driver.db['image']
    a = users.find_one({'_id': ObjectId(user_id), 'token': token})
    # Decide if user will get a train or test image
    if (a['roll_ave_score'] >= test_thresh) & (randint(1, test_per_train+1) < test_per_train):
        raise IndexError("test")

        # Getting a novel test image if possible
        mode = 'test'
        imode = 'test'
        seen_images, seen_ids = get_seen_images(user_id, mode, task)

        unseen_images = images.find({'_id': {'$nin': seen_ids},
                                     'mode': imode,
                                     'task': task},
                                    {'_id': 1})
        unseen_images = [r['_id'] for r in unseen_images]

        if len(unseen_images) > 0:
            lookup['_id'] = {'$nin': unseen_images}
            lookup['mode'] = imode
        else:
            least_seen = list(seen_images.loc[seen_images['count'] == seen_images['count'].min(), '_id'].values)
            lookup['_id'] = {'$in': least_seen}
            lookup['mode'] = imode

    elif randint(1, train_repeat+1) == train_repeat:
        # Getting a repeated training image
        mode = 'try'
        imode = 'train'
        seen_images, seen_ids = get_seen_images(user_id, mode, task)
        if len(seen_ids) > 0:
            raise Warning("train repeated seen_ids gt 0"+str(seen_ids))
            lookup['_id'] = {'$in': seen_ids}
            lookup['mode'] = imode
        else:
            raise Warning("train repeated seen_ids eq 0"+str(lookup))
            lookup['mode'] = imode

    else:
        # Getting a novel training image if possible
        # If not, get a training image they've seen the fewest number of times
        # Find the images a user has seen
        mode = 'try'
        imode = 'train'
        seen_images, seen_ids = get_seen_images(user_id, mode, task)
        raise Warning("what's going on with seen images"+str(seen_ids))
        unseen_images = images.find({'_id': {'$nin': seen_ids},
                                     'mode': imode,
                                     'task': task},
                                    {'_id': 1})
        unseen_images = [r['_id'] for r in unseen_images]

        if len(unseen_images) > 0:
            raise Warning("train new unseen gt 0"+str(unseen_images))
            lookup['_id'] = {'$nin': seen_ids}
            lookup['mode'] = imode
        else:
            least_seen = list(seen_images.loc[seen_images['count'] == seen_images['count'].min(), '_id'].values)
            raise Warning("train new unseen eq 0"+str(least_seen))
            lookup['_id'] = {'$in': least_seen}
            lookup['mode'] = imode
    


app.on_insert_mask += on_insert_mask
app.on_pre_GET_image += pre_image_get_callback

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
    token = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
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

@app.route('/api/authenticatenew/<logintype>/<provider>/<code>')
def authenticatenew(logintype, provider, code):
    provider = provider.upper()
    logintype = logintype.lower()
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
    token = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
    user_dat['id'] = str(user_dat['id'])
    users = app.data.driver.db[logintype]
    if users.find_one({'username': user_dat['login'], 'oa_id': user_dat['id']}) is not None:
        users.update_one(
            {'username': user_dat['login'], 'oa_id': user_dat['id']},
            {'$set': {'token': token,
                      'avatar': user_dat['avatar_url']}},
            upsert=True
            )
    elif logintype == 'user':
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
    elif logintype == 'researcher':
        users.update_one(
            {'username': user_dat['login'], 'oa_id': user_dat['id']},
            {'$set': {'token': token,
                      'avatar': user_dat['avatar_url']}},
            upsert=True)
    return jsonify({'token': token})

@app.route('/api/logout/')


def get_profile(provider, token):
    ur = requests.get(app.config[provider+'_USER_URL'],
                      headers={'authorization': 'token ' + token})
    print(ur.text)
    return ur.json()


if __name__ == '__main__':
    app.run(host='0.0.0.0')
