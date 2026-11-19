create database if not exists ambiental;

use ambiental;

create table usuario (
    id_usuario       int auto_increment primary key,
    nome             varchar(100) not null,
    email            varchar(254) not null,
    senha_hash       varchar(255) not null,
    recebe_alertas   boolean not null,
    recebe_relatorio boolean not null,
    ativo            boolean not null,
    criado_em        datetime not null
);

create table severidade (
    id_severidade tinyint primary key,
    nome          varchar(20) not null,
    ordem         tinyint not null,
    envia_email   boolean not null
);

create table leitura_sensor (
    id             bigint auto_increment primary key,
    temperature    decimal(5,2),
    pressure       decimal(7,2),
    altitude       decimal(7,2),
    humidity       decimal(5,2),
    CO2            smallint,
    particula1     decimal(7,2),
    particula2     decimal(7,2),
    registro_tempo datetime(3) not null,

    index (registro_tempo)
);

create table relatorio (
    id_relatorio   int auto_increment primary key,
    periodo_inicio date not null,
    periodo_fim    date not null,
    dados_entrada  text not null,
    texto_llm      mediumtext not null,
    modelo_llm     varchar(100) not null,
    gerado_em      datetime not null
);

create table meteorologico (
    id_meteo         int auto_increment primary key,
    referencia_tempo datetime not null,
    temperatura_ext  decimal(5,2),
    umidade_ext      decimal(5,2),
    pressao_ext      decimal(7,2),
    pm25_ext         decimal(7,2),
    pm10_ext         decimal(7,2),
    coletado_em      datetime not null
);

create table limite (
    id_limite        int auto_increment primary key,
    variavel         enum('temperature','pressure','humidity','CO2','particula1','particula2') not null,
    id_severidade    tinyint not null,
    operador         enum('>','>=','<','<=') not null,
    valor            decimal(9,2) not null,
    persistencia_min smallint not null,
    fonte            varchar(255) not null,
    ativo            boolean not null,

    foreign key (id_severidade) references severidade(id_severidade)
);

create table regra_combinacao (
    id_regra         int auto_increment primary key,
    nome             varchar(100) not null,
    descricao        varchar(255),
    id_severidade    tinyint not null,
    persistencia_min smallint not null,
    ativo            boolean not null,

    foreign key (id_severidade) references severidade(id_severidade)
);

create table regra_condicao (
    id_regra  int not null,
    id_limite int not null,

    primary key (id_regra, id_limite),
    foreign key (id_regra)  references regra_combinacao(id_regra),
    foreign key (id_limite) references limite(id_limite)
);

create table alerta (
    id_alerta          bigint auto_increment primary key,
    id_severidade      tinyint not null,
    id_regra           int,
    id_leitura_disparo bigint not null,
    inicio             datetime(3) not null,
    fim                datetime(3),
    status             varchar(9) not null,

    foreign key (id_severidade)      references severidade(id_severidade),
    foreign key (id_regra)           references regra_combinacao(id_regra),
    foreign key (id_leitura_disparo) references leitura_sensor(id)
);

create table alerta_variavel (
    id_alerta  bigint not null,
    id_limite  int not null,
    valor_pico decimal(9,2) not null,

    primary key (id_alerta, id_limite),
    foreign key (id_alerta) references alerta(id_alerta),
    foreign key (id_limite) references limite(id_limite)
);

create table notificacao (
    id_notificacao   bigint auto_increment primary key,
    id_usuario       int not null,
    id_alerta        bigint,
    id_relatorio     int,
    tipo             varchar(9) not null,
    tentativa_em     datetime not null,
    status           enum('enviado','falha') not null,
    gmail_message_id varchar(64),
    erro             varchar(500),

    foreign key (id_usuario)   references usuario(id_usuario),
    foreign key (id_alerta)    references alerta(id_alerta),
    foreign key (id_relatorio) references relatorio(id_relatorio)
);

insert into severidade (id_severidade, nome, ordem, envia_email) values
    (1, 'Moderado', 1, false),
    (2, 'Ruim',     2, false),
    (3, 'Grave',    3, true);