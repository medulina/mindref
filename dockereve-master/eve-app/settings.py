"""
    modified from eve-demo settings
    ~~~~~~~~~~~~~~~~~

    Settings file for our little demo.

    PLEASE NOTE: We don't need to create the two collections in MongoDB.
    Actually, we don't even need to create the database: GET requests on an
    empty/non-existant DB will be served correctly ('200' OK with an empty
    collection); DELETE/PATCH will receive appropriate responses ('404' Not
    Found), and POST requests will create database and collections when needed.
    Keep in mind however that such an auto-managed database will most likely
    perform poorly since it lacks any sort of optimized index.

    :copyright: (c) 2016 by Nicola Iarocci.
    :license: BSD, see LICENSE for more details.
"""

import os
from copy import deepcopy


# Our API will expose two resources (MongoDB collections): 'people' and
# 'works'. In order to allow for proper data validation, we define beaviour
# and structure.
image_schema = {
    'slice_direction': {'type': 'string', 'allowed': ['ax', 'cor', 'sag']},
    'task': {
        'type': 'string',
        'minlength': 1,
        'maxlength': 50,
    },
    'subject': {
        'type': 'string',
        'minlength': 1,
        'maxlength': 50,
    },
    'slice': {
        'type': 'integer',
        'min': -10000,
        'max': 10000,
    },
    'pic': {
        'type': 'media',
    },
}

mask_schema = {
    'owner': {
                'type': 'objectid',
                'required': True,
                'data_relation': {
                    'resource': 'image',
                    'embeddable': True
                },
            },
    'pic': {
        'type': 'media',
    },
}


settings = {
    'URL_PREFIX': 'api',
    'API_VERSION': 'v1',
    'ALLOWED_FILTERS': ['*'],
    'MONGO_HOST': os.environ.get('MONGODB_HOST', ''),
    'MONGO_PORT': os.environ.get('MONGODB_PORT', ''),
    'MONGO_DBNAME': 'mriqc_api',
    'PUBLIC_METHODS': ['GET'],
    'PUBLIC_ITEM_METHODS': ['GET'],
    'RESOURCE_METHODS': ['GET', 'POST'],
    'ITEM_METHODS': ['GET'],
    'X_DOMAINS': '*',
    'DOMAIN': {
        'image': {
            'item_title': 'image',
        },
        'mask': {
            'item_title': 'mask',
        },

    }
}

settings['DOMAIN']['image']['schema'] = deepcopy(image_schema)
settings['DOMAIN']['mask']['schema'] = deepcopy(mask_schema)