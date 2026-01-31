# python_spade/run_spade_sim.py
import asyncio
import spade
import common as cfg
from voter_agent import VoterAgent
from media_agent import MediaAgent
from authority_agent import ElectionAuthorityAgent
from supervisor_agent import SupervisorAgent

async def safe_start(agent, label):
    """
    Inicia o agente e aguarda a confirmação de que ele está rodando.
    """
    await agent.start()
    print(f"[BOOT] {label:.<20} OK (JID: {agent.jid})")

async def main():
    """
    Runner principal do Experimento Controlado: NEWS vs FAKENEWS.
    Gerencia o ciclo de vida dos agentes e encerra a execução após os resultados.
    """
    print("\n" + "="*60)
    print("      MULTI-AGENT SYSTEM: EXPERIMENTO CONTROLADO")
    print("          (FADIGA, ABSTENÇÃO E POLARIZAÇÃO)")
    print("="*60)
    print(f"MODO:        {cfg.EXPERIMENT_MODE}")
    print(f"NEWS_RATE:   {cfg.MEDIA_NEWS_RATE * 100}%")
    print(f"FAKE_RATE:   {cfg.MEDIA_FAKE_RATE * 100}%")
    print(f"ELEITORES:   {cfg.N_CITIZENS}")
    print("="*60 + "\n")

    # 1. Definição de JIDs para coordenação
    sup_jid  = cfg.generate_jid(cfg.SUPERVISOR_PREFIX, 1)
    auth_jid = cfg.generate_jid(cfg.AUTHORITY_PREFIX, 1)
    med_jid  = cfg.generate_jid(cfg.MEDIA_PREFIX, 1)

    # 2. Geração da Sequência de Partidos (Fixa para rigor científico)
    party_sequence = cfg.build_fixed_party_sequence(
        cfg.N_CITIZENS, 
        cfg.VOTER_PARTY_COUNTS, 
        seed=42
    )

    # 3. Instanciação dos Agentes
    # --- Voters ---
    voters = []
    for i, party in enumerate(party_sequence, 1):
        v_jid = cfg.generate_jid(cfg.VOTER_PREFIX, i)
        v = VoterAgent(v_jid, cfg.PASSWORD, sup_jid, auth_jid, party)
        voters.append(v)

    # --- Autoridade Eleitoral ---
    authority = ElectionAuthorityAgent(auth_jid, cfg.PASSWORD, supervisor_jid=sup_jid)

    # --- Mídia (Tratamento Experimental) ---
    media = MediaAgent(
        med_jid, 
        cfg.PASSWORD, 
        sup_jid, 
        [str(v.jid) for v in voters], 
        auth_jid
    )

    # --- Supervisor (Orquestrador) ---
    supervisor = SupervisorAgent(sup_jid, cfg.PASSWORD)
    supervisor.voter_jids = [str(v.jid) for v in voters]
    supervisor.media_jid  = med_jid
    supervisor.authority_jid = auth_jid

    # 4. Inicialização Segura (Bootstrap)
    print("[INICIALIZANDO AGENTES...]")
    await safe_start(authority, "AUTHORITY")
    await safe_start(media, "MEDIA")
    
    voter_tasks = [safe_start(v, f"VOTER_{i+1}") for i, v in enumerate(voters)]
    await asyncio.gather(*voter_tasks)
    
    await safe_start(supervisor, "SUPERVISOR")

    # 5. Sincronização Inicial
    # Garante que todos os behaviours estejam registrados antes do TICK_0
    print("\n[WAIT] Sincronizando instâncias (3s)...")
    await asyncio.sleep(3)
    
    # 6. Monitoramento da Simulação
    print("[EXEC] Simulação em curso. Aguardando conclusão do Supervisor...")
    
    # Timeout de segurança baseado na duração dos ticks
    max_timeout = (cfg.TICK_DURATION * (cfg.TOTAL_TICKS + 10)) + 20
    elapsed = 0
    
    try:
        while elapsed < max_timeout:
            # Verifica se o Supervisor sinalizou o término através do ResultsListener
            if supervisor.get("finished"):
                print("[DONE] Resultados recebidos e processados pelo Supervisor.")
                break
            
            await asyncio.sleep(2)
            elapsed += 2
    except KeyboardInterrupt:
        print("\n[!] Interrupção manual detectada.")

    # 7. Finalização e Limpeza
    print("\n" + "="*60)
    print("           ENCERRANDO EXPERIMENTO")
    print("="*60)
    
    all_agents = [supervisor, authority, media] + voters
    stop_tasks = [agent.stop() for agent in all_agents]
    await asyncio.gather(*stop_tasks)
    
    print("✅ Todos os agentes foram desconectados com segurança.")
    print("🏁 Simulação finalizada.")

if __name__ == "__main__":
    spade.run(main())