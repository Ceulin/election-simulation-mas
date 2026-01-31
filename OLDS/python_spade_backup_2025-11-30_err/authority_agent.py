# python_spade/authority_agent.py
import spade
import asyncio
import json
import random 
from collections import Counter, defaultdict
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
    PROTOCOL_PUNISH,
    PROTOCOL_ELIMINATION,
    CANDIDATE_INITIAL_BUDGET,
    N_SEATS, 
    N_CITIZENS, 
)

# Constante para a Punição Probabilística
P_DETECT_BASE = 0.7  

class ElectionAuthorityAgent(spade.agent.Agent):
    """
    Agente Autoridade Eleitoral:
    - Coleta votos, aplica D'Hondt e publica resultados ricos.
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
        self.media_jid: Optional[str] = None 
        
        # D'Hondt
        self.candidate_parties: Dict[str, str] = {} 
        
        # Punição e Economia
        self.violations: Dict[str, Dict[str, int]] = {}
        self.candidate_budgets: Dict[str, float] = {} 
        self.cand_punishments: Dict[str, int] = {}    
        self.eliminated_cands: Set[str] = set() 

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Autoridade Eleitoral iniciado.")

        # Listener 1: Votos
        self.add_behaviour(
            self.VoteCollector(),
            Template(metadata={"protocol": PROTOCOL_VOTE})
        )

        # Listener 2: Sinal de contagem
        self.add_behaviour(
            self.StartCountListener(),
            Template(metadata={"protocol": PROTOCOL_VOTING, "performative": "inform"})
        )

        # Listener 3: Anúncios de candidatos
        self.add_behaviour(
            self.CandidateAnnounceListener(),
            Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        )
        
        # Listener 4: Denúncias da Mídia
        tpl_report = Template()
        tpl_report.protocol = PROTOCOL_PUNISH
        self.add_behaviour(self.MediaReportBehaviour(), tpl_report)
    
    async def _notify_media_of_elimination(self, cand_jid: str, beh: CyclicBehaviour):
        """Notifica a Mídia sobre a eliminação de um candidato."""
        if self.media_jid:
            m = Message(to=self.media_jid)
            m.set_metadata("protocol", PROTOCOL_ELIMINATION)
            m.set_metadata("performative", "inform")
            m.body = cand_jid 
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
            cand = data["candidate"] 
            
            # 1. Detecção Probabilística
            if random.random() < P_DETECT_BASE:
                # DETECTADO: Aplica punição
                
                if cand not in self.agent.violations:
                    self.agent.violations[cand] = { "fake": 0 }

                self.agent.violations[cand]["fake"] += 1
                penalty = 100 
                
                if cand in self.agent.candidate_budgets:
                    self.agent.candidate_budgets[cand] -= penalty
                
                # Contagem de punições para eliminação
                self.agent.cand_punishments[cand] = self.agent.cand_punishments.get(cand, 0) + 1
                
                if self.agent.cand_punishments[cand] >= 3 and cand not in self.agent.eliminated_cands:
                    self.agent.eliminated_cands.add(cand)
                    await self.agent._notify_media_of_elimination(cand, self) 
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CANDIDATO ELIMINADO POR FAKE NEWS: {get_sender_name(cand).upper()}")

                # Logar evento
                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] PUNIÇÃO [DETECTADA]: "
                    f"cand={get_sender_name(cand).upper()}, multa={penalty}, "
                    f"total_punicoes={self.agent.cand_punishments.get(cand, 0)}, "
                    f"budget_restante={self.agent.candidate_budgets.get(cand, 0.0):.2f}"
                )
            else:
                # NÃO DETECTADO
                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] PUNIÇÃO [NÃO DETECTADA]: "
                    f"Denúncia recebida para {get_sender_name(cand).upper()} ignorada (P_DETECT_BASE={P_DETECT_BASE})."
                )


    # ============================================================
    #  Listener: anúncio de candidatos (Atualizado para parties)
    # ============================================================
    class CandidateAnnounceListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return

            body = (msg.body or "")
            if "CANDIDATES_ANNOUNCED" in body:
                try:
                    cands = []
                    parties = []
                    media_jid = None
                    
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="):
                            cands = [x.strip() for x in part.split("=", 1)[1].strip().split(",") if x.strip()]
                        elif part.startswith("CANDIDATE_PARTIES="): # Lendo parties
                            parties = [x.strip() for x in part.split("=", 1)[1].strip().split(",") if x.strip()]
                        elif part.startswith("MEDIA_JID="):
                            media_jid = part.split("=", 1)[1].strip()
                            
                    self.agent._candidate_jids = cands
                    self.agent.media_jid = media_jid
                    
                    # 2.1 Armazenar o partido de cada candidato
                    if cands and parties and len(cands) == len(parties):
                        self.agent.candidate_parties = dict(zip(cands, parties))

                    # Inicializa o budget e punições
                    for cand_jid in cands:
                        self.agent.candidate_budgets[cand_jid] = CANDIDATE_INITIAL_BUDGET
                        self.agent.cand_punishments[cand_jid] = 0 
                    
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos registrados: {len(self.agent._candidate_jids)} com partidos.")
                            
                except Exception as e:
                    print(f"[AUTHORITY_ANNOUNCE_ERR] Erro ao processar anúncio: {e}")

    # ============================================================
    #  Listener: comando de contagem e publicação (D'Hondt)
    # ============================================================
    class StartCountListener(CyclicBehaviour):
        
        @staticmethod
        def dhondt_allocation(votes_per_party: Dict[str, int], n_seats: int) -> Dict[str, int]:
            """Implementa o método D'Hondt para distribuição de cadeiras."""
            seats = {p: 0 for p in votes_per_party.keys()}
            quotients = []

            for party, v in votes_per_party.items():
                for k in range(1, n_seats + 1):
                    quotients.append((v / k, party))

            quotients.sort(reverse=True, key=lambda t: t[0])
            
            # Distribui as cadeiras
            for _, party in quotients[:n_seats]:
                seats[party] += 1

            return seats
        
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
            valid_cands = set(self.agent._candidate_jids)
            
            final_counts = {}
            for vote_jid, count in counts.items():
                if vote_jid in valid_cands or vote_jid == "NULO":
                    final_counts[vote_jid] = count

            # Adiciona zeros para candidatos válidos que não receberam votos
            for cand_jid in self.agent._candidate_jids:
                if cand_jid not in final_counts:
                    final_counts[cand_jid] = 0

            # 2.2 Calcular votos por partido
            party_votes = defaultdict(int)
            total_valid_votes = 0
            for cand_jid, votes in final_counts.items():
                if cand_jid == "NULO":
                    continue
                party = self.agent.candidate_parties.get(cand_jid, "SPD")
                party_votes[party] += votes
                total_valid_votes += votes

            # Aplicar D'Hondt
            seats_per_party = self.dhondt_allocation(party_votes, N_SEATS)
            
            # Calcular abstenções e nulos
            total_votes_received = len(self.agent._votes)
            abstentions = max(0, N_CITIZENS - total_votes_received)
            null_votes = final_counts.get("NULO", 0)

            # Payload rico
            payload_dict = {
                "by_candidate": final_counts,
                "by_party": dict(party_votes),
                "seats_dhondt": seats_per_party,
                "total_votes_received": total_votes_received,
                "total_citizens": N_CITIZENS,
                "abstentions": abstentions,
                "null_votes": null_votes,
            }

            payload = json.dumps(payload_dict)

            # Envia resultados ao Supervisor
            msg_sup = Message(to=self.agent.supervisor_jid)
            msg_sup.set_metadata("protocol", PROTOCOL_RESULTS)
            msg_sup.set_metadata("performative", "inform")
            msg_sup.body = payload
            await self.send(msg_sup)
            
            # Printa para debug
            print(
                f"[{get_sender_name(str(self.agent.jid)).upper()}] RESULTADOS FINAIS ENVIADOS: "
                f"Cadeiras={seats_per_party}, Válidos={total_valid_votes}, Nulos={null_votes}, Abst={abstentions}"
            )
            print(f"[{get_sender_name(str(self.agent.jid)).upper()}] PAYLOAD: {payload_dict}")

    # ============================================================
    #  VoteCollector (Inalterado)
    # ============================================================
    class VoteCollector(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1.0) 
            if not msg:
                return

            vote = (msg.body or "").strip()
            self.agent._votes.append(vote)