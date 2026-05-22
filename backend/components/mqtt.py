import paho.mqtt.client as mqtt
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import *

class MQTT():
    def __init__(self):
        print(f"Connecting to mqtt on '{MQTT_HOST}'...")
        try:
            # Для paho-mqtt >= 2.0.0 требуется CallbackAPIVersion
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "NOVA_Server")
            self.mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
            self.mqtt_client.connect(MQTT_HOST, 1883, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"mqtt connection failed due error: {e}")
