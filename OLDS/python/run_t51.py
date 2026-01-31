import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str((ROOT / "python").as_posix()))

from election_sim.sim_core import run_pre_campaign_and_select, run_campaign

if __name__ == "__main__":
    sim = run_pre_campaign_and_select(seed=42)  # T0–T10 + candidatos
    sim = run_campaign(sim, seed=42)            # T11–T50 + relatórios
    sim.tally_T51(seats_total=16, seed=42)      # T51 + D’Hondt + eleitos
    print("All outputs saved under ./outputs and ./outputs/reports")