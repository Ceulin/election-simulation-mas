# python_spade/supervisor_agent.py
import asyncio
import json
import spade
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
import common as cfg

class SupervisorAgent(spade.agent.Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tick = 0
        # Conexões injetadas pelo run_spade_sim.py
        self.voter_jids = []
        self.media_jid = None
        self.authority_jid = None

    class TimeController(CyclicBehaviour):
        """
        Gere o ciclo de vida temporal da simulação (T0 a T51).
        Envia TICKs para todos os agentes e coordena eventos especiais.
        """
        async def run(self):
            if self.agent._tick > cfg.TOTAL_TICKS:
                # O encerramento definitivo é feito pelo ResultsListener
                return
            
            t = self.agent._tick
            targets = self.agent.voter_jids + [self.agent.media_jid, self.agent.authority_jid]
            
            # 1. Broadcast de TICK (Sincronização global)
            for to in targets:
                m = Message(to=to)
                m.set_metadata("protocol", cfg.PROTOCOL_INIT_SIM)
                m.body = f"TICK_{t}"
                await self.send(m)

            # 2. T10 - Anúncio de Candidatos
            if t == 10:
                # No experimento controlado, os primeiros N são promovidos
                cands = self.agent.voter_jids[:cfg.N_CANDIDATES_TO_PROMOTE]
                m = Message()
                m.set_metadata("protocol", cfg.PROTOCOL_INIT_SIM)
                m.body = f"CANDIDATES_ANNOUNCED;CANDIDATES={','.join(cands)}"
                for to in targets:
                    m.to = to
                    await self.send(m)
                print(f"[{cfg.get_sender_name(str(self.agent.jid)).upper()}] T10: Candidatos anunciados.")

            # 3. T51 - Comando de Votação e Contagem
            if t == 51:
                print(f"[{cfg.get_sender_name(str(self.agent.jid)).upper()}] T51: Solicitando votos e contagem.")
                # Solicita votos aos eleitores
                for v in self.agent.voter_jids:
                    m = Message(to=v)
                    m.set_metadata("protocol", cfg.PROTOCOL_VOTING)
                    m.body = "REQUEST_VOTE"
                    await self.send(m)
                
                # Comando para Authority iniciar contagem
                m_auth = Message(to=str(self.agent.authority_jid))
                m_auth.set_metadata("protocol", cfg.PROTOCOL_VOTING)
                m_auth.body = "START_COUNT"
                await self.send(m_auth)
            
            self.agent._tick += 1
            await asyncio.sleep(cfg.TICK_DURATION)

    class ResultsListener(CyclicBehaviour):
        """
        Escuta os resultados finais da Authority e imprime o RESUMO científico.
        Finaliza o agente após a recepção.
        """
        async def run(self):
            # Timeout longo para aguardar o processamento da Authority
            msg = await self.receive(timeout=15) 
            if msg and msg.metadata.get("protocol") == cfg.PROTOCOL_RESULTS:
                try:
                    d = json.loads(msg.body)
                    
                    # RESUMO Rico e Parseável (Objetivo 4.1)
                    print(f"\n" + "="*60)
                    print(f"   📊 RESUMO CIENTÍFICO DA SIMULAÇÃO (NEWS RATE: {cfg.MEDIA_NEWS_RATE})")
                    print(f"   " + "-"*54)
                    print(f"   Votos por Partido: {d['votes_by_party']}")
                    print(f"   Assentos (D'Hondt): {d['seats_dhondt']}")
                    print(f"   Participação: Abstenções={d['abstentions']} | Nulos={d['null_votes']}")
                    print(f"   Exposição Média: NEWS={d['avg_news_exposure']:.2f} | FAKE={d['avg_fake_exposure']:.2f}")
                    print(f"   Comportamento: Engagement={d['mean_engagement']:.2f} | Overload={d['mean_overload']:.1f}")
                    print(f"   Polarização: Desvio Padrão Final={d['std_final_ideology']:.4f}")
                    print(f"   Delta Ideológico Médio: {d['mean_delta_ideology']:.4f}")
                    print("="*60 + "\n")
                    
                    # Sinaliza ao runner que terminamos (Objetivo 4.2)
                    self.agent.set("finished", True)
                    self.kill()
                    
                except Exception as e:
                    print(f"Erro ao processar resumo final: {e}")

    async def setup(self):
        # Estado interno para o run_spade_sim.py monitorar
        self.set("finished", False)
        
        self.add_behaviour(self.TimeController())
        
        # Template específico para os resultados finais
        tpl = Template(metadata={"protocol": cfg.PROTOCOL_RESULTS})
        self.add_behaviour(self.ResultsListener(), tpl)
        
        print(f"[{cfg.get_sender_name(str(self.jid)).upper()}] Supervisor iniciado e pronto.")