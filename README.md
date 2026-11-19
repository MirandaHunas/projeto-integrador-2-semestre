# API — Monitoramento da Qualidade do Ar (Sala 09)

Fluxo: caixinha → broker MQTT → `app.py` (grava em `leitura_sensor` e avalia alertas) → MySQL → API → dashboard.
Integrações externas: **Open-Meteo** (clima e qualidade do ar externos), **Gmail** (alertas graves e relatório) e **Gemini** (texto do relatório semanal).

## Arquivos

| Arquivo | Função |
|---|---|
| `app.py` | API Flask, recebimento MQTT e tarefas agendadas |
| `modelos.py` | Modelos das 11 tabelas do banco `ambiental` |
| `alertas.py` | Motor de alertas (limites, persistência de 10 min, regras de combinação) |
| `servicos.py` | Open-Meteo, Gmail (SMTP) e Gemini; geração do relatório |
| `ambiental.sql` | Criação do banco (rodar uma vez só) + 3 severidades |
| `limites.sql` | Limites com fonte (ANVISA e OMS) e a regra "Sala abafada" |
| `simular_caixinha.py` | Publica leituras falsas no MQTT para teste |
| `.env.exemplo` | Modelo das variáveis de ambiente |
| `iniciar.bat` | Instala as dependências e liga o sistema (Windows, dois cliques) |

## Instalação

```bash
pip install -r requirements.txt
```

1. No MySQL, rode `ambiental.sql` e depois `limites.sql` (cada um uma vez só).
2. Copie `.env.exemplo` para `.env` e preencha.
3. `python app.py`

## Rotas

Todas as datas são devolvidas em **UTC** com `Z` no final (ex.: `2026-11-18T13:00:00Z`); o dashboard converte para o horário local.
Nos filtros `inicio` e `fim`, uma data **sem fuso** é lida como **horário de Brasília** (ex.: `?inicio=2026-11-18T08:00`).

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/status` | Saúde da API, conexão MQTT, última leitura, alertas abertos |
| GET | `/api/leituras?inicio=&fim=&limite=` | Leituras do período (padrão: última hora) |
| GET | `/api/leituras/ultima` | Leitura mais recente (cards do dashboard e "última atualização") |
| GET | `/api/leituras/resumo?inicio=&fim=` | Média, mínimo e máximo de cada variável (padrão: 24 h) |
| GET | `/api/alertas?status=aberto\|encerrado&inicio=&fim=` | Alertas com severidade, regra e variáveis que causaram |
| GET | `/api/alertas/<id>` | Detalhe de um alerta |
| GET | `/api/meteorologico?inicio=&fim=` | Dados externos do Open-Meteo (padrão: 24 h) |
| GET | `/api/meteorologico/ultimo` | Dado externo mais recente |
| POST | `/api/meteorologico/coletar` | Força uma coleta no Open-Meteo |
| GET | `/api/relatorios` | Lista de relatórios (sem o texto) |
| GET | `/api/relatorios/<id>` | Relatório completo: texto do LLM e dados usados |
| POST | `/api/relatorios/gerar` | Gera um relatório na hora. Corpo opcional: `{"dias": 7, "enviar_email": true}` |
| GET | `/api/severidades` | Níveis de severidade |
| GET | `/api/limites` | Limites com a fonte de cada valor |
| GET | `/api/regras` | Regras de combinação |
| GET | `/api/usuarios` | Destinatários cadastrados |
| POST | `/api/usuarios` | Cadastra destinatário: `{"nome", "email", "senha"}` |
| GET | `/api/notificacoes` | Histórico de e-mails (enviado/falha) |
| POST | `/api/notificacoes/teste` | Envia e-mail de teste: `{"email": "..."}` |

## Gravação das leituras (MQTT)

- Cada mensagem da caixinha vira uma linha em `leitura_sensor`.
- `timestamp` em segundos ou milissegundos (Unix) é convertido para UTC. Se vier ausente, inválido ou com o relógio da caixinha desacertado (antes de 2020), a leitura é gravada com o horário do servidor e um aviso aparece no log.
- Valor inválido em um campo vira `NULL`; o resto da leitura é gravado.
- Leitura repetida (mesmo `registro_tempo`) é ignorada.

## Regras de alerta

- Um alerta abre quando a variável fica fora do limite por **10 minutos seguidos** e encerra na primeira leitura normal.
- Leitura sem valor (`NULL`) não abre nem encerra alerta.
- Só o nível **Grave** envia e-mail (`severidade.envia_email`).
- **Atenção:** os limites da OMS para PM2.5/PM10 são médias de 24 h; aplicá-los a 10 minutos é um critério conservador do grupo. Assumimos `particula1` = PM2.5 e `particula2` = PM10 (a confirmar com o sensor).

## Tarefas automáticas

- Open-Meteo: a cada 10 minutos (`INTERVALO_METEO_MIN`). Fonte: Open-Meteo, licença CC BY 4.0 (citar no dashboard).
- Relatório semanal: gerado automaticamente para a semana anterior (segunda a domingo) e enviado por e-mail.
