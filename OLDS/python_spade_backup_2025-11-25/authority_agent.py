# python_spade/authority_agent.py
import spade
import asyncio
import json
from collections import Counter
from typing import Dict, List, Optional

from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from common import (
    get_sender_name,
    generate_jid,
    SUPERVISOR_PREFIX,
    PROTOCOL_VOTE,
    PROTOCOL_RESULTS,
    PROTOCOL_VOTING,
    PROTOCOL_INIT_SIM,
)


class ElectionAuthorityAgent(spade.agent.Agent):
    """
    Agente Autoridade Eleitoral:
    - Coleta votos dos Voters (espera JID completo ou 'NULO').
    - Recebe a lista de candidatos do Supervisor.
    - Ao receber START_COUNT, AGUARDA 5s e calcula e publica os resultados.
    """

    def __init__(
        self,
        jid: str,
        password: str,
        supervisor_jid: Optional[str] = None,
        *args,
        **kwargs
    ):
        super().__init__(jid, password, *args, **kwargs)

        self.supervisor_jid = supervisor_jid or generate_jid(SUPERVISOR_PREFIX, 1)
        self._votes: List[str] = []           # Votos recebidos (JIDs completos ou 'NULO')
        self._candidate_jids: List[str] = []  # Candidatos válidos (JIDs completos do Supervisor)

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Autoridade Eleitoral iniciado.")

        # Listener 1: Votos (protocol: PROTOCOL_VOTE)
        self.add_behaviour(
            self.VoteCollector(),
            Template(metadata={"protocol": PROTOCOL_VOTE})
        )

        # Listener 2: Sinal de contagem (protocol: PROTOCOL_VOTING, performative: inform, body: START_COUNT)
        self.add_behaviour(
            self.StartCountListener(),
            Template(metadata={"protocol": PROTOCOL_VOTING, "performative": "inform"})
        )

        # Listener 3: Anúncios de candidatos (protocol: PROTOCOL_INIT_SIM)
        self.add_behaviour(
            self.CandidateAnnounceListener(),
            Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        )
        

    class CandidateAnnounceListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return

            body = (msg.body or "")
            if "CANDIDATES_ANNOUNCED" in body:
                try:
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="):
                            raw = part.split("=", 1)[1].strip()
                            if raw:
                                self.agent._candidate_jids = [x.strip() for x in raw.split(",") if x.strip()]
                                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos registrados: {len(self.agent._candidate_jids)}")
                except Exception as e:
                    print(f"[AUTHORITY_ANNOUNCE_ERR] Erro ao processar anúncio: {e}")

    class VoteCollector(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1.0) 
            if not msg:
                return

            vote = (msg.body or "").strip()
            
            self.agent._votes.append(vote)

    class StartCountListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return

            body = (msg.body or "").strip().upper()
            if body == "START_COUNT":
                # Sinal para começar a contagem
                await self._count_and_publish()
                self.kill() 

        async def _count_and_publish(self):
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Recebido START_COUNT. AGUARDANDO VOTOS POR 5 SEGUNDOS...")
            
            # Tempo de espera para o processamento de votos (CRÍTICO)
            await asyncio.sleep(5.0) 
            
            # Contagem bruta
            counts = Counter(self.agent._votes)

            # Candidatos válidos (JIDs completos + "NULO")
            valid = set(self.agent._candidate_jids + ["NULO"])
            
            # Filtra votos para apenas candidatos válidos e NULO
            final_counts = {}
            for vote_jid, count in counts.items():
                if vote_jid in valid:
                    final_counts[vote_jid] = count

            # Adiciona zeros para candidatos válidos que não receberam votos
            for cand_jid in self.agent._candidate_jids:
                if cand_jid not in final_counts:
                    final_counts[cand_jid] = 0

            # Serializa resultado
            payload = json.dumps(final_counts)

            # Envia resultados ao Supervisor
            msg_sup = Message(to=self.agent.supervisor_jid)
            msg_sup.set_metadata("protocol", PROTOCOL_RESULTS)
            msg_sup.set_metadata("performative", "inform")
            msg_sup.body = payload
            await self.send(msg_sup)
            
            # Printa para debug
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] RESULTADOS FINAIS ENVIADOS: {final_counts} ({len(self.agent._votes)} votos totais recebidos).")