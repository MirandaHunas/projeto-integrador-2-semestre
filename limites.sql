use ambiental;

insert into limite (variavel, id_severidade, operador, valor, persistencia_min, fonte, ativo) values
    ('temperature', 1, '>',  26.00, 10, 'ANVISA RE nº 9/2003 - faixa recomendável 23 a 26 °C (verão)', true),
    ('temperature', 1, '<',  20.00, 10, 'ANVISA RE nº 9/2003 - faixa recomendável 20 a 22 °C (inverno)', true),
    ('humidity',    1, '>',  65.00, 10, 'ANVISA RE nº 9/2003 - umidade relativa máxima recomendável 65%', true),
    ('humidity',    1, '<',  35.00, 10, 'ANVISA RE nº 9/2003 - umidade relativa mínima recomendável 35% (inverno)', true),
    ('CO2',         2, '>', 1000.00, 10, 'ANVISA RE nº 9/2003 - valor máximo recomendável de 1000 ppm (renovação de ar)', true),
    ('particula1',  1, '>',  15.00, 10, 'OMS 2021 - PM2.5, nível-guia de 24 h (15 µg/m³)', true),
    ('particula1',  2, '>',  37.50, 10, 'OMS 2021 - PM2.5, meta intermediária 3 de 24 h (37,5 µg/m³)', true),
    ('particula1',  3, '>',  75.00, 10, 'OMS 2021 - PM2.5, meta intermediária 1 de 24 h (75 µg/m³)', true),
    ('particula2',  1, '>',  45.00, 10, 'OMS 2021 - PM10, nível-guia de 24 h (45 µg/m³)', true),
    ('particula2',  2, '>',  75.00, 10, 'OMS 2021 - PM10, meta intermediária 3 de 24 h (75 µg/m³)', true),
    ('particula2',  3, '>', 150.00, 10, 'OMS 2021 - PM10, meta intermediária 1 de 24 h (150 µg/m³)', true);

insert into regra_combinacao (nome, descricao, id_severidade, persistencia_min, ativo) values
    ('Sala abafada', 'CO2 acima de 1000 ppm e umidade acima de 65% ao mesmo tempo: ventilação insuficiente', 3, 10, true);

insert into regra_condicao (id_regra, id_limite)
select r.id_regra, l.id_limite
from regra_combinacao r
join limite l on (l.variavel = 'CO2' and l.operador = '>')
             or (l.variavel = 'humidity' and l.operador = '>')
where r.nome = 'Sala abafada';
