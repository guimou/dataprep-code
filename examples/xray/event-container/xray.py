import sys
import boto3
import matplotlib.pyplot as plt
import numpy as np
import os
import logging
import json
from kncloudevents import CloudeventsServer
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

s3 = boto3.resource('s3','us-east-1', endpoint_url=service_point,
                       aws_access_key_id = access_key,
                       aws_secret_access_key = secret_key,
                        use_ssl = True if 'https' in service_point else False)

s3client = boto3.client('s3','us-east-1', endpoint_url=service_point,
                       aws_access_key_id = access_key,
                       aws_secret_access_key = secret_key,
                        use_ssl = True if 'https' in service_point else False)

model = load_model('./pneumonia_model.h5')

def extract_data(msg):
    content=json.loads(msg.value)
    bucket_eventName=content["Records"][0]["eventName"]
    bucket_name=content["Records"][0]["s3"]["bucket"]["name"]
    bucket_object=content["Records"][0]["s3"]["object"]["key"]
    data = {"bucket_eventName":bucket_eventName, "bucket_name":bucket_name, "bucket_object":bucket_object}
    return data

def load_image(bucket_name, img_path, show=False):
    obj = s3client.get_object(Bucket=bucket_name, Key=img_path)
    
    img = image.load_img(BytesIO(obj['Body'].read()), target_size=(150, 150))
    img_tensor = image.img_to_array(img)                    # (height, width, channels)
    img_tensor = np.expand_dims(img_tensor, axis=0)         # (1, height, width, channels), add a dimension because the model expects this shape: (batch_size, height, width, channels)
    img_tensor /= 255.                                      # imshow expects values in the range [0, 1]

    if show:
        plt.imshow(img_tensor[0])                           
        plt.axis('off')
        plt.show()

    return img_tensor

def prediction(new_image):
    pred = model.predict(new_image)
   
    if pred[0][0] > 0.80:
        label='Pneumonia, risk=' + str(round(pred[0][0]*100,2)) + '%'
    elif pred[0][0] < 0.60:
        label='Normal, risk=' + str(round(pred[0][0]*100,2)) + '%'
    else:
        label='Unsure, risk=' + str(round(pred[0][0]*100,2)) + '%'
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
    try:
        logging.info(event.Data())
        extracted_data = extract_data(event.Data())
        operation = extracted_data['bucket_name']
        bucket_name = extracted_data['bucket_name']
        img_name = extracted_data['bucket_eventName']

        if operation == 's3:ObjectCreated:Put':
            # Load image and make prediction
            new_image = load_image(bucket_name,img_name)
            result = prediction(new_image)

            # Get original image and print prediction on it
            image_object = s3client.get_object(Bucket=bucket_name,Key=img_name)['Body'].read()
            img = Image.open(BytesIO(image_object))
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype('FreeMono.ttf', 100)
            draw.text((0, 0), result, (255), font=font)

            # Save image with "-computed" appended to name
            computed_image_key = os.path.splitext(img_name)[0] + '-computed.' + os.path.splitext(img_name)[-1].strip('.')
            buffer = BytesIO()
            img.save(buffer, get_safe_ext(computed_image_key))
            buffer.seek(0)
            sent_data = s3client.put_object(Bucket=bucket_name, Key=computed_image_key, Body=buffer)
            if sent_data['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise logging.error('Failed to upload image {} to bucket {}'.format(computed_image_key, bucket_name))

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise


client = CloudeventsServer()
client.start_receiver(run_event)