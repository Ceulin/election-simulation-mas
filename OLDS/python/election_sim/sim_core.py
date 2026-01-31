from __future__ import annotations
import random
from pathlib import Path
from typing import Dict, Tuple, List
import pandas as pd
import networkx as nx
from collections import Counter

from .prolog_bridge import PrologBridge
from .network_setup import make_population, make_small_world_graph
from .nicknames import assign_nickname

AgentId = str
PARTIES = ["ped", "pdd", "pce", "pde", "pee", "spd"]

class SimState:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.pl = PrologBridge()
        self.pop: Dict[AgentId, dict] = make_population(1000, seed=seed)
        for aid in self.pop.keys():
            self.pop[aid].update({
                "support": 0.5,
                "involvement": self.rng.uniform(0.2, 0.6),
                "fatigue": self.rng.uniform(0.0, 0.2),
                "persuasion_cap": self.rng.uniform(0.0, 1.0),
                "nickname": None,
                "is_candidate": False,
            })
        self.G: nx.Graph = make_small_world_graph(1000, k=6, p=0.1, seed=seed)
        self.t = 0
        base = Path(__file__).resolve().parents[2]
        self.out_dir = base / "outputs"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "reports").mkdir(parents=True, exist_ok=True)

        # CAMPANHA
        self.candidates: List[AgentId] = []
        self.party_reputation: Dict[str, float] = {p: 0.5 for p in PARTIES}  # 0..1
        self.cand_reputation: Dict[AgentId, float] = {}
        self.cand_strategy: Dict[AgentId, dict] = {}
        self.message_log: List[dict] = []  # {t, sender, party, kind, detected, reach, keywords}

    # —————— PRE-CAMPAIGN T0–T10 ——————
    def tick_pre_campaign(self, K_local: int = 3):
        updates: List[Tuple[AgentId, float, float]] = []
        for aid, atr in self.pop.items():
            neighs = list(self.G.neighbors(aid))
            if not neighs:
                continue
            self.rng.shuffle(neighs)
            neighs = neighs[:K_local]
            s = atr["support"]
            fat = atr["fatigue"]
            my_party = atr["party"]
            for nb in neighs:
                nb_party = self.pop[nb]["party"]
                aff = self.pl.affinity(my_party, nb_party)  # 0..1
                tone = +1 if nb_party == my_party else 0
                rep = 0.4 + 0.6 * self.pop[nb]["involvement"]
                s = self.pl.update_support(s, aff, tone, rep)
                fat = min(1.0, fat + 0.02)
            inv = min(1.0, atr["involvement"] + 0.01 * len(neighs))
            updates.append((aid, s, fat))
            atr["involvement"] = inv
        for aid, ns, nf in updates:
            self.pop[aid]["support"] = ns
            self.pop[aid]["fatigue"] = nf
        self.t += 1

    def candidate_score(self, aid: AgentId) -> float:
        deg = self.G.degree(aid)
        cap = self.pop[aid]["persuasion_cap"]
        inv = self.pop[aid]["involvement"]
        return 0.60 * cap + 0.25 * (deg / 12.0) + 0.15 * inv

    def select_candidates_T10(self, n_candidates: int = 100, seed: int = 42):
        rng = self.rng
        scored = [(aid, self.candidate_score(aid)) for aid in self.pop.keys()]
        scored.sort(key=lambda x: x[1], reverse=True)
        chosen = [aid for aid, _ in scored[:n_candidates]]
        self.candidates = chosen
        for aid in chosen:
            self.pop[aid]["is_candidate"] = True
            if not self.pop[aid]["nickname"]:
                self.pop[aid]["nickname"] = assign_nickname(rng)
            self.cand_reputation[aid] = 0.6  # base > partido
            party = self.pop[aid]["party"]
            base_fake = {"ped": 0.25, "pdd": 0.15, "pce": 0.10, "pde": 0.15, "pee": 0.25, "spd": 0.10}[party]
            self.cand_strategy[aid] = {"p_fake": base_fake, "p_news": 1.0 - base_fake}

        rows = []
        for rank, aid in enumerate(chosen, start=1):
            atr = self.pop[aid]
            rows.append({
                "rank": rank, "agent_id": aid,
                "name": f"{aid} {atr['nickname']}",
                "party": atr["party"],
                "score": round(self.candidate_score(aid), 4),
                "persuasion_cap": round(atr["persuasion_cap"], 4),
                "degree": self.G.degree(aid),
                "involvement": round(atr["involvement"], 4),
                "support": round(atr["support"], 4),
            })
        pd.DataFrame(rows).to_csv(self.out_dir / "candidates_T10.csv", index=False, encoding="utf-8")
        return chosen

    # —————— CAMPAIGN T11–T50 ——————
    def _emit_message(self, cand: AgentId, kind: str, detected: bool, reach: int, keywords: List[str]):
        self.message_log.append({
            "t": self.t, "sender": cand,
            "party": self.pop[cand]["party"],
            "kind": kind, "detected": detected,
            "reach": reach, "keywords": keywords
        })

    def _audience_sample(self, cand: AgentId, size: int = 50) -> List[AgentId]:
        neighs = list(self.G.neighbors(cand))
        pool = set(neighs)
        while len(pool) < size:
            pool.add(f"A{self.rng.randint(1,1000):04d}")
        return list(self.rng.sample(list(pool), size))

    def _keywords_for(self, cand: AgentId, kind: str) -> List[str]:
        nick = (self.pop[cand]["nickname"] or "").split()[-1] if self.pop[cand]["nickname"] else "Tech"
        party = self.pop[cand]["party"].upper()
        base = ["#election", "#campaign", f"#{party}", f"#{nick}"]
        if kind == "NEWS":
            base += ["#proposal", "#roadmap", "#policy"]
        else:
            base += ["#bombshell", "#scandal", "#viral"]
        return base

    def campaign_tick(self, detect_prob: float = 0.35, punishment_drop: float = 0.12, audience_size: int = 50):
        for cand in self.candidates:
            party = self.pop[cand]["party"]
            strat = self.cand_strategy[cand]
            is_fake = (self.rng.random() < strat["p_fake"])
            detected = False
            kind = "FAKENEWS" if is_fake else "NEWS"
            if is_fake and (self.rng.random() < detect_prob):
                detected = True

            audience = self._audience_sample(cand, size=audience_size)
            reach = 0
            keywords = self._keywords_for(cand, "FAKENEWS" if is_fake else "NEWS")

            for recv in audience:
                rep_party = self.party_reputation[party]
                rep_cand = self.cand_reputation.get(cand, 0.6)
                rep_eff = 0.6*rep_cand + 0.4*rep_party
                voter_party = self.pop[recv]["party"]
                aff = self.pl.affinity(voter_party, party)  # 0..1

                if not detected:
                    tone = +1
                    rep_used = rep_eff - (0.10 if is_fake else 0.0)
                else:
                    tone = -2
                    rep_used = rep_eff - 0.20

                s0 = self.pop[recv]["support"]
                s1 = self.pl.update_support(s0, aff, tone, max(0.0, min(1.0, rep_used)))
                self.pop[recv]["support"] = s1
                self.pop[recv]["fatigue"] = min(1.0, self.pop[recv]["fatigue"] + (0.015 if not detected else 0.025))
                self.pop[recv]["involvement"] = min(1.0, self.pop[recv]["involvement"] + 0.005)
                reach += 1

            if is_fake and detected:
                drop = punishment_drop
                self.cand_reputation[cand] = max(0.0, self.cand_reputation.get(cand, 0.6) - drop)
                self.party_reputation[party] = max(0.0, self.party_reputation[party] - drop*0.5)
                if party in ("ped", "pee"):
                    self.cand_strategy[cand]["p_fake"] = max(0.0, strat["p_fake"] - 0.05)
                else:
                    self.cand_strategy[cand]["p_fake"] = max(0.0, strat["p_fake"] - 0.10)
                self.cand_strategy[cand]["p_news"] = 1.0 - self.cand_strategy[cand]["p_fake"]
            else:
                if not is_fake:
                    self.cand_reputation[cand] = min(1.0, self.cand_reputation.get(cand, 0.6) + 0.01)
                    self.party_reputation[party] = min(1.0, self.party_reputation[party] + 0.005)

            self._emit_message(cand, kind=("FAKENEWS" if is_fake else "NEWS"),
                               detected=detected, reach=reach, keywords=keywords)
        self.t += 1

    # —————— REPORTS (T20/T30/T40/T50) ——————
    def _top_keywords(self, window: Tuple[int, int]) -> List[Tuple[str, int]]:
        a, b = window
        all_kw = []
        for m in self.message_log:
            if a <= m["t"] <= b:
                all_kw.extend(m["keywords"])
        cnt = Counter(all_kw)
        return cnt.most_common(8)

    def _top_candidates(self, window: Tuple[int, int]) -> List[Tuple[str, int]]:
        a, b = window
        by_sender = Counter()
        for m in self.message_log:
            if a <= m["t"] <= b:
                by_sender[m["sender"]] += m["reach"]
        return by_sender.most_common(5)

    def write_report(self, t_mark: int):
        w = (max(11, t_mark-9), t_mark)
        top_kw = self._top_keywords(w)
        top_cands = self._top_candidates(w)
        by_party_msgs = Counter(m["party"] for m in self.message_log if w[0] <= m["t"] <= w[1])
        by_kind = Counter(m["kind"] for m in self.message_log if w[0] <= m["t"] <= w[1])
        dets = sum(1 for m in self.message_log if w[0] <= m["t"] <= w[1] and m["kind"]=="FAKENEWS" and m["detected"])
        fak  = sum(1 for m in self.message_log if w[0] <= m["t"] <= w[1] and m["kind"]=="FAKENEWS")
        det_rate = (dets / fak) if fak > 0 else 0.0

        lines = []
        lines.append(f"=== The Virtual Gazette — Campaign Report T{t_mark} ===")
        lines.append(f"Window: T{w[0]}–T{w[1]}")
        lines.append("")
        lines.append("Headlines:")
        lines.append(f"- Total messages: {sum(by_party_msgs.values())} | NEWS: {by_kind['NEWS']}, FAKENEWS: {by_kind['FAKENEWS']} (detected: {dets}/{fak}, rate={det_rate:.1%})")
        lines.append("- Party reputation now: " + ", ".join([f"{p.upper()}={self.party_reputation[p]:.2f}" for p in PARTIES]))
        lines.append("")
        lines.append("Top trending topics:")
        for k, c in top_kw:
            lines.append(f"  • {k}  ({c})")
        lines.append("")
        lines.append("Most influential senders (by estimated reach):")
        for aid, reach in top_cands:
            nick = self.pop[aid]['nickname'] or ''
            party = self.pop[aid]['party'].upper()
            lines.append(f"  • {aid} {nick} [{party}] — reach {reach}")
        lines.append("")
        lines.append("Color note:")
        lines.append("  Satirical nicknames continue to shape the media narrative; parties compete on agenda vs. scandal framing.")
        lines.append("")
        (self.out_dir / "reports" / f"report_T{t_mark}.txt").write_text("\n".join(lines), encoding="utf-8")

    # —————— AUX: alcance acumulado por candidato ——————
    def _aggregate_reach(self):
        total = Counter()
        for m in self.message_log:
            total[m["sender"]] += m["reach"]
        return total

    # —————— AUX: score de partido para eleitor ——————
    def _party_score_for_voter(self, voter_party: str, target_party: str, alpha_aff: float = 0.7) -> float:
        aff = self.pl.affinity(voter_party, target_party)   # 0..1
        rep = self.party_reputation.get(target_party, 0.5)  # 0..1
        return alpha_aff * aff + (1.0 - alpha_aff) * rep

    # —————— T51: votação + D’Hondt + eleitos ——————
    def tally_T51(self, seats_total: int = 16, seed: int = 42):
        rng = self.rng
        rng.seed(seed)

        # 1) Turnout + voto
        votes = Counter()
        blank_null = 0
        for aid, atr in self.pop.items():
            tprob = self.pl.turnout(0.5, atr["involvement"], atr["fatigue"])
            if rng.random() >= tprob:
                continue
            p_blank = min(0.05 + 0.10 * atr["fatigue"], 0.30)
            if rng.random() < p_blank:
                blank_null += 1
                continue
            scores = []
            for p in PARTIES:
                s = self._party_score_for_voter(atr["party"], p)
                scores.append((p, max(0.0, s)))
            total_s = sum(s for _, s in scores)
            if total_s <= 0:
                votes[atr["party"]] += 1
            else:
                r = rng.random() * total_s
                acc = 0.0
                chosen = PARTIES[0]
                for p, s in scores:
                    acc += s
                    if r <= acc:
                        chosen = p
                        break
                votes[chosen] += 1

        # 2) D’Hondt
        seats = self._dhondt(votes, seats_total)

        # 3) Eleitos (ranking por influência de campanha)
        reach = self._aggregate_reach()
        max_reach = max(reach.values()) if reach else 1
        def cand_influence(aid: str) -> float:
            r_norm = (reach.get(aid, 0) / max_reach) if max_reach > 0 else 0.0
            return 0.6 * self.cand_reputation.get(aid, 0.6) + 0.4 * r_norm

        elected_rows = []
        for party, s in seats.items():
            party_cands = [c for c in self.candidates if self.pop[c]["party"] == party]
            party_cands.sort(key=lambda c: cand_influence(c), reverse=True)
            winners = party_cands[:s]
            for aid in winners:
                elected_rows.append({
                    "party": party,
                    "agent_id": aid,
                    "name": f"{aid} {self.pop[aid]['nickname']}",
                    "influence_score": round(cand_influence(aid), 4),
                    "cand_reputation": round(self.cand_reputation.get(aid, 0.6), 4),
                    "campaign_reach": reach.get(aid, 0),
                })

        # 4) CSVs
        pd.DataFrame(
            [{"party": p, "votes": votes.get(p, 0)} for p in PARTIES] + [{"party": "blank_null", "votes": blank_null}]
        ).to_csv(self.out_dir / "votes_T51.csv", index=False, encoding="utf-8")

        pd.DataFrame([{"party": p, "seats": seats.get(p, 0)} for p in PARTIES]) \
            .to_csv(self.out_dir / "seats_T51.csv", index=False, encoding="utf-8")

        pd.DataFrame(elected_rows).to_csv(self.out_dir / "elected_T51.csv", index=False, encoding="utf-8")

        # 5) Report final
        self._write_final_report(votes, blank_null, seats, elected_rows)
        print("T51 done: votes_T51.csv, seats_T51.csv, elected_T51.csv, report_T51.txt saved.")
        return votes, seats, elected_rows

    def _dhondt(self, votes: Counter, seats_total: int) -> Dict[str, int]:
        quotients = []
        for p in PARTIES:
            v = votes.get(p, 0)
            for d in range(1, seats_total + 1):
                quotients.append((p, v / d))
        quotients.sort(key=lambda x: x[1], reverse=True)
        allocated = Counter()
        for i in range(seats_total):
            p, _ = quotients[i]
            allocated[p] += 1
        return dict(allocated)

    def _write_final_report(self, votes: Counter, blank_null: int, seats: Dict[str, int], elected_rows: List[dict]):
        total_valid = sum(votes.get(p, 0) for p in PARTIES)
        total_cast = total_valid + blank_null
        lines = []
        lines.append("=== The Virtual Gazette — Election Night (T51) ===")
        lines.append("")
        lines.append(f"Total ballots cast: {total_cast} (valid: {total_valid}, blank/null: {blank_null})")
        lines.append("Votes by party: " + ", ".join([f"{p.upper()}={votes.get(p,0)}" for p in PARTIES]))
        lines.append("Seats (D’Hondt, 16 total): " + ", ".join([f"{p.upper()}={seats.get(p,0)}" for p in PARTIES]))
        lines.append("")
        lines.append("Elected candidates:")
        for r in sorted(elected_rows, key=lambda r: (r["party"], -r["influence_score"])):
            lines.append(f"  • [{r['party'].upper()}] {r['name']}  "
                         f"(influence={r['influence_score']:.3f}, rep={r['cand_reputation']:.2f}, reach={r['campaign_reach']})")
        lines.append("")
        lines.append("Closing note:")
        lines.append("  Coalition talks will hinge on ideological distance and seat arithmetic; media framing during T11–T50 "
                     "appears to correlate with final influence ranks among winners.")
        (self.out_dir / "reports" / "report_T51.txt").write_text("\n".join(lines), encoding="utf-8")


# —————— DRIVERS ——————
def run_pre_campaign_and_select(seed: int = 42):
    sim = SimState(seed=seed)
    print(">>> Pre-campaign T0–T10 starting...")
    for _ in range(11):  # T0..T10
        sim.tick_pre_campaign(K_local=3)
    print(">>> Selecting top-100 candidates at T10...")
    chosen = sim.select_candidates_T10(n_candidates=100, seed=seed)
    print(f"Selected {len(chosen)} candidates. CSV saved to ./outputs/candidates_T10.csv")
    print("Top 10 preview:")
    for aid in chosen[:10]:
        atr = sim.pop[aid]
        print(f"  {aid} {atr['nickname']}  ({atr['party']})  score={sim.candidate_score(aid):.3f}")
    return sim

def run_campaign(sim: SimState, seed: int = 42):
    sim.rng.seed(seed)
    print(">>> Campaign T11–T50 running...")
    for _ in range(11, 51):  # T11..T50
        sim.campaign_tick(detect_prob=0.35, punishment_drop=0.12, audience_size=50)
        if sim.t in (20, 30, 40, 50):
            sim.write_report(sim.t)
            print(f"  Report T{sim.t} written to ./outputs/reports/report_T{sim.t}.txt")
    print(">>> T51 election day (tally in next patch).")
    return sim