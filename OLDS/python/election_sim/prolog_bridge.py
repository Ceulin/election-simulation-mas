from pathlib import Path
from pyswip import Prolog

class PrologBridge:
    def __init__(self):
        # .../PROJ/election_sim
        base = Path(__file__).resolve().parents[2]
        self.prolog = Prolog()
        bm = base / "prolog" / "belief_model.pl"
        tr = base / "prolog" / "transitions.pl"
        self.prolog.consult(str(bm.as_posix()))
        self.prolog.consult(str(tr.as_posix()))

    def affinity(self, voter_party: str, cand_party: str) -> float:
        q = f"affinity({voter_party},{cand_party},A)."
        res = list(self.prolog.query(q))
        return float(res[0]["A"]) if res else 0.0

    def can_switch(self, p_from: str, p_to: str) -> bool:
        q = f"can_switch({p_from},{p_to})."
        return bool(list(self.prolog.query(q)))

    def update_support(self, s0: float, aff: float, tone: int, rep: float) -> float:
        q = f"update_support({s0},{aff},{tone},{rep},S1)."
        res = list(self.prolog.query(q))
        return float(res[0]["S1"]) if res else s0

    def turnout(self, base: float, inv: float, fat: float) -> float:
        q = f"turnout({base},{inv},{fat},T)."
        res = list(self.prolog.query(q))
        return float(res[0]["T"]) if res else base