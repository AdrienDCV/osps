#!/usr/bin/env python3
import os, time, signal, subprocess
import sys
from multiprocessing import Process

# --- Constantes ---
# Couleurs pour les messages
ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Variable globale pour le statut des processus
process_status = {
    "dispatcher": False,
    "worker": False
}

def start_dispatcher_process():
    """Démarre le processus dispatcher"""
    from dispatcher import main as dispatcher_main

    try:
        print(f"{WARNING}[WATCHDOG] : Démarrage du dispatcher...{RESET}")
        # Utiliser subprocess au lieu de multiprocessing pour plus de contrôle
        dispatcher_process = Process(target=dispatcher_main)
        dispatcher_process.start()
        time.sleep(2)  # Laisser le temps au dispatcher de démarrer
        print(f"{SUCCESS}[WATCHDOG] : Dispatcher démarré (PID: {dispatcher_process.pid}){RESET}")
        return dispatcher_process

    except Exception as exception:
        print(f"{ERROR}[WATCHDOG] : Erreur lors du démarrage du dispatcher: {exception}{RESET}")
        return None

def handler_sigusr2(signum, frame):
    """Gestionnaire pour recevoir SIGUSR2 (OK reçu)"""
    global process_status
    # Quand un process répond, on le marque vivant
    for k in process_status:
        process_status[k] = True
    print(f"{SUCCESS}[WATCHDOG] : Signal SIGUSR2 reçu - processus marqués vivants{RESET}")

def is_process_alive(pid):
    """Vérifie si un processus existe"""
    try:
        if os.name == "posix":  # Unix/Linux/macOS
            os.kill(pid, 0)  # Signal 0 = test d'existence
            return True
        else:
            # Pour Windows (si nécessaire)
            return os.system(f"tasklist /FI \"PID eq {pid}\" 2>NUL | find \"{pid}\" >NUL") == 0
    except (OSError, ProcessLookupError):
        return False

def get_worker_pid():
    """Récupère le PID du worker depuis le fichier"""
    try:
        with open("/tmp/worker.pid", "r") as worker_pid:
            return int(worker_pid.read().strip())
    except (FileNotFoundError, ValueError) as exception:
        print(f"{WARNING}[WATCHDOG] : Impossible de lire le PID du worker: {exception}{RESET}")
        return None

def main():
    global process_status

    print(f"{SUCCESS}[WATCHDOG] : Watchdog démarré{RESET}")

    # Configurer le gestionnaire de signal
    signal.signal(signal.SIGUSR2, handler_sigusr2)

    # Démarrer le dispatcher
    dispatcher_process = start_dispatcher_process()
    if not dispatcher_process:
        print(f"{ERROR}[WATCHDOG] : Échec du démarrage du dispatcher{RESET}")
        return 1

    dispatcher_pid = dispatcher_process.pid

    # Attendre que le worker soit lancé
    print(f"{WARNING}[WATCHDOG] : Attente du démarrage du worker...{RESET}")
    worker_pid = None
    for attempt in range(10):  # 10 tentatives
        worker_pid = get_worker_pid()
        if worker_pid:
            break
        time.sleep(1)

    if not worker_pid:
        print(f"{ERROR}[WATCHDOG] : Worker non trouvé après 10 secondes{RESET}")
        return 1

    print(f"{SUCCESS}[WATCHDOG] : Surveillance - Dispatcher PID={dispatcher_pid}, Worker PID={worker_pid}{RESET}")

    try:
        while True:
            # Réinitialiser le statut
            process_status = {"dispatcher": False, "worker": False}

            for processus, pid in [("dispatcher", dispatcher_pid), ("worker", worker_pid)]:
                print(f"[WATCHDOG] : Vérification de {processus} (PID: {pid})")

                # Vérifier si le processus existe encore
                if not is_process_alive(pid):
                    print(f"{ERROR}[WATCHDOG] : {processus} n'existe plus, redémarrage...{RESET}")

                    if processus == "dispatcher":
                        dispatcher_process = start_dispatcher_process()
                        if dispatcher_process:
                            dispatcher_pid = dispatcher_process.pid
                            # Récupérer le nouveau PID du worker
                            time.sleep(2)
                            worker_pid = get_worker_pid()
                            if not worker_pid:
                                print(f"{ERROR}[WATCHDOG] : Nouveau worker non trouvé{RESET}")
                                continue
                    else:
                        print(f"{WARNING}[WATCHDOG] : Worker disparu, le dispatcher le relancera{RESET}")
                        # Attendre que le dispatcher relance le worker
                        time.sleep(3)
                        worker_pid = get_worker_pid()

                    continue

                # Envoyer le signal de test
                try:
                    print(f"[WATCHDOG] : Envoi SIGUSR1 à {processus}")
                    os.kill(pid, signal.SIGUSR1)
                except (OSError, ProcessLookupError):
                    print(f"{ERROR}[WATCHDOG] : {processus} n'existe plus lors de l'envoi du signal{RESET}")
                    continue

                # Attendre la réponse
                time.sleep(2)

                # Vérifier si le processus a répondu
                if not process_status[processus]:
                    print(f"{ERROR}[WATCHDOG] {processus} ne répond pas → kill{RESET}")
                    try:
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(1)
                    except (OSError, ProcessLookupError):
                        pass

                    if processus == "dispatcher":
                        print(f"{WARNING}[WATCHDOG] Relance du dispatcher{RESET}")
                        dispatcher_process = start_dispatcher_process()
                        if dispatcher_process:
                            dispatcher_pid = dispatcher_process.pid
                            time.sleep(2)
                            worker_pid = get_worker_pid()
                    else:
                        print(f"{WARNING}[WATCHDOG] Laisser dispatcher relancer worker{RESET}")
                        time.sleep(3)
                        worker_pid = get_worker_pid()
                else:
                    print(f"{SUCCESS}[WATCHDOG] {processus} répond correctement{RESET}")

            print(f"{WARNING}[WATCHDOG] Pause de 10 secondes...{RESET}")
            time.sleep(10)

    except KeyboardInterrupt:
        print(f"\n{WARNING}[WATCHDOG] Arrêt du watchdog demandé{RESET}")

        # Arrêter proprement les processus
        try:
            if is_process_alive(dispatcher_pid):
                os.kill(dispatcher_pid, signal.SIGTERM)
            if worker_pid and is_process_alive(worker_pid):
                os.kill(worker_pid, signal.SIGTERM)
        except:
            pass

        return 0

if __name__ == "__main__":
    sys.exit(main())