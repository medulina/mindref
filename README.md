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

Here's an example of posting an image with curl:
```
curl -F "slice=0" -F "task=task1" -F "pic=@relative/or/absolute/path/to/some/.jpg" -F "slice_direction=ax" -F "subject=test_sub" http://localhost/api/v1/image
```

And here's python 3 example of pulling all of the records down and saving out the image for the first one:

```
import requests
import base64

r = requests.get('http://localhost/api/v1/image')
img = r.json()['_items'][0]['pic']
with open("output/path/for/.jpg", "wb") as fh:
    fh.write(base64.decodebytes(img.encode()))
```

Masks are nominally implimented but presently completely untested.