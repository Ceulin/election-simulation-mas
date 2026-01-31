# python_spade/authority_agent.py
import spade
import asyncio
import json
import statistics
from collections import Counter
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
import common as cfg

class ElectionAuthorityAgent(spade.agent.Agent):
    def __init__(self, jid, password, supervisor_jid=None, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.votes_data = [] # Armazena os payloads ricos recebidos dos eleitores

    def apply_dhondt(self, votes_by_party):
        """
        Implementa o método D'Hondt para distribuição de N_SEATS cadeiras.
        O método divide o total de votos de cada partido por divisores sucessivos (1, 2, 3...).
        """
        n_seats = cfg.N_SEATS
        seats = {p: 0 for p in votes_by_party.keys()}
        
        if not votes_by_party or n_seats <= 0:
            return seats

        # Realiza a atribuição cadeira por cadeira
        for _ in range(n_seats):
            quocientes = {}
            for party, votes in votes_by_party.items():
                # Fórmula: Votos / (Cadeiras já obtidas + 1)
                quocientes[party] = votes / (seats[party] + 1)
            
            # O partido com o maior quociente ganha a cadeira da rodada
            winner = max(quocientes, key=quocientes.get)
            seats[winner] += 1
            
        return seats

    class StartCountListener(CyclicBehaviour):
        async def run(self):
            """Aguarda o comando START_COUNT do Supervisor."""
            msg = await self.receive(timeout=0.5)
            if msg and "START_COUNT" in (msg.body or ""):
                print(f"[{cfg.get_sender_name(str(self.agent.jid)).upper()}] Comando START_COUNT recebido. Processando votos...")
                # Pequeno delay para garantir que os últimos votos cheguem
                await asyncio.sleep(2.0)
                await self._count_and_publish()

        async def _count_and_publish(self):
            """Realiza a contagem eleitoral e gera o relatório científico final."""
            total_citizens = cfg.N_CITIZENS
            votes_received = len(self.agent.votes_data)
            
            # Inicialização de métricas
            votes_by_party = {}
            null_votes = 0
            
            # Listas para cálculos estatísticos (Objetivo 3.2)
            engagements = []
            overloads = []
            deltas = []
            final_ideologies = []
            news_exposures = []
            fake_exposures = []

            for data in self.agent.votes_data:
                vote = data.get("vote")
                if vote == "NULO":
                    null_votes += 1
                else:
                    votes_by_party[vote] = votes_by_party.get(vote, 0) + 1
                
                # Coleta de dados para médias
                engagements.append(data.get("engagement", 0))
                overloads.append(data.get("overload", 0))
                deltas.append(data.get("delta_ideology", 0))
                final_ideologies.append(data.get("final_ideology", 0))
                news_exposures.append(data.get("exposures_news", 0))
                fake_exposures.append(data.get("exposures_fake", 0))

            # Cálculo de cadeiras (D'Hondt)
            seats_dhondt = self.agent.apply_dhondt(votes_by_party)

            # Construção do Payload de Resultados (Objetivo 3.3)
            results = {
                "abstentions": total_citizens - votes_received,
                "null_votes": null_votes,
                "votes_by_party": votes_by_party,
                "seats_dhondt": seats_dhondt,
                "avg_news_exposure": statistics.mean(news_exposures) if news_exposures else 0,
                "avg_fake_exposure": statistics.mean(fake_exposures) if fake_exposures else 0,
                "mean_delta_ideology": statistics.mean(deltas) if deltas else 0,
                "std_final_ideology": statistics.stdev(final_ideologies) if len(final_ideologies) > 1 else 0,
                "mean_engagement": statistics.mean(engagements) if engagements else 0,
                "mean_overload": statistics.mean(overloads) if overloads else 0
            }

            # Envio para o Supervisor
            reply = Message(to=str(self.agent.supervisor_jid))
            reply.set_metadata("protocol", cfg.PROTOCOL_RESULTS)
            reply.body = json.dumps(results)
            await self.send(reply)
            
            print(f"[{cfg.get_sender_name(str(self.agent.jid)).upper()}] Resultados publicados com sucesso.")

    async def setup(self):
        # Comportamento para coletar votos continuamente (Objetivo 3.1)
        class VoteCollector(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=0.5)
                if msg and msg.metadata.get("protocol") == cfg.PROTOCOL_VOTE:
                    try:
                        payload = json.loads(msg.body)
                        self.agent.votes_data.append(payload)
                    except Exception as e:
                        print(f"Erro ao decodificar voto: {e}")

        self.add_behaviour(VoteCollector(), Template(metadata={"protocol": cfg.PROTOCOL_VOTE}))
        self.add_behaviour(self.StartCountListener(), Template(metadata={"protocol": cfg.PROTOCOL_VOTING}))