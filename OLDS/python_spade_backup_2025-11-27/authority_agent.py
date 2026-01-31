# python_spade/authority_agent.py
import spade
import asyncio
import json
import random # Necessário para detecção probabilística
from collections import Counter
from typing import Dict, List, Optional, Set

from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from common import (
    get_sender_name,
    generate_jid,
    SUPERVISOR_PREFIX,
    PROTOCOL_VOTE,
    PROTOCOL_RESULTS,
    PROTOCOL_VOTING,
    PROTOCOL_INIT_SIM,
    # Protocolo de Punição
    PROTOCOL_PUNISH,
    # Constantes Econômicas (para aplicar a punição)
    CANDIDATE_INITIAL_BUDGET
)

# Constante para a Punição Probabilística (TAREFA 3.1)
P_DETECT_BASE = 0.7  
PROTOCOL_ELIMINATION = "ELIMINATION" # Novo protocolo para notificar a mídia

class ElectionAuthorityAgent(spade.agent.Agent):
    """
    Agente Autoridade Eleitoral:
    - Coleta votos e publica resultados.
    - Ouve DENÚNCIAS da Mídia e aplica PUNIÇÕES (probabilísticas).
    - Gerencia a eliminação de candidatos após 3 punições.
    """

    def __init__(
        self,
        jid: str,
        password: str,
        supervisor_jid: Optional[str] = None,
        *args,
        **kwargs
    ):
        super().__init__(jid, password, *args, **kwargs)

        self.supervisor_jid = supervisor_jid or generate_jid(SUPERVISOR_PREFIX, 1)
        self._votes: List[str] = []           
        self._candidate_jids: List[str] = []  
        self.media_jid: Optional[str] = None # JID da Mídia para notificação
        
        # Estatísticas de Violação e Orçamentos para punição
        self.violations: Dict[str, Dict[str, int]] = {} # {cand_jid: {"fake": count}}
        self.candidate_budgets: Dict[str, float] = {} # {cand_jid: budget}
        
        # NOVO (TAREFA 3.2)
        self.cand_punishments: Dict[str, int] = {}    # cand_jid -> número de punições EFETIVAS
        self.eliminated_cands: Set[str] = set() # Candidatos eliminados

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Autoridade Eleitoral iniciado.")

        # Listener 1: Votos (protocol: PROTOCOL_VOTE)
        self.add_behaviour(
            self.VoteCollector(),
            Template(metadata={"protocol": PROTOCOL_VOTE})
        )

        # Listener 2: Sinal de contagem (protocol: PROTOCOL_VOTING)
        self.add_behaviour(
            self.StartCountListener(),
            Template(metadata={"protocol": PROTOCOL_VOTING, "performative": "inform"})
        )

        # Listener 3: Anúncios de candidatos (protocol: PROTOCOL_INIT_SIM)
        self.add_behaviour(
            self.CandidateAnnounceListener(),
            Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        )
        
        # Listener 4: Denúncias da Mídia (protocol: PROTOCOL_PUNISH)
        tpl_report = Template()
        tpl_report.protocol = PROTOCOL_PUNISH 
        self.add_behaviour(self.MediaReportBehaviour(), tpl_report)
    
    async def _notify_media_of_elimination(self, cand_jid: str, beh: CyclicBehaviour):
        """Notifica a Mídia sobre a eliminação de um candidato (TAREFA 3.2)."""
        if self.media_jid:
            m = Message(to=self.media_jid)
            m.set_metadata("protocol", PROTOCOL_ELIMINATION)
            m.set_metadata("performative", "inform")
            m.body = cand_jid # JID completo do candidato
            await beh.send(m)

    # ============================================================
    #  BEHAVIOUR: Processa Denúncias da Mídia e Pune
    # ============================================================
    class MediaReportBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg:
                return
            
            protocol = msg.get_metadata("protocol")
            if protocol != PROTOCOL_PUNISH:
                return
            
            data = json.loads(msg.body)
            cand = data["candidate"] # JID completo do candidato
            
            # 1. Detecção Probabilística (TAREFA 3.1)
            if random.random() < P_DETECT_BASE:
                # DETECTADO: Aplica punição
                
                # Inicializa contagem
                if cand not in self.agent.violations:
                    self.agent.violations[cand] = { "fake": 0 }

                # Registrar infração
                self.agent.violations[cand]["fake"] += 1

                # Aplicar punição (Hardcoded em 100, conforme tarefa anterior)
                penalty = 100 
                
                if cand in self.agent.candidate_budgets:
                    self.agent.candidate_budgets[cand] -= penalty
                
                # Contagem de punições para eliminação (TAREFA 3.2)
                self.agent.cand_punishments[cand] = self.agent.cand_punishments.get(cand, 0) + 1
                
                if self.agent.cand_punishments[cand] >= 3 and cand not in self.agent.eliminated_cands:
                    self.agent.eliminated_cands.add(cand)
                    await self.agent._notify_media_of_elimination(cand, self) # Notifica a Mídia
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CANDIDATO ELIMINADO POR FAKE NEWS: {get_sender_name(cand).upper()}")

                # Logar evento
                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] PUNIÇÃO [DETECTADA]: "
                    f"cand={get_sender_name(cand).upper()}, multa={penalty}, "
                    f"total_punicoes={self.agent.cand_punishments.get(cand, 0)}, "
                    f"budget_restante={self.agent.candidate_budgets.get(cand, 0.0):.2f}"
                )
            else:
                # NÃO DETECTADO: apenas loga a falha
                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] PUNIÇÃO [NÃO DETECTADA]: "
                    f"Denúncia recebida para {get_sender_name(cand).upper()} ignorada (P_DETECT_BASE={P_DETECT_BASE})."
                )

    # ============================================================
    #  Listener: anúncio de candidatos (Atualizado para budgets)
    # ============================================================
    class CandidateAnnounceListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return

            body = (msg.body or "")
            if "CANDIDATES_ANNOUNCED" in body:
                try:
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="):
                            raw = part.split("=", 1)[1].strip()
                            if raw:
                                cands = [x.strip() for x in raw.split(",") if x.strip()]
                                self.agent._candidate_jids = cands
                                
                                # Inicializa o budget para que a punição funcione
                                for cand_jid in cands:
                                    self.agent.candidate_budgets[cand_jid] = CANDIDATE_INITIAL_BUDGET
                                    self.agent.cand_punishments[cand_jid] = 0 # Inicializa contador de punições
                                
                                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos registrados: {len(self.agent._candidate_jids)}")
                                
                        if part.startswith("MEDIA_JID="):
                            self.agent.media_jid = part.split("=", 1)[1].strip() # Pega JID da Mídia para notificação
                            
                except Exception as e:
                    print(f"[AUTHORITY_ANNOUNCE_ERR] Erro ao processar anúncio: {e}")

    # ============================================================
    #  Outros Behaviours (Inalterados na lógica principal)
    # ============================================================
    class VoteCollector(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1.0) 
            if not msg:
                return

            vote = (msg.body or "").strip()
            self.agent._votes.append(vote)

    class StartCountListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return

            body = (msg.body or "").strip().upper()
            if body == "START_COUNT":
                await self._count_and_publish()
                self.kill() 

        async def _count_and_publish(self):
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Recebido START_COUNT. AGUARDANDO VOTOS POR 5 SEGUNDOS...")
            
            await asyncio.sleep(5.0) 
            
            counts = Counter(self.agent._votes)

            valid = set(self.agent._candidate_jids + ["NULO"])
            
            final_counts = {}
            for vote_jid, count in counts.items():
                if vote_jid in valid:
                    final_counts[vote_jid] = count

            for cand_jid in self.agent._candidate_jids:
                if cand_jid not in final_counts:
                    final_counts[cand_jid] = 0

            payload = json.dumps(final_counts)

            msg_sup = Message(to=self.agent.supervisor_jid)
            msg_sup.set_metadata("protocol", PROTOCOL_RESULTS)
            msg_sup.set_metadata("performative", "inform")
            msg_sup.body = payload
            await self.send(msg_sup)
            
            print(
                f"[{get_sender_name(str(self.agent.jid)).upper()}] RESULTADOS FINAIS ENVIADOS: {final_counts} "
                f"({len(self.agent._votes)} votos totais recebidos)."
            )