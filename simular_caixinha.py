"""Publica leituras falsas no MQTT para testar a API sem a caixinha.

Use um tópico de TESTE no .env (ex.: .../Grupo3_teste) para não misturar com os dados reais.
Uso:  python simular_caixinha.py            -> leituras normais
      python simular_caixinha.py abafada    -> CO2 e umidade altos (abre alertas após 10 min)
"""
import json
import os
import random
import sys
import time

import paho.mqtt.publish as publish
from dotenv import load_dotenv

load_dotenv()

TOPICO = os.environ.get('MQTT_TOPICO', 'projeto_integrado/SENAI134/Cienciadedados/GrupoX')
BROKER = os.environ.get('MQTT_BROKER', 'test.mosquitto.org')
abafada = len(sys.argv) > 1 and sys.argv[1] == 'abafada'

print(f"Publicando em {TOPICO} a cada 5 s (Ctrl+C para parar)")
while True:
    leitura = {
        'temperature': round(random.uniform(23, 25), 2),
        'pressure': round(random.uniform(924, 926), 2),
        'altitude': round(random.uniform(759, 762), 2),
        'humidity': round(random.uniform(68, 75) if abafada else random.uniform(50, 60), 2),
        'CO2': random.randint(1100, 1400) if abafada else random.randint(500, 800),
        'particula1': round(random.uniform(5, 12), 2),
        'particula2': round(random.uniform(10, 25), 2),
        'timestamp': int(time.time()),
    }
    publish.single(TOPICO, json.dumps(leitura), hostname=BROKER)
    print(leitura)
    time.sleep(5)
