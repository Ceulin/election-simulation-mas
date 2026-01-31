# python_spade/media_agent.py
import asyncio, random
import spade
import json
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict, Any, List

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
    RL_LAMBDA_COST
)

# Constante para o protocolo de denúncia (uso interno da Mídia)
PROTOCOL_MEDIA_REPORT = "MEDIA_REPORT" 

class MediaAgent(spade.agent.Agent):
    """
    Agente Mídia: Implementa Q-Learning para otimizar a campanha (NEWS/FAKENEWS)
    com base no orçamento restante.
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
        self.candidate_budgets: Dict[str, float] = {} # JID -> Budget
        self.q_values: Dict[str, Dict[str, Dict[str, float]]] = {} # JID -> {State: {Action: Q}}

        # ATRIBUTOS DE ESTATÍSTICA 
        self._stats_news_sent_total: int = 0
        self._stats_fakenews_sent_total: int = 0
        self._stats_per_candidate: Dict[str, Dict[str, int]] = {}
        self._printed_stats: bool = False

    # =========================================================
    # FUNÇÕES AUXILIARES DE REINFORCEMENT LEARNING
    # =========================================================
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
        
        # Garante que a estrutura Q-Value para o candidato/estado exista
        if cand_jid not in self.q_values:
            self.q_values[cand_jid] = {
                "HIGH": {"NEWS": 0.0, "FAKENEWS": 0.0},
                "MID":  {"NEWS": 0.0, "FAKENEWS": 0.0},
                "LOW":  {"NEWS": 0.0, "FAKENEWS": 0.0},
            }
        
        if state not in self.q_values[cand_jid]:
             self.q_values[cand_jid][state] = {"NEWS": 0.0, "FAKENEWS": 0.0}

        if random.random() < RL_EPSILON:
            # EXPLORAÇÃO (Escolhe aleatoriamente)
            return random.choice(["NEWS", "FAKENEWS"])
            
        # EXPLORAÇÃO GULOSA (Escolhe a ação com o maior Q-Value)
        q_state = self.q_values[cand_jid][state]
        if q_state["NEWS"] >= q_state["FAKENEWS"]:
            return "NEWS"
        else:
            return "FAKENEWS"

    def _update_q(self, cand_jid: str, state: str, action: str, 
                  reward: float, next_state: str) -> None:
        """Aplica a equação de Bellman para atualizar o Q-Value."""
        
        # Garante que a estrutura exista
        if cand_jid not in self.q_values: return 
        
        # Obtém Q(s, a)
        q_s_a = self.q_values[cand_jid][state][action]
        
        # Obtém max Q(s', a')
        next_qs = self.q_values[cand_jid][next_state]
        max_next = max(next_qs["NEWS"], next_qs["FAKENEWS"])
        
        # Equação de Bellman (Q-Learning)
        updated = q_s_a + RL_ALPHA * (reward + RL_GAMMA * max_next - q_s_a)
        
        self.q_values[cand_jid][state][action] = updated
        
        # Log de atualização para debug (JID para string)
        agent_name_upper = str(get_sender_name(self.jid)).upper()
        cand_name_short = str(get_sender_name(cand_jid))

        print(
            f"[{agent_name_upper}] RL_UPDATE: cand={cand_name_short}, state='{state}', "
            f"action='{action}', reward={reward:.4f}, Q_new={updated:.4f}, next_state='{next_state}'"
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
            
            # 2. Processa ANNOUNCE de Candidatos
            elif "CANDIDATES_ANNOUNCED" in body:
                try:
                    for part in body.split(";"):
                        if part.startswith("CANDIDATES="):
                            raw = part.split("=", 1)[1].strip()
                            if raw:
                                self.agent.known_candidates = [c for c in raw.split(",") if c]
                                
                                # Inicializa Orçamento e Estatísticas
                                for cand_jid in self.agent.known_candidates:
                                    self.agent.candidate_budgets[cand_jid] = CANDIDATE_INITIAL_BUDGET
                                    self.agent._stats_per_candidate[cand_jid] = {"NEWS": 0, "FAKE": 0}
                                    
                                    # Inicializa Q-values para todos estados/ações
                                    self.agent.q_values[cand_jid] = {
                                        "HIGH": {"NEWS": 0.0, "FAKENEWS": 0.0},
                                        "MID":  {"NEWS": 0.0, "FAKENEWS": 0.0},
                                        "LOW":  {"NEWS": 0.0, "FAKENEWS": 0.0},
                                    }

                                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Candidatos e Orçamentos inicializados: {len(self.agent.known_candidates)}")
                except Exception:
                    pass

    class Broadcaster(CyclicBehaviour):
        async def run(self):
            # Lógica de fim de campanha e resumo estatístico mantida
            if self.agent._tick > 50 and not self.agent._printed_stats:
                
                cand_summary = ", ".join([
                    f"{get_sender_name(jid).upper()}:{{'NEWS':{data['NEWS']}, 'FAKE':{data['FAKE']}}}"
                    for jid, data in self.agent._stats_per_candidate.items()
                ])

                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] STATS_CAMPANHA: "
                    f"NEWS_TOTAL={self.agent._stats_news_sent_total}, "
                    f"FAKE_TOTAL={self.agent._stats_fakenews_sent_total}"
                )
                print(
                    f"[{get_sender_name(str(self.agent.jid)).upper()}] STATS_POR_CANDIDATO: {cand_summary}"
                )
                
                # Log Q-Values ao final da simulação para análise de aprendizado
                q_log = {
                    get_sender_name(jid): {s: {a: q} for s, d in q_data.items() for a, q in d.items()} 
                    for jid, q_data in self.agent.q_values.items()
                }
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] Q_VALUES_FINAL: {q_log}")
                
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

            # 2. SUBSTITUIÇÃO DA LÓGICA DE ESCOLHA PELO RL
            
            # 2a. Definição de Estado e Ação
            cand_state = self.agent._get_budget_state(cand_jid)
            action = self.agent._select_action(cand_jid, cand_state)
            perf = action # "NEWS" ou "FAKENEWS"
            
            # Amostra de eleitores (40% da população)
            pop = max(1, int(0.4 * len(self.agent.voter_jids)))
            targets = random.sample(self.agent.voter_jids, pop)

            # 3. Lógica de Economia e Custo
            
            if perf == "NEWS":
                custo_alvo = COST_NEWS_PER_TARGET
                multa = 0
            else: # FAKENEWS
                custo_alvo = COST_FAKENEWS_PER_TARGET
                multa = PENALTY_PER_FAKENEWS
            
            cand_short = get_sender_name(cand_jid)
            budget = self.agent.candidate_budgets.get(cand_jid, 0)
            
            # Checagem de Orçamento (Budget <= 0 ou Budget < custo_alvo)
            if budget <= 0 or budget < custo_alvo:
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CUSTO_CAMPANHA: cand={cand_short}, Budget insuficiente ({budget:.2f}). Envio cancelado.")
                await asyncio.sleep(TICK_DURATION)
                return
            
            # Redução de alvos se orçamento insuficiente para todos
            max_targets = len(targets)
            targets_to_send = targets[:]
            
            if budget < (custo_alvo * max_targets) + multa:
                max_targets_calculados = budget // custo_alvo
                
                if max_targets_calculados < max_targets:
                     targets_to_send = targets_to_send[:max_targets_calculados]
                
                if budget < (custo_alvo * len(targets_to_send)) + multa:
                     targets_to_send = [] 

            if not targets_to_send:
                print(f"[{get_sender_name(str(self.agent.jid)).upper()}] CUSTO_CAMPANHA: cand={cand_short}, Envio de {perf} cancelado. Fundos insuficientes para {max_targets} alvos + multa.")
                await asyncio.sleep(TICK_DURATION)
                return

            # Calcular custo real
            custo_total = len(targets_to_send) * custo_alvo
            
            # 4. ATUALIZAÇÃO DO BUDGET
            self.agent.candidate_budgets[cand_jid] -= (custo_total + multa)
            
            # 5. ENVIO E DENÚNCIA (CORRIGIDA)
            for v in targets_to_send:
                m = Message(to=v)
                m.set_metadata("protocol", PROTOCOL_CAMPAIGN)
                m.set_metadata("performative", perf)
                m.body = f"pitch:{cand_short};t={self.agent._tick}"
                await self.send(m)
                
            if perf == "FAKENEWS":
                # CORREÇÃO CRÍTICA: Não passar protocol e performative para o construtor Message()
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
            self.agent._update_q(cand_jid, cand_state, action, reward, next_state)
            
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
                f"[{get_sender_name(str(self.agent.jid)).upper()}] CUSTO_CAMPANHA: "
                f"cand={cand_short}, tipo={perf}, enviados={len(targets_to_send)}, "
                f"custo={custo_total}, multa={multa}, restante={self.agent.candidate_budgets[cand_jid]:.2f}"
            )

            await asyncio.sleep(TICK_DURATION) 

    async def setup(self):
        print(f"[{get_sender_name(str(self.jid)).upper()}] Agente Mídia iniciado (com Q-Learning).")
        
        # 1. Listener de Simulação (TICKs/ANNOUNCE) 
        template_sim = Template(metadata={"protocol": PROTOCOL_INIT_SIM})
        self.add_behaviour(self.SimListener(), template_sim) 
        
        # 2. Broadcaster de Campanha
        self.add_behaviour(self.Broadcaster())