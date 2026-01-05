# Système et programmation sécurisée - Projet

DA COSTA VEIGA Adrien  
DESERT Lorick  

INSA Hauts-de-France  
FISA 4 - Informatique et Cybersécurité  
2025 - 2026

## Choix techniques

Nous avons fait le choix de lancer le Worker depuis le Dispatcher. Nous ne disposons que d'un unique Worker, cela nous 
paraîssait être le plus adéquat du fait de la relation entre le Dispatcher et le Worker.

Nous avons également fait le choix de ne pas lancer le Dispatcher ni le Worker depuis le Watchdog de sorte à laisser la
solution de monitoring relativement indépendante et ouverte à d'autres solutions.

Architecture Dispatcher-Worker : `Protocole "basique"`.

## Lancer les programmes

Se placer dans le répertoire `src`:
```bash
cd src/
```

Le Dispatcher se charge de lancer le Worker, il est nécessaire d'exécuter le programme `dispatcher.py` avant les autres
programmes. Il n'est pas nécessaire d'exécuter manuellement le programme `worker.py"

Exécuter le programme `dispatcher.py`:
```bash
python dispatcher.py
```

L'ordre d'exécution des programmes `watchdog.py` et `client.py` n'a pas d'importance.

Exécuter le programme `watchdog.py`:
```bash
python watchdog.py
```

Exécuter le programme `client.py`:
```bash
python client.py
```