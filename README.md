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
```python
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

```python
geti_url = url+'image?where={"_id":"%s"}'%image_id
res_i= requests.get(geti_url)

getm_url = url+'mask?where={"image_id":"%s"}'%image_id
res_m= requests.get(getm_url)
```


If you want to get statistics for all of the masks submitted for a training image send a get request like so:
```pthon
get_aggmasks = url+'maskagg?aggregate={"$image_search":"%s"}'%image_id
res_aggm = requests.get(get_aggmasks)
```
This will return a json response like so:
```
{'_items': [{'_id': '599d87d0d52c9f00099b2aab',
   'avescore': 0.1,
   'nattempts': 1,
   'nusers': 1,
   'sumscore': 0.1}]}
   ```

Backend selection logic is now tentatively implemented. It depends on several variables being available in the config file:
```
ROLL_N = 10
TEST_THRESH = 0.75
TEST_PER_TRAIN = 5
TRAIN_REPEAT = 10
```
If user_id and token parameters are set as parameters on the get item request, the backend will first decide if the user's rolling average score is above threshold. If it is and they don't randomly get assigned to training based on the test_per_train setting, then it will try to give them a novel test image, otherwise giving them an image seen the fewest number of times. If they are selected to get a training image, then they will get a repeated training image based on the train_repeat parameter or a novel or least seen training image. 

The reqeust should look something like this:
```python
geti_url = url+'image?where={"task":"dev"}&user_id=%s&token=%s'%(uid,token)
res_i= requests.get(geti_url)
```
