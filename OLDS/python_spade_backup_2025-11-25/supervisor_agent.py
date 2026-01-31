# python_spade/supervisor_agent.py
import asyncio
import json
import random
from typing import List, Tuple, Dict, Optional

import spade
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template

from common import (
    get_sender_name,
    TOTAL_TICKS,
    TICK_DURATION,
    PROTOCOL_INIT_SIM,
    PROTOCOL_REQUEST_ENGAGEMENT,
    PROTOCOL_RESPONSE_ENGAGEMENT,
    PROTOCOL_VOTING,
    PROTOCOL_RESULTS,
)

class SupervisorAgent(spade.agent.Agent):
    """
    Orquestrador AUTO-REGULADO:
      - Emite TICKs (T0..T51) automaticamente.
      - T10: solicita engagement, seleciona candidatos e anuncia.
      - T51: solicita votos + START_COUNT à Authority.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # CONFIG
        self.tick_duration: float   = TICK_DURATION
        self.n_candidates: int      = 3
        self.autostart_delay: float = 3.0 # Delay menor, pois o run_sim espera
        
        # ESTADO
        self._tick: int     = 0
        self._started: bool = False

        # CONEXÕES (Injetado pelo run_spade_sim.py)
        self.voter_jids: List[str] = []
        self.media_jid: Optional[str] = None
        self.authority_jid: Optional[str] = None

        # Dados auxiliares
        self.voter_party_map: Dict[str, str] = {}    
        self.candidate_jids: List[str]       = []

        # Coleta T10
        self._engagement_replies: List[Tuple[str, float]] = []

    # ---------------- Behaviours ----------------
    class AutoStart(OneShotBehaviour):
        async def run(self):
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Aguardando {self.agent.autostart_delay}s para iniciar o ciclo de TICKs...")
            await asyncio.sleep(self.agent.autostart_delay)
            self.agent._started = True
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] AutoStart concluído. Iniciando T0.")

    class TimeController(CyclicBehaviour):
        async def run(self):
            if not self.agent._started:
                await asyncio.sleep(1) 
                return

            # Condição de parada (Ciclo encerrado)
            if self.agent._tick > TOTAL_TICKS:
                self.kill()
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] *** FASE DE TICKING CONCLUÍDA ***")
                return
            
            # --- Executa o Tick atual ---
            t = self.agent._tick
            phase = self._phase(t)
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] TICK {t} de {TOTAL_TICKS}. Fase: {phase}.")
            await self.agent._broadcast_tick(t, self)

            if t == 10:
                await self.agent._t10_collect_and_promote(self)

            if t == 51:
                # O T51 envia o REQUEST_VOTE/START_COUNT e encerra
                await self.agent._t51_request_votes_and_count(self)
                
            # Prepara para o próximo tick
            self.agent._tick += 1
            await asyncio.sleep(self.agent.tick_duration)

        @staticmethod
        def _phase(t: int) -> str:
            if t <= 10: return "Pré-Campanha"
            if t <= 50: return "Campanha Eleitoral"
            return "Dia da Eleição"

    class ResultsListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg: return
            md = msg.metadata or {}
            
            if md.get("protocol") == PROTOCOL_RESULTS:
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] 🏆 RESULTADOS OFICIAIS RECEBIDOS: {msg.body}")
                self.kill() # Mata o listener após receber

    class EngagementSink(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg: return
            
            if msg.metadata.get("protocol") != PROTOCOL_RESPONSE_ENGAGEMENT:
                return

            try:
                payload = json.loads(msg.body or "{}")
                eng = float(payload.get("engagement", 0.0))
            except Exception:
                eng = 0.0
            self.agent._engagement_replies.append((str(msg.sender), eng))

    # --- Funções do Agente, chamadas pelo Behaviour ---
    async def _broadcast_tick(self, t: int, beh: CyclicBehaviour):
        """Envia a mensagem de TICK para todos os agentes relevantes."""
        body = f"TICK_{t}"
        md = {"protocol": PROTOCOL_INIT_SIM, "performative": "inform", "stage": "TICK"} 

        targets = list(self.voter_jids)
        if self.media_jid:
            targets.append(self.media_jid)
        if self.authority_jid:
            targets.append(self.authority_jid)

        for to in targets:
            m = Message(to=to)
            m.body = body
            m.metadata = dict(md)
            await beh.send(m)

    async def _t10_collect_and_promote(self, beh: CyclicBehaviour):
        """Passo T10: Coleta engagement e anuncia candidatos."""
        
        print(f"[{get_sender_name(str(self.jid)).upper()}] T10: Coletando Engagement e Promovendo Candidatos...")
        
        # 1) REQUEST_ENGAGEMENT
        self._engagement_replies.clear()
        base = Message()
        base.set_metadata("protocol", PROTOCOL_REQUEST_ENGAGEMENT)
        base.set_metadata("performative", "query")
        base.body = "SEND_ENGAGEMENT"

        for v in self.voter_jids: 
            m = Message(to=v)
            m.body = base.body
            m.metadata = dict(base.metadata)
            await beh.send(m)

        # 2) Aguarda respostas (até 8 segundos)
        expected = len(self.voter_jids)
        deadline = asyncio.get_event_loop().time() + 8.0
        while asyncio.get_event_loop().time() < deadline and len(self._engagement_replies) < expected:
            await asyncio.sleep(0.5)

        print(f"[{get_sender_name(str(self.jid)).upper()}] T10: recebidas {len(self._engagement_replies)}/{expected} respostas de engagement.")

        # 3) Seleciona Top-N
        ordered = sorted(self._engagement_replies, key=lambda t: t[1], reverse=True)
        promoted = [jid for jid, _ in ordered[:self.n_candidates]]
        
        if len(promoted) < self.n_candidates:
            universe = [v for v in self.voter_jids if v not in promoted]
            random.shuffle(universe)
            promoted += universe[:(self.n_candidates - len(promoted))]

        self.candidate_jids = promoted 

        # 4) Anúncio (com partidos)
        cand_parties = [self.voter_party_map.get(j, "SPD") for j in promoted]
        body = "CANDIDATES_ANNOUNCED;" \
               f"CANDIDATES={','.join(promoted)};" \
               f"PARTIES={','.join(cand_parties)}"

        md = {"protocol": PROTOCOL_INIT_SIM, "performative": "inform", "stage": "ANNOUNCE"}
        
        targets = list(self.voter_jids)
        if self.media_jid:
            targets.append(self.media_jid)
        if self.authority_jid:
            targets.append(self.authority_jid)

        for to in targets:
            m = Message(to=to)
            m.body = body
            m.metadata = dict(md)
            await beh.send(m)

        print(f"[{get_sender_name(str(self.jid)).upper()}] CANDIDATOS PROMOVIDOS (JIDs): {', '.join(promoted)}")
        print(f"[{get_sender_name(str(self.jid)).upper()}] Transição para FASE CAMPANHA (T11).")

    async def _t51_request_votes_and_count(self, beh: CyclicBehaviour):
        """Passo T51: Solicita votos e dá o comando de contagem."""
        print(f"[{get_sender_name(str(self.jid)).upper()}] T51 - Dia da Eleição. Solicitando Votos e Contagem.")

        # 1) Voters -> vote request
        base = Message()
        base.set_metadata("protocol", PROTOCOL_VOTING)
        base.set_metadata("performative", "request")
        base.body = "REQUEST_VOTE"
        for v in self.voter_jids:
            m = Message(to=v)
            m.body = base.body
            m.metadata = dict(base.metadata)
            await beh.send(m)

        # 2) Authority -> start count
        if self.authority_jid:
            inf = Message(to=self.authority_jid)
            inf.set_metadata("protocol", PROTOCOL_VOTING)
            inf.set_metadata("performative", "inform")
            inf.body = "START_COUNT"
            await beh.send(inf)


    # ---------------- setup ----------------

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Supervisor iniciado. Controle Temporal Cíclico.")
        
        self.add_behaviour(self.AutoStart())
        
        self.add_behaviour(self.TimeController())
        
        # Sink de respostas T10
        template_engagement = Template(metadata={"protocol": PROTOCOL_RESPONSE_ENGAGEMENT})
        self.add_behaviour(self.EngagementSink(), template_engagement)
        
        # Listener de resultados finais
        self.add_behaviour(self.ResultsListener(),  Template(metadata={"protocol": PROTOCOL_RESULTS}))