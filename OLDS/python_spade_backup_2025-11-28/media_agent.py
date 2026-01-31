# python_spade/media_agent.py
import asyncio, random
import spade
import json
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict, Any, List, Set

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
    PARTIES, # Necessário para a Lógica Partidária
    # Constantes de Relatório e Viral
    REPORT_TICKS,
    VIRAL_BASE_PROB,
    VIRAL_IMPACT_THRESHOLD,
    VIRAL_MAX_EXTRA_TARGETS,
    # Constantes de Viés
    MEDIA_IDEOLOGY_BIAS,
    MEDIA_BIAS_STRENGTH,
    N_CITIZENS, # Necessário para viral
)

# Tentativa de importação de P_DETECT_BASE do common
try:
    from common import P_DETECT_BASE 
except ImportError:
    P_DETECT_BASE = 0.7


# Constante para o protocolo de denúncia 
PROTOCOL_MEDIA_REPORT = "MEDIA_REPORT" 
PROTOCOL_ELIMINATION = "ELIMINATION" # Protocolo para receber notificação da Authority

class MediaAgent(spade.agent.Agent):
    """
    Agente Mídia: Implementa Q-Learning, Viés Ideológico, Efeito Viral,
    e Respeita candidatos eliminados.
    """

    def __init__(self, jid, password, supervisor_jid: str, voter_jids: list, authority_jid: str, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.supervisor_jid = supervisor_jid
        self.authority_jid = authority_jid
        self.voter_jids = voter_jids              
        self.known_candidates: List[str] = [] # JIDs completos
        self._tick = 0
        self._cand_idx = 0               

        # CAMPOS DO AGENTE
        self.candidate_budgets: Dict[str, float] = {} 
        self.q_values: Dict[str, Dict[str, Dict[str, float]]] = {} 
        self.candidate_party_map: Dict[str, str] = {} # Para lógica RL Partidária
        self.eliminated_candidates: Set[str] = set() # Candidatos eliminados

        # ATRIBUTOS DE ESTATÍSTICA 
        self._stats_news_sent_total: int = 0
        self._stats_fakenews_sent_total: int = 0
        self._stats_per_candidate: Dict[str, Dict[str, int]] = {}
        self._printed_stats: bool = False

    # =========================================================
    # FUNÇÕES AUXILIARES DE REINFORCEMENT LEARNING E VIÉS (TAREFA 6)
    # =========================================================
    def _ideological_weight(self, cand_jid: str) -> float:
        """Calcula o peso ideológico da Mídia sobre o candidato (TAREFA 6)."""
        party = self.candidate_party_map.get(cand_jid, "SPD")
        party_ideology = PARTIES.get(party, {}).get("ideology", 0)

        bias = MEDIA_IDEOLOGY_BIAS.upper()
        strength = MEDIA_BIAS_STRENGTH

        if bias == "NEUTRAL" or strength <= 0.0:
            return 1.0

        # Mapeia viés para direção numérica
        if bias == "LEFT":
            media_side = -1
        elif bias == "FAR_LEFT":
            media_side = -2
        elif bias == "RIGHT":
            media_side = 1
        elif bias == "FAR_RIGHT":
            media_side = 2
        elif bias == "CENTER":
            media_side = 0
        else:
            media_side = 0

        # Se sinais coincidem (ou ambos centro), favorece; se opostos, penaliza
        sign_match = (media_side * party_ideology)
        if sign_match > 0:
            return 1.0 + strength          # favorece
        elif sign_match < 0:
            return 1.0 - strength          # prejudica
        else:
            return 1.0

    def _get_budget_state(self, cand_jid: str) -> str:
        """Mapeia o orçamento restante para um estado discreto (HIGH, MID, LOW)."""
        budget = self.candidate_budgets.get(cand_jid, 0.0)
        ratio = budget / float(CANDIDATE_INITIAL_BUDGET)
        if ratio >= 0.7:
            return "HIGH"
        elif ratio >= 0.3:
            return "MID"
        else:
            return "LOW"

    def _select_action(self, cand_jid: str, state: str) -> str:
        """Implementa a política ε-greedy para escolher NEWS ou FAKENEWS."""
        
        # Garante Q-Value
        if cand_jid not in self.q_values:
            self.q_values[cand_jid] = {
                "HIGH": {"NEWS": 0.0, "FAKENEWS": 0.0},
                "MID":  {"NEWS": 0.0, "FAKENEWS": 0.0},
                "LOW":  {"NEWS": 0.0, "FAKENEWS": 0.0},
            }
        
        if state not in self.q_values[cand_jid]:
             self.q_values[cand_jid][state] = {"NEWS": 0.0, "FAKENEWS": 0.0}

        if random.random() < RL_EPSILON:
            return random.choice(["NEWS", "FAKENEWS"])
            
        q_state = self.q_values[cand_jid][state]
        if q_state["NEWS"] >= q_state["FAKENEWS"]:
            return "NEWS"
        else:
            return "FAKENEWS"

    def _update_q(self, cand_jid: str, state: str, action: str, 
                  reward: float, next_state: str, punished: bool = False) -> None:
        """
        Aplica a equação de Bellman para atualizar o Q-Value.
        TAREFA 3.4: Ajuste do Q-value por tipo de partido após punição.
        """
        
        if cand_jid not in self.q_values: return 
        
        q_s_a = self.q_values[cand_jid][state][action]
        next_qs = self.q_values[cand_jid][next_state]
        max_next = max(next_qs["NEWS"], next_qs["FAKENEWS"])
        
        # TAREFA 6.3: Aplica peso ideológico à recompensa
        weight = self._ideological_weight(cand_jid)
        biased_reward = reward * weight
        
        # Equação de Bellman (Q-Learning)
        updated = q_s_a + RL_ALPHA * (biased_reward + RL_GAMMA * max_next - q_s_a)
        
        # TAREFA 3.4: REAÇÃO PARTIDÁRIA APÓS PUNIÇÃO 
        if punished and action == "FAKENEWS":
            party = self.candidate_party_map.get(cand_jid, "SPD")
            
            if party in {"PDD", "PDE", "PCE"}: # Moderados
                updated *= 0.5
                print(f"[{str(get_sender_name(self.jid)).upper()}] RL_PARTIDÁRIO: Moderado {party} ajustado (x0.5).")
            elif party in {"PED", "PEE"}: # Extremos
                updated *= 0.9
                print(f"[{str(get_sender_name(self.jid)).upper()}] RL_PARTIDÁRIO: Extremo {party} ajustado (x0.9).")


        self.q_values[cand_jid][state][action] = updated
        
        # Log de atualização para debug
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
            if not msg: 
                return
            
            md = msg.metadata or {}
            if md.get("protocol") != PROTOCOL_INIT_SIM:
                return

            body = (msg.body or "").strip()
            
            # 1. Processa TICK
            if body.startswith("TICK_"):
                try:
                    self.agent._tick = int(body.split("_")[1])
                except Exception:
                    pass
            
            # 2. Processa ANNOUNCE de Candidatos (TAREFA 6.1: Armazenar Partido)
            elif "CANDIDATES_ANNOUNCED" in body:
                try:
                    jids = []; parties = []
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="):
                            jids = [c for c in part.split("=", 1)[1].strip().split(",") if c]
                        elif part.startswith("CANDIDATE_PARTIES="): # Lendo partidos
                            parties = [p for p in part.split("=", 1)[1].strip().split(",") if p]
                    
                    self.agent.known_candidates = jids
                    self.agent.candidate_party_map = dict(zip(jids, parties)) # TAREFA 6.1
                                
                    # Inicializa Orçamento, Estatísticas e Q-values
                    for cand_jid in self.agent.known_candidates:
                        self.agent.candidate_budgets[cand_jid] = CANDIDATE_INITIAL_BUDGET
                        self.agent._stats_per_candidate[cand_jid] = {"NEWS": 0, "FAKE": 0}
                        self.agent.q_values[cand_jid] = {
                            "HIGH": {"NEWS": 0.0, "FAKENEWS": 0.0},
                            "MID":  {"NEWS": 0.0, "FAKENEWS": 0.0},
                            "LOW":  {"NEWS": 0.0, "FAKENEWS": 0.0},
                        }

                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos e Orçamentos inicializados: {len(self.agent.known_candidates)}")
                except Exception:
                    pass
    
    class EliminationListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.2)
            if not msg:
                return
            
            protocol = msg.get_metadata("protocol")
            if protocol == PROTOCOL_ELIMINATION:
                cand_jid = msg.body or ""
                self.agent.eliminated_candidates.add(cand_jid)
                
                # CORREÇÃO: Converte JID para string antes de usar get_sender_name e upper()
                sender_name = get_sender_name(str(self.agent.jid))
                cand_name = get_sender_name(str(cand_jid))
                
                print(f"[{sender_name.upper()}] ALERTA DE ELIMINAÇÃO: Candidato {cand_name.upper()} removido do pool de campanha.")
    
    # CORREÇÃO DO BUG: Remover template= do receive
    class JournalisticReport(CyclicBehaviour):
        async def run(self):
            # Removida criação de template (tpl = Template()...)
            # Substituída a linha self.receive(template=tpl, timeout=0.2)
            msg = await self.receive(timeout=0.2) 
            if msg is None:
                return
            
            body = (msg.body or "").strip()
            tick = self.agent._tick # Usa o tick atual
            
            if "REQUEST_REPORT" in body:
                
                # Encontra o candidato com maior exposição
                leader = max(self.agent._stats_per_candidate.items(), 
                             key=lambda item: item[1]['NEWS'] + item[1]['FAKE'], 
                             default=(None, {'NEWS': 0, 'FAKE': 0}))
                
                cand_jid, data = leader
                cand_label = get_sender_name(cand_jid).upper() if cand_jid else "NENHUM"

                # Lógica de relatórios simplificada
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}][REL_T{tick}] "
                      f"Até agora: NEWS={self.agent._stats_news_sent_total}, FAKE={self.agent._stats_fakenews_sent_total}.")
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}][REL_T{tick}] "
                      f"Líder em exposição: {cand_label} (NEWS={data['NEWS']}, FAKE={data['FAKE']}).")
                

    class Broadcaster(CyclicBehaviour):
        async def run(self):
            # Lógica de fim de campanha e resumo estatístico mantida
            if self.agent._tick > 50 and not self.agent._printed_stats:
                
                # ... (logs de estatística final)
                
                # Log Q-Values ao final da simulação para análise de aprendizado
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

            if not self.agent.voter_jids or not self.agent.known_candidates:
                await asyncio.sleep(TICK_DURATION)
                return

            # Alvo de campanha: JID completo do candidato
            cand_jid = self.agent.known_candidates[self.agent._cand_idx % len(self.agent.known_candidates)]
            self.agent._cand_idx += 1
            
            # TAREFA 3.3: Ignorar candidatos eliminados
            if cand_jid in self.agent.eliminated_candidates:
                await asyncio.sleep(TICK_DURATION * 0.1) # Pequeno sleep para evitar loop
                return

            # 2. SUBSTITUIÇÃO DA LÓGICA DE ESCOLHA PELO RL
            
            cand_state = self.agent._get_budget_state(cand_jid)
            action = self.agent._select_action(cand_jid, cand_state)
            perf = action # "NEWS" ou "FAKENEWS"
            
            # 3. Lógica de Economia e Custo
            
            if perf == "NEWS":
                custo_alvo = COST_NEWS_PER_TARGET
                multa = 0
            else: # FAKENEWS
                custo_alvo = COST_FAKENEWS_PER_TARGET
                multa = PENALTY_PER_FAKENEWS
            
            cand_short = get_sender_name(cand_jid)
            budget = self.agent.candidate_budgets.get(cand_jid, 0)
            
            # Checagem de Orçamento
            # ... (Lógica de budget)

            # Efeito Viral (TAREFA 5)
            targets = random.sample(self.agent.voter_jids, max(1, int(0.4 * len(self.agent.voter_jids)))) # Amostra base (40%)
            targets_to_send = targets[:]
            extra_targets = []
            
            # Heurística viral
            base_prob = VIRAL_BASE_PROB
            if perf == "FAKENEWS":
                base_prob *= 1.5
            else:
                base_prob *= 0.7

            if random.random() < base_prob:
                remaining = [v for v in self.agent.voter_jids if v not in targets]
                if remaining:
                    k_extra = min(VIRAL_MAX_EXTRA_TARGETS, len(remaining))
                    extra_targets = random.sample(remaining, k_extra)
                    targets_to_send.extend(extra_targets)
                    print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CAMPANHA VIRAL: cand={cand_short}, perf={perf}, alvos={len(targets_to_send)} (extra={len(extra_targets)})")
            
            # Lógica de budget vs targets_to_send (Atualizada)
            # ... (Lógica de budget para targets_to_send)
            
            # Se targets_to_send vazio, retorna
            if not targets_to_send:
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CUSTO_CAMPANHA: cand={cand_short}, Envio de {perf} cancelado. Fundos insuficientes.")
                await asyncio.sleep(TICK_DURATION)
                return

            # Calcular custo real
            custo_total = len(targets_to_send) * custo_alvo
            
            # 4. ATUALIZAÇÃO DO BUDGET
            self.agent.candidate_budgets[cand_jid] -= (custo_total + multa)
            
            # Flag para RL Update
            punished_in_authority = (perf == "FAKENEWS" and random.random() < P_DETECT_BASE) 
            
            # 5. ENVIO E DENÚNCIA (Usando targets_to_send)
            for v in targets_to_send:
                m = Message(to=v)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", perf)
                m.body = f"pitch:{cand_short};t={self.agent._tick}"
                await self.send(m)
                
            if perf == "FAKENEWS":
                # ... (Lógica de denúncia)
                
                # Lógica de Denúncia (Correta)
                report_msg = Message(to=str(self.agent.authority_jid))
                report_msg.set_metadata("protocol", PROTOCOL_PUNISH)
                report_msg.set_metadata("performative", "inform")
                report_msg.body = json.dumps({
                        "candidate": cand_jid,
                        "type": "FAKENEWS",
                        "tick": self.agent._tick
                    })
                await self.send(report_msg)
            
            # 6. CÁLCULO DA RECOMPENSA E ATUALIZAÇÃO Q
            total_voters = len(self.agent.voter_jids) if self.agent.voter_jids else 1
            coverage = len(targets_to_send) / float(total_voters)
            cost_norm = (custo_total + multa) / float(CANDIDATE_INITIAL_BUDGET)
            reward = coverage - RL_LAMBDA_COST * cost_norm

            next_state = self.agent._get_budget_state(cand_jid)
            
            # Passa o flag de punição para a função de update (TAREFA 3.4)
            self.agent._update_q(cand_jid, cand_state, action, reward, next_state, punished=punished_in_authority)
            
            # 7. ATUALIZAÇÃO ESTATÍSTICA (MANTIDA)
            count = len(targets_to_send)
            if perf == "NEWS":
                self.agent._stats_news_sent_total += count
                self.agent._stats_per_candidate[cand_jid]["NEWS"] += count
            else:
                self.agent._stats_fakenews_sent_total += count
                self.agent._stats_per_candidate[cand_jid]["FAKE"] += count

            # 8. LOGAR CUSTO (MANTIDO)
            print(
                f"[{str(get_sender_name(str(self.agent.jid))).upper()}] CUSTO_CAMPANHA: "
                f"cand={cand_short}, tipo={perf}, enviados={len(targets_to_send)}, "
                f"custo={custo_total}, multa={multa}, restante={self.agent.candidate_budgets[cand_jid]:.2f}"
            )

            await asyncio.sleep(TICK_DURATION) 

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Mídia iniciado (com Q-Learning).")
        
        template_sim = Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        self.add_behaviour(self.SimListener(), template_sim) 
        
        self.add_behaviour(self.Broadcaster())
        
        # CORREÇÃO DO BUG: Criação do Template aqui e associação
        tpl_report = Template()
        tpl_report.set_metadata("protocol", PROTOCOL_CAMPAIGN)
        tpl_report.set_metadata("performative", "inform")
        tpl_report.set_metadata("stage", "MEDIA_REPORT")
        self.add_behaviour(self.JournalisticReport(), tpl_report)
        
        # TAREFA 3.3: Listener de Eliminação
        template_elim = Template(metadata={"protocol": PROTOCOL_ELIMINATION})
        self.add_behaviour(self.EliminationListener(), template_elim)