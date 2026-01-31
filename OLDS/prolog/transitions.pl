:- module(transitions, [can_switch/2]).

% partidos: ped pdd pce pde pee spd
can_switch(ped, pdd).
can_switch(pdd, ped).
can_switch(pdd, pce).
can_switch(pce, pdd).
can_switch(pce, pde).
can_switch(pde, pce).
can_switch(pde, pee).
can_switch(pee, pde).

% SPD <-> todos
can_switch(spd, ped).
can_switch(spd, pdd).
can_switch(spd, pce).
can_switch(spd, pde).
can_switch(spd, pee).

can_switch(ped, spd).
can_switch(pdd, spd).
can_switch(pce, spd).
can_switch(pde, spd).
can_switch(pee, spd).