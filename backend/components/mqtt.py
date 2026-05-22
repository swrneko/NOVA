import paho.mqtt.client as mqtt

from config import *

class MQTT():
    def __init__(self):
        print(f"Connecting to mqtt on '{MQTT_HOST}'...")
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
            self.mqtt_client.connect(MQTT_HOST, 1883, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"mqtt connection failed due error: {e}")
