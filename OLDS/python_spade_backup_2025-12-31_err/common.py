# python_spade/common.py
import random

# ----------------- Infra -----------------
SERVER = "localhost"
PASSWORD = "secret"

# Prefixos para JIDs
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
PROTOCOL_INIT_SIM           = "SIM_INIT"
PROTOCOL_CAMPAIGN           = "CAMPAIGN"
PROTOCOL_PUNISH             = "PUNISH"
PROTOCOL_VOTING             = "VOTING"
PROTOCOL_VOTE               = "VOTE"
PROTOCOL_RESULTS            = "RESULTS"
PROTOCOL_ELIMINATION        = "ELIMINATION"

# ----------------- Configurações de Tempo -----------------
TOTAL_TICKS = 51  # T51 é o dia da eleição
TICK_DURATION = 0.5 # Segundos por tick para estabilidade
N_CITIZENS = 10
N_SEATS = 3  # Número de cadeiras para o método D'Hondt

# ----------------- Experiment: NEWS vs FAKENEWS -----------------
# Configurações do "tratamento" controlado
EXPERIMENT_MODE = "NEWS_VS_FAKE"
MEDIA_NEWS_RATE = 0.7        # Probabilidade de enviar NEWS
MEDIA_FAKE_RATE = 0.3        # Probabilidade de enviar FAKENEWS

NEWS_IMPACT = 0.05           # Impacto ideológico moderador de NEWS
FAKE_IMPACT = 0.12           # Impacto ideológico radicalizador de FAKENEWS

TRUST_SENSITIVITY = 1.0      # Peso da confiança na mídia
P_DETECT_BASE = 0.2          # Probabilidade da autoridade detectar Fake News

# ----------------- Fadiga e Abstenção -----------------
# Parâmetros para análise de participação eleitoral
CAMPAIGN_TARGET_FRACTION = 0.4    # Fração da população alvo por broadcast
OVERLOAD_PER_NEWS = 1             # Custo de sobrecarga para notícias reais
OVERLOAD_PER_FAKE = 2             # Fake news sobrecarregam mais o eleitor
ENGAGEMENT_DECAY_PER_OVERLOAD = 0.02 # Redução de engajamento por ponto de overload
ABSTENTION_THRESHOLD = 0.30       # Limite abaixo do qual o eleitor se abstém

# ----------------- Partidos e Ideologias -----------------
# Escala de ideologia definida entre [-2..+2]
PARTIES = {
    "PED": {"name": "Extrema Direita", "ideology":  2},
    "PDD": {"name": "Direita",          "ideology":  1},
    "PCE": {"name": "Centro",           "ideology":  0},
    "PDE": {"name": "Esquerda",         "ideology": -1},
    "PEE": {"name": "Extrema Esquerda", "ideology": -2},
    "SPD": {"name": "Sem Partido",      "ideology":  0},
}

ALL_PARTIES = list(PARTIES.keys())

# Distribuição fixa para análise científica controlada
VOTER_PARTY_COUNTS = {
    "PED": 4,
    "PDD": 4,
    "PCE": 1,
    "PDE": 1,
}

def build_fixed_party_sequence(
    n: int,
    party_counts: dict,
    *,
    shuffle: bool = True,
    seed: int | None = None,
    fill_party: str = "SPD",
) -> list[str]:
    """
    Gera uma sequência de partidos com validações para o experimento.
    """
    if fill_party not in ALL_PARTIES:
        raise ValueError(f"fill_party '{fill_party}' não existe em ALL_PARTIES.")

    sequence = []
    
    for party, count in party_counts.items():
        if count < 0:
            raise ValueError(f"Contagem para {party} não pode ser negativa.")
        if party not in ALL_PARTIES:
            raise ValueError(f"Partido '{party}' é inválido.")
        sequence.extend([party] * count)

    if len(sequence) > n:
        raise ValueError(f"Soma de partidos ({len(sequence)}) excede N_CITIZENS ({n}).")

    # Preenche o restante com o partido default (SPD)
    if len(sequence) < n:
        sequence.extend([fill_party] * (n - len(sequence)))

    if shuffle:
        random.Random(seed).shuffle(sequence)

    return sequence[:n]