# python_spade/supervisor_agent.py
import asyncio
import json
import random
from typing import List, Tuple, Dict, Optional

import spade
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template
from dataclasses import dataclass # Importado para CandidateAgent

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
    PROTOCOL_CAMPAIGN, 
    generate_jid,
    SERVER, # Novo
    CANDIDATE_INITIAL_BUDGET, # Novo
)

# Importa as classes do CandidateAgent (Assumindo que o arquivo será criado)
try:
    from candidate_agent import CandidateAgent, CandidateConfig
except ImportError:
    print("[SUPERVISOR] AVISO: candidate_agent.py não encontrado. Usando classes mock.")
    # Mock para evitar crash
    @dataclass
    class CandidateConfig:
        candidate_voter_id: str; party: str; initial_budget: float = 1000.0; fake_news_propensity: float = 0.2; media_jid: str = "media_1@localhost"
    class CandidateAgent(object):
        def __init__(self, jid, password, config): self.jid = jid; self.config = config
        async def start(self): pass
        async def stop(self): pass
        def apply_cost(self, cost: float): pass
        

class SupervisorAgent(spade.agent.Agent):
    """
    Orquestrador AUTO-REGULADO.
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
        self.candidate_jids: List[str]       = [] # JIDs dos Voters que são candidatos
        
        # NOVO: Agentes Candidatos
        self.candidate_agents: Dict[str, CandidateAgent] = {}     # voter_id -> CandidateAgent instance

        # Coleta T10
        self._engagement_replies: List[Tuple[str, float]] = []


    # NOVO: Inicia e promove os CandidateAgents
    async def promote_candidates_and_start_agents(self, promoted_list, voter_parties):
        self.promoted_candidates = promoted_list
        self.candidate_agents = {}
        
        for voter_jid in promoted_list:
            voter_id = get_sender_name(voter_jid)
            party = voter_parties.get(voter_jid, "SPD")
            fake_propensity = 0.2

            # JID do Agente Candidato (cand_voter_X@localhost)
            cand_jid = generate_jid(f"cand_{voter_id}", "")
            cand_pwd = "candidate_password"

            config = CandidateConfig(
                candidate_voter_id=voter_jid, # JID COMPLETO do Voter
                party=party,
                initial_budget=CANDIDATE_INITIAL_BUDGET,
                fake_news_propensity=fake_propensity,
                media_jid=self.media_jid,
            )

            cand_agent = CandidateAgent(cand_jid, cand_pwd, config)
            await cand_agent.start()
            self.candidate_agents[voter_jid] = cand_agent

        print(f"[SUPERVISOR] CandidateAgents iniciados para JIDs Voters: {list(self.candidate_agents.keys())}")


    # ---------------- Behaviours ----------------
    class AutoStart(OneShotBehaviour):
        # ... (código inalterado)
        async def run(self):
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Aguardando {self.agent.autostart_delay}s para iniciar o ciclo de TICKs...")
            await asyncio.sleep(self.agent.autostart_delay)
            self.agent._started = True
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] AutoStart concluído. Iniciando T0.")


    class TimeController(CyclicBehaviour):
        # ... (código inalterado)
        async def run(self):
            if not self.agent._started:
                await asyncio.sleep(1) 
                return

            if self.agent._tick > TOTAL_TICKS:
                self.kill()
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] *** FASE DE TICKING CONCLUÍDA ***")
                return
            
            t = self.agent._tick
            phase = self._phase(t)
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] TICK {t} de {TOTAL_TICKS}. Fase: {phase}.")
            await self.agent._broadcast_tick(t, self, phase) # Passa 'phase'
            
            # ... (código T10, REPORT_TICKS, T51)
            if t == 10:
                await self.agent._t10_collect_and_promote(self)

            if t in REPORT_TICKS:
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
            # ... (código inalterado)
            if self.agent.media_jid:
                m = Message(to=self.agent.media_jid)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", "inform")
                m.set_metadata("stage", "MEDIA_REPORT")
                m.body = f"REQUEST_REPORT_T{t}"
                await self.send(m)


    class ResultsListener(CyclicBehaviour):
        # ... (código inalterado)
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
        # ... (código inalterado)
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

    # --- Funções do Agente (Brodcast/T10/T51) ---
    async def _broadcast_tick(self, t: int, beh: CyclicBehaviour, phase: str):
        """Envia a mensagem de TICK para todos os agentes relevantes."""
        # Novo payload para CandidateAgent
        body_payload = {"tick": t, "phase": phase}
        body = json.dumps(body_payload)
        md = {"protocol": "SUPERVISOR_TICK", "performative": "inform", "stage": "TICK"} # Novo protocolo para TICK
        
        # 1. Envia para Voters, Media, Authority
        targets = list(self.voter_jids)
        if self.media_jid:
            targets.append(self.media_jid)
        if self.authority_jid:
            targets.append(self.authority_jid)

        for to in targets:
            m = Message(to=to)
            m.body = json.dumps({"tick": t}) # Mantenha o body simples para Voters/Media/Authority
            m.metadata = {"protocol": "SIM_INIT", "performative": "inform", "stage": "TICK"} # Mantém protocolo antigo
            await beh.send(m)

        # 2. Envia para CandidateAgents (NOVO)
        for cand_agent in self.candidate_agents.values():
            m = Message(to=str(cand_agent.jid))
            m.body = json.dumps(body_payload)
            m.metadata = md # Usa o novo protocolo e body rico
            await beh.send(m)


    async def _t10_collect_and_promote(self, beh: CyclicBehaviour):
        """Passo T10: Coleta engagement, promove e INICIA CandidateAgents."""
        
        print(f"[{get_sender_name(str(self.jid)).upper()}] T10: Coletando Engagement e Promovendo Candidatos...")
        
        # ... (Lógica de REQUEST_ENGAGEMENT e espera) ...
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
        
        # NOVO: Inicia os CandidateAgents
        # self.voter_party_map tem as JIDs completas dos voters e seus partidos
        await self.promote_candidates_and_start_agents(promoted, self.voter_party_map) 


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
        # ... (código inalterado)
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