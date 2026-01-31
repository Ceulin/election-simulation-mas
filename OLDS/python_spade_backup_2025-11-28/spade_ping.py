import asyncio
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

SUPERVISOR = "supervisor@localhost"
CITIZEN    = "a0001@localhost"
PASSWORD   = "secret"  # qualquer string serve no servidor embutido

class Ponger(Agent):
    class Echo(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                print(f"[Ponger] recv: {msg.body}")
                reply = Message(to=str(msg.sender))
                reply.body = "pong"
                await self.send(reply)
    async def setup(self):
        self.add_behaviour(self.Echo())

class Pinger(Agent):
    class KickOff(OneShotBehaviour):
        async def run(self):
            msg = Message(to=CITIZEN)
            msg.body = "ping"
            await self.send(msg)
            print("[Pinger] sent: ping")
            reply = await self.receive(timeout=10)
            print(f"[Pinger] recv: {getattr(reply,'body',None)}")
            await self.agent.stop()
    async def setup(self):
        self.add_behaviour(self.KickOff())

async def main():
    ponger = Ponger(CITIZEN, PASSWORD)
    await ponger.start()

    pinger = Pinger(SUPERVISOR, PASSWORD)
    await pinger.start()

    await asyncio.sleep(3)
    await ponger.stop()

if __name__ == "__main__":
    asyncio.run(main())