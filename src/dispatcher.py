#! /usr/bin/env python3
# _*_ coding: utf8 _*_

import os
import signal
import socket
import sys
import time
from multiprocessing import Process, shared_memory

# --- Constantes ---
# Couleurs pour les messages
ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Configuration réseau
HOST = '127.0.0.1'
PORT = 2222

# Chemins des tubes nommés
TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"

# Chemin du fichier PID
DISPATCHER_PID_FILE = "/tmp/dispatcher.pid"

# Configuration mémoire partagée
SHM_NAME = 'shared_memory'
SHM_SIZE = 10
INITIAL_DATA = bytearray([74, 73, 72, 71, 70, 69, 68, 67, 66, 65])

# Variable globale pour gérer l'arrêt propre
shutdown_requested = False


# --- Gestion des signaux ---
def handle_sigusr1(sig, frame):
    """Gestionnaire pour le signal SIGUSR1"""
    os.kill(os.getppid(), signal.SIGUSR2)

def handle_sigint(sig, frame):
    """Gestionnaire pour SIGINT (Ctrl+C)"""
    global shutdown_requested
    if not shutdown_requested:  # Éviter les messages multiples
        print(f"\n{WARNING}Dispatcher - INFO : Signal d'arrêt reçu, arrêt en cours...{RESET}")
        shutdown_requested = True

signal.signal(signal.SIGUSR1, handle_sigusr1)
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)


# --- Fonctions utilitaires ---
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
        print(f"{ERROR}[Dispatcher] - ERREUR : Une erreur est survenue au moment d'attacher le port : {exception}{RESET}")
        print(f"{ERROR}[Dispatcher] - ERREUR : Le port {PORT} est peut-être utilisé par un autre programme{RESET}")
        return None


def setup_shared_memory():
    """Configure et retourne le segment de mémoire partagée"""
    try:
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
        print('[Dispatcher] - INFO : Nom du segment mémoire partagée :', shm_segment.name)
        print('[Dispatcher] - INFO : Taille du segment mémoire partagée en octets :', len(shm_segment.buf))

        # Écrire les données initiales
        shm_segment.buf[:SHM_SIZE] = INITIAL_DATA
        return shm_segment
    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur lors de la création de la mémoire partagée : {exception}{RESET}")
        return None


def start_worker_process():
    """Démarre le processus worker"""
    from worker import main as worker_main

    worker_process = Process(target=worker_main)
    worker_process.start()
    print(f"{SUCCESS}[Dispatcher] - SUCCESS : Worker démarré (PID: {worker_process.pid}){RESET}")
    return worker_process


def handle_worker_communication(worker_process):
    """Gère la communication avec le worker via les tubes nommés"""
    global shutdown_requested

    fifo_out = None
    fifo_in = None

    try:
        # Donner du temps au worker pour démarrer et se préparer
        print("[Dispatcher] - INFO : Attente du démarrage du worker...")
        time.sleep(3)  # Attendre 3 secondes pour que le worker se prépare

        if shutdown_requested:
            print(f"{WARNING}[Dispatcher] - INFO : Arrêt demandé pendant l'attente du worker{RESET}")
            return

        # Vérifier que le worker est encore vivant
        if not worker_process.is_alive():
            print(f"{ERROR}[Dispatcher] - ERREUR : Le worker s'est arrêté prématurément{RESET}")
            return

        print("[Dispatcher] - INFO : Ouverture des tubes de communication...")
        fifo_out = open(TUBE_D_W, "w")
        fifo_in = open(TUBE_W_D, "r")

        print("[Dispatcher] - INFO : Début de la communication ping-pong...")

        # Communication ping-pong
        N = 5
        for i in range(N):
            if shutdown_requested or not worker_process.is_alive():
                break

            print(f"[Dispatcher] → ping {i}")
            try:
                fifo_out.write("ping\n")
                fifo_out.flush()
            except (BrokenPipeError, OSError) as e:
                if shutdown_requested:
                    print(f"{WARNING}[Dispatcher] - INFO : Tube fermé pendant l'arrêt{RESET}")
                else:
                    print(f"{ERROR}[Dispatcher] - ERREUR : Tube cassé lors de l'écriture: {e}{RESET}")
                break

            # Lecture avec gestion d'erreur
            try:
                reply = fifo_in.readline().strip()
                if reply:
                    print(f"Réponse worker : {reply}")
                else:
                    print(f"{WARNING}[Dispatcher] - WARNING : Réponse vide du worker{RESET}")
            except Exception as e:
                if shutdown_requested:
                    print(f"{WARNING}[Dispatcher] - INFO : Lecture interrompue pendant l'arrêt{RESET}")
                else:
                    print(f"{ERROR}[Dispatcher] - ERREUR : Erreur de lecture depuis le worker: {e}{RESET}")
                break

        # Arrêter le worker proprement
        if fifo_out and not shutdown_requested and worker_process.is_alive():
            try:
                print("[Dispatcher] - INFO : Envoi de la commande STOP au worker...")
                fifo_out.write("STOP\n")
                fifo_out.flush()
                time.sleep(1)  # Laisser le temps au worker de traiter STOP
            except (BrokenPipeError, OSError):
                print(f"{WARNING}Dispatcher - INFO : Worker déjà arrêté (tube fermé){RESET}")

        # Attendre la fin du worker
        if worker_process.is_alive():
            print("[Dispatcher] - INFO : Attente de la fermeture du worker...")
            worker_process.join(timeout=5)
            if worker_process.is_alive():
                print(f"{WARNING}Dispatcher - WARNING : Forcer l'arrêt du worker...{RESET}")
                worker_process.terminate()
                worker_process.join(timeout=2)
                if worker_process.is_alive():
                    worker_process.kill()

        print("[Dispatcher] - INFO : Communication terminée")

    except (BrokenPipeError, OSError) as e:
        if shutdown_requested:
            print(f"{WARNING}[Dispatcher] - INFO : Communication interrompue pendant l'arrêt{RESET}")
        else:
            print(f"{ERROR}[Dispatcher] - ERREUR : Erreur de communication (tube cassé): {e}{RESET}")
    except Exception as e:
        if not shutdown_requested:
            print(f"{ERROR}[Dispatcher] - ERREUR : Erreur inattendue dans la communication : {e}{RESET}")

    finally:
        # Fermeture sécurisée des fichiers
        for fifo, name in [(fifo_out, "sortie"), (fifo_in, "entrée")]:
            if fifo:
                try:
                    fifo.close()
                except:
                    pass

        # Nettoyer les tubes nommés
        for tube in (TUBE_D_W, TUBE_W_D):
            try:
                if os.path.exists(tube):
                    os.unlink(tube)
            except:
                pass

def cleanup_resources(shm_segment, dispatcher_socket, worker_process=None):
    """Nettoie les ressources utilisées"""
    print("[Dispatcher] - INFO : Nettoyage des ressources...")

    # Arrêter le worker si nécessaire
    if worker_process and worker_process.is_alive():
        print("[Dispatcher] - INFO : Arrêt du processus worker...")
        worker_process.terminate()
        worker_process.join(timeout=3)
        if worker_process.is_alive():
            worker_process.kill()

    # Nettoyer la mémoire partagée
    if shm_segment:
        try:
            shm_segment.close()
            shm_segment.unlink()
            print("[Dispatcher] - INFO : Segment mémoire partagé fermé et nettoyé")
        except Exception as exception:
            print(f"{ERROR}Dispatcher - ERREUR : Erreur lors du nettoyage de la mémoire: {exception}{RESET}")

    # Fermer le socket
    if dispatcher_socket:
        try:
            dispatcher_socket.close()
            print("[Dispatcher] - INFO : Socket du Dispatcher fermée")
        except:
            pass

    # Nettoyer les fichiers temporaires
    try:
        if os.path.exists(DISPATCHER_PID_FILE):
            os.unlink(DISPATCHER_PID_FILE)
    except:
        pass

def main():
    """Fonction principale"""
    global shutdown_requested

    dispatcher_socket = None
    shm_segment = None
    worker_process = None

    # Écrire le PID dans un fichier
    with open(DISPATCHER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Configuration des tubes nommés
    setup_named_pipes()

    try:
        # Configuration réseau
        dispatcher_socket = setup_network()
        if not dispatcher_socket or shutdown_requested:
            return 1

        print('[Dispatcher] - INFO : Début processus 1')

        # Configuration de la mémoire partagée
        shm_segment = setup_shared_memory()
        if not shm_segment or shutdown_requested:
            return 1

        # Lancement du worker
        worker_process = start_worker_process()
        if shutdown_requested:
            return 1

        # Gérer la communication avec le worker
        handle_worker_communication(worker_process)

    except KeyboardInterrupt:
        print(f"\n{WARNING}[Dispatcher] - INFO : Interruption clavier détectée{RESET}")
        shutdown_requested = True
    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur inattendue: {exception}{RESET}")
        return 1

    finally:
        cleanup_resources(shm_segment, dispatcher_socket, worker_process)

    print(f"{SUCCESS}[Dispatcher] - INFO : Dispatcher arrêté correctement{RESET}")
    return 0

if __name__ == "__main__":
    sys.exit(main())