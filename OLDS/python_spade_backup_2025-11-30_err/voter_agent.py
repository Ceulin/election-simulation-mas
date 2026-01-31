# python_spade/voter_agent.py
import asyncio
import random
import json
from typing import List, Dict, Tuple

import spade
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from common import (
    get_sender_name,
    PARTIES,
    PROTOCOL_CAMPAIGN,
    PROTOCOL_VOTING,
    PROTOCOL_VOTE,
    PROTOCOL_INIT_SIM,
    PROTOCOL_REQUEST_ENGAGEMENT,
    PROTOCOL_RESPONSE_ENGAGEMENT,
    SERVER, 
    TOTAL_TICKS,
    # Constantes de Abstenção/Nulo
    N_CITIZENS,
    P_BASE_ABSTAIN,
    P_BASE_NULL,
    ENGAGEMENT_ABSTAIN_THRESHOLD,
)

# Tempo de espera para o receive.
RECEIVE_TIMEOUT = 1.0 
# Protocolo de influência (usado localmente)
PROTOCOL_INFLUENCE = "INFLUENCE"


class VoterAgent(spade.agent.Agent):
    def __init__(self, jid: str, password: str, supervisor_jid: str, authority_jid: str, party: str, *args, **kwargs):
        neighbours = kwargs.pop("neighbours", [])
        super().__init__(jid, password, *args, **kwargs)

        self.supervisor_jid = supervisor_jid
        self.authority_jid = authority_jid
        self.server = SERVER

        # Perfil político
        self.party = party
        base = PARTIES.get(party, {"ideologia": 0})
        self.ideology = float(base.get("ideologia", 0))
        self.engagement = random.random()
        self.confianca_midia = random.uniform(0.5, 0.9)

        # Memória de campanha: Dict[str, List[float]] para Memória Curta (2)
        self.memoria_campanha: Dict[str, List[float]] = {} 
        
        # Contador de mensagens de campanha (Fadiga)
        self.msg_count_campaign: int = 0

        self.is_candidate = False
        self.voto_final: str | None = None
        self.voted: bool = False

        # Rede social local
        self.neighbours: List[str] = neighbours

        # Estado interno global
        self.tick: int = 0
        self.candidates_known: List[str] = [] # JIDs completos dos candidatos
        
    async def setup(self):
        print(
            f"[{get_sender_name(str(self.jid)).upper()}] Iniciado: "
            f"{self.party} (Ideologia: {self.ideology:.2f})"
        )

        # 1. Behaviour para receber TICKs (CORRIGIDO: Template específico)
        tpl_tick = Template(metadata={"protocol": PROTOCOL_INIT_SIM, "stage": "TICK"})
        self.add_behaviour(self.TickReceiverAndBaseCycle(), tpl_tick)

        # 2. Behaviour para receber Campanhas da Mídia (PROTOCOL_CAMPAIGN)
        tpl_campaign = Template(metadata={"protocol": PROTOCOL_CAMPAIGN})
        self.add_behaviour(self.MediaReceiverBehaviour(), tpl_campaign)
        
        # 3. Behaviour para responder a Queries de Influência (PROTOCOL_INFLUENCE / query)
        tpl_influence_query = Template(metadata={"protocol": PROTOCOL_INFLUENCE, "performative": "query"})
        self.add_behaviour(self.InfluenceResponderBehaviour(), tpl_influence_query)
        
        # 4. Behaviour para Votação/Engagement/ANNOUNCE/etc (Captura o que sobrou)
        # 4a. Capta REQUEST_ENGAGEMENT (T10)
        tpl_engage = Template(metadata={"protocol": PROTOCOL_REQUEST_ENGAGEMENT, "performative": "query"})
        self.add_behaviour(self.RequestAnnounceAndVotingReceiver(), tpl_engage)
        
        # 4b. Capta REQUEST_VOTE (T51)
        tpl_vote_req = Template(metadata={"protocol": PROTOCOL_VOTING, "performative": "request"})
        self.add_behaviour(self.RequestAnnounceAndVotingReceiver(), tpl_vote_req)

        # 4c. Capta Respostas INFORM de Influência (INFLUENCE / inform)
        tpl_influence_inform = Template(metadata={"protocol": PROTOCOL_INFLUENCE, "performative": "inform"})
        self.add_behaviour(self.RequestAnnounceAndVotingReceiver(), tpl_influence_inform)

        # 4d. Capta ANNOUNCE (SIM_INIT sem stage='TICK')
        tpl_announce = Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        # Este template pega ANNOUNCE.
        self.add_behaviour(self.RequestAnnounceAndVotingReceiver(), tpl_announce)

    # =========================================================
    # Helpers (Decisão, Memória, Logs) [CORRIGIDOS CONTRA ATTRIBUTEERROR]
    # =========================================================
    
    def handle_init_sim(self, body: str):
        """Processa ANNOUNCE de candidatos (CORRIGIDO: Método do Agente)."""
        body = (body or "").strip()
        if "CANDIDATES_ANNOUNCED" in body:
            try:
                parts = body.split(";")
                cands = []
                for p in parts:
                    if p.startswith("CANDIDATES="):
                        raw = p.split("=", 1)[1].strip()
                        if raw:
                            cands = [x.strip() for x in raw.split(",") if x.strip()]
                self.candidates_known = cands 
                
                if str(self.jid) in cands:
                    self.is_candidate = True
                    print(f"[{get_sender_name(str(self.jid)).upper()}] *** PROMOVIDO A CANDIDATO ***")
            except Exception:
                pass


    async def handle_engagement_request(self, msg: Message, beh: CyclicBehaviour):
        """Responde ao REQUEST_ENGAGEMENT do Supervisor (T10) (CORRIGIDO: Método do Agente)."""
        data = {
            "engagement": self.engagement,
            "party": self.party,
            "ideology": self.ideology,
            "credibility": self.confianca_midia,
        }
        reply = Message(to=str(msg.sender))
        reply.set_metadata("protocol", PROTOCOL_RESPONSE_ENGAGEMENT)
        reply.set_metadata("performative", "inform")
        reply.body = json.dumps(data)
        await beh.send(reply)

    def apply_influence(self, msg: Message):
        """APLICAR INFLUÊNCIA SOCIAL: Aplica influência de vizinhos (CORRIGIDO: Método do Agente)."""
        try:
            payload = json.loads(msg.body or "{}")
            n_ideol = float(payload.get("ideology", 0))
            n_eng = float(payload.get("engagement", 0))
            
            influence_factor = (n_ideol * n_eng) * 0.1
            
            self.ideology = (self.ideology * 0.9) + influence_factor
            self.ideology = max(-2.0, min(2.0, self.ideology))
        except Exception:
            pass
    
    def debug_summary(self) -> str:
        party_name = PARTIES.get(self.party, {}).get("name", self.party)
        memoria_str = ", ".join([f"('{c}':{i[-2:]})" for c, i in self.memoria_campanha.items()])
        return (
            f"Party={party_name} ({self.party}), Ideology={self.ideology:.2f}, "
            f"Engagement={self.engagement:.2f}, Credibility={self.confianca_midia:.2f}, "
            f"Msg_Count={self.msg_count_campaign}, Memoria=[{memoria_str}]"
        )

    def update_campaign_memory(self, campaign_msg: Message):
        """
        Atualiza a memória de impacto de campanha (Memória Curta: 2).
        """
        performative = campaign_msg.metadata.get("performative", "").upper()
        
        impact = 0.0
        if performative == "NEWS":
            impact = random.uniform(0.05, 0.2) * self.confianca_midia
        elif performative == "FAKENEWS":
            impact = random.uniform(0.1, 0.3)
            if self.confianca_midia > 0.7:
                impact *= -0.5

        candidate_id_short = None
        try:
            # Body da mídia tem o formato: pitch:{cand_short};t={tick}
            candidate_id_short = campaign_msg.body.split(':')[1].split(';')[0]
        except:
            return 
        
        known_short_jids = [get_sender_name(j) for j in self.candidates_known]
        if not candidate_id_short or candidate_id_short not in known_short_jids:
            return

        # 3. ATUALIZAÇÃO DA MEMÓRIA CURTA
        if candidate_id_short not in self.memoria_campanha:
            self.memoria_campanha[candidate_id_short] = []

        self.memoria_campanha[candidate_id_short].append(impact)
        # Limita a memória aos 2 últimos impactos
        self.memoria_campanha[candidate_id_short] = self.memoria_campanha[candidate_id_short][-2:]
        
        # 4. LOG DE INSTRUMENTAÇÃO
        resumo_mem = {c: f"{[f'{i:.4f}' for i in l]}" for c, l in self.memoria_campanha.items()}
        print(
            f"[{get_sender_name(str(self.jid)).upper()}] CAMPANHA PROCESSADA: "
            f"cand={candidate_id_short}, perf={performative}, impacto={impact:.4f}, "
            f"memoria={resumo_mem}"
        )


    async def decide_and_vote(self, beh: CyclicBehaviour):
        """
        Lógica de decisão de voto e envio para Authority.
        """
        if self.voted: return
        me = str(self.jid)
        label = get_sender_name(me).upper()

        # 1. CÁLCULO DA FADIGA
        overload_threshold = 20
        overload_factor = max(0, self.msg_count_campaign - overload_threshold)
        fatigue_penalty = min(0.40, 0.02 * overload_factor)
        effective_engagement = max(0.0, self.engagement - fatigue_penalty)
        eng = effective_engagement 

        # 2. LÓGICA DE ABSTENÇÃO
        p_abstain = P_BASE_ABSTAIN
        if eng < ENGAGEMENT_ABSTAIN_THRESHOLD: p_abstain += 0.4 

        if random.random() < p_abstain:
            print(f"[{label}] ABSTENÇÃO: não enviou voto (Engagement={self.engagement:.2f}, Eng_Eff={eng:.2f}, P_Abstain={p_abstain:.2f}).")
            self.voted = True
            return

        # 3. CÁLCULO DE SCORES (usa effective_engagement)
        vote_scores: Dict[str, float] = {}
        PESO_IDEO = 0.5; PESO_CAMP = 0.5 

        candidate_short_jids = [get_sender_name(j) for j in self.candidates_known]
        for short_jid in candidate_short_jids:
             vote_scores[short_jid] = PESO_IDEO * random.uniform(0.1, 0.3) * effective_engagement

        for cand_jid_short, impactos in self.memoria_campanha.items():
            if cand_jid_short in vote_scores:
                avg_impact = sum(impactos) / len(impactos) if impactos else 0.0
                vote_scores[cand_jid_short] += PESO_CAMP * avg_impact

        # 4. DECISÃO INICIAL / NULO PROBABILÍSTICO
        if not vote_scores: chosen_short = "NULO"; max_score = 0.0
        else:
            chosen_short = max(vote_scores, key=vote_scores.get)
            max_score = vote_scores.get(chosen_short, 0.0)

        p_null_extra = 0.0
        if max_score < 0.05: p_null_extra = 0.25
        p_null = P_BASE_NULL + p_null_extra
        
        if random.random() < p_null: chosen_short = "NULO"

        # 6. Regra: candidato vota em si mesmo (Prioridade máxima)
        me_short = get_sender_name(me)
        if self.is_candidate:
            if random.random() < 0.99: chosen_short = me_short
            else: chosen_short = "NULO" 

        
        # 7. LOGS FINAIS
        print(f"[{label}] ESTADO_NO_MOMENTO_DO_VOTO: {self.debug_summary()}")
        
        # 8. Envio
        self.voto_final = chosen_short
        if chosen_short != "NULO": self.voto_final = f"{chosen_short}@{self.server}"

        print(f"[{label}] VOTO FINAL DECIDIDO: {self.voto_final.upper()}")

        msg = Message(to=self.authority_jid)
        msg.set_metadata("protocol", PROTOCOL_VOTE)
        msg.set_metadata("performative", "inform")
        msg.body = self.voto_final 
        await beh.send(msg)
        
        self.voted = True 


    # =========================================================
    # BEHAVIOURS DE RECEPÇÃO DEDICADOS
    # =========================================================

    class MediaReceiverBehaviour(CyclicBehaviour):
        """Recebe Campanhas da Mídia (PROTOCOL_CAMPAIGN) e atualiza estado."""
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg: return
            
            # Garante que a mensagem seja da fase de campanha (T > 10)
            if self.agent.tick > 10 and not self.agent.is_candidate:
                # Contador de mensagens (Fadiga)
                self.agent.msg_count_campaign += 1
                self.agent.update_campaign_memory(msg)
                
                # Log de recepção de Campanha
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] MSG_MIDIA_RECEBIDA: tick={self.agent.tick}, action={msg.metadata.get('performative')}, Msg_Count={self.agent.msg_count_campaign}.")
            
    
    class InfluenceResponderBehaviour(CyclicBehaviour):
        """Responde a queries de influência de vizinhos (PROTOCOL_INFLUENCE / query)."""
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg: return
            
            # Rotear o corpo da query
            if (msg.body or "").upper() == "QUERY_PROFILE":
                # Resposta de Perfil
                data = {
                    "ideology": self.agent.ideology,
                    "engagement": self.agent.engagement,
                }
                reply = Message(to=str(msg.sender))
                reply.set_metadata("protocol", PROTOCOL_INFLUENCE)
                reply.set_metadata("performative", "inform")
                reply.body = json.dumps(data)
                await self.send(reply)
                
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] DEBUG_INFLUENCE_REPLY_ENVIADA para {get_sender_name(str(msg.sender))}")

    class RequestAnnounceAndVotingReceiver(CyclicBehaviour):
        """
        Captura mensagens genéricas de controle (VOTING/ENGAGEMENT/ANNOUNCE/INFLUENCE inform).
        """
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg:
                return

            # CORREÇÃO CRÍTICA DE SINTAXE: Removendo o segundo argumento default de get_metadata()
            proto = msg.get_metadata("protocol")
            
            # --- ROTEAMENTO DE MENSAGENS ---
            
            # ANNOUNCE (PROTOCOL_INIT_SIM, mas sem stage='TICK')
            if proto == PROTOCOL_INIT_SIM and not msg.get_metadata("stage") == "TICK":
                self.agent.handle_init_sim(msg.body or "")

            elif proto == PROTOCOL_REQUEST_ENGAGEMENT:
                await self.agent.handle_engagement_request(msg, self) 
            
            elif proto == PROTOCOL_INFLUENCE:
                # Captura respostas INFORM de influência
                if msg.get_metadata("performative") == "inform":
                    self.agent.apply_influence(msg)
            
            elif proto == PROTOCOL_VOTING:
                # Comando REQUEST_VOTE (T51)
                if (msg.get_metadata("performative") == "request" and 
                    (msg.body or "").strip().upper() == "REQUEST_VOTE" and 
                    not self.agent.voted):
                    
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] REQUEST_VOTE recebido. Iniciando votação.")
                    await self.agent.decide_and_vote(self)


    class TickReceiverAndBaseCycle(CyclicBehaviour):
        """
        Recebe e processa o TICK do Supervisor (PROTOCOL_INIT_SIM, stage=TICK).
        Responsável por interações sociais (T0-T10) e atualização de TICK.
        """
        async def run(self):
            # 1. Processa mensagens TICK (Template específico no setup)
            msg = await self.receive(timeout=0.2) 
            if msg:
                # O payload do TICK é um JSON {"tick": X}
                try:
                    data = json.loads(msg.body)
                    new_tick = data.get("tick")
                    if new_tick is not None:
                        self.agent.tick = new_tick
                except Exception:
                    pass

            # 2. Failsafe T51 (Votação)
            if self.agent.tick >= TOTAL_TICKS and not self.agent.voted:
                 await self.agent.decide_and_vote(self) 
                 return

            # 3. Interação Social (T0-T10) - Onde o envio da QUERY ocorre
            if self.agent.tick <= 10 and self.agent.neighbours and random.random() < 0.2:
                neighbour = random.choice(self.agent.neighbours)
                q = Message(to=neighbour)
                q.set_metadata("protocol", PROTOCOL_INFLUENCE) 
                q.set_metadata("performative", "query") 
                q.body = "QUERY_PROFILE"
                await self.send(q)

            await asyncio.sleep(RECEIVE_TIMEOUT)