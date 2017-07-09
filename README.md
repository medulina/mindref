# mindref
webapi for mindgames image server


Initially based on examples from [eve-demo](https://github.com/pyeve/eve-demo) and [mriqc's web api](https://github.com/poldracklab/mriqcwebapi).

Currently super bare bones.

Start it up as follows:

```
cd docker-ever
docker-compose build
docker-compose up
```

Browse to localhost for the swagger api documentation, then promptly ignore that documentation for uploading images. Instead of doing what it says, you'll need to submit images as a form as described [here](https://github.com/pyeve/eve/blob/ab1c6c028a68918df51ba22c7a157fe74ecbcd34/docs/features.rst#file-storage).

Here's an example of posting an image and associated mask with the Python 3 requests library:
```
import requests
from pathlib import Path
import json
import os
# this code assumes that the jpg, the json describing it, 
# and the mask file have the same name with different extenstions
url = 'http://localhost/api/v1/'
i = Path('data/0ff016cefb9590eb8cc1e3f7afc74ac372a6e0c27f98d1373b54e244.jpg')
j = i.with_suffix('.json')
with open(j,'r') as h:
    manifest = json.load(h)
with open(i,'rb') as img:
    r = requests.post(url+'image',files={'pic':img},data=manifest, headers={'Authorization':os.environ.get('API_TOKEN','"testing_secret"')})
m = i.with_suffix('.mask')
image_id = r.json()['_id']
if m.exists():
    mask_dat = {'image_id':image_id,'mode':'truth'}
    with open(m,'rb') as h:
        mask_dat['pic'] = json.dumps(json.load(h))
        rm = requests.post(url+'mask',data=mask_dat, headers={'Authorization':os.environ.get('API_TOKEN','"testing_secret"')})
        
```

Here we use the id of the image we just uploaded to download an image and it's mask:

```
geti_url = url+'image?where={"_id":"%s"}'%image_id
res_i= requests.get(geti_url)

getm_url = url+'mask?where={"image_id":"%s"}'%image_id
res_m= requests.get(getm_url)
```
