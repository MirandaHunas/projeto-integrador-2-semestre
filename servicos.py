"""Integrações externas: Open-Meteo, Gmail (SMTP) e Gemini (relatório semanal)."""
import json
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from email.utils import make_msgid

from sqlalchemy import func

from modelos import (Alerta, AlertaVariavel, Limite, Meteorologico, Notificacao,
                     Registro, Relatorio, Severidade, Usuario, mybd)

# Horário de Brasília (sem horário de verão desde 2019). O banco grava tudo em UTC.
BRT = timezone(timedelta(hours=-3))

VARIAVEIS = ['temperature', 'pressure', 'altitude', 'humidity', 'CO2', 'particula1', 'particula2']
NOMES_VARIAVEIS = {
    'temperature': 'temperatura (°C)', 'pressure': 'pressão (hPa)', 'altitude': 'altitude (m)',
    'humidity': 'umidade relativa (%)', 'CO2': 'CO2 (ppm)',
    'particula1': 'partículas 1 (µg/m³)', 'particula2': 'partículas 2 (µg/m³)',
}


# ********************* TEMPO *****************************************

def agora_utc():
    """Data e hora atual em UTC, sem fuso (formato das colunas DATETIME)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_para_brt(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(BRT) if dt else None


def inicio_do_dia_brt_em_utc(d):
    """00:00 de um dia no horário de Brasília, convertido para UTC."""
    return datetime(d.year, d.month, d.day, tzinfo=BRT).astimezone(timezone.utc).replace(tzinfo=None)


# ********************* HTTP (sem dependências extras) ****************

def _http_json(url, metodo='GET', corpo=None, cabecalhos=None, timeout=20):
    dados = json.dumps(corpo).encode('utf-8') if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos or {})
    if dados is not None:
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


# ********************* OPEN-METEO ************************************

def coletar_meteorologico():
    """Consulta o Open-Meteo e grava uma linha em 'meteorologico'.

    Precisa estar dentro de app.app_context(). Devolve a linha gravada ou None.
    """
    lat = os.environ.get('LATITUDE', '-23.5505')
    lon = os.environ.get('LONGITUDE', '-46.6333')

    clima = _http_json(
        'https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode({
            'latitude': lat, 'longitude': lon,
            'current': 'temperature_2m,relative_humidity_2m,surface_pressure',
        })
    )['current']

    try:
        ar = _http_json(
            'https://air-quality-api.open-meteo.com/v1/air-quality?' + urllib.parse.urlencode({
                'latitude': lat, 'longitude': lon, 'current': 'pm10,pm2_5',
            })
        )['current']
    except Exception as e:  # a qualidade do ar é opcional; o clima continua sendo gravado
        print(f"[Open-Meteo] Falha na API de qualidade do ar: {e}")
        ar = {}

    # Sem o parâmetro 'timezone', o Open-Meteo devolve o horário em GMT (= UTC)
    referencia = datetime.fromisoformat(clima['time'])

    if Meteorologico.query.filter_by(referencia_tempo=referencia).first():
        print(f"[Open-Meteo] Dado de {referencia} já gravado; nada a fazer")
        return None

    linha = Meteorologico(
        referencia_tempo=referencia,
        temperatura_ext=clima.get('temperature_2m'),
        umidade_ext=clima.get('relative_humidity_2m'),
        pressao_ext=clima.get('surface_pressure'),
        pm25_ext=ar.get('pm2_5'),
        pm10_ext=ar.get('pm10'),
        coletado_em=agora_utc(),
    )
    mybd.session.add(linha)
    mybd.session.commit()
    print(f"[Open-Meteo] Gravado: id {linha.id_meteo} ({referencia} UTC)")
    return linha


# ********************* GMAIL (SMTP com senha de app) *****************

def enviar_email(destinatario, assunto, texto):
    """Envia um e-mail pelo Gmail. Devolve o Message-ID; levanta exceção se falhar."""
    usuario = os.environ.get('GMAIL_USER')
    senha = os.environ.get('GMAIL_SENHA_APP')
    if not usuario or not senha:
        raise RuntimeError('GMAIL_USER ou GMAIL_SENHA_APP não configurados no .env')

    msg = EmailMessage()
    msg['From'] = usuario
    msg['To'] = destinatario
    msg['Subject'] = assunto
    msg['Message-ID'] = make_msgid(domain='ambiental.local')
    msg.set_content(texto)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as smtp:
        smtp.login(usuario, senha.replace(' ', ''))
        smtp.send_message(msg)
    return msg['Message-ID'][:64]


def notificar_usuarios(tipo, assunto, texto, id_alerta=None, id_relatorio=None):
    """Envia o e-mail a cada usuário ativo que aceita aquele tipo e grava em 'notificacao'."""
    filtro = Usuario.recebe_alertas if tipo == 'alerta' else Usuario.recebe_relatorio
    usuarios = Usuario.query.filter(Usuario.ativo.is_(True), filtro.is_(True)).all()
    if not usuarios:
        print(f"[E-mail] Nenhum usuário cadastrado para receber '{tipo}'")

    enviados = 0
    for u in usuarios:
        registro = Notificacao(id_usuario=u.id_usuario, id_alerta=id_alerta, id_relatorio=id_relatorio,
                               tipo=tipo, tentativa_em=agora_utc(), status='falha')
        try:
            registro.gmail_message_id = enviar_email(u.email, assunto, texto)
            registro.status = 'enviado'
            enviados += 1
        except Exception as e:
            registro.erro = str(e)[:500]
            print(f"[E-mail] Falha ao enviar para {u.email}: {e}")
        mybd.session.add(registro)
    mybd.session.commit()
    return enviados


# ********************* GEMINI (LLM) **********************************

GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models'


def _modelo_flash_disponivel(chave):
    """Se o modelo configurado não existir mais, procura um modelo 'flash' disponível."""
    modelos = _http_json(GEMINI_URL, cabecalhos={'x-goog-api-key': chave}).get('models', [])
    candidatos = [m['name'].split('/', 1)[1] for m in modelos
                  if 'generateContent' in m.get('supportedGenerationMethods', [])
                  and 'flash' in m['name'] and 'image' not in m['name'] and 'tts' not in m['name']]
    if not candidatos:
        raise RuntimeError('Nenhum modelo Gemini disponível para generateContent')
    return candidatos[0]


def gerar_texto_gemini(prompt):
    """Chama o Gemini e devolve (texto, nome_do_modelo)."""
    chave = os.environ.get('GEMINI_API_KEY')
    if not chave:
        raise RuntimeError('GEMINI_API_KEY não configurada no .env')
    modelo = os.environ.get('GEMINI_MODEL', 'gemini-flash-latest')
    corpo = {'contents': [{'parts': [{'text': prompt}]}]}

    try:
        resposta = _http_json(f'{GEMINI_URL}/{modelo}:generateContent', 'POST', corpo,
                              {'x-goog-api-key': chave}, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        modelo = _modelo_flash_disponivel(chave)
        print(f"[Gemini] Modelo configurado não encontrado; usando {modelo}")
        resposta = _http_json(f'{GEMINI_URL}/{modelo}:generateContent', 'POST', corpo,
                              {'x-goog-api-key': chave}, timeout=60)

    partes = resposta['candidates'][0]['content']['parts']
    texto = ''.join(p.get('text', '') for p in partes).strip()
    if not texto:
        raise RuntimeError('O Gemini devolveu uma resposta vazia')
    return texto, modelo


# ********************* RELATÓRIO SEMANAL *****************************

def _num(v):
    return round(float(v), 2) if v is not None else None


def montar_dados_periodo(inicio_utc, fim_utc):
    """Estatísticas do período, usadas como entrada do LLM e guardadas em 'dados_entrada'."""
    variaveis = {}
    for nome in VARIAVEIS:
        col = getattr(Registro, nome)
        n, media, minimo, maximo = mybd.session.query(
            func.count(col), func.avg(col), func.min(col), func.max(col)
        ).filter(Registro.registro_tempo >= inicio_utc, Registro.registro_tempo < fim_utc).one()
        variaveis[nome] = {'leituras_validas': n, 'media': _num(media), 'minimo': _num(minimo), 'maximo': _num(maximo)}

    total_leituras = Registro.query.filter(
        Registro.registro_tempo >= inicio_utc, Registro.registro_tempo < fim_utc).count()

    alertas = Alerta.query.filter(Alerta.inicio >= inicio_utc, Alerta.inicio < fim_utc).all()
    por_severidade, por_variavel, duracoes = {}, {}, []
    for a in alertas:
        sev = mybd.session.get(Severidade, a.id_severidade).nome
        por_severidade[sev] = por_severidade.get(sev, 0) + 1
        for av in AlertaVariavel.query.filter_by(id_alerta=a.id_alerta).all():
            var = mybd.session.get(Limite, av.id_limite).variavel
            por_variavel[var] = por_variavel.get(var, 0) + 1
        if a.fim:
            duracoes.append((a.fim - a.inicio).total_seconds() / 60)

    externo = {}
    for nome in ['temperatura_ext', 'umidade_ext', 'pressao_ext', 'pm25_ext', 'pm10_ext']:
        externo[nome] = _num(mybd.session.query(func.avg(getattr(Meteorologico, nome))).filter(
            Meteorologico.referencia_tempo >= inicio_utc, Meteorologico.referencia_tempo < fim_utc).scalar())

    return {
        'periodo_utc': [inicio_utc.isoformat(), fim_utc.isoformat()],
        'total_leituras': total_leituras,
        'variaveis_internas': variaveis,
        'alertas': {
            'total': len(alertas),
            'por_severidade': por_severidade,
            'por_variavel': por_variavel,
            'duracao_media_min': round(sum(duracoes) / len(duracoes), 1) if duracoes else None,
            'ainda_abertos': sum(1 for a in alertas if a.fim is None),
        },
        'medias_externas_open_meteo': externo,
    }


def _prompt_relatorio(dados, periodo_inicio, periodo_fim):
    return (
        "Você é um assistente que escreve relatórios de qualidade do ar interno para os responsáveis "
        "pela Sala 09 de uma escola técnica. Escreva em português do Brasil, em texto simples (sem markdown), "
        "com no máximo 300 palavras, nestas partes: 1) Resumo da semana; 2) Variáveis que exigem atenção; "
        "3) Alertas emitidos; 4) Comparação com o ar externo; 5) Recomendações práticas (ventilação, ocupação). "
        "Use somente os números do JSON abaixo, sem inventar valores. Se faltar dado, diga que faltou. "
        "Valores de referência: CO2 até 1000 ppm (ANVISA RE 9/2003); umidade 35% a 65% e temperatura 20 °C "
        "a 26 °C (ANVISA RE 9/2003); PM2.5 até 15 µg/m³ e PM10 até 45 µg/m³ em média de 24 h (OMS 2021). "
        f"Período: {periodo_inicio:%d/%m/%Y} a {periodo_fim:%d/%m/%Y}.\n\nDados:\n"
        + json.dumps(dados, ensure_ascii=False, indent=2)
    )


def _texto_sem_llm(dados, periodo_inicio, periodo_fim):
    """Texto de reserva caso o Gemini esteja indisponível; o relatório não deixa de existir."""
    linhas = [f"Relatório de qualidade do ar — Sala 09 — {periodo_inicio:%d/%m/%Y} a {periodo_fim:%d/%m/%Y}",
              "(Texto gerado automaticamente, sem LLM.)", "",
              f"Leituras recebidas: {dados['total_leituras']}"]
    for nome, v in dados['variaveis_internas'].items():
        if v['leituras_validas']:
            linhas.append(f"- {NOMES_VARIAVEIS[nome]}: média {v['media']}, mín. {v['minimo']}, máx. {v['maximo']}")
    a = dados['alertas']
    linhas += ["", f"Alertas: {a['total']} (por severidade: {a['por_severidade'] or 'nenhum'})"]
    return '\n'.join(linhas)


def gerar_relatorio(periodo_inicio, periodo_fim, enviar=True):
    """Gera o relatório de periodo_inicio a periodo_fim (datas locais, inclusive), grava e envia por e-mail."""
    inicio_utc = inicio_do_dia_brt_em_utc(periodo_inicio)
    fim_utc = inicio_do_dia_brt_em_utc(periodo_fim + timedelta(days=1))
    dados = montar_dados_periodo(inicio_utc, fim_utc)

    try:
        texto, modelo = gerar_texto_gemini(_prompt_relatorio(dados, periodo_inicio, periodo_fim))
    except Exception as e:
        print(f"[Gemini] Falha, usando texto automático: {e}")
        texto, modelo = _texto_sem_llm(dados, periodo_inicio, periodo_fim), 'sem LLM (texto automático)'

    rel = Relatorio(periodo_inicio=periodo_inicio, periodo_fim=periodo_fim,
                    dados_entrada=json.dumps(dados, ensure_ascii=False), texto_llm=texto,
                    modelo_llm=modelo[:100], gerado_em=agora_utc())
    mybd.session.add(rel)
    mybd.session.commit()
    print(f"[Relatório] Gerado: id {rel.id_relatorio} ({modelo})")

    if enviar:
        notificar_usuarios('relatorio',
                           f'Relatório semanal de qualidade do ar — {periodo_inicio:%d/%m} a {periodo_fim:%d/%m}',
                           texto, id_relatorio=rel.id_relatorio)
    return rel


def semana_anterior(hoje=None):
    """Segunda a domingo da semana passada, no calendário local."""
    hoje = hoje or datetime.now(BRT).date()
    segunda = hoje - timedelta(days=hoje.weekday() + 7)
    return segunda, segunda + timedelta(days=6)
