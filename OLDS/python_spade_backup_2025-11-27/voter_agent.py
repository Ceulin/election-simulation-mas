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
        base = PARTIES.get(party, {"ideology": 0})
        self.ideology = float(base.get("ideology", 0))
        self.engagement = random.random()
        self.confianca_midia = random.uniform(0.5, 0.9)

        # Memória de campanha: Dict[str, List[float]] para Memória Curta
        # Chave: cand_jid_short (ex: voter_8), Valor: lista de impactos
        self.memoria_campanha: Dict[str, List[float]] = {} 
        
        # NOVO: Contador de mensagens de campanha (Fadiga)
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

        # CyclicBehaviour ÚNICO para processar todas as mensagens (Sem FSM)
        self.add_behaviour(self.VoterCycle(), Template())

    # =========================================================
    # INSTRUMENTAÇÃO DE DEBUG
    # =========================================================
    def debug_summary(self) -> str:
        """
        Retorna um resumo textual do estado interno relevante do eleitor
        no momento da decisão de voto.
        """
        party_name = PARTIES.get(self.party, {}).get("name", self.party)
        
        # Formata memória curta
        memoria_str = ", ".join([f"('{c}':{i[-2:]})" for c, i in self.memoria_campanha.items()])

        return (
            f"Party={party_name} ({self.party}), Ideology={self.ideology:.2f}, "
            f"Engagement={self.engagement:.2f}, Credibility={self.confianca_midia:.2f}, "
            f"Msg_Count={self.msg_count_campaign}, Memoria=[{memoria_str}]"
        )


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
            reply.set_metadata("protocol", PROTOCOL_INFLUENCE) # Usando a constante local
            reply.set_metadata("performative", "inform")
            reply.body = json.dumps(data)
            await beh.send(reply)

    def apply_influence(self, msg: Message):
        """Aplica influência social de vizinhos."""
        try:
            payload = json.loads(msg.body or "{}")
            n_ideol = float(payload.get("ideology", 0))
            n_eng = float(payload.get("engagement", 0))
            
            influence_factor = (n_ideol * n_eng) * 0.1
            
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
        """
        Atualiza a memória de impacto de campanha.
        TAREFA 1: Implementa Memória Curta (2 últimas interações por candidato).
        """
        performative = campaign_msg.metadata.get("performative", "").upper()
        
        # 1. CÁLCULO DE IMPACTO
        impact = 0.0
        if performative == "NEWS":
            impact = random.uniform(0.05, 0.2) * self.confianca_midia
        elif performative == "FAKENEWS":
            impact = random.uniform(0.1, 0.3)
            if self.confianca_midia > 0.7:
                impact *= -0.5

        # 2. EXTRAÇÃO DO CANDIDATO
        candidate_id_short = None
        try:
            candidate_id_short = campaign_msg.body.split(':')[1].split(';')[0]
        except:
            return 
        
        known_short_jids = [get_sender_name(j) for j in self.candidates_known]
        if not candidate_id_short or candidate_id_short not in known_short_jids:
            return

        # 3. ATUALIZAÇÃO DA MEMÓRIA CURTA (TAREFA 1)
        if candidate_id_short not in self.memoria_campanha:
            self.memoria_campanha[candidate_id_short] = []

        self.memoria_campanha[candidate_id_short].append(impact)
        # Limita a memória aos 2 últimos impactos
        self.memoria_campanha[candidate_id_short] = self.memoria_campanha[candidate_id_short][-2:]
        
        # 4. LOG DE INSTRUMENTAÇÃO
        resumo_mem = {c: f"{[f'{i:.4f}' for i in l]}" for c, l in self.memoria_campanha.items()}
        print(
            f"[{get_sender_name(str(self.jid)).upper()}] CAMPANHA RECEBIDA: "
            f"cand={candidate_id_short}, perf={performative}, impacto={impact:.4f}, "
            f"memoria={resumo_mem}"
        )


    async def decide_and_vote(self, beh: CyclicBehaviour):
        """
        Lógica de decisão de voto e envio para Authority.
        TAREFA 2: Implementa Fadiga Política.
        """
        if self.voted:
            return

        me = str(self.jid)
        label = get_sender_name(me).upper()

        # 1. CÁLCULO DA FADIGA (TAREFA 2)
        overload_threshold = 20
        overload_factor = max(0, self.msg_count_campaign - overload_threshold)
        fatigue_penalty = min(0.40, 0.02 * overload_factor)
        effective_engagement = max(0.0, self.engagement - fatigue_penalty)

        # 2. CÁLCULO DE SCORES
        vote_scores: Dict[str, float] = {}
        PESO_IDEO = 0.5 
        PESO_CAMP = 0.5 

        candidate_short_jids = [get_sender_name(j) for j in self.candidates_known]
        for short_jid in candidate_short_jids:
             # Pontuação base (influenciada pelo engagement efetivo)
             vote_scores[short_jid] = PESO_IDEO * random.uniform(0.1, 0.3) * effective_engagement

        # Aplica o impacto da memória de campanha
        for cand_jid_short, impactos in self.memoria_campanha.items():
            if cand_jid_short in vote_scores:
                # Usa a média dos 2 últimos impactos para o score
                avg_impact = sum(impactos) / len(impactos) if impactos else 0.0
                vote_scores[cand_jid_short] += PESO_CAMP * avg_impact

        # 3. LOG DE INSTRUMENTAÇÃO DE SCORES
        scores_str = {c: f"{s:.4f}" for c, s in vote_scores.items()}
        memoria_str = {c: f"{[f'{i:.4f}' for i in l]}" for c, l in self.memoria_campanha.items()}
        print(
            f"[{label}] DECISAO_DE_VOTO: "
            f"scores={scores_str}, memoria={memoria_str}, "
            f"Fatigue_Pen={fatigue_penalty:.2f}, Eng_Eff={effective_engagement:.2f}"
        )


        # 4. Decisão
        if not vote_scores:
            chosen_short = "NULO"
        else:
            chosen_short = max(vote_scores, key=vote_scores.get)
        
        # 5. Regra de voto nulo (somente se o melhor score for realmente ruim)
        max_score = vote_scores.get(chosen_short, -float('inf'))
        if max_score <= 0.05 and random.random() < 0.4: 
             chosen_short = "NULO" 

        # 6. Regra: candidato vota em si mesmo (Prioridade máxima)
        me_short = get_sender_name(me)
        if self.is_candidate:
            if random.random() < 0.99:
                chosen_short = me_short
            else:
                chosen_short = "NULO" 

        
        # 7. LOG DE ESTADO
        print(f"[{label}] ESTADO_NO_MOMENTO_DO_VOTO: {self.debug_summary()}")
        
        # 8. Envio
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
                    q.set_metadata("protocol", PROTOCOL_INFLUENCE) 
                    q.set_metadata("performative", "query") 
                    q.body = "QUERY_PROFILE"
                    await self.send(q)
                return

            proto = msg.metadata.get("protocol", "")
            
            if proto == PROTOCOL_INIT_SIM:
                self.agent.handle_init_sim(msg.body or "")

            elif proto == PROTOCOL_REQUEST_ENGAGEMENT:
                await self.agent.handle_engagement_request(msg, self)
            
            elif proto == PROTOCOL_INFLUENCE:
                performative = msg.metadata.get("performative")
                if performative == "query":
                    await self.agent.handle_influence_query(msg, self)
                elif performative == "inform":
                    self.agent.apply_influence(msg)
            
            elif proto == PROTOCOL_CAMPAIGN:
                if not self.agent.is_candidate and self.agent.tick > 10:
                    # NOVO: Contador de mensagens (Fadiga)
                    self.agent.msg_count_campaign += 1
                    self.agent.update_campaign_memory(msg)
            
            elif proto == PROTOCOL_VOTING:
                # Comando REQUEST_VOTE (T51)
                if (msg.metadata.get("performative") == "request" and 
                    (msg.body or "").strip().upper() == "REQUEST_VOTE" and 
                    not self.agent.voted):
                    
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] REQUEST_VOTE recebido. Iniciando votação.")
                    await self.agent.decide_and_vote(self)