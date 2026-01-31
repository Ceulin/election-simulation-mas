# python_spade/candidate_agent.py — Candidato (Modelo)

import asyncio
import random
import spade
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from common import (
    get_sender_name,
    PROTOCOL_INIT_SIM,
    PROTOCOL_CAMPAIGN,
)

class CandidateAgent(spade.agent.Agent):
    """
    Agente Candidato (modelo de alto nível, não usado diretamente no run_spade_sim.py atual).
    A lógica de campanha do rascunho é mantida aqui.
    """
    def __init__(self, jid, password, supervisor_jid: str, party: str, initial_budget: int = 1000, credibility: float = 0.5, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.party = party
        self.budget = int(initial_budget)
        self.credibility = float(max(0.0, min(1.0, credibility)))
        self._last_tick = -1
        # Media JID é hardcoded aqui, o que é um ponto a ser melhorado na próxima iteração
        self.media_jid = "media_1@localhost" 

    class Campaigner(CyclicBehaviour):
        async def run(self):
            # 1. Ouve o TICK do Supervisor
            template = Template(metadata={"protocol": PROTOCOL_INIT_SIM})
            msg = await self.receive(template=template, timeout=0.2) 
            if not msg: return

            body = msg.body or ""
            if not body.startswith("TICK_"): return

            try:
                t = int(body.split("_", 1)[1])
            except Exception: return
            self.agent._last_tick = t

            # 2. Lógica de Campanha
            # Ativa de T11 a T50 e com orçamento
            if 10 < t <= 50 and self.agent.budget > 0:
                # Decide se é NEWS (65%) ou FAKENEWS (35%)
                perform = "NEWS" if random.random() > 0.35 else "FAKENEWS"
                
                # Envia mensagem para a Mídia filtrar e difundir
                m = Message(to=self.agent.media_jid)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", perform) # Performative: Ação/Tipo de Mensagem
                m.body = f"campanha:{get_sender_name(str(self.agent.jid)).lower()}:t={t}" # Conteúdo
                
                await self.send(m)
                self.agent.budget -= 1
                
                await asyncio.sleep(0.5) # Pausa para não sobrecarregar a Mídia

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Candidato iniciado. Party={self.party} Budget={self.budget} Cred={self.credibility:.2f}")
        self.add_behaviour(self.Campaigner(), Template(metadata={"protocol": PROTOCOL_INIT_SIM}))