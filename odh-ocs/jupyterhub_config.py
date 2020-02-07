import os
from kubernetes.client.rest import ApiException
from kubernetes.client import V1EnvVar, V1ConfigMap, V1ObjectMeta, V1SecurityContext, V1Capabilities, V1SELinuxOptions
import kubernetes
import logging
import yaml

_LOGGER = logging.getLogger(__name__)

# Bucket verification and creation
api_client = None

service_account_path = '/var/run/secrets/kubernetes.io/serviceaccount'
if os.path.exists(service_account_path):
    with open(os.path.join(service_account_path, 'namespace')) as fp:
        namespace = fp.read().strip()
    kubernetes.config.load_incluster_config()
    api_client = kubernetes.client.CoreV1Api()
    api_client_custom = kubernetes.client.CustomObjectsApi()

def get_noobaa_config_maps():
    target_label = 'bucket-provisioner=openshift-storage.noobaa.io-obc'
    config_maps_list = []
    try:
        config_maps = api_client.list_namespaced_config_map(namespace, label_selector=target_label)
    except ApiException as e:
        if e.status != 404:
            _LOGGER.error(e)
        return config_maps_list
    for cm in config_maps.items:
        config_maps_list.append(cm.metadata.name)
    _LOGGER.info("Found these Config Maps: %s" % config_maps_list)
    return config_maps_list

def read_config_map(config_map_name, key_name="profiles"):
    try:
        config_map = api_client.read_namespaced_config_map(config_map_name, namespace)
    except ApiException as e:
        if e.status != 404:
            _LOGGER.error(e)
        return {}
        
    config_map_yaml = yaml.safe_load(config_map.name)
    return config_map_yaml

def escape(text):
  import re
  return re.sub("[^a-zA-Z0-9]+", "-", text)

def load_keys(claim_name):
    import base64
    print("load_keys: "+claim_name)
    config_map = api_client.read_namespaced_config_map(claim_name, namespace)
    bucket_name = yaml.safe_load(config_map.data["BUCKET_NAME"])
    print(bucket_name)
    secret = api_client.read_namespaced_secret(claim_name, namespace)
    key = base64.b64decode(yaml.safe_load(secret.data["AWS_ACCESS_KEY_ID"])).decode("utf-8")
    key_secret = base64.b64decode(yaml.safe_load(secret.data["AWS_SECRET_ACCESS_KEY"])).decode("utf-8")
    print(key)
    return bucket_name, key, key_secret;

def create_claim(username):
    import json
    import time
    print("create claim")
    user_bucket_name = ''
    aws_access_key = ''
    aws_secret_access_key = ''
    group = 'objectbucket.io'
    version = 'v1alpha1'
    plural = 'objectbucketclaims'
    body = (
      '{'
      '  "apiVersion": "objectbucket.io/v1alpha1",'
      '  "kind": "ObjectBucketClaim",'
      '  "metadata": {'
      '    "name": "odh-bucket-'+username+'"'
      '  },'
      '  "spec": {'
      '    "generateBucketName": "odh",'
      '    "storageClassName": "openshift-storage.noobaa.io"'
      '  }'
      '}'
    )
    print(json.loads(body))
    pretty = 'true' # str | If 'true', then the output is pretty printed. (optional)

    try:
        api_response = api_client_custom.create_namespaced_custom_object(group, version, namespace, plural, json.loads(body), pretty=pretty)
        print(api_response)
    except ApiException as e:
        print("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)

    cm_name = "odh-bucket-" + username
    attempts = 0
    while attempts < 5:
      try:
        user_bucket_name, aws_access_key, aws_secret_access_key = load_keys(cm_name)
        break
      except:
        attempts += 1
        time.sleep(5)
    return user_bucket_name, aws_access_key, aws_secret_access_key

def load_config_map(spawner_username):
    buckets_config_maps = get_noobaa_config_maps()
    for cm_name in buckets_config_maps:
        username = cm_name.replace('odh-bucket-','')
        print(username)
        if username == escape(spawner_username):
            user_bucket_name, aws_access_key, aws_secret_access_key = load_keys(cm_name)
            return user_bucket_name, aws_access_key, aws_secret_access_key
    user_bucket_name, aws_access_key, aws_secret_access_key = create_claim(escape(spawner_username))
    return user_bucket_name, aws_access_key, aws_secret_access_key

def profile_plus_s3(spawner, pod):
  # Apply profile from singleuser-profiles
  apply_pod_profile(spawner, pod)
  # Get OBC info, create it if needed
  user_bucket_name, aws_access_key, aws_secret_access_key = load_config_map(spawner.user.name)
  pod.spec.containers[0].env.append(V1EnvVar('AWS_ACCESS_KEY_ID', aws_access_key))
  pod.spec.containers[0].env.append(V1EnvVar('AWS_SECRET_ACCESS_KEY', aws_secret_access_key))
  #spawner.environment.update(dict(AWS_ACCESS_KEY_ID=aws_access_key,AWS_SECRET_ACCESS_KEY=aws_secret_access_key))   
  return pod
  
c.OpenShiftSpawner.modify_pod_hook = profile_plus_s3

c.KubeSpawner.debug = True


