#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import socket
import sys
import time
from multiprocessing import Process, shared_memory

# --- Constantes ---
ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

HOST = '127.0.0.1'
PORT = 2222

TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"
DISPATCHER_PID_FILE = "/tmp/dispatcher.pid"

SHM_NAME = 'shared_memory'
SHM_SIZE = 10
INITIAL_DATA = bytearray([74, 73, 72, 71, 70, 69, 68, 67, 66, 65])

shutdown_requested = False

# --- Gestion des signaux ---
def handle_sigint(sig, frame):
    """Gestionnaire pour SIGINT (Ctrl+C)"""
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[Dispatcher] - INFO : Signal d'arrêt reçu (PID: {os.getpid()}){RESET}")
        shutdown_requested = True

# Configuration des signaux
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def setup_named_pipes():
    """Configure les tubes nommés"""
    for tube in (TUBE_D_W, TUBE_W_D):
        if not os.path.exists(tube):
            os.mkfifo(tube, 0o600)
    print(f"[Dispatcher] - INFO : Tubes nommés configurés")

def setup_network():
    """Configure et retourne le socket réseau"""
    try:
        dispatcher_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dispatcher_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dispatcher_socket.bind((HOST, PORT))
        dispatcher_socket.listen()
        print(f"[Dispatcher] - INFO : Dispatcher en écoute sur {HOST}:{PORT}")
        return dispatcher_socket
    except OSError as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur socket : {exception}{RESET}")
        return None

def setup_shared_memory():
    """Configure et retourne le segment de mémoire partagée"""
    try:
        # Nettoyer mémoire existante
        try:
            shm_segment = shared_memory.SharedMemory(name=SHM_NAME)
            print(f'{WARNING}[Dispatcher] - WARNING : Mémoire existante, nettoyage...{RESET}')
            shm_segment.close()
            shm_segment.unlink()
        except FileNotFoundError:
            pass

        # Créer nouvelle mémoire
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
        print('[Dispatcher] - INFO : Mémoire partagée créée :', shm_segment.name)
        shm_segment.buf[:SHM_SIZE] = INITIAL_DATA
        return shm_segment
    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur mémoire partagée : {exception}{RESET}")
        return None

def start_worker_process():
    """Démarre le processus worker"""
    from worker import main as worker_main
    worker_process = Process(target=worker_main)
    worker_process.start()
    print(f"{SUCCESS}[Dispatcher] - SUCCESS : Worker démarré (PID: {worker_process.pid}){RESET}")
    return worker_process

def cleanup_resources(shm_segment, dispatcher_socket, worker_process=None):
    """Nettoie les ressources utilisées"""
    print("[Dispatcher] - INFO : Nettoyage des ressources...")

    # Arrêter le worker
    if worker_process and worker_process.is_alive():
        print("[Dispatcher] - INFO : Arrêt du worker...")
        worker_process.terminate()
        worker_process.join(timeout=3)
        if worker_process.is_alive():
            print(f"{WARNING}[Dispatcher] - WARNING : Arrêt forcé du worker{RESET}")
            worker_process.kill()
            worker_process.join()

    # Nettoyer mémoire
    if shm_segment:
        try:
            shm_segment.close()
            shm_segment.unlink()
            print("[Dispatcher] - INFO : Mémoire partagée nettoyée")
        except Exception as e:
            print(f"{ERROR}[Dispatcher] - ERREUR : Nettoyage mémoire : {e}{RESET}")

    # Fermer socket
    if dispatcher_socket:
        try:
            dispatcher_socket.close()
            print("[Dispatcher] - INFO : Socket fermé")
        except:
            pass

    # Nettoyer fichiers temporaires
    for path in [DISPATCHER_PID_FILE, TUBE_D_W, TUBE_W_D]:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except:
            pass

def main():
    """Fonction principale"""
    global shutdown_requested

    dispatcher_socket = None
    watchdog_connection = None
    shm_segment = None
    worker_process = None

    # Écrire PID
    with open(DISPATCHER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    setup_named_pipes()

    try:
        # Configuration
        dispatcher_socket = setup_network()
        if not dispatcher_socket:
            return 1

        print('[Dispatcher] - INFO : Début processus 1')

        shm_segment = setup_shared_memory()
        if not shm_segment:
            return 1

        # Lancer worker
        worker_process = start_worker_process()

        # Timeout pour vérifications régulières
        dispatcher_socket.settimeout(1.0)

        print('[Dispatcher] - INFO : En attente de connexions watchdog...')

        while not shutdown_requested:
            # Vérifier si le worker est toujours vivant
            if not worker_process.is_alive():
                print(f"{WARNING}[Dispatcher] - WARNING : Worker arrêté, fin du dispatcher{RESET}")
                break

            try:
                watchdog_connection, watchdog_addr = dispatcher_socket.accept()
                print(f"[Dispatcher] - INFO : Connexion depuis {watchdog_addr}")

                data = watchdog_connection.recv(1024)
                print(f"[Dispatcher] - INFO : Données reçues : {data!r}")

                if data == b'watchdog-health-test':
                    print("[Dispatcher] - INFO : Health check OK")
                    try:
                        watchdog_connection.send(b'dispatcher-alive')
                    except OSError as e:
                        print(f'{ERROR}[Dispatcher] - ERROR : Erreur réponse : {e}{RESET}')

            except socket.timeout:
                # Timeout normal, la boucle vérifie shutdown_requested et worker
                continue
            except OSError as e:
                if shutdown_requested:
                    break
                print(f"{ERROR}[Dispatcher] - ERREUR : Erreur socket : {e}{RESET}")
                break

        print(f"{SUCCESS}[Dispatcher] - INFO : Sortie de la boucle principale{RESET}")

    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur inattendue : {exception}{RESET}")
        return 1

    finally:
        if watchdog_connection:
            try:
                watchdog_connection.close()
                print(f'{SUCCESS}[Dispatcher] - SUCCESS : Socket du Watchdog correctement fermée.{RESET}')
            except:
                pass

        cleanup_resources(shm_segment, dispatcher_socket, worker_process)

    print(f"{SUCCESS}[Dispatcher] - INFO : Dispatcher arrêté correctement{RESET}")
    return 0

if __name__ == "__main__":
    sys.exit(main())