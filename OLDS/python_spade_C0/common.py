# python_spade/common.py
import random
from collections import Counter

# ----------------- Infra -----------------
SERVER = "localhost"
PASSWORD = "secret"

# Prefixes (JIDs)
SUPERVISOR_PREFIX = "supervisor"
AUTHORITY_PREFIX  = "authority"
MEDIA_PREFIX      = "media"
VOTER_PREFIX      = "voter"
CANDIDATE_PREFIX  = "candidate"


def generate_jid(prefix: str, i: int) -> str:
    """Gera um JID no formato prefix_i@server"""
    return f"{prefix}_{i}@{SERVER}"


def get_sender_name(jid: str) -> str:
    """Extrai apenas o prefixo_id do JID (ex: 'voter_1')"""
    try:
        return jid.split("@", 1)[0]
    except Exception:
        return jid


# ----------------- Protocolos -----------------
# Fases da Simulação e Comunicação
PROTOCOL_INIT_SIM            = "SIM_INIT"            # TICKs e ANNOUNCE de Candidatos
PROTOCOL_REQUEST_ENGAGEMENT  = "REQUEST_ENGAGEMENT"  # sup -> voters (T10)
PROTOCOL_RESPONSE_ENGAGEMENT = "RESPONSE_ENGAGEMENT" # voters -> sup (T10)
PROTOCOL_CAMPAIGN            = "CAMPAIGN"            # media/candidate -> voters
PROTOCOL_PUNISH              = "PUNISH"              # media -> authority (Denúncia)
PROTOCOL_VOTING              = "VOTING"              # sup -> voters ; sup -> authority (START_COUNT)
PROTOCOL_VOTE                = "VOTE"                # voters -> authority
PROTOCOL_RESULTS             = "RESULTS"             # authority -> sup
PROTOCOL_ELIMINATION         = "ELIMINATION"         # authority -> media (Eliminação de cand.)


# ----------------- Tempo e Config -----------------
TOTAL_TICKS = 51                # 0..51 (T51 = eleição)
TICK_DURATION = 2.5             # 0.5s em teste / 2.5s em simulação real
N_CITIZENS = 60                # 10 em teste / 60 em simulação real
N_CANDIDATES_TO_PROMOTE = 6    # 3 em teste / 6 em simulação real

# --- Sistema eleitoral ---
N_SEATS = 3  # número de cadeiras para o método D'Hondt

# --- Abstenção / Voto Nulo ---
P_BASE_ABSTAIN = 0.05           # probabilidade base de abstenção
P_BASE_NULL = 0.05              # probabilidade base de voto nulo
ENGAGEMENT_ABSTAIN_THRESHOLD = 0.20  # abaixo disso, abstenção sobe bastante


# --- Viés ideológico da mídia ---
# Valores possíveis: "LEFT", "RIGHT", "FAR_LEFT", "FAR_RIGHT", "CENTER", "NEUTRAL"
MEDIA_IDEOLOGY_BIAS = "CENTER"
MEDIA_BIAS_STRENGTH = 0.15  # 0.0 (=neutro) a ~0.3 (viés bem forte)


# --- Efeito viral ---
VIRAL_BASE_PROB = 0.15          # probabilidade base de viralizar
VIRAL_IMPACT_THRESHOLD = 0.18   # impacto mínimo para considerar um conteúdo “viralizável”
VIRAL_MAX_EXTRA_TARGETS = 2     # máximo de alvos extras na viralização


# --- Parâmetros Econômicos da Campanha ---
"""Constantes que definem custos, orçamentos e multas no ciclo eleitoral."""
CANDIDATE_INITIAL_BUDGET = 1000
COST_NEWS_PER_TARGET = 10
COST_FAKENEWS_PER_TARGET = 4
PENALTY_PER_FAKENEWS = 50


# --- Parâmetros de Reinforcement Learning (Q-Learning) ---
# Estes parâmetros serão usados pelo MediaAgent para aprender o mix ótimo de NEWS/FAKENEWS para cada candidato.
RL_EPSILON = 0.2       # probabilidade de exploração (escolher ação aleatória)
RL_ALPHA = 0.2         # taxa de aprendizado
RL_GAMMA = 0.9         # fator de desconto futuro
RL_LAMBDA_COST = 0.5   # peso do custo (campanha + multas) na função de recompensa


# --- Ticks de Relatório Jornalístico ---
REPORT_TICKS = [20, 30, 40, 50]


# --- Mix manual de NEWS/FAKENEWS na Mídia ---
# Estes valores são o "core" do experimento.
# Podem ser alterados livremente (0.0 a 1.0) e não precisam somar 1,
# pois serão normalizados na Mídia.
NEWS_RATIO = 0.70   # 70% NEWS
FAKE_RATIO = 0.30   # 30% FAKENEWS

# Quando True, a Mídia usa (NEWS_RATIO, FAKE_RATIO) para decidir NEWS/FAKE.
# Quando False, a Mídia pode usar somente RL (Q-Learning) para escolher ações.
MEDIA_USE_MANUAL_RATIOS = True


# ----------------- Partidos -----------------
# ideologia em [-2, +2]
PARTIES = {
    "PED": {"name": "Extrema Direita",    "ideology":  2},
    "PDD": {"name": "Direita",            "ideology":  1},
    "PCE": {"name": "Centro",             "ideology":  0},
    "PDE": {"name": "Esquerda",           "ideology": -1},
    "PEE": {"name": "Extrema Esquerda",   "ideology": -2},
    "SPD": {"name": "Sem Partido",        "ideology":  0},
}

ALL_PARTIES = list(PARTIES.keys())

# ----------------- Distribuição Fixa de Eleitores por Partido -----------------
# Percentual MANUAL de eleitores para cada partido.
# Estes percentuais são o "alvo" da distribuição partidária inicial.
# Default solicitado:
#   PED 10%, PDD 15%, PCE 40%, PDE 15%, PEE 10%, SPD 10%
PARTY_PERCENTAGES = {
    "PED": 0.10,
    "PDD": 0.15,
    "PCE": 0.40,
    "PDE": 0.15,
    "PEE": 0.10,
    "SPD": 0.10,
}


def random_party() -> str:
    """
    Retorna um partido de acordo com os percentuais definidos em PARTY_PERCENTAGES.

    Observação:
      - A cada eleitor, o sorteio respeita os pesos fixados acima.
      - Em N_CITIZENS grandes, a distribuição tende a se aproximar dos percentuais.
    """
    parties = ALL_PARTIES
    weights = [PARTY_PERCENTAGES[p] for p in parties]
    return random.choices(parties, weights=weights, k=1)[0]


def compute_party_counts(n_citizens: int) -> Counter:
    """
    Função auxiliar opcional:
    Calcula um Counter com a distribuição esperada de eleitores por partido,
    arredondando para inteiros e ajustando o resto para somar n_citizens.

    Útil para logs em run_spade_sim.py, se quiser mostrar o plano teórico.
    """
    base_counts = {
        p: int(PARTY_PERCENTAGES[p] * n_citizens) for p in ALL_PARTIES
    }
    total_assigned = sum(base_counts.values())
    remaining = n_citizens - total_assigned

    # Ajusta o restante distribuindo 1 em 1 nos partidos com maior fração residual
    # (aqui usamos apenas a ordem de PARTIES; pode ser refinado se precisar).
    while remaining > 0:
        for p in ALL_PARTIES:
            if remaining <= 0:
                break
            base_counts[p] += 1
            remaining -= 1

    return Counter(base_counts)
