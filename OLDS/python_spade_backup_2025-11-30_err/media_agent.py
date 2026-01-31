# python_spade/media_agent.py
import asyncio, random
import spade
import json
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict, Any, List, Set, Optional
from collections import defaultdict

from common import (
    PROTOCOL_CAMPAIGN,
    PROTOCOL_PUNISH,
    PROTOCOL_INIT_SIM,
    get_sender_name,
    TICK_DURATION, 
    # CONSTANTES ECONÔMICAS
    CANDIDATE_INITIAL_BUDGET,
    COST_NEWS_PER_TARGET,
    COST_FAKENEWS_PER_TARGET,
    PENALTY_PER_FAKENEWS,
    # CONSTANTES DE REINFORCEMENT LEARNING (RL)
    RL_EPSILON,
    RL_ALPHA,
    RL_GAMMA,
    RL_LAMBDA_COST,
    PARTIES, 
    # Constantes de Relatório e Viral
    REPORT_TICKS,
    VIRAL_BASE_PROB,
    VIRAL_IMPACT_THRESHOLD,
    VIRAL_MAX_EXTRA_TARGETS,
    # Constantes de Viés
    MEDIA_IDEOLOGY_BIAS,
    MEDIA_BIAS_STRENGTH,
    N_CITIZENS,
)

# Tentativa de importação de P_DETECT_BASE do common
try:
    from common import P_DETECT_BASE 
except ImportError:
    P_DETECT_BASE = 0.7


# Constante para o protocolo de denúncia 
PROTOCOL_MEDIA_REPORT = "MEDIA_REPORT" 
PROTOCOL_ELIMINATION = "ELIMINATION" 
PROTOCOL_CAMPAIGN_INTENT = "CANDIDATE_CAMPAIGN" # Protocolo para receber intenção

class MediaAgent(spade.agent.Agent):
    """
    Agente Mídia: Recebe intenções dos candidatos, aplica RL e viralização,
    e executa a campanha.
    """

    def __init__(self, jid, password, supervisor_jid: str, voter_jids: list, authority_jid: str, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.authority_jid = authority_jid
        self.voter_jids = voter_jids              
        self.known_candidates: List[str] = [] # JIDs completos (Voters que são candidatos)
        self._tick = 0
        self._cand_idx = 0

        # NOVO: Intenções de Campanha recebidas
        self.campaign_intents: Dict[str, Dict[str, Any]] = {} 

        # Q-Learning
        self.candidate_budgets: Dict[str, float] = {} 
        self.q_values: Dict[str, Dict[str, Dict[str, float]]] = {} 
        self.candidate_party_map: Dict[str, str] = {} 
        self.eliminated_candidates: Set[str] = set() 

        # ATRIBUTOS DE ESTATÍSTICA (MANTIDOS)
        self._stats_news_sent_total: int = 0
        self._stats_fakenews_sent_total: int = 0
        self._stats_per_candidate: Dict[str, Dict[str, int]] = defaultdict(lambda: {"NEWS": 0, "FAKE": 0})
        self._printed_stats: bool = False

    # =========================================================
    # FUNÇÃO DE BROADCAST (Substitui o loop de envio)
    # =========================================================

    async def broadcast_to_voters(self, cand_short: str, action: str, targets: List[str], tick: int, beh: CyclicBehaviour):
        """
        Envia mensagens de campanha para os eleitores e loga o evento.
        Mantém o protocolo PROTOCOL_CAMPAIGN que os Voters esperam.
        """
        
        # O perf é a performative que o VoterAgent usa para calcular o impacto
        perf = action 
        
        # Loga o broadcast (para a verificação da query)
        print(f"[{get_sender_name(str(self.jid)).upper()}] T{tick}: broadcast {action} de {cand_short} para {len(targets)} alvos.")

        for v in targets:
            m = Message(to=v)
            m.set_metadata("protocol", PROTOCOL_CAMPAIGN) 
            m.set_metadata("performative", perf)
            # Body: Formato que o VoterAgent espera para extrair o candidato e o tick
            m.body = f"pitch:{cand_short};t={tick}" 
            await beh.send(m)

        # Retorna o número de mensagens enviadas
        return len(targets)


    # =========================================================
    # FUNÇÕES AUXILIARES DE RL E VIÉS (MANTIDAS)
    # =========================================================
    def _ideological_weight(self, cand_jid: str) -> float:
        """Calcula o peso ideológico da Mídia sobre o candidato."""
        party = self.candidate_party_map.get(cand_jid, "SPD")
        party_ideology = PARTIES.get(party, {}).get("ideology", 0)
        bias = MEDIA_IDEOLOGY_BIAS.upper()
        strength = MEDIA_BIAS_STRENGTH
        if bias == "NEUTRAL" or strength <= 0.0: return 1.0
        if bias == "LEFT": media_side = -1
        elif bias == "FAR_LEFT": media_side = -2
        elif bias == "RIGHT": media_side = 1
        elif bias == "FAR_RIGHT": media_side = 2
        elif bias == "CENTER": media_side = 0
        else: media_side = 0
        sign_match = (media_side * party_ideology)
        if sign_match > 0: return 1.0 + strength
        elif sign_match < 0: return 1.0 - strength
        else: return 1.0

    def _get_budget_state(self, cand_jid: str) -> str:
        """Mapeia o orçamento restante para um estado discreto (HIGH, MID, LOW)."""
        budget = self.candidate_budgets.get(cand_jid, 0.0)
        ratio = budget / float(CANDIDATE_INITIAL_BUDGET)
        if ratio >= 0.7: return "HIGH"
        elif ratio >= 0.3: return "MID"
        else: return "LOW"

    def _select_action(self, cand_jid: str, state: str) -> str:
        """Implementa a política ε-greedy para escolher NEWS ou FAKENEWS."""
        if cand_jid not in self.q_values:
            self.q_values[cand_jid] = {"HIGH": {"NEWS": 0.0, "FAKENEWS": 0.0}, "MID":  {"NEWS": 0.0, "FAKENEWS": 0.0}, "LOW":  {"NEWS": 0.0, "FAKENEWS": 0.0}}
        if state not in self.q_values[cand_jid]:
             self.q_values[cand_jid][state] = {"NEWS": 0.0, "FAKENEWS": 0.0}
        if random.random() < RL_EPSILON: return random.choice(["NEWS", "FAKENEWS"])
        q_state = self.q_values[cand_jid][state]
        if q_state["NEWS"] >= q_state["FAKENEWS"]: return "NEWS"
        else: return "FAKENEWS"

    def _update_q(self, cand_jid: str, state: str, action: str, 
                  reward: float, next_state: str, punished: bool = False) -> None:
        """
        Aplica a equação de Bellman e ajusta o Q-Value.
        """
        if cand_jid not in self.q_values: return 
        q_s_a = self.q_values[cand_jid][state][action]
        next_qs = self.q_values[cand_jid][next_state]
        max_next = max(next_qs["NEWS"], next_qs["FAKENEWS"]) 
        weight = self._ideological_weight(cand_jid)
        biased_reward = reward * weight
        updated = q_s_a + RL_ALPHA * (biased_reward + RL_GAMMA * max_next - q_s_a)
        
        if punished and action == "FAKENEWS":
            party = self.candidate_party_map.get(cand_jid, "SPD")
            if party in {"PDD", "PDE", "PCE"}: updated *= 0.5
            elif party in {"PED", "PEE"}: updated *= 0.9

        self.q_values[cand_jid][state][action] = updated
        
        agent_name_upper = str(get_sender_name(self.jid)).upper()
        cand_name_short = str(get_sender_name(cand_jid))

        print(
            f"[{agent_name_upper}] RL_UPDATE: cand={cand_name_short}, state='{state}', "
            f"action='{action}', reward={biased_reward:.4f} (W={weight:.2f}), Q_new={updated:.4f}, next_state='{next_state}'"
        )


    # =========================================================
    # BEHAVIOURS
    # =========================================================
    class SimListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.3)
            if not msg: return
            md = msg.metadata or {}
            if md.get("protocol") != PROTOCOL_INIT_SIM: return

            body = (msg.body or "").strip()
            
            if body.startswith("TICK_"):
                try:
                    self.agent._tick = int(body.split("_")[1])
                except Exception: pass
            
            elif "CANDIDATES_ANNOUNCED" in body:
                try:
                    jids = []; parties = []
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="): jids = [c for c in part.split("=", 1)[1].strip().split(",") if c]
                        elif part.startswith("CANDIDATE_PARTIES="): parties = [p for p in part.split("=", 1)[1].strip().split(",") if p]
                    
                    self.agent.known_candidates = jids
                    self.agent.candidate_party_map = dict(zip(jids, parties)) 
                                
                    for cand_jid in self.agent.known_candidates:
                        self.agent.candidate_budgets[cand_jid] = CANDIDATE_INITIAL_BUDGET
                        self.agent._stats_per_candidate[cand_jid] = {"NEWS": 0, "FAKE": 0}
                        self.agent.q_values[cand_jid] = {"HIGH": {"NEWS": 0.0, "FAKENEWS": 0.0}, "MID":  {"NEWS": 0.0, "FAKENEWS": 0.0}, "LOW":  {"NEWS": 0.0, "FAKENEWS": 0.0}}

                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos e Orçamentos inicializados: {len(self.agent.known_candidates)}")
                except Exception: pass
    
    class EliminationListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg: return
            protocol = msg.get_metadata("protocol")
            if protocol == PROTOCOL_ELIMINATION:
                cand_jid = msg.body or ""
                self.agent.eliminated_candidates.add(cand_jid)
                
                sender_name = get_sender_name(str(self.agent.jid))
                cand_name = get_sender_name(str(cand_jid))
                
                print(f"[{sender_name.upper()}] ALERTA DE ELIMINAÇÃO: Candidato {cand_name.upper()} removido do pool de campanha.")
    
    class JournalisticReport(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2) 
            if msg is None: return
            body = (msg.body or "").strip()
            tick = self.agent._tick
            if "REQUEST_REPORT" in body:
                
                block_coverage = defaultdict(lambda: {"NEWS": 0, "FAKE": 0, "TOTAL": 0})
                
                for cand_jid, stats in self.agent._stats_per_candidate.items():
                    party = self.agent.candidate_party_map.get(cand_jid, "SPD")
                    ideology = PARTIES.get(party, {}).get("ideology", 0)
                    
                    if ideology < 0: block = "ESQ"
                    elif ideology > 0: block = "DIR"
                    else: block = "CEN"
                        
                    block_coverage[block]["NEWS"] += stats["NEWS"]
                    block_coverage[block]["FAKE"] += stats["FAKE"]
                    block_coverage[block]["TOTAL"] += stats["NEWS"] + stats["FAKE"]

                total_messages = sum(bc["TOTAL"] for bc in block_coverage.values())
                
                block_summary = ", ".join([
                    f"{b}: NEWS={d['NEWS']}, FAKE={d['FAKE']} ({d['TOTAL']} total, {d['TOTAL']/total_messages*100:.1f}%)"
                    for b, d in block_coverage.items() if total_messages > 0
                ])

                leader = max(self.agent._stats_per_candidate.items(), key=lambda item: item[1]['NEWS'] + item[1]['FAKE'], default=(None, {'NEWS': 0, 'FAKE': 0}))
                cand_jid, data = leader
                cand_label = get_sender_name(cand_jid).upper() if cand_jid else "NENHUM"

                print(f"[{get_sender_name(str(self.agent.jid)).upper()}][REL_T{tick}] Através de: NEWS={self.agent._stats_news_sent_total}, FAKE={self.agent._stats_fakenews_sent_total}.")
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}][REL_T{tick}] Líder em exposição: {cand_label} (NEWS={data['NEWS']}, FAKE={data['FAKE']}).")
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Cobertura por bloco ideológico: {block_summary}")
                
    class CandidateCampaignReceiver(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return

            if msg.metadata.get("protocol") != PROTOCOL_CAMPAIGN_INTENT:
                return

            candidate_id = msg.metadata.get("candidate_id") # JID COMPLETO do Voter
            action = msg.metadata.get("action") # "NEWS" ou "FAKENEWS"
            
            try:
                payload = json.loads(msg.body)
            except Exception:
                payload = {}
                
            tick = payload.get("tick") 
            
            if candidate_id and action and tick is not None:
                # Armazena a intenção recebida com dados ricos
                self.agent.campaign_intents[candidate_id] = {
                    "action": action,
                    "tick": tick, 
                    "party": payload.get("party"),
                    "budget": payload.get("budget_remaining"),
                }
                
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] INTENÇÃO RECEBIDA: cand={get_sender_name(candidate_id)}, action={action}, tick={tick}")

    class Broadcaster(CyclicBehaviour):
        async def run(self):
            # Lógica de logs finais e condição de fim
            if self.agent._tick > 50 and not self.agent._printed_stats:
                
                q_log = {
                    get_sender_name(jid): {s: {a: f"{q:.4f}" for a, q in d.items()} for s, d in q_data.items()} 
                    for jid, q_data in self.agent.q_values.items()
                }
                print(f"[{str(get_sender_name(self.agent.jid)).upper()}] Q_VALUES_FINAL: {q_log}")
                
                self.agent._printed_stats = True
                await asyncio.sleep(TICK_DURATION)
                return

            # 1. Condição de Campanha
            if not (10 < self.agent._tick <= 50):
                await asyncio.sleep(TICK_DURATION)
                return

            # --- Execução das Intenções ---
            
            executed_any_campaign = False
            
            # CRÍTICO: Itera sobre todas as intenções recebidas neste tick e executa a campanha
            # O dicionário 'campaign_intents' contêm JID completos.
            
            # Usa list() para iterar sobre uma cópia (Segurança)
            for cand_jid, intent_data in list(self.agent.campaign_intents.items()):
                
                # 2a. Verifica se o candidato é válido para execução
                if cand_jid not in self.agent.known_candidates or cand_jid in self.agent.eliminated_candidates:
                    continue
                
                # --- PARSING DA INTENÇÃO E DADOS ---
                action = intent_data.get("action", "NEWS")
                perf = action # Performative (NEWS/FAKENEWS)
                cand_short = get_sender_name(cand_jid)
                tick_intent = intent_data.get("tick", self.agent._tick) # Usa o tick da intenção ou o tick atual
                
                # 3. Lógica de RL (Estado)
                cand_state = self.agent._get_budget_state(cand_jid)
                budget = self.agent.candidate_budgets.get(cand_jid, 0)
                
                # 4. Lógica de Economia e Custo
                if perf == "NEWS":
                    custo_alvo = COST_NEWS_PER_TARGET
                    multa = 0
                else:
                    custo_alvo = COST_FAKENEWS_PER_TARGET
                    multa = PENALTY_PER_FAKENEWS
                
                # Checagem de Orçamento
                if budget <= 0:
                    print(f"[{str(get_sender_name(self.agent.jid)).upper()}] CUSTO_CAMPANHA: cand={cand_short}, Budget insuficiente ({budget:.2f}). Envio cancelado.")
                    continue
                
                # Efeito Viral (Targets)
                targets = random.sample(self.agent.voter_jids, max(1, int(0.4 * len(self.agent.voter_jids))))
                targets_to_send = targets[:]
                extra_targets = []
                
                base_prob = VIRAL_BASE_PROB
                if perf == "FAKENEWS": base_prob *= 1.5
                else: base_prob *= 0.7

                if random.random() < base_prob:
                    remaining = [v for v in self.agent.voter_jids if v not in targets]
                    if remaining:
                        k_extra = min(VIRAL_MAX_EXTRA_TARGETS, len(remaining))
                        extra_targets = random.sample(remaining, k_extra)
                        targets_to_send.extend(extra_targets)
                        print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CAMPANHA VIRAL: cand={cand_short}, perf={perf}, alvos={len(targets_to_send)} (extra={len(extra_targets)})")
                
                # Lógica de budget vs targets_to_send
                max_targets = len(targets_to_send)
                if budget < (custo_alvo * max_targets) + multa:
                    max_targets_calculados = budget // custo_alvo
                    if max_targets_calculados < max_targets: targets_to_send = targets_to_send[:max_targets_calculados]
                    if budget < (custo_alvo * len(targets_to_send)) + multa: targets_to_send = [] 
                
                if not targets_to_send:
                    print(f"[{str(get_sender_name(self.agent.jid)).upper()}] CUSTO_CAMPANHA: cand={cand_short}, Envio de {perf} cancelado. Fundos insuficientes para alvos + multa.")
                    continue

                # Calcular custo real
                custo_total = len(targets_to_send) * custo_alvo
                
                # 5. ATUALIZAÇÃO DO BUDGET LOCAL DA MÍDIA
                self.agent.candidate_budgets[cand_jid] -= (custo_total + multa)
                
                # Flag para RL Update
                punished_in_authority = (perf == "FAKENEWS" and random.random() < P_DETECT_BASE) 
                
                # 6. ENVIO E DENÚNCIA
                count = await self.agent.broadcast_to_voters(
                    cand_short=cand_short,
                    action=action,
                    targets=targets_to_send,
                    tick=tick_intent,
                    beh=self
                )
                
                # Log de Denúncia (mantido)
                if perf == "FAKENEWS":
                    report_msg = Message(to=str(self.agent.authority_jid))
                    report_msg.set_metadata("protocol", PROTOCOL_PUNISH)
                    report_msg.set_metadata("performative", "inform")
                    report_msg.body = json.dumps({"candidate": cand_jid, "type": "FAKENEWS", "tick": self.agent._tick})
                    await self.send(report_msg)
                
                # 7. CÁLCULO DA RECOMPENSA E ATUALIZAÇÃO Q
                total_voters = len(self.agent.voter_jids) if self.agent.voter_jids else 1
                coverage = count / float(total_voters) 
                cost_norm = (custo_total + multa) / float(CANDIDATE_INITIAL_BUDGET)
                reward = coverage - RL_LAMBDA_COST * cost_norm

                next_state = self.agent._get_budget_state(cand_jid)
                
                self.agent._update_q(cand_jid, cand_state, action, reward, next_state, punished=punished_in_authority)
                
                # 8. ATUALIZAÇÃO ESTATÍSTICA (CRÍTICO: Incrementa os contadores)
                if perf == "NEWS":
                    self.agent._stats_news_sent_total += count
                    self.agent._stats_per_candidate[cand_jid]["NEWS"] += count
                else:
                    self.agent._stats_fakenews_sent_total += count
                    self.agent._stats_per_candidate[cand_jid]["FAKE"] += count

                # 9. LOGAR CUSTO
                print(
                    f"[{str(get_sender_name(self.agent.jid)).upper()}] CUSTO_CAMPANHA: "
                    f"cand={cand_short}, tipo={perf}, enviados={count}, "
                    f"custo={custo_total}, multa={multa}, restante={self.agent.candidate_budgets.get(cand_jid, 0):.2f}"
                )
                
                executed_any_campaign = True

            # 10. Limpar intenções (CRÍTICO: Limpa todas as intenções processadas neste TICK)
            self.agent.campaign_intents.clear() 
            self.agent._cand_idx = 0 

            # Garante que o Broadcaster durma um tick
            await asyncio.sleep(TICK_DURATION)

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Mídia iniciado (com Q-Learning).")
        
        # 1. Listener de Simulação (TICKs/ANNOUNCE) 
        template_sim = Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        self.add_behaviour(self.SimListener(), template_sim) 
        
        # 2. Broadcaster de Campanha
        self.add_behaviour(self.Broadcaster())
        
        # 3. Listener de Eliminação
        template_elim = Template(metadata={"protocol": PROTOCOL_ELIMINATION})
        self.add_behaviour(self.EliminationListener(), template_elim)
        
        # 4. Listener de Intenção de Campanha
        tpl_intent = Template(metadata={"protocol": PROTOCOL_CAMPAIGN_INTENT})
        self.add_behaviour(self.CandidateCampaignReceiver(), tpl_intent)