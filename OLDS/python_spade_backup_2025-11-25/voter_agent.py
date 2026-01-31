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
    SERVER, # Importar para montar o JID final
    TOTAL_TICKS
)

# Tempo de espera para o receive.
RECEIVE_TIMEOUT = 1.0 


class VoterAgent(spade.agent.Agent):
    def __init__(self, jid: str, password: str, supervisor_jid: str, authority_jid: str, party: str, *args, **kwargs):
        neighbours = kwargs.pop("neighbours", [])
        super().__init__(jid, password, *args, **kwargs)

        self.supervisor_jid = supervisor_jid
        self.authority_jid = authority_jid
        self.server = SERVER

        # Perfil político
        self.party = party
        base = PARTIES.get(party, {"ideology": 0})
        self.ideology = float(base.get("ideology", 0)) # -2..2
        self.engagement = random.random()
        self.confianca_midia = random.uniform(0.5, 0.9)

        # Memória de campanha [(candidate_jid_short, impacto)]
        self.memoria_campanha: List[Tuple[str, float]] = []

        self.is_candidate = False
        self.voto_final: str | None = None
        self.voted: bool = False # Para garantir que vota apenas uma vez

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

        # CyclicBehaviour ÚNICO para processar todas as mensagens (Sem FSM)
        self.add_behaviour(self.VoterCycle(), Template())

    # =========================================================
    # Helpers internos
    # =========================================================

    def handle_init_sim(self, body: str):
        """Processa mensagens PROTOCOL_INIT_SIM (ticks e anúncio de candidatos)."""
        if body.startswith("TICK_"):
            try:
                new_tick = int(body.split("_", 1)[1])
                self.tick = new_tick
            except Exception:
                pass

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
    
    async def handle_influence_query(self, msg: Message, beh: CyclicBehaviour):
        """Responde a queries de vizinhos com ideologia e engajamento."""
        if (msg.body or "").upper() == "QUERY_PROFILE":
            data = {
                "ideology": self.ideology,
                "engagement": self.engagement,
            }
            reply = Message(to=str(msg.sender))
            reply.set_metadata("protocol", "INFLUENCE")
            reply.set_metadata("performative", "inform")
            reply.body = json.dumps(data)
            await beh.send(reply)

    def apply_influence(self, msg: Message):
        """Aplica influência social de vizinhos."""
        try:
            payload = json.loads(msg.body or "{}")
            n_ideol = float(payload.get("ideology", 0))
            n_eng = float(payload.get("engagement", 0))
            
            # Cálculo de influência social
            influence_factor = (n_ideol * n_eng) * 0.1
            
            # Ajuste de ideologia: 90% da minha + 10% da influência
            self.ideology = (self.ideology * 0.9) + influence_factor
            self.ideology = max(-2.0, min(2.0, self.ideology))
        except Exception:
            pass


    async def handle_engagement_request(self, msg: Message, beh: CyclicBehaviour):
        """Responde ao REQUEST_ENGAGEMENT do Supervisor (T10)."""
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

    def update_campaign_memory(self, campaign_msg: Message):
        """Atualiza a memória de impacto de campanha."""
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
            candidate_id_short = campaign_msg.body.split(':')[1].split(';')[0]
        except:
            return 
        
        known_short_jids = [get_sender_name(j) for j in self.candidates_known]
        if not candidate_id_short or candidate_id_short not in known_short_jids:
            return

        updated = False
        new_mem = []
        for jid, current in self.memoria_campanha:
            if jid == candidate_id_short:
                new_mem.append((jid, current + impact))
                updated = True
            else:
                new_mem.append((jid, current * 0.95))

        if not updated:
            new_mem.append((candidate_id_short, impact))

        self.memoria_campanha = new_mem[-5:]
        
    async def decide_and_vote(self, beh: CyclicBehaviour):
        """Lógica de decisão de voto e envio para Authority."""
        if self.voted:
            return # Já votou

        me = str(self.jid)
        label = get_sender_name(me).upper()

        # Lógica de decisão de voto
        vote_scores: Dict[str, float] = {}
        # NOVO: Peso da Ideologia introduzido para garantir um voto
        PESO_IDEO = 0.5 
        PESO_CAMP = 0.5 

        # 1. Pontuação Base (Ideologia)
        candidate_short_jids = [get_sender_name(j) for j in self.candidates_known]
        for short_jid in candidate_short_jids:
             # Voto ideológico simples: alinhamento com a ideologia base do eleitor
             cand_jid_full = f"{short_jid}@{self.server}"
             
             # NOTA: O alinhamento ideológico requer saber a ideologia do candidato, 
             # que não está mapeada no VoterAgent. Simplificamos para um voto não-nulo.
             # Para simplificar na reconstrução, damos uma pontuação base positiva para todos.
             vote_scores[short_jid] = PESO_IDEO * random.uniform(0.1, 0.3) 

        # 2. Aplica o impacto da memória de campanha
        for cand_jid_short, impact in self.memoria_campanha:
            if cand_jid_short in vote_scores:
                vote_scores[cand_jid_short] += PESO_CAMP * impact

        # 3. Decisão
        if not vote_scores:
            chosen_short = "NULO"
        else:
            chosen_short = max(vote_scores, key=vote_scores.get)
        
        # 4. Regra de voto nulo (somente se o melhor score for realmente ruim)
        max_score = vote_scores.get(chosen_short, -float('inf'))
        # Se o score mais alto for negativo OU próximo de zero, há chance de NULO
        if max_score <= 0.05 and random.random() < 0.4: 
             chosen_short = "NULO" 

        # 5. Regra: candidato vota em si mesmo (Prioridade máxima)
        me_short = get_sender_name(me)
        if self.is_candidate:
            if random.random() < 0.99:
                chosen_short = me_short
            else:
                chosen_short = "NULO" # 1% de chance de nulo se for candidato

        
        # 6. Envio
        self.voto_final = chosen_short
        if chosen_short != "NULO":
            self.voto_final = f"{chosen_short}@{self.server}"


        print(f"[{label}] VOTO FINAL DECIDIDO: {chosen_short.upper()}")

        # Envia voto à Authority
        msg = Message(to=self.authority_jid)
        msg.set_metadata("protocol", PROTOCOL_VOTE)
        msg.set_metadata("performative", "inform")
        msg.body = self.voto_final 
        await beh.send(msg)
        
        self.voted = True # Marca como votado


    # =========================================================
    # Behaviour: Cyclic
    # =========================================================

    class VoterCycle(CyclicBehaviour):
        async def run(self):
            # 1. Checa se deve votar (Failsafe T51)
            if self.agent.tick >= TOTAL_TICKS and not self.agent.voted:
                 # Vota se T51 for atingido e ainda não votou
                 await self.agent.decide_and_vote(self) 
                 await asyncio.sleep(RECEIVE_TIMEOUT)
                 return

            # 2. Processa mensagens
            msg = await self.receive(timeout=RECEIVE_TIMEOUT) 
            if not msg:
                # 3. Interação Social (T0-T10)
                if self.agent.tick <= 10 and self.agent.neighbours and random.random() < 0.2:
                    neighbour = random.choice(self.agent.neighbours)
                    q = Message(to=neighbour)
                    q.set_metadata("protocol", "INFLUENCE")
                    q.set_metadata("performative", "query")
                    q.body = "QUERY_PROFILE"
                    await self.send(q)
                return

            proto = msg.metadata.get("protocol", "")
            
            if proto == PROTOCOL_INIT_SIM:
                self.agent.handle_init_sim(msg.body or "")

            elif proto == PROTOCOL_REQUEST_ENGAGEMENT:
                await self.agent.handle_engagement_request(msg, self)
            
            elif proto == "INFLUENCE":
                if msg.metadata.get("performative") == "inform":
                    self.agent.apply_influence(msg)
            
            elif proto == PROTOCOL_CAMPAIGN:
                if not self.agent.is_candidate and self.agent.tick > 10: 
                    self.agent.update_campaign_memory(msg)
            
            elif proto == PROTOCOL_VOTING:
                # Comando REQUEST_VOTE (T51)
                if (msg.metadata.get("performative") == "request" and 
                    (msg.body or "").strip().upper() == "REQUEST_VOTE" and 
                    not self.agent.voted):
                    
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] REQUEST_VOTE recebido. Iniciando votação.")
                    await self.agent.decide_and_vote(self)