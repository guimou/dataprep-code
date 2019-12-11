import sys
from kncloudevents import CloudeventsServer
import logging

logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def run_event(event):
    try:
        logging.info(event.Data())
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise


client = CloudeventsServer()
client.start_receiver(run_event)