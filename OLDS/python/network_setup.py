# election_sim/python/network_setup.py
import networkx as nx
import random
import pandas as pd
from typing import Dict, List, Tuple
from election_sim.python_spade.common import N_CITIZENS # Deve ser alterado para 1000

# Parâmetros conforme o projeto (1000 habitantes)
N_FULL_CITIZENS = 1000
N_CANDIDATES = 100
K_NEIGHBORS = 3 # Vizinhos na rede small-world

# Distribuição ideológica inicial (usada para 1000 habitantes no projeto)
INITIAL_DISTRIBUTION = {
    'PED': 241,  # Extrema Direita (+2)
    'PDD': 374,  # Direita (+1)
    'PCE': 10,   # Centro (0)
    'PDE': 303,  # Esquerda (-1)
    'PEE': 31,   # Extrema Esquerda (-2)
    'SPD': 41,   # Sem Partido Definido (Neutro/Próximo de 0)
}

def generate_initial_data(n_citizens: int = N_FULL_CITIZENS, seed: int = 42) -> pd.DataFrame:
    """
    Gera o DataFrame inicial com atributos sociopolíticos para os eleitores.
    
    Atenção: A função usa a distribuição real (1000), mesmo que o SPADE esteja
    rodando com N_CITIZENS=5 no common.py para testes.
    """
    random.seed(seed)
    
    # 1. Atribuição de Ideologia
    ideologies = []
    # Cria a lista de ideologias baseada nas contagens
    for party, count in INITIAL_DISTRIBUTION.items():
        ideologies.extend([party] * count)
    
    # Se o número de eleitores for diferente de 1000 (ex: para testes)
    if len(ideologies) != N_FULL_CITIZENS:
        # Reduz ou aumenta o número de eleitores para coincidir com n_citizens
        # Aqui, estamos assumindo que para o teste, n_citizens DEVE ser 1000 ou 
        # a distribuição deve ser escalonada. Vamos forçar 1000 por enquanto.
        if n_citizens < N_FULL_CITIZENS:
             ideologies = random.sample(ideologies, n_citizens)
        elif n_citizens > N_FULL_CITIZENS:
            # Não deve acontecer, mas se acontecer, duplicamos aleatoriamente
            ideologies.extend(random.choices(ideologies, k=n_citizens - N_FULL_CITIZENS))

    random.shuffle(ideologies)

    data = {
        'jid': [f"a{i:04d}@localhost" for i in range(1, n_citizens + 1)],
        'ideology': ideologies,
        # Atributos Cognitivos/Emocionais (distribuição uniforme inicial)
        'fadiga': [random.uniform(0.1, 0.4) for _ in range(n_citizens)], # Baixa fadiga inicial
        'confianca_midia': [random.uniform(0.4, 0.8) for _ in range(n_citizens)],
        'etica': [random.uniform(0.5, 0.9) for _ in range(n_citizens)],
        'memoria': [2] * n_citizens, # Memória curta N=2
        'influencia': [random.uniform(0.1, 0.9) for _ in range(n_citizens)], # Potencial para ser candidato
    }
    
    df = pd.DataFrame(data)
    # Define o JID como índice
    df.set_index('jid', inplace=True) 
    return df


def create_social_network(citizens: List[str], k: int = K_NEIGHBORS, p: float = 0.1, seed: int = 42) -> nx.Graph:
    """
    Cria a rede social Small-World (modelo Watts-Strogatz).
    - k: vizinhos mais próximos (Grau médio ~ 2k)
    - p: probabilidade de religamento de arestas
    """
    G = nx.watts_strogatz_graph(n=len(citizens), k=k, p=p, seed=seed)
    
    # Mapeia os índices de volta para os JIDs dos agentes
    mapping = {i: jid for i, jid in enumerate(citizens)}
    G = nx.relabel_nodes(G, mapping)
    
    print(f"[NetworkX] Rede Small-World criada. N={G.number_of_nodes()}, E={G.number_of_edges()}")
    return G

def get_network_setup(n_citizens: int = N_FULL_CITIZENS, seed: int = 42) -> Tuple[pd.DataFrame, nx.Graph]:
    """Função principal para obter os dados iniciais e a rede."""
    # 1. Gera os dados
    df_citizens = generate_initial_data(n_citizens, seed)
    
    # 2. Cria a rede
    citizens_jids = df_citizens.index.tolist()
    G = create_social_network(citizens_jids, seed=seed)
    
    return df_citizens, G

# Exemplo de uso
if __name__ == '__main__':
    # Usando N=1000 para gerar os dados reais
    df_data, social_graph = get_network_setup(n_citizens=N_FULL_CITIZENS)
    
    print("\n--- Dados Iniciais (Amostra) ---")
    print(df_data.head())
    
    print("\n--- Estrutura da Rede ---")
    print(f"Vizinhos do a0001: {list(social_graph.neighbors('a0001@localhost'))}")
    # Nota: os JIDs precisam coincidir com o formato usado no common.py!