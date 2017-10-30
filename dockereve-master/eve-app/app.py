# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:

import os
import sys
import socket
import json
import re
import secrets
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
from flask import request
from flask.json import jsonify
from flask_cors import CORS
import bcrypt
from numpy.random import randint, choice
from flask import abort, request

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

# load wordlists for random user names
with open('words/animals.csv','r') as h:
    animals = [n.strip() for n in h.readlines()]
with open('words/adjs.csv','r') as h:
    adjs = [n.strip() for n in h.readlines()]
with open('words/names.csv','r') as h:
    names = [n.strip() for n in h.readlines()]

def get_ave(x):
    if len(x) == 0:
        return 0
    total = 0.0
    for xi in x:
        total += xi
    return total/len(x)

def get_cfx_mat(truth, attempt, totaln=None):
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
                yjv = 0
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
    if totaln is not None:
        cm[0][0] = totaln-rt
    return cm


def get_dice(cm):
    """Given a confusion matrix in dictionary form, return dice coefficient"""
    try:
        tp = cm[1][1]
    except KeyError:
        tp = 0
    try:
        fp = cm[0][1]
    except KeyError:
        fp = 0
    try:
        fn = cm[1][0]
    except KeyError:
        fn = 0
    return (2 * tp)/(2 * tp + fp + fn)


def get_totaln(image_id):
    images = app.data.driver.db['image']
    img = images.find_one({'_id': ObjectId(image_id)})
    return img.shape[0] * img.shape[1]

def roll_scores(a, score):
    # Deal with growing the rolling score
    if 'roll_scores' not in a.keys():
        a['roll_scores'] = []
    if len(a['roll_scores']) < roll_n:
        updt_rs = a['roll_scores'].copy()
    else:
        updt_rs = a['roll_scores'][1:].copy()
    updt_rs.append(score)
    return updt_rs

def on_insert_mask(items):
    for i in items:
        # Convert encode string as json
        if isinstance(i['pic'], str):
            i['pic'] = json.loads(i['pic'])
        # Pull the image for that mask and see if it's set to training or test
        images = app.data.driver.db['image']
        image = images.find_one({'_id':i['image_id']})
        if image['mode'] == 'test' and i['mode'] == 'try':
            i['mode'] = 'test'
        # For attempts on training data, update users training score
        if i['mode'] == 'try':
            # Find the truth
            masks = app.data.driver.db['mask']
            truth = masks.find_one({'image_id': ObjectId(i['image_id']), 'mode': 'truth'})

            # Score the attempt
            cm = get_cfx_mat(truth['pic'], i['pic'])
            i['score'] = get_dice(cm)

            # Find the user
            users = app.data.driver.db['user']
            a = users.find_one({'_id': ObjectId(i['user_id'])})
            # Update user's rolling score
            updated_roll = roll_scores(a, i['score'])

            # TODO: Verify submission is novel
            # Update user's stats
            users.update_one(
                {'_id': ObjectId(i['user_id'])},
                {'$inc': {'n_subs': 1, 'n_try': 1, 'total_score': i['score']},
                 '$set': {'ave_score': (a['total_score'] + i['score']) / (a['n_try'] + 1),
                          'roll_scores': updated_roll,
                          'roll_ave_score': get_ave(updated_roll)}}
            )

            # Find the user_project_score
            scores = app.data.driver.db['score']
            ups = scores.find_one({'user_project_id': str(i['user_id'])+'__'+i['task']})
            try:
                updated_ups_roll = roll_scores(ups, i['score'])
                scores.update_one(
                    {'user_project_id': ups['user_project_id']},
                    {'$inc': {'n_subs': 1, 'n_try': 1, 'total_score': i['score']},
                     '$set': {'ave_score': (ups['total_score'] + i['score']) / (ups['n_try'] + 1),
                              'roll_scores': updated_ups_roll,
                              'roll_ave_score': get_ave(updated_ups_roll),
                              'username': a['username']}}
                )
            # If find_one returns None, initialize the score record
            except AttributeError:
                ups = {}
                ups['user_project_id'] = str(i['user_id'])+'__'+i['task']
                ups['user'] = i['user_id']
                ups['username'] = a['username']
                ups['task'] = i['task']
                ups['n_subs'] = 1
                ups['n_try'] = 1
                ups['n_test'] = 0
                ups['total_score'] = 0
                ups['ave_score'] = i['score']
                ups['roll_scores'] = [i['score']]
                ups['roll_ave_score'] = i['score']
                scores.insert_one(ups)

        # Increment user test counter
        elif i['mode'] == 'test':
            users = app.data.driver.db['user']
            users.update_one(
                {'_id': ObjectId(i['user_id'])},
                {'$inc': {'n_subs': 1, 'n_test': 1}}
            )

            scores = app.data.driver.db['score']
            ups = scores.find_one({'user_project_id': str(i['user_id'])+'__'+i['task']})
            scores.update_one(
                {'user_project_id': str(i['user_id'])+'__'+i['task']},
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
    #a = users.find_one({'_id': ObjectId(user_id), 'token': token})
    seen_test_images, seen_test_ids = get_seen_images(user_id, 'test', task)

    task_test_images = images.find({'task': task, 'mode': 'test'})
    task_test_images = [r for r in task_test_images]

    scores = app.data.driver.db['score']
    ups = scores.find_one({'user_project_id': str(user_id)+'__'+task})
    if ups is None:
        ups = {}
        ups['user_project_id'] = str(user_id)+'__'+task
        ups['user'] = user_id
        ups['task'] = task
        ups['n_subs'] = 0
        ups['n_try'] = 0
        ups['n_test'] = 0
        ups['total_score'] = 0
        ups['ave_score'] = 0
        ups['roll_scores'] = []
        ups['roll_ave_score'] = 0
        scores.insert_one(ups)

    train_roll = randint(1, test_per_train+1)

    # Decide if user will get a train or test image
    if (ups['roll_ave_score'] >= test_thresh) & (train_roll < test_per_train) & (len(task_test_images) > 0):

        # Getting a novel test image if possible
        mode = 'test'
        imode = 'test'

        unseen_images = images.find({'_id': {'$nin': seen_test_ids},
                                     'mode': imode,
                                     'task': task},
                                    {'_id': 1})
        unseen_images = [r['_id'] for r in unseen_images]

        if len(unseen_images) > 0:
            lookup['_id'] = ObjectId(choice(unseen_images, 1)[0])
            lookup['mode'] = imode
            if images.find_one({'_id':lookup['_id'], 'mode':lookup['mode']}) is None:
                raise Exception("Image id %s not found. Image ID was looked up from the unseen test images"%lookup['_id'])
            
        else:
            least_seen = list(seen_test_images.loc[seen_test_images['count'] == seen_test_images['count'].min(), '_id'].values)
            lookup['_id'] = ObjectId(choice(least_seen, 1)[0])
            lookup['mode'] = imode
            if images.find_one({'_id':lookup['_id'], 'mode':lookup['mode']}) is None:
                raise Exception("Image id %s not found. Image ID was looked up from the least seen test images"%lookup['_id'])
            

    elif randint(1, train_repeat+1) == train_repeat:
        # Getting a repeated training image
        mode = 'try'
        imode = 'train'
        seen_images, seen_ids = get_seen_images(user_id, mode, task)

        if len(seen_ids) > 0:
            lookup['_id'] = ObjectId(choice(seen_ids, 1)[0])
            lookup['mode'] = imode
            if images.find_one({'_id':lookup['_id'], 'mode':lookup['mode']}) is None:
                raise Exception("I have a mask for this image, but I can't find the image anymore. Repeat.")
        else:
            lookup['mode'] = imode

    else:
        # Getting a novel training image if possible
        # If not, get a training image they've seen the fewest number of times
        # Find the images a user has seen
        mode = 'try'
        imode = 'train'
        seen_images, seen_ids = get_seen_images(user_id, mode, task)
        unseen_images = images.find({'_id': {'$nin': seen_ids},
                                     'mode': imode,
                                     'task': task},
                                    {'_id': 1})
        unseen_images = [r['_id'] for r in unseen_images]
        if len(unseen_images) > 0:
            lookup['_id'] = choice(unseen_images, 1)[0]
            lookup['mode'] = imode
            if images.find_one({'_id':lookup['_id'], 'mode':lookup['mode']}) is None:
                raise Exception("Image id %s not found. Image ID was looked up from the unseen training images"%lookup['_id'])
        elif len(seen_ids) == 0:
            raise Exception("Seen Ids and Unseen Ids are both empty. FML.")
        else:
            least_seen = list(seen_images.loc[seen_images['count'] == seen_images['count'].min(), '_id'].values)
            lookup['_id'] = choice(least_seen, 1)[0]
            lookup['mode'] = imode
            if images.find_one({'_id':lookup['_id'], 'mode':lookup['mode']}) is None:
                raise Exception("I have a mask for this image, but I can't find the image anymore. Least Seen")
    #raise Warning(str(lookup))

def get_cfx_masks(truth, attempt):
    x = deepcopy(truth)
    y = deepcopy(attempt)
    cm = {}
    # Run through truth and add to confusion matrix mask
    for ik, iv in x.items():
        while len(iv) > 0:
            jk, jv = iv.popitem()
            try:
                yjv = y[ik].pop(jk)
            except KeyError:
                yjv = 0
            # Instatiate the mask dict for this combination of truth
            # and try values
            try:
                target_mask = cm[jv][yjv]
            except KeyError:
                try:
                    cm[jv][yjv] = {}
                    target_mask = cm[jv][yjv]
                except KeyError:
                    cm[jv] = {}
                    cm[jv][yjv] = {}
                    target_mask = cm[jv][yjv]
            try:
                #mask for true value, test value, ik, jk = 1
                target_mask[ik][jk] = 1
            except KeyError:
                #If ik doesn't exist, create the dict
                target_mask[ik] = {}
                target_mask[ik][jk] = 1
    # Run through try and add items not in truth to confustion matrix mask
    for ik, iv in y.items():
        while len(iv) > 0:
            jk, yjv = iv.popitem()
            # Instatiate the mask dict for this combination of truth
            # and try values
            try:
                target_mask = cm[0][yjv]
            except KeyError:
                try:
                    cm[0][yjv] = {}
                    target_mask = cm[0][yjv]
                except KeyError:
                    cm[0] = {}
                    cm[0][yjv] = {}
                    target_mask = cm[0][yjv]
            try:
                # mask for true value, test value, ik, jk = 1
                target_mask[ik][jk] = 1
            except KeyError:
                # If ik doesn't exist, create the dict
                target_mask[ik] = {}
                target_mask[ik][jk] = 1
    return cm

def post_post_mask(request, payload):
    resp = json.loads(payload.response[0].decode("utf-8"))
    mask_id = resp['_id']
    masks = app.data.driver.db['mask']
    mask = masks.find_one({'_id': ObjectId(mask_id)})
    # If the mask doesn't have a score, don't return masks
    try:
        resp['score'] = mask['score']
    except:
        return None
    truth = masks.find_one({'image_id': ObjectId(mask['image_id']), 'mode': 'truth'})
    cm = get_cfx_masks(truth['pic'], mask['pic'])
    # TODO: Make this code work for multiclass
    try: 
        resp['tp'] = cm[1][1]
    except KeyError:
        resp['tp'] = {}
    try:
        resp['fp'] = cm[0][1]
    except KeyError:
        resp['fp'] = {}
    try:
        resp['fn'] = cm[1][0]
    except KeyError:
        resp['fn'] = {}
    payload.response[0] = json.dumps(resp).encode()
    payload.headers['Content-Length'] = len(payload.response[0])

def sum_masks(mask_list):
    res = {}
    for m in mask_list:
        for ik, iv in m.items():
            for jk, jv in iv.items():
                if jv > 0:
                    try:
                        res[ik][jk] += jv
                    except KeyError:
                        try:
                            res[ik][jk] = jv
                        except KeyError:
                            res[ik] = {}
                            res[ik][jk] = jv
    return res

def post_get_maskagg(request, payload):
    resp = json.loads(payload.response[0].decode("utf-8"))
    image_id = resp['_items'][0]['_id']
    masks = app.data.driver.db['mask']
    mask_list = [m['pic'] for m in masks.find({'image_id': ObjectId(image_id), 'mode': 'try'})]
    mask_sum = sum_masks(mask_list)
    resp['mask_sum'] = mask_sum
    payload.response[0] = json.dumps(resp).encode()
    payload.headers['Content-Length'] = len(payload.response[0])



app.on_insert_mask += on_insert_mask
app.on_pre_GET_image += pre_image_get_callback
app.on_post_POST_mask += post_post_mask
app.on_post_GET_maskagg += post_get_maskagg

# required. See http://swagger.io/specification/#infoObject for details.
app.config['SWAGGER_INFO'] = {
    'title': 'Medulina Web API',
    'version': 'v1'
}


@app.route('/api/authenticate/<domain>/<provider>/<code>')
def authenticate(domain, provider, code):
    # Get args and set default values
    has_consented = None
    use_profile_pic = False
    email_ok = False
    try:
        transfer_user_id = str(request.args['transfer_user_id'])
    except KeyError:
        transfer_user_id = None
    try:
        transfer_token = str(request.args['transfer_token'])
    except KeyError:
        transfer_token = None
    try:
        nickname = str(request.args['nickname'])
    except KeyError:
        nickname = None
    try:
        if request.args['has_consented'] == 'true':
            has_consented = True
    except KeyError:
        pass
    try:
        if request.args['use_profile_pic'] == 'true':
            use_profile_pic = True
    except KeyError:
        pass
    try:
        if request.args['email_ok'] == 'true':
            email_ok = True
    except KeyError:
        pass

    provider = provider.upper()
    domain = domain.upper()
    data = {'client_id': app.config[domain+provider+'_CLIENT_ID'],
            'client_secret': app.config[domain+provider+'_CLIENT_SECRET'],
            'code': code}
    tr = requests.post(app.config[provider+'_ACCESS_TOKEN_URL'], data=data)

    try:
        token = re.findall(app.config['TOKEN_RE'], tr.text)[0]
    except IndexError:
        return tr.text
    user_dat = get_profile(provider, token)
    token = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
    user_dat['id'] = str(user_dat['id'])


    users = app.data.driver.db['user']
    transfer_tokens = app.data.driver.db['transfer_token']
    # If the user exists, set their token
    if users.find_one({'oa_id': user_dat['id'],
                       'provider': app.config[provider+'_ACCESS_TOKEN_URL']}) is not None:
        users.update_one({'oa_id': user_dat['id'],
                          'provider': app.config[provider+'_ACCESS_TOKEN_URL']},
                         {'$set': {'token': token,
                                   'avatar': user_dat['avatar_url']}},
                         upsert=True)
    # If the user doesn't exist
    # And they've got a transfer token, transfer them

    elif (transfer_token is not None) and (transfer_tokens.find_one({'user_id': ObjectId(transfer_user_id)}) is not None):
        tt_record = transfer_tokens.find_one({'user_id': transfer_user_id})
        if bcrypt.hashpw(transfer_token, tt_record['transfer_token']) == tt_record['transfer_token']:
            if nickname is not None:
                user_dat['login'] = nickname
            users.update_one({'_id': ObjectId(transfer_user_id)},
                             {'$set': {'username': user_dat['login'],
                                       'token': token,
                                       'avatar': user_dat['avatar_url'],
                                       'oa_id': user_dat['id'],
                                       'provider': app.config[provider+'_ACCESS_TOKEN_URL'],
                                       'use_profile_pic': use_profile_pic,
                                       'email_ok': email_ok}})
        else:
            abort(403)
    # If the user doesn't exist
    # and they consented, create a new user
    elif has_consented is True:
        if nickname is not None:
            user_dat['login'] = nickname
        users.update_one({'oa_id': user_dat['id'],
                          'provider': app.config[provider+'_ACCESS_TOKEN_URL']},
                         {'$set': {'token': token,
                                   'username': user_dat['login'],
                                   'avatar': user_dat['avatar_url'],
                                   'n_subs': 0,
                                   'n_try': 0,
                                   'n_test': 0,
                                   'total_score': 0.0,
                                   'ave_score': 0.0,
                                   'roll_scores': [],
                                   'roll_ave_score': 0.0,
                                   'has_consented': has_consented,
                                   'use_profile_pic': use_profile_pic,
                                   'email_ok': email_ok}},
                         upsert=True)
    else:
        abort(403)
    return jsonify({'token': token})


@app.route('/api/anonymous')
def anonymous():
    has_consented = None
    use_profile_pic = False
    try:
        if request.args['has_consented'] == 'true':
            has_consented = True
    except KeyError:
        pass
    try:
        if request.args['use_profile_pic'] == 'true':
            use_profile_pic = True
    except KeyError:
        pass

    if has_consented is True:
        username = choice(names) + ', the ' + choice(adjs) + ' ' + choice(animals)
        token = secrets.token_urlsafe(64)
        token = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
        transfer_token = secrets.token_urlsafe(64)

        users = app.data.driver.db['user']
        transfer_tokens = app.data.driver.db['transfer_token']

        result = users.insert_one({'username': username,
                                   'token': token,
                                   'n_subs': 0,
                                   'n_try': 0,
                                   'n_test': 0,
                                   'total_score': 0.0,
                                   'ave_score': 0.0,
                                   'roll_scores': [],
                                   'roll_ave_score': 0.0,
                                   'has_consented': has_consented,
                                   'use_profile_pic': use_profile_pic})
        transfer_tokens.insert_one({'user_id': result.inserted_id,
                                   'transfer_token': bcrypt.hashpw(transfer_token.encode(), bcrypt.gensalt()).decode()})
        return jsonify({'token': token,
                        'user_id': str(result.inserted_id),
                        'tranfer_token': transfer_token})
    else:
        abort(403)

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
