import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # .../election_sim
sys.path.append(str((ROOT / "python").as_posix()))

from election_sim.sim_core import run_pre_campaign_and_select

if __name__ == "__main__":
    run_pre_campaign_and_select(seed=42)