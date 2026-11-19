import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import paho.mqtt.client as mqtt
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from dotenv import load_dotenv
load_dotenv()
# ********************* CONFIGURAÇÃO *********************************

app = Flask(__name__)

# A conexão vem de uma variável de ambiente, para não publicar senha no código.
# Exemplo: mysql+pymysql://usuario:senha@localhost:3306/ambiental
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'mysql+pymysql://root:senha@localhost:3306/ambiental'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

mybd = SQLAlchemy(app)

MQTT_BROKER = os.environ.get('MQTT_BROKER', 'test.mosquitto.org')
MQTT_TOPICO = os.environ.get('MQTT_TOPICO', 'projeto_integrado/SENAI134/Cienciadedados/GrupoX')


# ********************* MODELO (tabela leitura_sensor) ****************

class Registro(mybd.Model):
    __tablename__ = 'leitura_sensor'

    id = mybd.Column(mybd.BigInteger, primary_key=True, autoincrement=True)
    temperature = mybd.Column(mybd.Numeric(5, 2))
    pressure = mybd.Column(mybd.Numeric(7, 2))
    altitude = mybd.Column(mybd.Numeric(7, 2))
    humidity = mybd.Column(mybd.Numeric(5, 2))
    CO2 = mybd.Column(mybd.SmallInteger)
    particula1 = mybd.Column(mybd.Numeric(7, 2))
    particula2 = mybd.Column(mybd.Numeric(7, 2))
    registro_tempo = mybd.Column(mybd.DateTime, nullable=False)


# ********************* FUNÇÕES DE APOIO *****************************

def numero(valor):
    """Converte o valor recebido em número; devolve None se vier vazio ou inválido."""
    if valor is None or valor == '':
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def inteiro(valor):
    """Converte para inteiro (usado no CO2); devolve None se inválido."""
    n = numero(valor)
    return int(round(n)) if n is not None else None


# ********************* CONEXÃO SENSORES *****************************

mqtt_data = {}


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Conectado ao broker, código {reason_code}")
    client.subscribe(MQTT_TOPICO)


def on_message(client, userdata, msg):
    global mqtt_data

    try:
        mqtt_data = json.loads(msg.payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"Mensagem ignorada, não é um JSON válido: {e}")
        return

    print(f"Mensagem recebida: {mqtt_data}")

    timestamp_unix = mqtt_data.get('timestamp')
    if timestamp_unix is None:
        print("Mensagem ignorada: timestamp não encontrado")
        return

    # Timestamp Unix (segundos) -> data e hora em UTC, sem fuso (coluna DATETIME)
    try:
        registro_tempo = datetime.fromtimestamp(int(float(timestamp_unix)), tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError) as e:
        print(f"Mensagem ignorada: timestamp inválido ({e})")
        return

    with app.app_context():
        try:
            # Política de duplicados: se já existe leitura nesse instante, ignora
            if Registro.query.filter_by(registro_tempo=registro_tempo).first():
                print(f"Leitura duplicada ignorada: {registro_tempo}")
                return

            nova_leitura = Registro(
                temperature=numero(mqtt_data.get('temperature')),
                pressure=numero(mqtt_data.get('pressure')),
                altitude=numero(mqtt_data.get('altitude')),
                humidity=numero(mqtt_data.get('humidity')),
                CO2=inteiro(mqtt_data.get('CO2')),
                particula1=numero(mqtt_data.get('particula1')),
                particula2=numero(mqtt_data.get('particula2')),
                registro_tempo=registro_tempo,
            )

            mybd.session.add(nova_leitura)
            mybd.session.commit()
            print(f"Leitura gravada: id {nova_leitura.id}")

        except Exception as e:
            mybd.session.rollback()
            print(f"Erro ao gravar a leitura: {e}")


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


def start_mqtt():
    mqtt_client.connect(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()


# CONTEUDO


if __name__ == '__main__':
    with app.app_context():
        start_mqtt()
        port = int(os.environ.get("PORT", 8080))
        app.run(host='0.0.0.0', port=port)