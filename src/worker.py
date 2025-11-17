#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import socket
from multiprocessing import shared_memory

# --- Constantes ---
RED = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

HOST = '127.0.0.1'
PORT = 2223

WORKER_PID_FILE = "/tmp/worker.pid"
SHM_NAME = 'shared_memory'

shutdown_requested = False

# --- Gestion des signaux ---
def handle_sigint(sig, frame):
    """Gestionnaire pour SIGINT (Ctrl+C)"""
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[Worker] - INFO : Signal d'arrêt reçu (PID: {os.getpid()}){RESET}")
        shutdown_requested = True

# Configuration des signaux
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def setup_network():
    """Configure et retourne le socket réseau du worker"""
    try:
        worker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        worker_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        worker_socket.bind((HOST, PORT))
        worker_socket.listen()
        print(f"[Worker] - INFO : Worker en écoute sur {HOST}:{PORT}")
        return worker_socket
    except OSError as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur socket : {exception}{RESET}")
        return None

def access_shared_memory():
    """Accède au segment de mémoire partagée"""
    try:
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        print('[Worker] - INFO : Mémoire partagée :', shm_segment.name)
        print('[Worker] - INFO : Contenu (10 octets) :', bytes(shm_segment.buf[:10]))
        return shm_segment
    except Exception as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur mémoire : {exception}{RESET}")
        return None

def cleanup_resources(shm_segment, worker_socket):
    """Nettoie les ressources"""
    if shm_segment:
        try:
            shm_segment.close()
            print('[Worker] - INFO : Mémoire fermée')
        except Exception as e:
            print(f"{RED}[Worker] - ERREUR : {e}{RESET}")

    if worker_socket:
        try:
            worker_socket.close()
            print("[Worker] - INFO : Socket fermé")
        except:
            pass

    try:
        if os.path.exists(WORKER_PID_FILE):
            os.unlink(WORKER_PID_FILE)
    except:
        pass

def main():
    """Fonction principale du worker"""
    global shutdown_requested

    worker_socket = None
    watchdog_connection = None
    shm_segment = None

    # Écrire PID
    with open(WORKER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        # Configuration
        worker_socket = setup_network()
        if not worker_socket:
            return 1

        print('[Worker] - INFO : Début processus 2')

        shm_segment = access_shared_memory()
        if not shm_segment:
            return 1

        # Timeout pour vérifications
        worker_socket.settimeout(1.0)

        print('[Worker] - INFO : En attente de connexions watchdog...')

        while not shutdown_requested:
            try:
                watchdog_connection, watchdog_addr = worker_socket.accept()
                print(f"[Worker] - INFO : Connexion depuis {watchdog_addr}")

                data = watchdog_connection.recv(1024)
                print(f"[Worker] - INFO : Données reçues : {data!r}")

                if data == b'watchdog-health-test':
                    print("[Worker] - INFO : Health check OK")
                    try:
                        watchdog_connection.send(b'worker-alive')
                    except OSError as e:
                        print(f'{RED}[Worker] - ERROR : Erreur réponse : {e}{RESET}')

            except socket.timeout:
                # Timeout normal
                continue
            except OSError as e:
                if shutdown_requested:
                    break
                print(f"{RED}[Worker] - ERREUR : Erreur socket : {e}{RESET}")
                break

        print(f"{SUCCESS}[Worker] - INFO : Sortie de la boucle principale{RESET}")
        print('[Worker] - INFO : Fin processus 2')

    except Exception as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur inattendue : {exception}{RESET}")
        return 1

    finally:
        if watchdog_connection:
            try:
                watchdog_connection.close()
                print(f'{SUCCESS}[Worker] - SUCCESS : Socket du Watchdog correctement fermée.')
            except:
                pass

        cleanup_resources(shm_segment, worker_socket)

    print(f"{SUCCESS}[Worker] - SUCCESS : Worker terminé{RESET}")
    return 0

if __name__ == "__main__":
    exit(main())