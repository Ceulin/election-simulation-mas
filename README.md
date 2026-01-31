# 🗳️ Election Simulation – Multi-Agent System

Este projeto é um simulador de processos eleitorais baseado em **Sistemas Multiagente (MAS)**, desenvolvido para a disciplina **Sistemas Multiagente (PRODEI012)** na **Faculdade de Engenharia da Universidade do Porto (FEUP)**.

A simulação utiliza agentes autônomos para representar diferentes atores do ecossistema político, modelando interações complexas, fluxos de informação e tomada de decisão.

## 🤖 Arquitetura do Sistema
O sistema é composto por diversos tipos de agentes especializados:
* **Voter Agents**: Representam os eleitores com preferências e inclinações variadas.
* **Candidate Agents**: Representam os candidatos em disputa.
* **Media Agents**: Responsáveis pela disseminação de informação e influência na opinião pública.
* **Authority Agent**: Supervisiona a integridade e o fluxo do processo eleitoral.

## 🛠️ Tecnologias Utilizadas
* **Python 3.11**: Linguagem base do projeto.
* **SPADE**: Framework para o desenvolvimento dos agentes (Smart Python Agent Development Environment).
* **NetworkX**: Utilizado para modelar as redes de influência entre os agentes.
* **Matplotlib**: Geração de gráficos e visualização da evolução dos votos em tempo real.

## 🚀 Como Executar
1. **Clone o repositório:**
   ```bash
   git clone [https://github.com/Ceulin/election-simulation-mas.git](https://github.com/Ceulin/election-simulation-mas.git)

2. **Instale as dependências:**
    ```bash
    pip install -r requirements.txt

3. **Inicie a simulação:**
    ```bash
    python run_spade_sim.py