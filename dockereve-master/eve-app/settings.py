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
import json
from copy import deepcopy
from bson.objectid import ObjectId


def key_type(d, t=int):
    try:
        kt = [isinstance(t(k), t) for k in d.keys()]
    except ValueError:
        return False
    return sum(kt) == len(kt)


def value_type(d, t=dict):
    kt = [isinstance(k, t) for k in d.values()]
    return sum(kt) == len(kt)


def mask_json(field, value, error):
    if isinstance(value, str):
        try:
            jv = json.loads(value)
        except json.JSONDecodeError as e:
            error(field, "If a string is posted as the mask, it must be decodable to a JSON. JSON decoding failed with the following error: %s"%e)
    elif isinstance(value, dict):
        jv = value
    else:
        error(field, "The mask must be a json dict of dicts or a string that can be decoded to a JSON")

    if not key_type(jv):
        error(field, "Must be a dict with int keys")
    if not value_type(jv):
        error(field, "Must be a dict of dicts")
    kv = [key_type(v) for v in jv.values()]
    if not sum(kv) == len(kv):
        error(field, "Nested dict should have integer keys")
    kvv = [value_type(v, int) for v in jv.values()]
    if not sum(kvv) == len(kvv):
        error(field, "Values of nested dict should all be integers")

# Our API will expose three resources (MongoDB collections): 'image' and 'mask'.
# In order to allow for proper data validation, we define beaviour
# and structure.
image_schema = {
    'slice_direction': {
        'type': 'string',
        'allowed': ['ax', 'cor', 'sag']
    },
    'mode': {
        'type': 'string',
        'allowed': ['test', 'train'],
        'required': True
    },
    'task': {
        'type': 'string',
        'minlength': 1,
        'maxlength': 50,
        'required': True
    },
    'subject': {
        'type': 'string',
        'minlength': 1,
        'maxlength': 50,
    },
    'session': {
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
    'image_hash': {
        'type': 'string',
        'unique': True
    },
    'context': {
        'type': 'media'
    },
    'shape': {
        'type': 'list',
        'schema': {
            'type': 'float',
        }
    }
}

mask_schema = {
    'image_id': {
        'type': 'objectid',
        'required': True,
        'data_relation': {
            'resource': 'image',
            'field': '_id',
            'embeddable': True
        },
    },
    'user_id': {
        'type': 'objectid',
        #'required': True,
        'data_relation': {
            'resource': 'user',
            'field': '_id',
            'embeddable': True
        },
    },
    'mode': {
        'type': 'string',
        'allowed': ['test', 'truth', 'try'],
        'required': True
    },
    'score': {
        'type': 'float'
    },
    'pic': {
        'validator': mask_json,
    },
    'user_agent': {
        'type': 'string'
    },
    'resolution': {
        'type': 'list',
        'schema': {
            'type': 'float',
            }},
    'task': {
        'type': 'string',
        'minlength': 1,
        'maxlength': 50,
        'required': True
    },
    'time': {
    'type': 'float',
    'min': 0.0
    }
}

mask_agg = {}

user_schema = {
    'username': {
        'type': 'string',
        'required': True
    },
    'token': {
        'type': 'string'
    },
    'avatar': {
        'type': 'string',
    },
    'oa_id': {
        'type': 'string',
    },
    'n_subs': {
        'type': 'integer',
        'default': 0,
        'readonly': True
    },
    'n_try': {
        'type': 'integer',
        'default': 0,
        'readonly': True
    },
    'n_test': {
        'type': 'integer',
        'default': 0,
        'readonly': True
    },
    'total_score': {
        'type': 'float',
        'default': 0.0,
        'readonly': True
    },
    'ave_score': {
        'type': 'float',
        'default': 0.0,
        'readonly': True
    },
    'roll_scores': {
        'type': 'list',
        'schema': {
            'type': 'float',
        },
        'default': [],
        'readonly': True
    },
    'roll_ave_score': {
        'type': 'float',
        'default': 0.0,
        'readonly': True
    }
}

score_schema = {
    'user_project_id': {
        'type': 'string',
        'required': True,
        'unique': True
    },
    'user_id': {
        'type': 'objectid',
        #'required': True,
        'data_relation': {
            'resource': 'user',
            'field': '_id',
            'embeddable': True
        },
    },
    'username': {
        'type': 'string',
        #'required': True,
        'data_relation': {
            'resource': 'user',
            'field': 'username',
            'embeddable': True
        },
    },
    'task': {
        'type': 'string',
        'minlength': 1,
        'maxlength': 50,
        'required': True
    },
    'n_subs': {
        'type': 'integer',
        'default': 0,
        'readonly': True
    },
    'n_try': {
        'type': 'integer',
        'default': 0,
        'readonly': True
    },
    'n_test': {
        'type': 'integer',
        'default': 0,
        'readonly': True
    },
    'total_score': {
        'type': 'float',
        'default': 0.0,
        'readonly': True
    },
    'ave_score': {
        'type': 'float',
        'default': 0.0,
        'readonly': True
    },
    'roll_scores': {
        'type': 'list',
        'schema': {
            'type': 'float',
        },
        'default': [],
        'readonly': True
    },
    'roll_ave_score': {
        'type': 'float',
        'default': 0.0,
        'readonly': True
    }
}

researcher_schema = {
    'username': {
        'type': 'string',
        'required': True
    },
    'token': {
        'type': 'string'
    },
    'avatar': {
        'type': 'string',
    },
    'oa_id': {
        'type': 'string',
    }
}

project_schema = {
    'name': {
        'type': 'string',
        'unique': True
    },
    'url': {
        'type': 'string'
    },
    'images': {
        'type': 'list',
        'schema': {
            'image_id': {
                'type': 'objectid',
                'data_relation': {
                    'resource': 'image',
                    'embeddable': True
                },
            }
        }
    },
    'managers': {
        'type': 'list',
        'schema': {
            'manager_id': {
                'type': 'objectid',
                'data_relation': {
                    'resource': 'manager',
                    'embeddable': True
                },
            }
        }
    }
}

settings = {
    'URL_PREFIX': 'api',
    'API_VERSION': 'v1',
    'ALLOWED_FILTERS': ['*'],
    'MONGO_HOST': os.environ.get('MONGODB_HOST', ''),
    'MONGO_PORT': os.environ.get('MONGODB_PORT', ''),
    'MONGO_DBNAME': 'mriqc_api',
    'MULTIPART_FORM_FIELDS_AS_JSON': True,
    'PUBLIC_METHODS': ['GET'],
    'PUBLIC_ITEM_METHODS': ['GET'],
    'RESOURCE_METHODS': ['GET'],
    'ITEM_METHODS': ['GET'],
    'X_DOMAINS': '*',
    'X_HEADERS': ['X-Requested-With',
                  'Content-Length',
                  'Authorization',
                  'Content-Type',
                  'username',
                  'password'],
    'X_ALLOW_CREDENTIALS': True,
    'DOMAIN': {
        'image': {
            'item_title': 'image',
        },
        'mask': {
            'item_title': 'mask',
        },
        'user': {
            'item_title': 'user',
        },
        'researcher': {
            'item_title': 'researcher',
        },
        'project': {
            'item_title': 'project',
        },
        'maskagg': {
            'item_title': 'maskagg'
        },
        'score': {
            'item_title': 'score',
            'id_field': 'user_project_id'
        }

    }
}

settings['DOMAIN']['image']['schema'] = deepcopy(image_schema)
settings['DOMAIN']['mask']['schema'] = deepcopy(mask_schema)
settings['DOMAIN']['user']['schema'] = deepcopy(user_schema)
settings['DOMAIN']['score']['schema'] = deepcopy(score_schema)
settings['DOMAIN']['researcher']['schema'] = deepcopy(researcher_schema)
settings['DOMAIN']['project']['schema'] = deepcopy(project_schema)

# Add aggregation endpoint for masks
settings['DOMAIN']['maskagg']['datasource'] = {
    'source': 'mask',
    'aggregation': {
        'pipeline': [
            {'$match': {'image_id': '$image_search',
                        'mode': 'try'}},
            {'$group': {
                '_id': {
                    'image_id': '$image_id',
                    'user_id': '$user_id'
                },
                'count': {'$sum': 1},
                'sumscore': {'$sum': '$score'}
                }},
            {'$group': {
                '_id':  '$_id.image_id',
                'nattempts': {'$sum': '$count'},
                'nusers': {'$sum': 1},
                'sumscore': {'$sum': '$sumscore'}
                }},
            {'$project': {
                'nattempts': 1,
                'nusers': 1,
                'sumscore': 1,
                'avescore': {'$divide': ['$sumscore', '$nattempts']}
                }}
        ]
    }
}
