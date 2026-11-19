import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from sqlalchemy import func
from werkzeug.security import generate_password_hash

load_dotenv()

from alertas import motor_alertas  # noqa: E402  (precisa vir depois do load_dotenv)
from modelos import (Alerta, AlertaVariavel, Limite, Meteorologico, Notificacao,  # noqa: E402
                     RegraCombinacao, RegraCondicao, Registro, Relatorio, Severidade,
                     Usuario, mybd)
from servicos import (BRT, VARIAVEIS, agora_utc, coletar_meteorologico, enviar_email,  # noqa: E402
                      gerar_relatorio, semana_anterior)

# ********************* CONFIGURAÇÃO *********************************

app = Flask(__name__)
app.json.sort_keys = False

# A conexão vem do .env, para não publicar senha no código.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'mysql+pymysql://root:Hunas081729@localhost:3306/ambiental'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Testa a conexão antes de usar e renova conexões paradas
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 280}

mybd.init_app(app)

MQTT_BROKER = os.environ.get('MQTT_BROKER', 'test.mosquitto.org')
MQTT_TOPICO = os.environ.get('MQTT_TOPICO', 'projeto_integrado/SENAI134/Cienciadedados/grupoX')
INTERVALO_METEO_S = int(os.environ.get('INTERVALO_METEO_MIN', '10')) * 60
# Fuso do relógio da caixinha. Se ela manda o horário de Brasília dentro do timestamp
# (em vez de UTC), use CAIXINHA_FUSO_HORAS=-3 no .env para corrigir.
CAIXINHA_FUSO_HORAS = float(os.environ.get('CAIXINHA_FUSO_HORAS', '0'))


# ********************* FUNÇÕES DE APOIO *****************************

def numero(valor):
    """Converte o valor recebido em número; devolve None se vier vazio ou inválido."""
    if valor is None or valor == '':
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def pressao_hpa(valor):
    """A caixinha envia a pressão em pascal (ex.: 92906.55); o banco e o Open-Meteo usam hPa."""
    n = numero(valor)
    if n is not None and n > 2000:  # nenhum valor em hPa passa de ~1100; acima disso está em Pa
        n = (n / 100).quantize(Decimal('0.01'))
    return n


def inteiro(valor):
    """Converte para inteiro (usado no CO2); devolve None se inválido."""
    n = numero(valor)
    return int(round(n)) if n is not None else None


def converter_timestamp(valor):
    """Timestamp Unix (segundos ou milissegundos) -> data e hora UTC sem fuso. None se inválido."""
    try:
        segundos = float(valor)
        if segundos > 1e11:  # veio em milissegundos
            segundos /= 1000
        dt = datetime.fromtimestamp(int(segundos), tz=timezone.utc).replace(tzinfo=None)
        dt -= timedelta(hours=CAIXINHA_FUSO_HORAS)  # relógio local da caixinha -> UTC
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    # Relógio da caixinha sem acertar (ex.: 1970) não serve como horário da medição
    return dt if dt.year >= 2020 else None


def iso_utc(dt):
    """Data/hora do banco (UTC) no formato ISO com 'Z', para o dashboard converter."""
    return dt.isoformat() + 'Z' if dt else None


def num(v):
    return float(v) if v is not None else None


def ler_data_hora(texto, padrao):
    """Lê 'inicio'/'fim' da URL. Sem fuso, considera horário de Brasília. Devolve UTC sem fuso."""
    if not texto:
        return padrao
    dt = datetime.fromisoformat(texto.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BRT)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def periodo_da_url(horas_padrao):
    fim = ler_data_hora(request.args.get('fim'), agora_utc())
    inicio = ler_data_hora(request.args.get('inicio'), fim - timedelta(hours=horas_padrao))
    return inicio, fim


def leitura_json(r):
    return {
        'id': r.id,
        'temperature': num(r.temperature), 'pressure': num(r.pressure), 'altitude': num(r.altitude),
        'humidity': num(r.humidity), 'CO2': r.CO2,
        'particula1': num(r.particula1), 'particula2': num(r.particula2),
        'registro_tempo': iso_utc(r.registro_tempo),
    }


def alerta_json(a):
    sev = mybd.session.get(Severidade, a.id_severidade)
    regra = mybd.session.get(RegraCombinacao, a.id_regra) if a.id_regra else None
    variaveis = []
    for av in AlertaVariavel.query.filter_by(id_alerta=a.id_alerta).all():
        lim = mybd.session.get(Limite, av.id_limite)
        variaveis.append({'variavel': lim.variavel, 'operador': lim.operador, 'limite': num(lim.valor),
                          'valor_pico': num(av.valor_pico), 'fonte': lim.fonte})
    fim_ref = a.fim or agora_utc()
    return {
        'id_alerta': a.id_alerta, 'status': a.status,
        'severidade': {'id': sev.id_severidade, 'nome': sev.nome, 'ordem': sev.ordem},
        'regra': regra.nome if regra else None,
        'variaveis': variaveis,
        'inicio': iso_utc(a.inicio), 'fim': iso_utc(a.fim),
        'duracao_min': round((fim_ref - a.inicio).total_seconds() / 60, 1),
        'id_leitura_disparo': a.id_leitura_disparo,
    }


def meteo_json(m):
    return {
        'id_meteo': m.id_meteo, 'referencia_tempo': iso_utc(m.referencia_tempo),
        'temperatura_ext': num(m.temperatura_ext), 'umidade_ext': num(m.umidade_ext),
        'pressao_ext': num(m.pressao_ext), 'pm25_ext': num(m.pm25_ext), 'pm10_ext': num(m.pm10_ext),
        'coletado_em': iso_utc(m.coletado_em),
    }


def relatorio_json(r, com_texto=True):
    dados = {
        'id_relatorio': r.id_relatorio,
        'periodo_inicio': r.periodo_inicio.isoformat(), 'periodo_fim': r.periodo_fim.isoformat(),
        'modelo_llm': r.modelo_llm, 'gerado_em': iso_utc(r.gerado_em),
    }
    if com_texto:
        dados['texto_llm'] = r.texto_llm
        dados['dados_entrada'] = json.loads(r.dados_entrada)
    return dados


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

    registro_tempo = converter_timestamp(mqtt_data.get('timestamp'))
    if registro_tempo is None:
        # Sem timestamp válido, usa o horário do servidor para não perder a leitura
        registro_tempo = agora_utc().replace(microsecond=agora_utc().microsecond // 1000 * 1000)
        print(f"Aviso: timestamp ausente ou inválido ({mqtt_data.get('timestamp')!r}); usando o horário do servidor")

    with app.app_context():
        try:
            # Política de duplicados: se já existe leitura nesse instante, ignora
            if Registro.query.filter_by(registro_tempo=registro_tempo).first():
                print(f"Leitura duplicada ignorada: {registro_tempo}")
                return

            nova_leitura = Registro(
                temperature=numero(mqtt_data.get('temperature')),
                pressure=pressao_hpa(mqtt_data.get('pressure')),
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
            return

        # A leitura já está salva; um erro nos alertas não pode apagá-la
        try:
            motor_alertas.avaliar(nova_leitura)
        except Exception as e:
            mybd.session.rollback()
            print(f"Erro ao avaliar alertas: {e}")


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


def start_mqtt():
    # connect_async: se o broker estiver fora do ar, a API sobe mesmo assim e o MQTT reconecta sozinho
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
    mqtt_client.connect_async(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()


# ********************* TAREFAS AGENDADAS ****************************

def agendador():
    """Coleta o Open-Meteo a cada 10 min e gera o relatório da semana anterior às segundas."""
    ultima_coleta = 0.0
    while True:
        with app.app_context():
            if time.time() - ultima_coleta >= INTERVALO_METEO_S:
                ultima_coleta = time.time()
                try:
                    coletar_meteorologico()
                except Exception as e:
                    mybd.session.rollback()
                    print(f"[Open-Meteo] Falha na coleta: {e}")

            try:
                segunda, domingo = semana_anterior()
                if not Relatorio.query.filter_by(periodo_inicio=segunda, periodo_fim=domingo).first():
                    gerar_relatorio(segunda, domingo)
            except Exception as e:
                mybd.session.rollback()
                print(f"[Relatório] Falha ao gerar: {e}")
        time.sleep(30)


def iniciar_servicos():
    with app.app_context():
        motor_alertas.carregar_abertos()
    start_mqtt()
    threading.Thread(target=agendador, daemon=True).start()


# ********************* API ******************************************

@app.after_request
def liberar_cors(resposta):
    """Permite que o dashboard (em outro endereço/porta) consulte a API."""
    resposta.headers['Access-Control-Allow-Origin'] = '*'
    resposta.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resposta.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resposta


@app.errorhandler(ValueError)
def parametro_invalido(e):
    return jsonify({'erro': f'Parâmetro inválido: {e}'}), 400


@app.get('/api/status')
def status():
    ultima = Registro.query.order_by(Registro.registro_tempo.desc()).first()
    return jsonify({
        'api': 'ok',
        'mqtt_conectado': mqtt_client.is_connected(),
        'topico': MQTT_TOPICO,
        'ultima_leitura': iso_utc(ultima.registro_tempo) if ultima else None,
        'alertas_abertos': Alerta.query.filter_by(status='aberto').count(),
        'horario_servidor_utc': iso_utc(agora_utc()),
    })


# ----- Leituras do sensor -----

@app.get('/api/leituras')
def listar_leituras():
    inicio, fim = periodo_da_url(horas_padrao=1)
    limite = min(int(request.args.get('limite', 5000)), 50000)
    linhas = (Registro.query
              .filter(Registro.registro_tempo >= inicio, Registro.registro_tempo <= fim)
              .order_by(Registro.registro_tempo.desc()).limit(limite).all())
    linhas.reverse()
    return jsonify({'inicio': iso_utc(inicio), 'fim': iso_utc(fim), 'quantidade': len(linhas),
                    'leituras': [leitura_json(r) for r in linhas]})


@app.get('/api/leituras/ultima')
def ultima_leitura():
    r = Registro.query.order_by(Registro.registro_tempo.desc()).first()
    if not r:
        return jsonify({'erro': 'Nenhuma leitura registrada ainda'}), 404
    return jsonify(leitura_json(r))


@app.get('/api/leituras/resumo')
def resumo_leituras():
    inicio, fim = periodo_da_url(horas_padrao=24)
    resumo = {}
    for nome in VARIAVEIS:
        col = getattr(Registro, nome)
        n, media, minimo, maximo = mybd.session.query(
            func.count(col), func.avg(col), func.min(col), func.max(col)
        ).filter(Registro.registro_tempo >= inicio, Registro.registro_tempo <= fim).one()
        resumo[nome] = {'leituras': n, 'media': round(num(media), 2) if media is not None else None,
                        'minimo': num(minimo), 'maximo': num(maximo)}
    return jsonify({'inicio': iso_utc(inicio), 'fim': iso_utc(fim), 'variaveis': resumo})


# ------------------------------------------------------------------------- Alertas (email) -----

@app.get('/api/alertas')
def listar_alertas():
    consulta = Alerta.query
    if request.args.get('status'):
        consulta = consulta.filter_by(status=request.args['status'])
    if request.args.get('inicio') or request.args.get('fim'):
        inicio, fim = periodo_da_url(horas_padrao=24 * 7)
        consulta = consulta.filter(Alerta.inicio >= inicio, Alerta.inicio <= fim)
    alertas = consulta.order_by(Alerta.inicio.desc()).limit(500).all()
    return jsonify({'quantidade': len(alertas), 'alertas': [alerta_json(a) for a in alertas]})


@app.get('/api/alertas/<int:id_alerta>')
def detalhar_alerta(id_alerta):
    a = mybd.session.get(Alerta, id_alerta)
    if not a:
        return jsonify({'erro': 'Alerta não encontrado'}), 404
    return jsonify(alerta_json(a))


# ----- Dados externos (Open-Meteo) -----

@app.get('/api/meteorologico')
def listar_meteorologico():
    inicio, fim = periodo_da_url(horas_padrao=24)
    linhas = (Meteorologico.query
              .filter(Meteorologico.referencia_tempo >= inicio, Meteorologico.referencia_tempo <= fim)
              .order_by(Meteorologico.referencia_tempo).all())
    return jsonify({'inicio': iso_utc(inicio), 'fim': iso_utc(fim), 'quantidade': len(linhas),
                    'fonte': 'Open-Meteo (open-meteo.com), licença CC BY 4.0',
                    'dados': [meteo_json(m) for m in linhas]})


@app.get('/api/meteorologico/ultimo')
def ultimo_meteorologico():
    m = Meteorologico.query.order_by(Meteorologico.referencia_tempo.desc()).first()
    if not m:
        return jsonify({'erro': 'Nenhum dado externo coletado ainda'}), 404
    return jsonify(meteo_json(m))


@app.post('/api/meteorologico/coletar')
def coletar_agora():
    """Força uma coleta no Open-Meteo (útil para demonstração)."""
    try:
        linha = coletar_meteorologico()
    except Exception as e:
        mybd.session.rollback()
        return jsonify({'erro': f'Falha ao consultar o Open-Meteo: {e}'}), 502
    if not linha:
        return jsonify({'mensagem': 'O Open-Meteo ainda não atualizou; dado já gravado'}), 200
    return jsonify(meteo_json(linha)), 201


# ------------------------------------------------ Relatórios (llm) -----

@app.get('/api/relatorios')
def listar_relatorios():
    rels = Relatorio.query.order_by(Relatorio.gerado_em.desc()).all()
    return jsonify({'quantidade': len(rels), 'relatorios': [relatorio_json(r, com_texto=False) for r in rels]})


@app.get('/api/relatorios/<int:id_relatorio>')
def detalhar_relatorio(id_relatorio):
    r = mybd.session.get(Relatorio, id_relatorio)
    if not r:
        return jsonify({'erro': 'Relatório não encontrado'}), 404
    return jsonify(relatorio_json(r))


@app.post('/api/relatorios/gerar')
def gerar_relatorio_agora():
    """Gera um relatório na hora (demonstração). Corpo opcional: {"dias": 7, "enviar_email": true}."""
    corpo = request.get_json(silent=True) or {}
    dias = int(corpo.get('dias', 7))
    hoje = datetime.now(BRT).date()
    rel = gerar_relatorio(hoje - timedelta(days=dias - 1), hoje, enviar=bool(corpo.get('enviar_email', True)))
    return jsonify(relatorio_json(rel)), 201


# ----- Configuração: severidades, limites, regras -----

@app.get('/api/severidades')
def listar_severidades():
    return jsonify([{'id_severidade': s.id_severidade, 'nome': s.nome, 'ordem': s.ordem,
                     'envia_email': s.envia_email}
                    for s in Severidade.query.order_by(Severidade.ordem).all()])


@app.get('/api/limites')
def listar_limites():
    return jsonify([{'id_limite': l.id_limite, 'variavel': l.variavel, 'id_severidade': l.id_severidade,
                     'operador': l.operador, 'valor': num(l.valor), 'persistencia_min': l.persistencia_min,
                     'fonte': l.fonte, 'ativo': l.ativo}
                    for l in Limite.query.order_by(Limite.variavel, Limite.id_severidade).all()])


@app.get('/api/regras')
def listar_regras():
    regras = []
    for r in RegraCombinacao.query.all():
        ids = [c.id_limite for c in RegraCondicao.query.filter_by(id_regra=r.id_regra).all()]
        regras.append({'id_regra': r.id_regra, 'nome': r.nome, 'descricao': r.descricao,
                       'id_severidade': r.id_severidade, 'persistencia_min': r.persistencia_min,
                       'ativo': r.ativo, 'limites': ids})
    return jsonify(regras)


# ----- Usuários (destinatários dos e-mails) e notificações -----

@app.get('/api/usuarios')
def listar_usuarios():
    return jsonify([{'id_usuario': u.id_usuario, 'nome': u.nome, 'email': u.email,
                     'recebe_alertas': u.recebe_alertas, 'recebe_relatorio': u.recebe_relatorio,
                     'ativo': u.ativo} for u in Usuario.query.all()])


@app.post('/api/usuarios')
def cadastrar_usuario():
    """Corpo: {"nome", "email", "senha", "recebe_alertas"?, "recebe_relatorio"?}"""
    corpo = request.get_json(silent=True) or {}
    faltando = [c for c in ('nome', 'email', 'senha') if not corpo.get(c)]
    if faltando:
        return jsonify({'erro': f"Campos obrigatórios: {', '.join(faltando)}"}), 400
    if Usuario.query.filter_by(email=corpo['email']).first():
        return jsonify({'erro': 'E-mail já cadastrado'}), 409
    u = Usuario(nome=corpo['nome'], email=corpo['email'], senha_hash=generate_password_hash(corpo['senha']),
                recebe_alertas=bool(corpo.get('recebe_alertas', True)),
                recebe_relatorio=bool(corpo.get('recebe_relatorio', True)),
                ativo=True, criado_em=agora_utc())
    mybd.session.add(u)
    mybd.session.commit()
    return jsonify({'id_usuario': u.id_usuario, 'nome': u.nome, 'email': u.email}), 201


@app.get('/api/notificacoes')
def listar_notificacoes():
    ns = (Notificacao.query
          .order_by(Notificacao.tentativa_em.desc(), Notificacao.id_notificacao.desc())
          .limit(200).all())
    return jsonify([{'id_notificacao': n.id_notificacao, 'tipo': n.tipo, 'status': n.status,
                     'id_usuario': n.id_usuario, 'id_alerta': n.id_alerta, 'id_relatorio': n.id_relatorio,
                     'tentativa_em': iso_utc(n.tentativa_em), 'erro': n.erro} for n in ns])


@app.post('/api/notificacoes/teste')
def testar_email():
    """Envia um e-mail de teste para confirmar a configuração do Gmail. Corpo: {"email": "..."}"""
    corpo = request.get_json(silent=True) or {}
    if not corpo.get('email'):
        return jsonify({'erro': 'Informe o campo "email"'}), 400
    try:
        enviar_email(corpo['email'], 'Teste — Monitoramento da qualidade do ar',
                     'Se você recebeu esta mensagem, o envio pelo Gmail está funcionando.')
    except Exception as e:
        return jsonify({'erro': f'Falha no envio: {e}'}), 502
    return jsonify({'mensagem': f"E-mail de teste enviado para {corpo['email']}"})


# CONTEUDO


if __name__ == '__main__':
    iniciar_servicos()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
