import random
import networkx as nx
from collections import Counter

PARTIES = ["ped", "pdd", "pce", "pde", "pee", "spd"]

INITIAL_COUNTS = {
    "ped": 241,
    "pdd": 374,
    "pce": 10,
    "pde": 303,
    "pee": 31,
    "spd": 41,
}

def make_population(n=1000, seed=42):
    random.seed(seed)
    pop_list = []
    for p, c in INITIAL_COUNTS.items():
        pop_list += [p] * c
    assert len(pop_list) == n
    random.shuffle(pop_list)
    ids = [f"A{idx:04d}" for idx in range(1, n+1)]
    population = {aid: {"party": party} for aid, party in zip(ids, pop_list)}
    return population

def make_small_world_graph(n=1000, k=6, p=0.1, seed=42):
    G = nx.watts_strogatz_graph(n, k, p, seed=seed)
    mapping = {i: f"A{i+1:04d}" for i in range(n)}
    return nx.relabel_nodes(G, mapping)

def summarize_population(pop):
    return dict(Counter(v["party"] for v in pop.values()))