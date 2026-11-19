# Configuração do Banco de Dados

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import paho.mqtt.client as mqtt
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask('ambiental')

# A conexão vem de uma variável de ambiente, para não publicar senha no código.
# Exemplo: mysql+pymysql://usuario:senha@localhost:3306/ambiental
app.config['SQLALCHEMY_DATABASE_URI'] = (
    'mysql+pythonsql://root' + quote('Hunas081729') + '@localhost:3306/ambiental'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

mybd = SQLAlchemy(app)

MQTT_BROKER = os.environ.get('MQTT_BROKER', 'test.mosquitto.org')
MQTT_TOPICO = os.environ.get('MQTT_TOPICO', 'projeto_integrado/SENAI134/Cienciadedados/GrupoX')


# ********************* CONEXÃO SENSORES *********************************

mqtt_data = {}

def on_connect(client, userdata, flags, rc):
    # client: A instância do cliente MQTT.
    # userdata: Dados do usuário definidos quando o cliente foi configurado (geralmente None).
    # flags: Dicionário contendo sinalizadores de resposta do broker.
    # rc: Código de resultado da conexão (0 significa sucesso; valores diferentes de zero indicam erros).
    print("Connected with result code " + str(rc))
    client.subscribe("projeto_integrado/SENAI134/Cienciadedados/GrupoX")

def on_message(client, userdata, msg):
    global mqtt_data
 # Decodifica a mensagem recebida de bytes para string
    payload = msg.payload.decode('utf-8')
    
    # Converte a string JSON em um dicionário Python
    mqtt_data = json.loads(payload)
    
    # Imprime a mensagem recebida
    print(f"Received message: {mqtt_data}")

    # Adiciona o contexto da aplicação para a manipulação do banco de dados
    with app.app_context():
        try:
            temperatura = mqtt_data.get('temperature')
            pressao = mqtt_data.get('pressure')
            altitude = mqtt_data.get('altitude')
            umidade = mqtt_data.get('humidity')
            co2 = mqtt_data.get('CO2')
            poeira1 = mqtt_data.get('particula1')
            poeira2 = mqtt_data.get('particula2')
            timestamp_unix = mqtt_data.get('timestamp')

            if timestamp_unix is None:
                print("Timestamp não encontrado no payload")
                return

            # Converte timestamp Unix para datetime
            try:
                timestamp = datetime.fromtimestamp(int(timestamp_unix), tz=timezone.utc)
            except (ValueError, TypeError) as e:
                print(f"Erro ao converter timestamp: {str(e)}")
                return

            # Cria o objeto Registro com os dados
            new_data = Registro(
                temperatura=temperatura,
                pressao=pressao,
                altitude=altitude,
                umidade=umidade,
                co2=co2,
                poeira1=poeira1,
                poeira2=poeira2,
                tempo_registro=timestamp
            )

            # Adiciona o novo registro ao banco de dados
            mybd.session.add(new_data)
            mybd.session.commit()
            print("Dados inseridos no banco de dados com sucesso")

        except Exception as e:
            print(f"Erro ao processar os dados do MQTT: {str(e)}")
            mybd.session.rollback()

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect("test.mosquitto.org", 1883, 60)

def start_mqtt():
    mqtt_client.loop_start()

# CONTEUDO



if __name__ == '__main__':  # Verifica se este arquivo está sendo executado como o programa principal.
    with app.app_context():  # Cria um contexto de aplicativo Flask para executar a criação do banco de dados.
        # mybd.create_all()  # Chama o método 'create_all' para criar todas as tabelas definidas no modelo do banco de dados.
    
        start_mqtt()  # Chama a função 'start_mqtt', que presumivelmente inicia um cliente MQTT (protocolo de mensagens para dispositivos).
        port = int(os.environ.get("PORT", 8080))  # Azure define a porta automaticamente
        app.run(host='0.0.0.0', port=port)  # Ouvir em todas as interfaces e usar a porta fornecida pela Azure