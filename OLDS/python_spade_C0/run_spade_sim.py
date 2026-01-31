# python_spade/run_spade_sim.py

import asyncio
import random
from collections import Counter

import spade
import networkx as nx

import common as cfg
from common import get_sender_name, generate_jid

from authority_agent import ElectionAuthorityAgent
from media_agent import MediaAgent
from voter_agent import VoterAgent
from supervisor_agent import SupervisorAgent

# Importa comandos do supervisor (necessário para o novo fluxo)
try:
    from supervisor_agent import (
        PROTOCOL_CONTROL,
        COMMAND_RUN_T10,
        COMMAND_RUN_CAMPAIGN,
        COMMAND_RUN_VOTE,
    )
except ImportError:
    # Fallback caso o supervisor_agent.py ainda não tenha sido carregado
    PROTOCOL_CONTROL = "SIM_CONTROL"
    COMMAND_RUN_T10 = "RUN_T10"
    COMMAND_RUN_CAMPAIGN = "RUN_CAMPAIGN"
    COMMAND_RUN_VOTE = "RUN_VOTE"


# ==========================
# Configurações
# ==========================
SERVER = cfg.SERVER
PASSWORD = cfg.PASSWORD

N_CITIZENS = cfg.N_CITIZENS
N_CANDIDATES_TO_PROMOTE = cfg.N_CANDIDATES_TO_PROMOTE

AUTHORITY_PREFIX = cfg.AUTHORITY_PREFIX
MEDIA_PREFIX = cfg.MEDIA_PREFIX
SUPERVISOR_PREFIX = cfg.SUPERVISOR_PREFIX
VOTER_PREFIX = cfg.VOTER_PREFIX
TOTAL_TICKS = cfg.TOTAL_TICKS


# ==========================
# Função de start segura
# ==========================
async def safe_start(
    agent: spade.agent.Agent,
    label: str,
    timeout: float = 20.0, # 10s em teste / 20s em simulação real
    retries: int = 3,
) -> bool:
    """Tenta iniciar o agente de forma segura, com retries."""
    for attempt in range(1, retries + 1):
        try:
            fut = agent.start(auto_register=True)
            await asyncio.wait_for(fut, timeout=timeout)
            print(f"[BOOT] {label} => start() OK (tentativa {attempt})")
            return True
        except Exception as e:
            print(f"[BOOT][ERRO] {label} (tentativa {attempt}): {e!r}")
            await asyncio.sleep(1.0 * attempt)
    return False


# ==========================
# Função de Comando (Nova) - Reescrita para ser robusta
# ==========================
class CommandSenderAgent(spade.agent.Agent):
    """Agente temporário para enviar comandos ao Supervisor."""

    def __init__(self, jid, password, target_jid, command, *args, **kwargs):
        super().__init__(jid, password, *args, **kwargs)
        self.target_jid = target_jid
        self.command = command

    class CommandSender(spade.behaviour.OneShotBehaviour):
        async def run(self):
            m = spade.message.Message(to=self.agent.target_jid)
            m.set_metadata("protocol", PROTOCOL_CONTROL)
            m.body = self.agent.command
            print(
                f"\n[COMANDO] Enviando: {self.agent.command} "
                f"para {get_sender_name(self.agent.target_jid)}."
            )
            await self.send(m)
            # O OneShotBehaviour encerra o agente automaticamente após run()

    async def setup(self):
        self.add_behaviour(self.CommandSender())


async def send_command(
    supervisor_jid: str, command: str, wait_time: float = 0.5
):
    """Cria e inicia um agente temporário para enviar o comando."""
    sender_jid = generate_jid(
        "controller_temp", random.randint(1000, 9999)
    )
    sender_agent = CommandSenderAgent(
        sender_jid, PASSWORD, supervisor_jid, command
    )

    await sender_agent.start(auto_register=True)
    await asyncio.sleep(wait_time)


# ==========================
# Rede social (small-world)
# ==========================
def build_social_network(n: int, k: int = 4, p: float = 0.3):
    """Cria uma rede social de Watts-Strogatz (small-world)."""
    if n < 2:
        return nx.empty_graph(n)
    k = max(1, min(k, n - 1))
    return nx.watts_strogatz_graph(n, k, p)


# ==========================
# MAIN
# ==========================
async def main():
    print("\n--- 🚀 Iniciando a Simulação Multiagente (PRODEI012) ---")
    print(
        f"Escala: {N_CITIZENS} Eleitores, "
        f"{N_CANDIDATES_TO_PROMOTE} Candidatos a promover"
    )

    # ==========================
    # Log de Configuração Global
    # ==========================
    print("\n[CONFIG] Distribuição alvo de eleitores por partido (%):")
    for code, perc in cfg.PARTY_PERCENTAGES.items():
        name = cfg.PARTIES.get(code, {}).get("name", "")
        print(f"  - {code} ({name}): {perc*100:.1f}%")

    modo_midia = (
        "MANUAL (NEWS/FAKE fixos)"
        if cfg.MEDIA_USE_MANUAL_RATIOS
        else "RL (Q-Learning)"
    )
    print(
        f"[CONFIG] Mídia: NEWS={cfg.NEWS_RATIO*100:.1f}% | "
        f"FAKENEWS={cfg.FAKE_RATIO*100:.1f}%  -> modo {modo_midia}"
    )

    # JIDs principais
    sup_jid = generate_jid(SUPERVISOR_PREFIX, 1)
    auth_jid = generate_jid(AUTHORITY_PREFIX, 1)
    media_jid = generate_jid(MEDIA_PREFIX, 1)

    # ==========================
    # Cria rede social + voters
    # ==========================
    G = build_social_network(N_CITIZENS, k=4, p=0.3)

    voters = []
    voter_party_map = {}  # Mapeamento JID -> Party (essencial p/ Supervisor)
    party_counts = Counter()

    # Distribuição FIXA de eleitores por partido
    target_counts = cfg.compute_party_counts(N_CITIZENS)
    # Cria lista determinística de partidos (sem sorteio)
    party_list: list[str] = []
    for party_code, count in target_counts.items():
        party_list.extend([party_code] * count)

    # Garantia de tamanho exato
    if len(party_list) < N_CITIZENS:
        party_list.extend(
            ["SPD"] * (N_CITIZENS - len(party_list))
        )
    elif len(party_list) > N_CITIZENS:
        party_list = party_list[:N_CITIZENS]

    # Criação dos eleitores com a distribuição fixa
    for i in range(1, N_CITIZENS + 1):
        v_jid = generate_jid(VOTER_PREFIX, i)
        party = party_list[i - 1]
        party_counts[party] += 1
        voter_party_map[v_jid] = party

        # Define vizinhos
        neighbours = []
        if G.has_node(i - 1):
            for n in G.neighbors(i - 1):
                neighbours.append(generate_jid(VOTER_PREFIX, n + 1))

        # Instancia o VoterAgent
        voter = VoterAgent(
            v_jid,
            PASSWORD,
            supervisor_jid=sup_jid,
            authority_jid=auth_jid,  # Passando a JID da Authority
            party=party,
            neighbours=neighbours,
        )
        voters.append(voter)

    print(f"\n[SETUP] Distribuição Partidária Alvo (compute_party_counts): {target_counts}")
    print(f"[SETUP] Distribuição Partidária Efetiva (eleitores criados):   {party_counts}")

    # ==========================
    # Instancia e Conecta Agentes Centrais
    # ==========================

    # 1. Authority
    authority = ElectionAuthorityAgent(
        auth_jid,
        PASSWORD,
        supervisor_jid=sup_jid,
    )

    # 2. Media
    media = MediaAgent(
        media_jid,
        PASSWORD,
        supervisor_jid=sup_jid,
        authority_jid=auth_jid,
        voter_jids=[str(v.jid) for v in voters],
    )

    # 3. Supervisor
    supervisor = SupervisorAgent(
        sup_jid,
        PASSWORD,
    )

    # Wiring Supervisor: Injeção de dependências (IMPORTANTE)
    supervisor.voter_jids = [str(v.jid) for v in voters]
    supervisor.voter_party_map = voter_party_map
    supervisor.media_jid = media_jid
    supervisor.authority_jid = auth_jid
    supervisor.n_candidates = N_CANDIDATES_TO_PROMOTE

    # ==========================
    # Start dos agentes
    # ==========================

    # 1) Authority e Media (Agentes de serviço)
    await safe_start(authority, get_sender_name(auth_jid).upper())
    await safe_start(media, get_sender_name(media_jid).upper())

    # 2) Voters
    voter_start_tasks = []
    for idx, v in enumerate(voters, start=1):
        label = f"VOTER_{idx}"
        voter_start_tasks.append(safe_start(v, label))

    await asyncio.gather(*voter_start_tasks)

    # 3) Supervisor (Controlador Temporal)
    await safe_start(supervisor, get_sender_name(sup_jid).upper())

    # ===============================================
    # EXECUÇÃO AUTOMÁTICA DA SIMULAÇÃO (T0 -> T51)
    # ===============================================
    total_run_time = (cfg.TICK_DURATION * (cfg.TOTAL_TICKS + 5)) + 30 # (cfg.TOTAL_TICKS + 1)) + 15 em teste / (cfg.TOTAL_TICKS + 5)) + 30 em simulação real
    print(
        f"\n[EXEC] Simulação rodará automaticamente até T{cfg.TOTAL_TICKS} "
        f"por {total_run_time:.1f} segundos."
    )
    await asyncio.sleep(total_run_time)

    # ===============================================
    # Shutdown
    # ===============================================
    print("\n[SHUTDOWN] Encerrando todos os agentes...")

    all_agents = voters + [supervisor, media, authority]

    shutdown_tasks = []
    for ag in all_agents:
        shutdown_tasks.append(ag.stop())

    await asyncio.gather(*shutdown_tasks, return_exceptions=True)

    await asyncio.sleep(2)
    print("[SHUTDOWN] Simulação Encerrada.")


if __name__ == "__main__":
    spade.run(main())
