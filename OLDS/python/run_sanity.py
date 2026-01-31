import sys
from pathlib import Path

# .../election_sim
ROOT = Path(__file__).resolve().parents[1]
# add .../election_sim/python to sys.path
sys.path.append(str((ROOT / "python").as_posix()))

from election_sim.prolog_bridge import PrologBridge
from election_sim.network_setup import make_population, make_small_world_graph, summarize_population

def main():
    print("== Sanity: Prolog + Population ==")
    pl = PrologBridge()
    aff = pl.affinity("pdd", "pde")
    print(f"Affinity(pdd,pde) = {aff:.3f}")
    can = pl.can_switch("pdd", "pce")
    print(f"can_switch(pdd->pce) = {can}")
    s1 = pl.update_support(0.4, aff, +1, 0.7)
    print(f"update_support from 0.4 with tone=+1, rep=0.7 => {s1:.3f}")
    tprob = pl.turnout(0.5, 0.6, 0.2)
    print(f"turnout(base=0.5, involvement=0.6, fatigue=0.2) = {tprob:.3f}")

    pop = make_population(1000)
    G = make_small_world_graph(1000)
    counts = summarize_population(pop)
    print("Initial party counts:", counts)

    a1_neighbors = list(G.neighbors("A0001"))[:5]
    print("A0001 neighbors (first 5):", a1_neighbors)

if __name__ == "__main__":
    main()