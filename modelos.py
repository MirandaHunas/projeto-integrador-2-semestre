"""Modelos do banco 'ambiental' (espelham o DDL; as tabelas são criadas pelo script SQL)."""
from flask_sqlalchemy import SQLAlchemy

mybd = SQLAlchemy()


class Usuario(mybd.Model):
    __tablename__ = 'usuario'

    id_usuario = mybd.Column(mybd.Integer, primary_key=True, autoincrement=True)
    nome = mybd.Column(mybd.String(100), nullable=False)
    email = mybd.Column(mybd.String(254), nullable=False)
    senha_hash = mybd.Column(mybd.String(255), nullable=False)
    recebe_alertas = mybd.Column(mybd.Boolean, nullable=False)
    recebe_relatorio = mybd.Column(mybd.Boolean, nullable=False)
    ativo = mybd.Column(mybd.Boolean, nullable=False)
    criado_em = mybd.Column(mybd.DateTime, nullable=False)


class Severidade(mybd.Model):
    __tablename__ = 'severidade'

    id_severidade = mybd.Column(mybd.SmallInteger, primary_key=True, autoincrement=False)
    nome = mybd.Column(mybd.String(20), nullable=False)
    ordem = mybd.Column(mybd.SmallInteger, nullable=False)
    envia_email = mybd.Column(mybd.Boolean, nullable=False)


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


class Relatorio(mybd.Model):
    __tablename__ = 'relatorio'

    id_relatorio = mybd.Column(mybd.Integer, primary_key=True, autoincrement=True)
    periodo_inicio = mybd.Column(mybd.Date, nullable=False)
    periodo_fim = mybd.Column(mybd.Date, nullable=False)
    dados_entrada = mybd.Column(mybd.Text, nullable=False)
    texto_llm = mybd.Column(mybd.Text, nullable=False)
    modelo_llm = mybd.Column(mybd.String(100), nullable=False)
    gerado_em = mybd.Column(mybd.DateTime, nullable=False)


class Meteorologico(mybd.Model):
    __tablename__ = 'meteorologico'

    id_meteo = mybd.Column(mybd.Integer, primary_key=True, autoincrement=True)
    referencia_tempo = mybd.Column(mybd.DateTime, nullable=False)
    temperatura_ext = mybd.Column(mybd.Numeric(5, 2))
    umidade_ext = mybd.Column(mybd.Numeric(5, 2))
    pressao_ext = mybd.Column(mybd.Numeric(7, 2))
    pm25_ext = mybd.Column(mybd.Numeric(7, 2))
    pm10_ext = mybd.Column(mybd.Numeric(7, 2))
    coletado_em = mybd.Column(mybd.DateTime, nullable=False)


class Limite(mybd.Model):
    __tablename__ = 'limite'

    id_limite = mybd.Column(mybd.Integer, primary_key=True, autoincrement=True)
    variavel = mybd.Column(
        mybd.Enum('temperature', 'pressure', 'humidity', 'CO2', 'particula1', 'particula2'),
        nullable=False,
    )
    id_severidade = mybd.Column(mybd.SmallInteger, mybd.ForeignKey('severidade.id_severidade'), nullable=False)
    operador = mybd.Column(mybd.Enum('>', '>=', '<', '<='), nullable=False)
    valor = mybd.Column(mybd.Numeric(9, 2), nullable=False)
    persistencia_min = mybd.Column(mybd.SmallInteger, nullable=False)
    fonte = mybd.Column(mybd.String(255), nullable=False)
    ativo = mybd.Column(mybd.Boolean, nullable=False)


class RegraCombinacao(mybd.Model):
    __tablename__ = 'regra_combinacao'

    id_regra = mybd.Column(mybd.Integer, primary_key=True, autoincrement=True)
    nome = mybd.Column(mybd.String(100), nullable=False)
    descricao = mybd.Column(mybd.String(255))
    id_severidade = mybd.Column(mybd.SmallInteger, mybd.ForeignKey('severidade.id_severidade'), nullable=False)
    persistencia_min = mybd.Column(mybd.SmallInteger, nullable=False)
    ativo = mybd.Column(mybd.Boolean, nullable=False)


class RegraCondicao(mybd.Model):
    __tablename__ = 'regra_condicao'

    id_regra = mybd.Column(mybd.Integer, mybd.ForeignKey('regra_combinacao.id_regra'), primary_key=True)
    id_limite = mybd.Column(mybd.Integer, mybd.ForeignKey('limite.id_limite'), primary_key=True)


class Alerta(mybd.Model):
    __tablename__ = 'alerta'

    id_alerta = mybd.Column(mybd.BigInteger, primary_key=True, autoincrement=True)
    id_severidade = mybd.Column(mybd.SmallInteger, mybd.ForeignKey('severidade.id_severidade'), nullable=False)
    id_regra = mybd.Column(mybd.Integer, mybd.ForeignKey('regra_combinacao.id_regra'))
    id_leitura_disparo = mybd.Column(mybd.BigInteger, mybd.ForeignKey('leitura_sensor.id'), nullable=False)
    inicio = mybd.Column(mybd.DateTime, nullable=False)
    fim = mybd.Column(mybd.DateTime)
    status = mybd.Column(mybd.String(9), nullable=False)


class AlertaVariavel(mybd.Model):
    __tablename__ = 'alerta_variavel'

    id_alerta = mybd.Column(mybd.BigInteger, mybd.ForeignKey('alerta.id_alerta'), primary_key=True)
    id_limite = mybd.Column(mybd.Integer, mybd.ForeignKey('limite.id_limite'), primary_key=True)
    valor_pico = mybd.Column(mybd.Numeric(9, 2), nullable=False)


class Notificacao(mybd.Model):
    __tablename__ = 'notificacao'

    id_notificacao = mybd.Column(mybd.BigInteger, primary_key=True, autoincrement=True)
    id_usuario = mybd.Column(mybd.Integer, mybd.ForeignKey('usuario.id_usuario'), nullable=False)
    id_alerta = mybd.Column(mybd.BigInteger, mybd.ForeignKey('alerta.id_alerta'))
    id_relatorio = mybd.Column(mybd.Integer, mybd.ForeignKey('relatorio.id_relatorio'))
    tipo = mybd.Column(mybd.String(9), nullable=False)
    tentativa_em = mybd.Column(mybd.DateTime, nullable=False)
    status = mybd.Column(mybd.Enum('enviado', 'falha'), nullable=False)
    gmail_message_id = mybd.Column(mybd.String(64))
    erro = mybd.Column(mybd.String(500))
