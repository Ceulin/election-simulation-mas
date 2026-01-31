# python_spade/voter_agent.py
import asyncio
import random
import json
import spade
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
import common as cfg

class VoterAgent(spade.agent.Agent):
    def __init__(self, jid, password, supervisor_jid, authority_jid, party, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.authority_jid = authority_jid
        self.party = party
        
        # Perfil ideológico inicial
        base_party_data = cfg.PARTIES.get(party, {"ideology": 0})
        self.ideology = float(base_party_data["ideology"])
        self.ideology_t0 = self.ideology
        
        # Atributos comportamentais
        self.media_trust = random.uniform(0.5, 0.9)
        self.voted = False
        self.tick = 0
        
        # Estados para análise de fadiga e abstenção (Objetivo 2)
        self.engagement = random.uniform(0.4, 0.9)
        self.overload = 0
        self.exposures_news = 0
        self.exposures_fake = 0

    def update_ideology(self, msg):
        """
        Processa o impacto de NEWS e FAKENEWS na ideologia e no engagement.
        Implementa o efeito causal e a fadiga política (overload).
        """
        try:
            content = json.loads(msg.body)
            msg_type = content.get("type")
            
            # Peso da confiança na mídia ajustado pela sensibilidade global
            trust_factor = (self.media_trust ** cfg.TRUST_SENSITIVITY)
            
            if msg_type == "NEWS":
                self.exposures_news += 1
                self.overload += cfg.OVERLOAD_PER_NEWS
                # NEWS puxam a ideologia para o centro (0.0)
                direction = -1 if self.ideology > 0 else 1
                self.ideology += (cfg.NEWS_IMPACT * trust_factor) * direction
            
            elif msg_type == "FAKENEWS":
                self.exposures_fake += 1
                self.overload += cfg.OVERLOAD_PER_FAKE
                # FAKENEWS empurram para os extremos (afastam de 0.0)
                direction = 1 if self.ideology >= 0 else -1
                self.ideology += (cfg.FAKE_IMPACT * trust_factor) * direction
            
            # Atualiza o engagement com base no decaimento por sobrecarga
            self.engagement = max(0.0, self.engagement - cfg.ENGAGEMENT_DECAY_PER_OVERLOAD * self.overload)
            
            # Garante que a ideologia permaneça no range [-2, 2]
            self.ideology = max(-2.0, min(2.0, self.ideology))
            
        except Exception as e:
            print(f"[{cfg.get_sender_name(str(self.jid)).upper()}] Erro ao processar campanha: {e}")

    async def decide_and_vote(self, beh):
        """
        Lógica de decisão de voto. Implementa abstenção e voto nulo.
        """
        if self.voted:
            return
        
        self.voted = True
        label = cfg.get_sender_name(str(self.jid)).upper()

        # 1. Checagem de Abstenção por baixo Engagement (Fadiga)
        if self.engagement < cfg.ABSTENTION_THRESHOLD:
            print(f"[{label}] ABSTENÇÃO: Baixo engajamento ({self.engagement:.2f}) devido a overload ({self.overload})")
            return

        # 2. Decisão entre Voto Partidário ou Nulo
        # Se a ideologia estiver muito próxima do centro (indecisão), vota nulo
        if abs(self.ideology) < 0.25:
            chosen_vote = "NULO"
        else:
            chosen_vote = self.party

        # 3. Envio do voto com payload rico para a Authority (Objetivo 1 e 3)
        msg = Message(to=self.authority_jid)
        msg.set_metadata("protocol", cfg.PROTOCOL_VOTE)
        msg.body = json.dumps({
            "vote": chosen_vote,
            "exposures_news": self.exposures_news,
            "exposures_fake": self.exposures_fake,
            "delta_ideology": self.ideology - self.ideology_t0,
            "final_ideology": self.ideology,
            "engagement": self.engagement,
            "overload": self.overload
        })
        
        await beh.send(msg)
        print(f"[{label}] VOTO ENVIADO: {chosen_vote} (Ideologia Final: {self.ideology:.2f})")

    class VoterCycle(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return
            
            proto = msg.metadata.get("protocol")
            
            if proto == cfg.PROTOCOL_INIT_SIM:
                if "TICK_" in (msg.body or ""):
                    self.agent.tick = int(msg.body.split("_")[1])
            
            elif proto == cfg.PROTOCOL_CAMPAIGN:
                self.agent.update_ideology(msg)
            
            elif proto == cfg.PROTOCOL_VOTING:
                if "REQUEST_VOTE" in (msg.body or ""):
                    await self.agent.decide_and_vote(self)

    async def setup(self):
        # Escuta geral para capturar todos os protocolos relevantes
        self.add_behaviour(self.VoterCycle(), Template())