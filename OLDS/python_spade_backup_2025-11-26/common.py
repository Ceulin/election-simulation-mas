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
PROTOCOL_INIT_SIM           = "SIM_INIT"            # TICKs e ANNOUNCE de Candidatos
PROTOCOL_REQUEST_ENGAGEMENT = "REQUEST_ENGAGEMENT"  # sup -> voters (T10)
PROTOCOL_RESPONSE_ENGAGEMENT= "RESPONSE_ENGAGEMENT" # voters -> sup (T10)
PROTOCOL_CAMPAIGN           = "CAMPAIGN"            # media/candidate -> voters
PROTOCOL_PUNISH             = "PUNISH"              # media -> authority (Denúncia)
PROTOCOL_VOTING             = "VOTING"              # sup -> voters ; sup -> authority (START_COUNT)
PROTOCOL_VOTE               = "VOTE"                # voters -> authority
PROTOCOL_RESULTS            = "RESULTS"             # authority -> sup

# ----------------- Tempo e Config -----------------
TOTAL_TICKS = 51  # 0..51 (T51 = eleição)
TICK_DURATION = 0.5 # Aumentado para 0.5s para maior estabilidade
N_CITIZENS = 10 # 10 no TESTE / 1000 no REAL
N_CANDIDATES_TO_PROMOTE = 3 # 3 no TESTE / 100 no REAL

# ----------------- Partidos -----------------
# ideologia em [-2..+2]
PARTIES = {
    "PED": {"name": "Extrema Direita", "ideology":  2},
    "PDD": {"name": "Direita",          "ideology":  1},
    "PCE": {"name": "Centro",           "ideologia":  0},
    "PDE": {"name": "Esquerda",         "ideologia": -1},
    "PEE": {"name": "Extrema Esquerda", "ideologia": -2},
    "SPD": {"name": "Sem Partido",      "ideologia":  0},
}

ALL_PARTIES = list(PARTIES.keys())

def random_party() -> str:
    # Distribuição não-uniforme
    weights = [0.18, 0.22, 0.18, 0.22, 0.15, 0.05]
    return random.choices(ALL_PARTIES, weights=weights, k=1)[0]


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