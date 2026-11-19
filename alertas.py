"""Motor de alertas: compara cada leitura com os limites e as regras de combinação.

Um alerta só abre quando a condição persiste por 'persistencia_min' minutos seguidos,
e é encerrado na primeira leitura em que a condição deixa de existir.
"""
import operator
import threading

from modelos import (Alerta, AlertaVariavel, Limite, RegraCombinacao, RegraCondicao,
                     Severidade, mybd)
from servicos import NOMES_VARIAVEIS, notificar_usuarios, utc_para_brt

OPERADORES = {'>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le}


class MotorAlertas:
    def __init__(self):
        self.inicio_violacao = {}   # chave -> horário da primeira leitura fora do limite
        self.abertos = {}           # chave -> id_alerta aberto
        self.trava = threading.Lock()

    # Chaves: ('L', id_limite) para limite simples, ('R', id_regra) para regra de combinação

    def carregar_abertos(self):
        """Ao iniciar o programa, retoma os alertas que ficaram abertos no banco."""
        for a in Alerta.query.filter_by(status='aberto').all():
            if a.id_regra:
                chave = ('R', a.id_regra)
            else:
                av = AlertaVariavel.query.filter_by(id_alerta=a.id_alerta).first()
                if av is None:
                    continue
                chave = ('L', av.id_limite)
            self.abertos[chave] = a.id_alerta
            self.inicio_violacao[chave] = a.inicio
        print(f"[Alertas] {len(self.abertos)} alerta(s) aberto(s) retomado(s)")

    def avaliar(self, leitura):
        """Chamar depois de gravar cada leitura (dentro de app.app_context())."""
        with self.trava:
            t = leitura.registro_tempo
            limites = Limite.query.filter_by(ativo=True).all()

            violados, sem_dado = {}, set()
            for lim in limites:
                valor = getattr(leitura, lim.variavel)
                if valor is None:
                    sem_dado.add(lim.id_limite)
                elif OPERADORES[lim.operador](valor, lim.valor):
                    violados[lim.id_limite] = valor

            # 1) Limites simples
            for lim in limites:
                if lim.id_limite in sem_dado:
                    continue  # sem dado nesta leitura: mantém o estado como está
                self._processar(('L', lim.id_limite), lim.id_limite in violados, t, lim.persistencia_min,
                                lim.id_severidade, None, [lim], violados, leitura)

            # 2) Regras de combinação (todos os limites da regra violados ao mesmo tempo)
            for regra in RegraCombinacao.query.filter_by(ativo=True).all():
                ids = [c.id_limite for c in RegraCondicao.query.filter_by(id_regra=regra.id_regra).all()]
                lims = [lim for lim in limites if lim.id_limite in ids]
                if not lims or len(lims) != len(ids) or any(i in sem_dado for i in ids):
                    continue
                self._processar(('R', regra.id_regra), all(i in violados for i in ids), t,
                                regra.persistencia_min, regra.id_severidade, regra, lims, violados, leitura)

    def _processar(self, chave, violado, t, persistencia_min, id_severidade, regra, lims, violados, leitura):
        if violado:
            self.inicio_violacao.setdefault(chave, t)
            if chave in self.abertos:
                self._atualizar_pico(self.abertos[chave], lims, violados)
            elif (t - self.inicio_violacao[chave]).total_seconds() >= persistencia_min * 60:
                self._abrir(chave, id_severidade, regra, lims, violados, leitura)
        else:
            self.inicio_violacao.pop(chave, None)
            if chave in self.abertos:
                self._encerrar(chave, t)

    def _abrir(self, chave, id_severidade, regra, lims, violados, leitura):
        alerta = Alerta(id_severidade=id_severidade, id_regra=regra.id_regra if regra else None,
                        id_leitura_disparo=leitura.id, inicio=self.inicio_violacao[chave], status='aberto')
        mybd.session.add(alerta)
        mybd.session.flush()
        for lim in lims:
            mybd.session.add(AlertaVariavel(id_alerta=alerta.id_alerta, id_limite=lim.id_limite,
                                            valor_pico=violados[lim.id_limite]))
        mybd.session.commit()
        self.abertos[chave] = alerta.id_alerta

        sev = mybd.session.get(Severidade, id_severidade)
        causa = ' + '.join(f"{NOMES_VARIAVEIS[l.variavel]} {l.operador} {l.valor}" for l in lims)
        print(f"[Alertas] ABERTO id {alerta.id_alerta} ({sev.nome}): {causa}")

        if sev.envia_email:
            inicio_local = utc_para_brt(alerta.inicio)
            texto = (
                f"Alerta de qualidade do ar — Sala 09\n\n"
                f"Severidade: {sev.nome}\n"
                f"{'Regra: ' + regra.nome + chr(10) if regra else ''}"
                f"Causa: {causa}\n"
                f"Valores medidos: " + ', '.join(
                    f"{NOMES_VARIAVEIS[l.variavel]} = {violados[l.id_limite]}" for l in lims) + "\n"
                f"Fora do limite desde: {inicio_local:%d/%m/%Y %H:%M} (horário de Brasília)\n\n"
                f"Recomendação: ventile o ambiente (abra portas e janelas) e reduza a ocupação até normalizar."
            )
            notificar_usuarios('alerta', f'[{sev.nome}] Alerta de qualidade do ar — Sala 09', texto,
                               id_alerta=alerta.id_alerta)

    def _atualizar_pico(self, id_alerta, lims, violados):
        mudou = False
        for lim in lims:
            av = mybd.session.get(AlertaVariavel, (id_alerta, lim.id_limite))
            novo = violados.get(lim.id_limite)
            if av is None or novo is None:
                continue
            pior = max if lim.operador in ('>', '>=') else min
            if pior(novo, av.valor_pico) != av.valor_pico:
                av.valor_pico = novo
                mudou = True
        if mudou:
            mybd.session.commit()

    def _encerrar(self, chave, t):
        alerta = mybd.session.get(Alerta, self.abertos.pop(chave))
        if alerta:
            alerta.fim = t
            alerta.status = 'encerrado'
            mybd.session.commit()
            print(f"[Alertas] ENCERRADO id {alerta.id_alerta}")


motor_alertas = MotorAlertas()
