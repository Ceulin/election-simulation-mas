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
PROTOCOL_VOTING             = "VOTING"              # sup -> voters (REQUEST_VOTE) ; sup -> authority (START_COUNT)
PROTOCOL_VOTE               = "VOTE"                # voters -> authority
PROTOCOL_RESULTS            = "RESULTS"             # authority -> sup

# ----------------- Tempo e Config -----------------
TOTAL_TICKS = 51  # 0..51 (T51 = eleição)
TICK_DURATION = 0.5 # Aumentado para 0.5s para maior estabilidade
N_CITIZENS = 10
N_CANDIDATES_TO_PROMOTE = 3

# ----------------- Partidos -----------------
# ideologia em [-2..+2]
PARTIES = {
    "PED": {"name": "Extrema Direita", "ideology":  2},
    "PDD": {"name": "Direita",          "ideology":  1},
    "PCE": {"name": "Centro",           "ideology":  0},
    "PDE": {"name": "Esquerda",         "ideology": -1},
    "PEE": {"name": "Extrema Esquerda", "ideology": -2},
    "SPD": {"name": "Sem Partido",      "ideology":  0},
}

ALL_PARTIES = list(PARTIES.keys())

def random_party() -> str:
    # Distribuição não-uniforme
    weights = [0.18, 0.22, 0.18, 0.22, 0.15, 0.05]
    return random.choices(ALL_PARTIES, weights=weights, k=1)[0]