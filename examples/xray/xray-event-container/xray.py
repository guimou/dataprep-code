import sys
import boto3
import numpy as np
import os
import logging
import json

import http.server
import socketserver
import json
import logging
import io
from cloudevents.sdk.event import v02
from cloudevents.sdk import marshaller
from keras.models import load_model
from keras.preprocessing import image
from io import BytesIO
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw

access_key = os.environ['AWS_ACCESS_KEY_ID']
secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
service_point = os.environ['service_point']

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

s3client = boto3.client('s3','us-east-1', endpoint_url=service_point,
                       aws_access_key_id = access_key,
                       aws_secret_access_key = secret_key,
                        use_ssl = True if 'https' in service_point else False)

m = marshaller.NewDefaultHTTPMarshaller()


class ForkedHTTPServer(socketserver.ForkingMixIn, http.server.HTTPServer):
    """Handle requests with fork."""


class CloudeventsServer(object):
    """Listen for incoming HTTP cloudevents requests.
    cloudevents request is simply a HTTP Post request following a well-defined
    of how to pass the event data.
    """
    def __init__(self, port=8080):
        self.port = port

    def start_receiver(self, func):
        """Start listening to HTTP requests
        :param func: the callback to call upon a cloudevents request
        :type func: cloudevent -> none
        """
        class BaseHttp(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                content_type = self.headers.get('Content-Type')
                content_len = int(self.headers.get('Content-Length'))
                headers = dict(self.headers)
                data = self.rfile.read(content_len)
                data = data.decode('utf-8')

                if content_type != 'application/json':
                    data = io.StringIO(data)

                event = v02.Event()
                event = m.FromRequest(event, headers, data, json.loads)
                func(event)
                self.send_response(204)
                self.end_headers()
                return

        socketserver.TCPServer.allow_reuse_address = True
        with ForkedHTTPServer(("", self.port), BaseHttp) as httpd:
            try:
                logging.info("serving at port {}".format(self.port))
                httpd.serve_forever()
            except:
                httpd.server_close()
                raise

def extract_data(msg):
    bucket_eventName=msg['Records'][0]['eventName']
    bucket_name=msg['Records'][0]['s3']['bucket']['name']
    bucket_object=msg['Records'][0]['s3']['object']['key']
    data = {'bucket_eventName':bucket_eventName, 'bucket_name':bucket_name, 'bucket_object':bucket_object}
    return data

def load_image(bucket_name, img_path):
    obj = s3client.get_object(Bucket=bucket_name, Key=img_path)
    
    img = image.load_img(BytesIO(obj['Body'].read()), target_size=(150, 150))
    img_tensor = image.img_to_array(img)                    # (height, width, channels)
    img_tensor = np.expand_dims(img_tensor, axis=0)         # (1, height, width, channels), add a dimension because the model expects this shape: (batch_size, height, width, channels)
    img_tensor /= 255.                                      # imshow expects values in the range [0, 1]

    return img_tensor

def prediction(new_image):
    try:
        model = load_model('./pneumonia_model.h5')
        pred = model.predict(new_image)
    
        if pred[0][0] > 0.80:
            label='Pneumonia, risk=' + str(round(pred[0][0]*100,2)) + '%'
        elif pred[0][0] < 0.60:
            label='Normal, risk=' + str(round(pred[0][0]*100,2)) + '%'
        else:
            label='Unsure, risk=' + str(round(pred[0][0]*100,2)) + '%'
    except Exception as e:
        logging.error(f"Prediction error: {e}")
        raise   
    return label

def get_safe_ext(key):
    ext = os.path.splitext(key)[-1].strip('.').upper()
    if ext in ['JPG', 'JPEG']:
        return 'JPEG' 
    elif ext in ['PNG']:
        return 'PNG' 
    else:
        logging.error('Extension is invalid')   

def run_event(event):
    logging.info(event.Data())
    try:
        extracted_data = extract_data(event.Data())
        bucket_eventName = extracted_data['bucket_eventName']
        bucket_name = extracted_data['bucket_name']
        img_name = extracted_data['bucket_object']
        logging.info(bucket_eventName + ' ' + bucket_name + ' ' + img_name)

        if bucket_eventName == 's3:ObjectCreated:Put':
            # Load image and make prediction
            new_image = load_image(bucket_name,img_name)
            result = prediction(new_image)
            logging.info('result=' + result)

            # Get original image and print prediction on it
            image_object = s3client.get_object(Bucket=bucket_name,Key=img_name)
            img = Image.open(BytesIO(image_object['Body'].read()))
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype('FreeMono.ttf', 100)
            draw.text((0, 0), result, (255), font=font)

            # Save image with "-computed" appended to name
            computed_image_key = os.path.splitext(img_name)[0] + '-processed.' + os.path.splitext(img_name)[-1].strip('.')
            buffer = BytesIO()
            img.save(buffer, get_safe_ext(computed_image_key))
            buffer.seek(0)
            sent_data = s3client.put_object(Bucket=bucket_name+'-processed', Key=computed_image_key, Body=buffer)
            if sent_data['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise logging.error('Failed to upload image {} to bucket {}'.format(computed_image_key, bucket_name))

            logging.info('Image processed')

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise


client = CloudeventsServer()
client.start_receiver(run_event)