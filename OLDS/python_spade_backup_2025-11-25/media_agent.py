# python_spade/media_agent.py
import asyncio, random
import spade
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from common import (
    PROTOCOL_CAMPAIGN,
    PROTOCOL_PUNISH,
    PROTOCOL_INIT_SIM,
    get_sender_name,
    TICK_DURATION, 
)

class MediaAgent(spade.agent.Agent):
    """
    Agente Mídia:
    - Recebe TICKs e Anúncio de Candidatos.
    - Na fase de Campanha (T11-T50), difunde mensagens (NEWS/FAKENEWS)
      para uma amostra de eleitores.
    """

    def __init__(self, jid, password, supervisor_jid: str, voter_jids: list, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.voter_jids = voter_jids              
        self.known_candidates = []        # JIDs completos
        self._tick = 0
        self._cand_idx = 0               

    class SimListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.3)
            if not msg: 
                return
            
            body = (msg.body or "").strip()
            
            # 1. Processa TICK
            if body.startswith("TICK_"):
                try:
                    self.agent._tick = int(body.split("_")[1])
                except Exception:
                    pass
            
            # 2. Processa ANNOUNCE de Candidatos
            elif "CANDIDATES_ANNOUNCED" in body:
                try:
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="):
                            raw = part.split("=", 1)[1].strip()
                            if raw:
                                self.agent.known_candidates = [c for c in raw.split(",") if c]
                                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos conhecidos: {len(self.agent.known_candidates)}")
                except Exception:
                    pass

    class Broadcaster(CyclicBehaviour):
        async def run(self):
            # 1. Condição de Campanha
            if not (10 < self.agent._tick <= 50):
                await asyncio.sleep(TICK_DURATION)
                return

            if not self.agent.voter_jids or not self.agent.known_candidates:
                await asyncio.sleep(TICK_DURATION)
                return

            # Alvo de campanha: candidato por rodízio (JID completo)
            cand_jid = self.agent.known_candidates[self.agent._cand_idx % len(self.agent.known_candidates)]
            self.agent._cand_idx += 1

            # Amostra de eleitores (40% da população)
            pop = max(1, int(0.4 * len(self.agent.voter_jids)))
            targets = random.sample(self.agent.voter_jids, pop)

            # Variação: 2/3 NEWS, 1/3 FAKENEWS
            perf = "NEWS" if (random.random() < 0.67) else "FAKENEWS" 
            
            cand_jid_name = get_sender_name(cand_jid)

            for v in targets:
                m = Message(to=v)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", perf)
                m.body = f"pitch:{cand_jid_name};t={self.agent._tick}"
                await self.send(m)
                
            # Esperar o TICK completo para não sobrecarregar
            await asyncio.sleep(TICK_DURATION) 

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Mídia iniciado.")
        
        # 1. Listener de Simulação (TICKs/ANNOUNCE) 
        template_sim = Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        self.add_behaviour(self.SimListener(), template_sim) 
        
        # 2. Broadcaster de Campanha
        self.add_behaviour(self.Broadcaster())