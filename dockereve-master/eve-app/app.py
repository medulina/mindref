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
from bson.errors import InvalidId
from flask import request
from flask.json import jsonify
from flask_cors import CORS
import bcrypt
from numpy.random import randint, choice
from flask import abort, request
from pymongo import ASCENDING, DESCENDING


API_TOKEN = os.environ.get("API_TOKEN")

class TokenAuth(TokenAuth):
    def check_auth(self, token, allowed_roles, resource, method):
        return token == API_TOKEN

class UserAuth(BasicAuth):
    def check_auth(self, username, password, allowed_roles, resource, method):
        up = app.data.driver.db['user_private']
        user = up.find_one({'_id': ObjectId(username)})
        res = user and user['token'] == password
        #raise Exception(f"submitted_username: {username}\nsubmitted_password: {password}\nUser: {user}\nres: {res}")
        return res


#settings['DOMAIN']['mask']['authentication'] = UserAuth
settings['DOMAIN']['mask']['public_methods'] = ['GET']
settings['DOMAIN']['mask']['public_item_methods'] = ['GET']
settings['DOMAIN']['mask']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['user']['authentication'] = UserAuth
settings['DOMAIN']['user']['public_methods'] = ['GET']
settings['DOMAIN']['user']['public_item_methods'] = ['GET']
settings['DOMAIN']['user']['resource_methods'] = ['GET']
settings['DOMAIN']['user']['item_methods'] = ['GET', 'PATCH']


settings['DOMAIN']['image']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['project']['resource_methods'] = ['GET', 'POST']

settings['DOMAIN']['researcher']['resource_methods'] = ['GET']
settings['DOMAIN']['researcher']['item_methods'] = ['GET']


#app = Eve(settings=settings, auth=TokenAuth)
app = Eve(settings=settings)
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

def update_score(mask):
    # update a users score given a mask
    users = app.data.driver.db['user']
    user = users.find_one({'user_id': ObjectId(mask['user_id'])})
    if len(user) == 0:
        raise Exception("No user found with user_id %s"%mask['user_id'])
    scores = app.data.driver.db['score']
    ups = scores.find_one({'user_project_id': str(mask['user_id'])+'__'+mask['task']})
    try:
        user_anon = user['anonymous']
    except KeyError:
        user_anon = False

    if (not user['has_consented']) and (mask['mode'] == 'test'):
        abort(403)
    elif (not user['has_consented']) and (mask['mode'] == 'try'):
        mask['consent'] = False
    elif (user['has_consented']) and (mask['mode'] == 'try'):
        updated_roll = roll_scores(user, mask['score'])
        users.update_one(
            {'user_id': ObjectId(mask['user_id'])},
            {'$inc': {'n_subs': 1, 'n_try': 1, 'total_score': mask['score']},
             '$set': {'ave_score': (user['total_score'] + mask['score']) / (user['n_try'] + 1),
                      'roll_scores': updated_roll,
                      'roll_ave_score': get_ave(updated_roll)}}
        )

        try:
            updated_ups_roll = roll_scores(ups, mask['score'])
            scores.update_one(
                {'user_project_id': ups['user_project_id']},
                {'$inc': {'n_subs': 1, 'n_try': 1, 'total_score': mask['score']},
                 '$set': {'ave_score': (ups['total_score'] + mask['score']) / (ups['n_try'] + 1),
                          'roll_scores': updated_ups_roll,
                          'roll_ave_score': get_ave(updated_ups_roll),
                          'nickname': user['nickname'],
                          'anonymous': user_anon}}
            )
        # If find_one returns None, initialize the score record
        except AttributeError:
            ups = {}
            ups['user_project_id'] = str(mask['user_id'])+'__'+mask['task']
            ups['user'] = mask['user_id']
            ups['nickname'] = user['nickname']
            ups['task'] = mask['task']
            ups['n_subs'] = 1
            ups['n_try'] = 1
            ups['n_test'] = 0
            ups['total_score'] = 0
            ups['ave_score'] = mask['score']
            ups['roll_scores'] = [mask['score']]
            ups['roll_ave_score'] = mask['score']
            ups['anonymous'] = user_anon
            scores.insert_one(ups)
    elif (user['has_consented']) and (mask['mode'] == 'test'):
        users.update_one(
            {'user_id': ObjectId(mask['user_id'])},
            {'$inc': {'n_subs': 1, 'n_test': 1}}
            )

        if len(ups) > 0:
            scores.update_one(
                {'user_project_id': str(mask['user_id'])+'__'+mask['task']},
                {'$inc': {'n_subs': 1, 'n_test': 1},
                 '$set': {'anonymous': user_anon,
                          'nickname': user['nickname']}}
            )
        else:
            ups = {}
            ups['user_project_id'] = str(mask['user_id'])+'__'+mask['task']
            ups['user'] = mask['user_id']
            ups['nickname'] = user['nickname']
            ups['task'] = mask['task']
            ups['n_subs'] = 1
            ups['n_try'] = 0
            ups['n_test'] = 1
            ups['total_score'] = 0
            ups['ave_score'] = 0
            ups['roll_scores'] = []
            ups['roll_ave_score'] = 0
            ups['anonymous'] = user_anon
            scores.insert_one(ups)

def on_insert_mask(items):
    for i in items:
        i['image_id_str'] = str(i['image_id'])
        # Convert encode string as json
        if isinstance(i['pic'], str):
            i['pic'] = json.loads(i['pic'])
        # Pull the image for that mask and see if it's set to training or test
        images = app.data.driver.db['image']
        image = images.find_one({'_id': i['image_id']})
        if image['mode'] == 'test' and i['mode'] == 'try':
            i['mode'] = 'test'
        # For attempts on training data, add a score to the mask
        if i['mode'] == 'try':
            # Find the truth
            masks = app.data.driver.db['mask']
            truth = masks.find_one({'image_id': ObjectId(i['image_id']), 'mode': 'truth'})

            # Score the attempt
            cm = get_cfx_mat(truth['pic'], i['pic'])
            i['score'] = get_dice(cm)
            update_score(i)
        

def get_seen_images(lookup):
    gsi_lookup = lookup.copy()
    if gsi_lookup['mode'] == 'train':
        gsi_lookup['mode'] = 'try'
    masks = app.data.driver.db['mask']
    pipeline = [{'$match': lookup},
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
        #task = request.args['task']
        try:
            prev_img_id = ObjectId(request.args['prev_img_id'])
        except InvalidId:
            prev_img_id = None
        try:
            task = re.findall(app.config['TASK_RE'], request.args['where'])[0]
        except IndexError as e:
            raise type(e)(str(e)+request.args['where'])
    except KeyError:
        # raise type(e)(str(e)+request.args['where'])
        return None
    
    scores = app.data.driver.db['score']
    users = app.data.driver.db['user']
    images = app.data.driver.db['image']
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
    test_elligible = ((ups['roll_ave_score'] >= test_thresh)
                      and (len(ups['roll_scores']) >= roll_n)
                      and (train_roll < test_per_train))

    imode_dict = {True: 'test', False: 'train'}
    imode = imode_dict[test_elligible]

    # Try to find an image with the right mode
    lookup['task'] = task
    lookup['mode'] = imode
    if prev_img_id:
        lookup['id'] = {'$ne': prev_img_id}
    
    if not images.find_one(lookup):
        # If there isn't an image with the right mode
        # Try to get an image with the other mode
        test_elligible = not test_elligible
        imode = imode_dict[test_elligible]
        lookup['mode'] = imode
        if not images.find_one(lookup):
            # Can't get an image in either case, give up
            abort(404)

    # Should we send them a repeated test image
    if (not test_elligible) and (randint(1, train_repeat+1) == train_repeat):
        # give a repeated image
        seen_images, seen_ids = get_seen_images(lookup)
        if len(seen_ids) > 0:
            lookup['_id'] = ObjectId(choice(seen_ids, 1)[0])
            return None

    # If we're not repeating give them an unseen image
    seen_images, seen_ids = get_seen_images(lookup)
    unseen_lookup = lookup.copy()
    unseen_lookup['_id'] = {'$ne': seen_ids + [prev_img_id]}
    unseen_images = images.find(unseen_lookup)
    unseen_images = [r['_id'] for r in unseen_images]
    if len(unseen_images) > 0:
        lookup['_id'] = ObjectId(choice(unseen_images, 1)[0])
    else:
        # If we can't give them an unseen image give them a least seen image
        least_seen = list(seen_images.loc[seen_images['count'] == seen_images['count'].min(), '_id'].values)
        lookup['_id'] = choice(least_seen, 1)[0]

    if (images.find_one(lookup) is None) or (images.find_one(lookup)['_id'] == prev_img_id):
        raise Exception(lookup)
    

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
    try:
        mask_id = resp['_id']
    except KeyError:
        return None
    masks = app.data.driver.db['mask']
    mask = masks.find_one({'_id': ObjectId(mask_id)})
    # If the mask doesn't have a score, don't return masks
    try:
        resp['score'] = mask['score']
    except KeyError:
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
    
    try:
        if mask['consent'] is False:
            masks.delete_one({'_id': ObjectId(mask_id)})
    except KeyError:
        pass

def sum_masks(mask_list, prepend=''):
    # need to be able to prepend a character to make it valid xml
    res = {}
    for m in mask_list:
        for ik, iv in m.items():
            ik = prepend+ik
            for jk, jv in iv.items():
                jk = prepend+jk
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

def pre_get_maskagg(request, lookup):
    raise Exception(request, lookup)

def post_get_maskagg(request, payload):
    #response payload may be xml or json, just return the xml if it's an xml request
    try:
        resp = json.loads(payload.response[0].decode("utf-8"))
        image_id = resp['_items'][0]['_id']
        masks = app.data.driver.db['mask']
        mask_list = [m['pic'] for m in masks.find({'image_id': ObjectId(image_id), 'mode': {'$ne': 'truth'}})]
        mask_sum = sum_masks(mask_list)
        resp['mask_sum'] = mask_sum
        payload.response[0] = json.dumps(resp).encode()
        payload.headers['Content-Length'] = len(payload.response[0])
    except (json.decoder.JSONDecodeError, IndexError):
        pass

def on_updated_user(updates, original):
    try:
        scores = app.data.driver.db['score']
        scores.update_many({'user_id': ObjectId(original['user_id'])},
                           {'$set': {'nickname': updates['nickname']}})
    except KeyError:
        pass

app.on_insert_mask += on_insert_mask
app.on_pre_GET_image += pre_image_get_callback
app.on_post_POST_mask += post_post_mask
#app.on_pre_GET_maskagg += pre_get_maskagg
app.on_post_GET_maskagg += post_get_maskagg
app.on_updated_user += on_updated_user

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
        #raise Exception(tr.text)
        abort(403)

    # Process data from Oauth provider
    user_dat = get_profile(provider, token)
    token = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
    user_dat['id'] = str(user_dat['id'])
    try:
        user_dat['email'] = str(user_dat['email'])
    except KeyError:
        user_dat['email'] = None

    users = app.data.driver.db['user']
    up = app.data.driver.db['user_private']
    masks = app.data.driver.db['mask']
    scores = app.data.driver.db['score']
    transfer_tokens = app.data.driver.db['transfer_token']
    # If the user exists, set their Oauth provider data
    # transerf all makss from transfer user id to user
    # update scores
    # delete transfer user id user from user and user private
    if up.find_one({'oa_id': user_dat['id'],
                    'provider': app.config[provider+'_ACCESS_TOKEN_URL']}) is not None:

        up.update_one({'oa_id': user_dat['id'],
                       'provider': app.config[provider+'_ACCESS_TOKEN_URL']},
                      {'$set': {'token': token,
                                'avatar': user_dat['avatar_url'],
                                'email': user_dat['email']}})
        user_id = up.find_one({'oa_id': user_dat['id'],
                               'provider': app.config[provider+'_ACCESS_TOKEN_URL']})['_id']
        # Update user-project Scores
        # loop through transfer user scores and update user score and user-project score
        transfer_masks = masks.find({'user_id': ObjectId(transfer_user_id)},
                                    sort=[('_updated', ASCENDING)])
        for tm in transfer_masks:
            tm['user_id'] = user_id
            update_score(tm)

        # Transfer all masks from transfer user id to user_id
        masks.update_many({'user_id': ObjectId(transfer_user_id)},
                          {'$set': {'user_id': user_id}})
        # Delete transfer user id
        users.delete_one({'user_id': ObjectId(transfer_user_id)})
        scores.delete_many({'user_id': ObjectId(transfer_user_id)})

        whichpath = 1

    # If the user doesn't exist
    # And they've got a transfer token, transfer them
    elif (transfer_token is not None) and (transfer_tokens.find_one({'user_id': ObjectId(transfer_user_id)}) is not None):
        tt_record = transfer_tokens.find_one({'user_id': ObjectId(transfer_user_id)})
        if bcrypt.hashpw(transfer_token.encode(), tt_record['transfer_token'].encode()).decode() == tt_record['transfer_token']:
            up.update_one({'_id': ObjectId(transfer_user_id)},
                          {'$set': {'username': user_dat['login'],
                                    'token': token,
                                    'avatar': user_dat['avatar_url'],
                                    'oa_id': user_dat['id'],
                                    'provider': app.config[provider+'_ACCESS_TOKEN_URL'],
                                    'email': user_dat['email']}},
                          upsert=True)
            user_id = ObjectId(transfer_user_id)
            try:
                users.update_one({'user_id': ObjectId(transfer_user_id)},
                                 {'$set': {'use_profile_pic': use_profile_pic,
                                           'anonymous': False,
                                           'has_consented': tt_record['has_consented'],
                                           'email_ok': email_ok}},
                                 upsert=True)
            except KeyError:
                users.update_one({'user_id': ObjectId(transfer_user_id)},
                                 {'$set': {'use_profile_pic': use_profile_pic,
                                           'anonymous': False,
                                           'has_consented': None,
                                           'email_ok': email_ok}},
                                 upsert=True)
            # Update their scores with their nickname
            scores.update_many({'user_id': ObjectId(transfer_user_id)},
                               {'$set': {'anonymous': False}})
            whichpath = 2
  
        else:
            #raise Exception(str(bcrypt.hashpw(transfer_token.encode(),tt_record['transfer_token'].encode())) + ' '  + str(tt_record['transfer_token']))
            abort(403)
    # If the user doesn't exist
    # and they consented, create a new user
    else:
        upsert_res = up.update_one({'oa_id': user_dat['id'],
                       'provider': app.config[provider+'_ACCESS_TOKEN_URL']},
                      {'$set': {'token': token,
                                'avatar': user_dat['avatar_url'],
                                'email': user_dat['email']}},
                      upsert=True)

        user_id = upsert_res.upserted_id
        if user_id is None:
            raise Exception('No record upserted for purportedly new user %s,%s'%(str(user_dat['id']), str(app.config[provider+'_ACCESS_TOKEN_URL'])))
        users.update_one({'oa_id': user_dat['id'],
                          'provider': app.config[provider+'_ACCESS_TOKEN_URL']},
                         {'$set': {'user_id': user_id,
                                   'avatar': None,
                                   'n_subs': 0,
                                   'n_try': 0,
                                   'n_test': 0,
                                   'total_score': 0.0,
                                   'ave_score': 0.0,
                                   'roll_scores': [],
                                   'roll_ave_score': 0.0,
                                   'has_consented': has_consented,
                                   'use_profile_pic': use_profile_pic,
                                   'anonymous': False,
                                   'email_ok': email_ok}},
                         upsert=True)
        whichpath = 3

    return jsonify({'user_id': str(user_id), 'token': token, 'whichpath':whichpath})



@app.route('/api/anonymous')
def anonymous():
    has_consented = None
    use_profile_pic = False
    try:
        if request.args['has_consented'] == 'true':
            has_consented = True
        else:
            has_consented = False
    except KeyError:
        pass
    try:
        if request.args['use_profile_pic'] == 'true':
            use_profile_pic = True
    except KeyError:
        pass

    username = choice(names) + ', the ' + choice(adjs) + ' ' + choice(animals)
    token = secrets.token_urlsafe(64)
    token = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
    transfer_token = secrets.token_urlsafe(64)

    users = app.data.driver.db['user']
    up = app.data.driver.db['user_private']
    transfer_tokens = app.data.driver.db['transfer_token']

    result = up.insert_one({'username': username,
                            'token': token})
    user_id = result.inserted_id
    users.insert_one({'user_id': user_id,
                      'nickname': None,
                      'avatar': None,
                      'n_subs': 0,
                      'n_try': 0,
                      'n_test': 0,
                      'total_score': 0.0,
                      'ave_score': 0.0,
                      'roll_scores': [],
                      'roll_ave_score': 0.0,
                      'has_consented': has_consented,
                      'use_profile_pic': use_profile_pic,
                      'anonymous': True,
                      'email_ok': False})
    transfer_tokens.insert_one({'user_id': user_id,
                               'transfer_token': bcrypt.hashpw(transfer_token.encode(), bcrypt.gensalt()).decode()})
    return jsonify({'token': token,
                    'user_id': str(user_id),
                    'transfer_token': transfer_token})

@app.route('/api/consent')
def consent():
    has_consented = None
    try:
        user_id = str(request.args['user_id'])
    except KeyError:
        user_id = None
    try:
        token = str(request.args['token'])
    except KeyError:
        token = None
    try:
        if request.args['has_consented'] == 'true':
            has_consented = True
        else:
            has_consented = False
    except KeyError:
        pass
    up = app.data.driver.db['user_private']
    users = app.data.driver.db['user']

    up_a = up.find_one({'_id': ObjectId(user_id), 'token': token})
    print("userid", user_id, "token", token)
    if up_a is not None:
        users.update_one(
            {'user_id': up_a['_id']},
            {'$set': {'has_consented': has_consented}}
        )
        return jsonify({'user_id': user_id,
                        'has_consented': has_consented})
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

    return ur.json()


if __name__ == '__main__':
    app.run(host='0.0.0.0')
