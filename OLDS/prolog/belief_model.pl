:- module(belief_model, [
    ideology_point/2,
    affinity/3,
    update_support/5,
    turnout/4
]).

% eixo ideológico
ideology_point(pee, -2.0).
ideology_point(pde, -1.0).
ideology_point(pce,  0.0).
ideology_point(pdd,  1.0).
ideology_point(ped,  2.0).
ideology_point(spd,  0.0).

% Affinity = clamp(1 - |x-y|/2)
affinity(V, C, A) :-
    ideology_point(V, Xv),
    ideology_point(C, Xc),
    D is abs(Xv - Xc),
    A0 is 1.0 - (D / 2.0),
    (A0 < 0.0 -> A = 0.0 ; (A0 > 1.0 -> A = 1.0 ; A = A0)).

% Tone: +1 (positiva), 0 (neutra), -1 (ataque), -2 (punida)
update_support(S0, Aff, Tone, Rep, S1) :-
    Gamma = 0.5,  Tau = 0.3,  Rho = 0.4,
    Delta is Gamma*Aff + Tau*Tone + Rho*(Rep - 0.5),
    Sraw is S0 + 0.2*Delta,
    (Sraw < 0.0 -> S1 = 0.0 ; (Sraw > 1.0 -> S1 = 1.0 ; S1 = Sraw)).

% turnout(Base, Involvement, Fatigue, T) -> clamp
turnout(Base, Inv, Fat, T) :-
    Sraw is Base + 0.4*Inv - 0.3*Fat,
    (Sraw < 0.0 -> T = 0.0 ; (Sraw > 1.0 -> T = 1.0 ; T = Sraw)).