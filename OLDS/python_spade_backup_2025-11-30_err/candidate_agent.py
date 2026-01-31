import random
import json
from dataclasses import dataclass
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict

# Constantes de Protocolo (para consistência com Supervisor/Mídia)
PROTOCOL_TICK = "SUPERVISOR_TICK"
PROTOCOL_CAMPAIGN_INTENT = "CANDIDATE_CAMPAIGN"
MEDIA_JID_DEFAULT = "media_1@localhost"

@dataclass
class CandidateConfig:
    candidate_voter_id: str # JID COMPLETO do Voter original
    party: str
    initial_budget: float = 1000.0
    fake_news_propensity: float = 0.2
    media_jid: str = MEDIA_JID_DEFAULT

class CandidateAgent(Agent):
    """
    Agente Candidato Autônomo. Decide a ação (NEWS/FAKENEWS)
    e envia a intenção para a Mídia para execução.
    """
    def __init__(self, jid, password, config: CandidateConfig, **kwargs):
        super().__init__(jid, password, **kwargs)
        self.config = config
        self.current_budget = config.initial_budget
        self._last_tick = -1

    class TickReceiverBehaviour(CyclicBehaviour):
        async def run(self):
            # CORREÇÃO: Remover template= do receive, tpl já está no setup
            msg = await self.receive(timeout=0.2) 
            if not msg:
                return

            protocol = msg.metadata.get("protocol", "")
            
            # Garante que a mensagem é um TICK do Supervisor
            if protocol != PROTOCOL_TICK:
                return

            try:
                payload = json.loads(msg.body)
            except Exception:
                return 
                
            tick = payload.get("tick")
            phase = payload.get("phase")
            self.agent._last_tick = tick

            # Só atua na fase de campanha (T11 a T50)
            if phase != "Campanha Eleitoral":
                return
            
            if not (10 < tick <= 50):
                return

            agent = self.agent

            # 1. Checa Orçamento
            if agent.current_budget <= 0:
                return

            # 2. Decide Ação
            action = agent.decide_action()

            # 3. Envia Intenção para a Mídia
            media_msg = Message(to=agent.config.media_jid)
            media_msg.set_metadata("protocol", PROTOCOL_CAMPAIGN_INTENT)
            media_msg.set_metadata("performative", "request")
            media_msg.set_metadata("candidate_id", agent.config.candidate_voter_id) 
            media_msg.set_metadata("action", action)

            media_payload = {
                "tick": tick,
                "party": agent.config.party,
                "budget_remaining": agent.current_budget,
            }
            media_msg.body = json.dumps(media_payload)
            
            print(f"[{agent.jid}] Enviando campanha: cand={agent.config.candidate_voter_id}, action={action}, tick={tick}")

            await self.send(media_msg)

    async def setup(self):
        print(f"[{self.jid}] CandidateAgent iniciado para {self.config.candidate_voter_id} ({self.config.party}).")
        
        b = self.TickReceiverBehaviour()
        # Template associado em add_behaviour (CORREÇÃO DE SINTAXE)
        tpl = Template()
        tpl.set_metadata("protocol", PROTOCOL_TICK) 
        self.add_behaviour(b, tpl)

    def decide_action(self) -> str:
        """Decisão de ação baseada na propensão a Fake News."""
        if random.random() < self.config.fake_news_propensity:
            return "FAKENEWS"
        return "NEWS"

    def apply_cost(self, cost: float):
        """Método chamado pela Mídia para deduzir o custo."""
        self.current_budget = max(0.0, self.current_budget - cost)