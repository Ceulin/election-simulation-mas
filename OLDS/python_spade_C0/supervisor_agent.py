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
    PROTOCOL_ELIMINATION, 
    REPORT_TICKS, 
    MEDIA_PREFIX, 
    N_SEATS, 
    PROTOCOL_CAMPAIGN, # Necessário para _request_media_report
)

class SupervisorAgent(spade.agent.Agent):
    """
    Orquestrador AUTO-REGULADO:
      - Emite TICKs (T0..T51) automaticamente.
      - T10: solicita engagement, seleciona candidatos e anuncia.
      - T51: solicita votos + START_COUNT à Authority.
      - Emite pedidos de relatório em REPORT_TICKS.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # CONFIG
        self.tick_duration: float   = TICK_DURATION
        self.n_candidates: int      = 3
        self.autostart_delay: float = 3.0
        
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

            if t in REPORT_TICKS: # Solicita Relatórios Jornalísticos (TAREFA 4)
                await self._request_media_report(t)

            if t == 51:
                await self.agent._t51_request_votes_and_count(self)
                
            self.agent._tick += 1
            await asyncio.sleep(self.agent.tick_duration)

        @staticmethod
        def _phase(t: int) -> str:
            if t <= 10: return "Pré-Campanha"
            if t <= 50: return "Campanha Eleitoral"
            return "Dia da Eleição"
        
        async def _request_media_report(self, t: int):
            """Envia solicitação de relatório jornalístico para a Mídia."""
            if self.agent.media_jid:
                m = Message(to=self.agent.media_jid)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", "inform")
                m.set_metadata("stage", "MEDIA_REPORT")
                m.body = f"REQUEST_REPORT_T{t}"
                await self.send(m)


    class ResultsListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg: return
            md = msg.metadata or {}
            
            if md.get("protocol") == PROTOCOL_RESULTS:
                
                try:
                    data = json.loads(msg.body or "{}")
                    
                    # Impressão de resultados ricos
                    print(f"\n[{get_sender_name(str(self.agent.jid)).upper()}] 🏆 RESULTADOS OFICIAIS RECEBIDOS")
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}]   -> CIDADÃOS: {data.get('total_citizens', '?')}, ABSTENÇÕES: {data.get('abstentions', '?')}, NULOS: {data.get('null_votes', '?')}")
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}]   -> VOTOS POR PARTIDO: {data.get('by_party', {})}")
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}]   -> CADEIRAS (D'HONDT, N={N_SEATS}): {data.get('seats_dhondt', {})}")
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}]   -> VOTOS POR CANDIDATO: {data.get('by_candidate', {})}")
                
                except Exception as e:
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] ERRO ao processar resultados: {e}. Payload bruto: {msg.body}")
                
                self.kill()


    class EngagementSink(CyclicBehaviour):
        # Lógica inalterada
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

    # --- Funções do Agente, chamadas pelo Behaviour (Brodcast/T10/T51) ---
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
               f"CANDIDATE_PARTIES={','.join(cand_parties)};" \
               f"MEDIA_JID={self.media_jid}" # Envia o JID da Mídia para a Authority

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
        
        template_engagement = Template(metadata={"protocol": PROTOCOL_RESPONSE_ENGAGEMENT})
        self.add_behaviour(self.EngagementSink(), template_engagement)
        
        self.add_behaviour(self.ResultsListener(),  Template(metadata={"protocol": PROTOCOL_RESULTS}))