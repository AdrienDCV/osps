#! /usr/bin/env python3
# _*_ coding: utf8 _*_

import os
import signal
import socket
import time
from multiprocessing import shared_memory


# --- Constantes ---
# Couleurs pour les messages
RED = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Configuration réseau
HOST = '127.0.0.1'
PORT = 2223

# Chemins des tubes nommés
TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"

# Chemin du fichier PID
WORKER_PID_FILE = "/tmp/worker.pid"

# Configuration mémoire partagée
SHM_NAME = 'shared_memory'

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
        print(f"\n{WARNING}Worker - INFO : Signal d'arrêt reçu{RESET}")
        shutdown_requested = True

signal.signal(signal.SIGUSR1, handle_sigusr1)
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)


# --- Fonctions utilitaires ---
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
        print(f"{RED}[Worker] - ERREUR : Une erreur est survenue au moment d'attacher le port : {exception}{RESET}")
        print(f"{RED}[Worker] - ERREUR : Le port {PORT} est peut-être utilisé par un autre programme{RESET}")
        return None


def access_shared_memory():
    """Accède au segment de mémoire partagée créé par le dispatcher"""
    try:
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=False)

        print('[Worker] - INFO : Nom du segment mémoire partagée :', shm_segment.name)
        print('[Worker] - INFO : Taille du segment mémoire partagée en octets :', len(shm_segment.buf))
        print('[Worker] - INFO : Contenu du segment mémoire partagée (10 octets) :', bytes(shm_segment.buf[:10]))

        return shm_segment
    except Exception as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur lors de l'accès à la mémoire partagée : {exception}{RESET}")
        return None


def handle_fifo_communication():
    """Gère la communication via les tubes nommés"""
    global shutdown_requested

    print(f"{SUCCESS}[Worker] - SUCCESS : Worker prêt{RESET}")

    fifo_in = None
    fifo_out = None

    try:
        # Attendre que les tubes soient disponibles
        max_attempts = 10
        for attempt in range(max_attempts):
            if shutdown_requested:
                return
            try:
                fifo_in = open(TUBE_D_W, "r")
                fifo_out = open(TUBE_W_D, "w")
                break
            except FileNotFoundError:
                if attempt < max_attempts - 1:
                    time.sleep(0.5)
                else:
                    raise

        while not shutdown_requested:
            try:
                # Lecture non-bloquante simulée avec un timeout
                import select
                ready, _, _ = select.select([fifo_in], [], [], 1.0)
                if ready:
                    msg = fifo_in.readline().strip()
                    if msg == "":
                        continue

                    print(f"[Worker] reçoit : {msg}")

                    if msg == "STOP":
                        print(f"{WARNING}[Worker] : arrêt demandé{RESET}")
                        break

                    if msg == "ping":
                        try:
                            fifo_out.write("pong\n")
                            fifo_out.flush()
                        except (BrokenPipeError, OSError):
                            if shutdown_requested:
                                print(f"{WARNING}[Worker] - INFO : Tube fermé pendant l'arrêt{RESET}")
                            else:
                                print(f"{WARNING}[Worker] - WARNING : Dispatcher déconnecté{RESET}")
                            break

            except (BrokenPipeError, OSError) as e:
                if shutdown_requested:
                    print(f"{WARNING}[Worker] - INFO : Communication interrompue pendant l'arrêt{RESET}")
                else:
                    print(f"{WARNING}[Worker] - WARNING : Tube cassé, dispatcher probablement arrêté{RESET}")
                break
            except Exception as e:
                if not shutdown_requested:
                    print(f"{RED}[Worker] - ERREUR : Erreur de communication : {e}{RESET}")
                break

    except Exception as e:
        if not shutdown_requested:
            print(f"{RED}[Worker] - ERREUR : Erreur dans la communication FIFO : {e}{RESET}")

    finally:
        # Fermeture sécurisée des fichiers
        for fifo, name in [(fifo_in, "entrée"), (fifo_out, "sortie")]:
            if fifo:
                try:
                    fifo.close()
                except:
                    pass
        print("[Worker] - INFO : Worker terminé")

def cleanup_resources(shm_segment, worker_socket):
    """Nettoie les ressources utilisées"""
    if shm_segment:
        try:
            shm_segment.close()
            print('[Worker] - INFO : Segment mémoire partagée fermé')
        except Exception as exception:
            print(f"{RED}[Worker] - ERREUR : Erreur lors de la fermeture de la mémoire partagée : {exception}{RESET}")

    if worker_socket:
        try:
            worker_socket.close()
            print("[Worker] - INFO : Socket du Worker fermée")
        except:
            pass

    # Nettoyer le fichier PID
    try:
        if os.path.exists(WORKER_PID_FILE):
            os.unlink(WORKER_PID_FILE)
    except:
        pass


def main():
    """Fonction principale du worker"""
    global shutdown_requested

    worker_socket = None
    shm_segment = None

    # Écrire le PID dans un fichier (pour watchdog)
    with open(WORKER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        # Configuration réseau
        worker_socket = setup_network()
        if not worker_socket or shutdown_requested:
            return 1

        print('Worker - INFO : Début processus 2')

        # Accès à la mémoire partagée
        shm_segment = access_shared_memory()
        if not shm_segment or shutdown_requested:
            return 1

        # Gestion de la communication FIFO
        handle_fifo_communication()

        print('[Worker] : Fin processus 2')

    except KeyboardInterrupt:
        print(f"\n{WARNING}[Worker] - INFO : Interruption clavier détectée{RESET}")
        shutdown_requested = True
    except Exception as exception:
        print(f"{RED}[Worker] - ERREUR : Une erreur inattendue est survenue : {exception}{RESET}")
        return 1

    finally:
        cleanup_resources(shm_segment, worker_socket)

    print(f"{SUCCESS}[Worker] - SUCCESS : Worker terminé{RESET}")
    return 0

if __name__ == "__main__":
    exit(main())