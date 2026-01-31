# python_spade/media_agent.py
import asyncio, random, json, spade
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
import common as cfg
from common import (PROTOCOL_CAMPAIGN, PROTOCOL_PUNISH, PROTOCOL_INIT_SIM, 
                    get_sender_name, TICK_DURATION, PROTOCOL_ELIMINATION)

class MediaAgent(spade.agent.Agent):
    def __init__(self, jid, password, supervisor_jid, voter_jids, authority_jid, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.authority_jid = authority_jid
        self.voter_jids = voter_jids              
        self.known_candidates = []
        self._tick = 0
        self._cand_idx = 0
        self.eliminated_candidates = set()
        self.sent_news = 0
        self.sent_fake = 0

    class SimListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.3)
            if not msg: return
            body = msg.body or ""
            if "TICK_" in body:
                self.agent._tick = int(body.split("_")[1])
            elif "CANDIDATES_ANNOUNCED" in body:
                for part in body.split(";"):
                    if part.startswith("CANDIDATES="):
                        self.agent.known_candidates = part.split("=", 1)[1].split(",")

    class EliminationListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if msg and msg.metadata.get("protocol") == PROTOCOL_ELIMINATION:
                self.agent.eliminated_candidates.add(msg.body)

    class Broadcaster(CyclicBehaviour):
        async def run(self):
            if not (10 < self.agent._tick <= 50) or not self.agent.known_candidates:
                await asyncio.sleep(TICK_DURATION)
                return

            cand_jid = self.agent.known_candidates[self.agent._cand_idx % len(self.agent.known_candidates)]
            self.agent._cand_idx += 1
            if cand_jid in self.agent.eliminated_candidates: return

            msg_type = "NEWS" if random.random() < cfg.MEDIA_NEWS_RATE else "FAKENEWS"
            if msg_type == "NEWS": self.agent.sent_news += 1
            else: self.agent.sent_fake += 1

            targets = random.sample(self.agent.voter_jids, max(1, int(0.4 * len(self.agent.voter_jids))))
            for v_jid in targets:
                m = Message(to=v_jid)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", msg_type)
                m.body = json.dumps({"type": msg_type, "tick": self.agent._tick, "cand": get_sender_name(cand_jid)})
                await self.send(m)

            if msg_type == "FAKENEWS":
                report = Message(to=str(self.agent.authority_jid))
                report.set_metadata("protocol", PROTOCOL_PUNISH)
                report.body = json.dumps({"candidate": cand_jid, "type": "FAKENEWS", "tick": self.agent._tick})
                await self.send(report)
            await asyncio.sleep(TICK_DURATION)

    async def setup(self):
        self.add_behaviour(self.SimListener(), Template(metadata={"protocol": PROTOCOL_INIT_SIM}))
        self.add_behaviour(self.Broadcaster())
        self.add_behaviour(self.EliminationListener(), Template(metadata={"protocol": PROTOCOL_ELIMINATION}))