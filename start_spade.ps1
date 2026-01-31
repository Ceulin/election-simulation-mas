$proj = Split-Path $MyInvocation.MyCommand.Path
Set-Location $proj
# ativa o venv
& "$proj\election_sim\.spade4\Scripts\Activate.ps1"
# roda módulo
python -m election_sim.python_spade.run_spade_sim