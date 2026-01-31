# python_spade/authority_agent.py
import spade
import asyncio
import json
from collections import Counter
from typing import Dict, List, Optional

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


class ElectionAuthorityAgent(spade.agent.Agent):
    """
    Agente Autoridade Eleitoral:
    - Coleta votos e publica resultados.
    - Ouve DENÚNCIAS da Mídia e aplica PUNIÇÕES (multiplicações no orçamento).
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
        
        # Estatísticas de Violação e Orçamentos para punição
        self.violations: Dict[str, Dict[str, int]] = {} # {cand_jid: {"fake": count}}
        self.candidate_budgets: Dict[str, float] = {} # {cand_jid: budget}

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
        tpl_report.protocol = PROTOCOL_PUNISH # Usando o PROTOCOL_PUNISH de common.py
        self.add_behaviour(self.MediaReportBehaviour(), tpl_report)

    # ============================================================
    #  BEHAVIOUR: Processa Denúncias da Mídia e Pune
    # ============================================================
    class MediaReportBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5) 
            if not msg:
                return
            
            # CORREÇÃO CRÍTICA: Acessar o protocolo via metadados na SPADE 4.x
            protocol = msg.get_metadata("protocol")
            if protocol != PROTOCOL_PUNISH:
                return
            
            data = json.loads(msg.body)
            cand = data["candidate"] # JID completo do candidato
            
            # 1. Inicializar contagem
            if cand not in self.agent.violations:
                self.agent.violations[cand] = { "fake": 0 }

            # 2. Registrar infração
            self.agent.violations[cand]["fake"] += 1

            # 3. Aplicar punição (Hardcoded em 100, conforme tarefa)
            penalty = 100 
            
            # 4. Checar se o orçamento existe e aplicar
            if cand in self.agent.candidate_budgets:
                self.agent.candidate_budgets[cand] -= penalty
                
                # 5. Logar evento
                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] PUNIÇÃO: "
                    f"cand={get_sender_name(cand).upper()}, multa={penalty}, "
                    f"total_fake={self.agent.violations[cand]['fake']}, "
                    f"budget_restante={self.agent.candidate_budgets[cand]:.2f}"
                )
            else:
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] PUNIÇÃO FALHOU: Candidato {get_sender_name(cand).upper()} não encontrado em budgets.")


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
                                
                                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos registrados: {len(self.agent._candidate_jids)}")
                except Exception as e:
                    print(f"[AUTHORITY_ANNOUNCE_ERR] Erro ao processar anúncio: {e}")

    # ============================================================
    #  Listener: recebimento de votos
    # ============================================================
    class VoteCollector(CyclicBehaviour):
        async def run(self):
            # Timeout mais longo para garantir recebimento
            msg = await self.receive(timeout=1.0) 
            if not msg:
                return

            vote = (msg.body or "").strip()
            self.agent._votes.append(vote)

    # ============================================================
    #  Listener: comando de contagem e publicação
    # ============================================================
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
            
            # Tempo de espera para o processamento de votos (CRÍTICO)
            await asyncio.sleep(5.0) # 5.0 no TESTE / 12.0 no REAL  
            
            # Contagem bruta
            counts = Counter(self.agent._votes)

            # Candidatos válidos (JIDs completos + "NULO")
            valid = set(self.agent._candidate_jids + ["NULO"])
            
            # Filtra votos para apenas candidatos válidos e NULO
            final_counts = {}
            for vote_jid, count in counts.items():
                if vote_jid in valid:
                    final_counts[vote_jid] = count

            # Adiciona zeros para candidatos válidos que não receberam votos
            for cand_jid in self.agent._candidate_jids:
                if cand_jid not in final_counts:
                    final_counts[cand_jid] = 0

            # Serializa resultado
            payload = json.dumps(final_counts)

            # Envia resultados ao Supervisor
            msg_sup = Message(to=self.agent.supervisor_jid)
            msg_sup.set_metadata("protocol", PROTOCOL_RESULTS)
            msg_sup.set_metadata("performative", "inform")
            msg_sup.body = payload
            await self.send(msg_sup)
            
            # Printa para debug
            print(
                f"[{get_sender_name(str(self.agent.jid)).upper()}] RESULTADOS FINAIS ENVIADOS: {final_counts} "
                f"({len(self.agent._votes)} votos totais recebidos)."
            )