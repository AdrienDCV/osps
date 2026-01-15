#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import socket
import sys
import select
from multiprocessing import Process, shared_memory, resource_tracker

# Constantes affichage des logs
ERROR = '\033[91m'    # Rouge pour les erreurs
SUCCESS = '\033[92m'  # Vert pour les succès
WARNING = '\033[93m'  # Jaune pour les avertissements
RESET = '\033[0m'     # Réinitialisation de la couleur

# Constantes configuration réseau
HOST = '127.0.0.1'   # Adresse IP localhost
PORT = 2222          # Port pour la logique métier
HEALTH_PORT = 2224   # Port pour le Watchdog

# Fichiers et tubes nommés utilisés
TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"
DISPATCHER_PID_FILE = "/tmp/dispatcher.pid"

# Mémoire partagée
SHM_NAME = 'shared_memory'
SHM_SIZE = 10

# Flag global pour arrêter proprement le Dispatcher
shutdown_requested = False

# Gestion des signaux (CTRL + C)
def handle_sigint(signum, frame):
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[Dispatcher] - INFO : Signal d'arrêt reçu (PID: {os.getpid()}){RESET}")
        shutdown_requested = True
        shutdown_requested = True

# Configuration des signaux
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def setup_named_pipes():
    # Création des tubes nommés si inexistants
    try:
        for tube in (TUBE_D_W, TUBE_W_D):
            if not os.path.exists(tube):
                os.mkfifo(tube, 0o600)
        print(f"[Dispatcher] - INFO : Tubes nommés configurés")
    except OSError as e:
        print(f"{ERROR}[Dispatcher] - ERREUR : Impossible de créer les FIFOs : {e}{RESET}")
        raise  # remonter l'erreur pour arrêt propre

def open_named_pipes():
    """
    Ouverture des tubes nommés pour lecture/écriture
    """
    try:
        fifo_dw = os.open(TUBE_D_W, os.O_RDWR)
        fifo_wd = os.open(TUBE_W_D, os.O_RDWR)
        fifo_dw = os.fdopen(fifo_dw, "w", buffering=1)
        fifo_wd = os.fdopen(fifo_wd, "r", buffering=1)
        return fifo_dw, fifo_wd
    except OSError as e:
        print(f"{ERROR}[Dispatcher] - ERREUR : Impossible d'ouvrir les FIFOs : {e}{RESET}")
        raise

def setup_network():
    """
    Configure et retourne le socket réseau pour la logique métier
    """
    try:
        dispatcher_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dispatcher_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dispatcher_socket.bind((HOST, PORT))
        dispatcher_socket.listen()
        print(f"[Dispatcher] - INFO : Dispatcher en écoute sur {HOST}:{PORT} (logique métier)")
        return dispatcher_socket
    except OSError as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur socket métier : {exception}{RESET}")
        return None

def setup_health_socket():
    """
    Configure et retourne le socket réseau pour les health checks
    """
    try:
        health_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        health_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        health_socket.bind((HOST, HEALTH_PORT))
        health_socket.listen()
        print(f"[Dispatcher] - INFO : Dispatcher en écoute sur {HOST}:{HEALTH_PORT} (health checks)")
        return health_socket
    except OSError as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur socket health : {exception}{RESET}")
        return None

def setup_shared_memory():
    """
    Crée ou réinitialise le segment de mémoire partagée
    """
    try:
        # Nettoyage du segment existant (inchangé)
        try:
            temp_shm = shared_memory.SharedMemory(name=SHM_NAME)
            print(f'{WARNING}[Dispatcher] - WARNING : Mémoire existante, nettoyage...{RESET}')
            temp_shm.close()
            temp_shm.unlink()
        except FileNotFoundError:
            pass

        # Création du nouveau segment
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)

        print(f"[Dispatcher] INFO : Segment mémoire partagée créé ({SHM_NAME}, {SHM_SIZE} octets)")
        return shm_segment

    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur mémoire partagée : {exception}{RESET}")
        # Si le segment a été créé mais qu'une erreur suit, on le détruit immédiatement
        if shm_segment:
            try:
                shm_segment.close()
                shm_segment.unlink()
                print(f"{WARNING}[Dispatcher] - INFO : Mémoire défectueuse supprimée{RESET}")
            except:
                pass
        return None

def start_worker_process():
    """
    Démarre le processus worker
    """
    from worker import main as worker_main
    worker_process = Process(target=worker_main)
    try:
        worker_process.start()
        print(f"{SUCCESS}[Dispatcher] - SUCCESS : Worker démarré (PID: {worker_process.pid}){RESET}")
    except Exception as e:
        print(f"{ERROR}[Dispatcher] - ERREUR : Impossible de démarrer le worker : {e}{RESET}")
        return None
    return worker_process

def close_resource(resource, label: str):
    """
    Ferme proprement une ressource (socket, FIFO, etc.) avec gestion d'erreurs.
    Si c'est une socket, on tente d'abord un shutdown pour libération propre.
    """
    if not resource:
        return
    try:
        if isinstance(resource, socket.socket):
            try:
                resource.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass  # Déjà fermé ou non connecté
        resource.close()
        print(f"{SUCCESS}[Dispatcher] - INFO : {label} fermé{RESET}")
    except Exception as error:
        print(f"{WARNING}[Dispatcher] - WARNING : Impossible de fermer {label} : {error}{RESET}")

    # Suppression fichiers temporaires
    for path in (DISPATCHER_PID_FILE, TUBE_D_W, TUBE_W_D):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception as error:
            print(f"{WARNING}[Dispatcher] - WARNING : Impossible de supprimer {path} : {error}{RESET}")

def cleanup_resources(
        shm_segment,
        dispatcher_socket,
        health_socket,
        fifo_wd=None,
        fifo_dw=None,
        worker_process=None,
):
    """
    Nettoie les ressources utilisées/allouées au Dispatcher
    """
    print("[Dispatcher] - INFO : Nettoyage des ressources...")

    # Arrêt propre du worker si possible
    try:
        if worker_process and worker_process.is_alive() and fifo_dw:
            fifo_dw.write("STOP\n")
            fifo_dw.flush()
            worker_process.join(timeout=2)
    except Exception as error:
        print(f"{WARNING}[Dispatcher] - WARNING : Impossible d'envoyer STOP au worker : {error}{RESET}")

    # Terminaison forcée si nécessaire
    if worker_process and worker_process.is_alive():
        print("[Dispatcher] - INFO : Arrêt du worker...")
        worker_process.terminate()
        worker_process.join(timeout=3)
        if worker_process.is_alive():
            print(f"{WARNING}[Dispatcher] - WARNING : Arrêt forcé du worker{RESET}")
            worker_process.kill()
            worker_process.join()

    # Fermeture des FIFOs
    close_resource(fifo_wd, "FIFO Worker->Dispatcher")
    close_resource(fifo_dw, "FIFO Dispatcher->Worker")

    # Nettoyage mémoire partagée (AVANT de fermer les sockets)
    if shm_segment:
        try:
            shm_segment.close()
            print("[Dispatcher] - INFO : Mémoire partagée fermée")

            try:
                shm_segment.unlink()
                print("[Dispatcher] - INFO : Mémoire partagée supprimée")
            except Exception as error:
                print(f"{WARNING}[Dispatcher] - WARNING : Impossible de supprimer la mémoire : {error}{RESET}")
        except Exception as error:
            print(f"{ERROR}[Dispatcher] - ERREUR : Nettoyage mémoire : {error}{RESET}")

    # Fermeture des sockets réseau
    close_resource(dispatcher_socket, "Socket du Dispatcher")
    close_resource(health_socket, "Socket du Watchdog")

    # Suppression fichiers temporaires (EN DERNIER)
    for path in (DISPATCHER_PID_FILE, TUBE_D_W, TUBE_W_D):
        try:
            if os.path.exists(path):
                os.unlink(path)
                print(f"{SUCCESS}[Dispatcher] - INFO : {path} supprimé{RESET}")
        except Exception as error:
            print(f"{WARNING}[Dispatcher] - WARNING : Impossible de supprimer {path} : {error}{RESET}")

def handle_watchdog_connection(watchdog_connection):
    """
    Gère les requêtes health check du watchdog sur une connexion persistante
    """
    try:
        watchdog_connection.settimeout(0.1)  # Timeout très court
        try:
            data = watchdog_connection.recv(1024)
            if not data:
                print(f"{WARNING}[Dispatcher] - INFO : Watchdog a fermé la connexion{RESET}")
                return False

            print(f"[Dispatcher] - INFO : Health check reçu : {data!r}")
            if data == b'watchdog-health-test':
                try:
                    watchdog_connection.send(b'dispatcher-alive')
                except OSError as e:
                    print(f"{ERROR}[Dispatcher] - ERROR : Envoi watchdog impossible : {e}{RESET}")
                    return False
                return True

        except socket.timeout:
            return True
        except OSError as error:
            print(f"{ERROR}[Dispatcher] - ERROR : Erreur lecture watchdog : {error}{RESET}")
            return False

    except OSError as error:
        print(f"{ERROR}[Dispatcher] - ERROR : Erreur socket watchdog : {error}{RESET}")
        return False

def main():
    """
    Programme principal
    """
    global shutdown_requested
    dispatcher_socket = None
    health_socket = None
    watchdog_connection = None
    client_connection = None
    shm_segment = None
    worker_process = None
    fifo_dw = None
    fifo_wd = None

    # Création des tubes nommés
    setup_named_pipes()

    try:
        # Configuration réseau
        dispatcher_socket = setup_network()
        if not dispatcher_socket:
            return 1
        health_socket = setup_health_socket()
        if not health_socket:
            return 1

        print('[Dispatcher] - INFO : Début processus 1')

        # Mémoire partagée
        shm_segment = setup_shared_memory()
        if not shm_segment:
            return 1

        # Lancement du worker
        worker_process = start_worker_process()

        # Ouverture des FIFOs pour dialogue avec le worker
        try:
            fifo_dw, fifo_wd = open_named_pipes()
            print("[Dispatcher] - INFO : FIFOs ouvertes avec succès")
        except Exception:
            return 1

        try:
            with open(DISPATCHER_PID_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            print(f"{ERROR}[Dispatcher] - ERREUR : Impossible d'écrire le PID : {e}{RESET}")
            return 1

        # Timeout pour accept() afin de vérifier shutdown_requested
        health_socket.settimeout(1.0)
        dispatcher_socket.settimeout(1.0)

        print(f"[Dispatcher] INFO : En attente de connexions (métier {HOST}:{PORT}, health {HOST}:{HEALTH_PORT})...")

        # Boucle principale
        while not shutdown_requested:
            if not worker_process.is_alive():
                print(f"{WARNING}[Dispatcher] - WARNING : Worker arrêté, fin du dispatcher{RESET}")
                break

            # Gestion de la communication avec le Watchdog
            if watchdog_connection is None:
                # Si la connexion n'existe pas, alors une nouvelle est créée
                try:
                    watchdog_connection, watchdog_addr = health_socket.accept()
                    print(f"{SUCCESS}[Dispatcher] - INFO : Connexion watchdog établie depuis {watchdog_addr}{RESET}")
                except socket.timeout:
                    pass
                except OSError as error:
                    if not shutdown_requested:
                        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur accept health : {error}{RESET}")
            else:
                # S'il en existe une, alors le Dispatcher s'attend à recevoir des requêtes de santé de la part du Watchdog
                if not handle_watchdog_connection(watchdog_connection):
                    try:
                        watchdog_connection.close()
                    except Exception:
                        pass
                    watchdog_connection = None

            # Gestion de la communication avec le Client
            try:
                client_connection, client_addr = dispatcher_socket.accept()
                print(f"[Dispatcher] - INFO : Connexion client depuis {client_addr}")
                try:
                    while not shutdown_requested:
                        potential_readers = [client_connection]
                        if watchdog_connection:
                            potential_readers.append(watchdog_connection)
                        try:
                            ready_to_read, _, _ = select.select(potential_readers, [], [], 1.0)     # Permet d'alterner la lecture de la socket du Watchdog et du Client pour les gérer simultanément
                        except (OSError, ValueError) as e:
                            print(f"{ERROR}[Dispatcher] - ERREUR : select() échoué : {e}{RESET}")
                            break

                        if not ready_to_read:
                            continue

                        # Lecture de la socket du Watchdog
                        if watchdog_connection in ready_to_read:
                            if not handle_watchdog_connection(watchdog_connection):
                                watchdog_connection.close()
                                watchdog_connection = None

                        # Lecture de la socket du Client
                        if client_connection in ready_to_read:
                            data = client_connection.recv(1024)
                            if not data:
                                break
                            cmd = data.decode().strip()
                            if cmd == "QUIT":
                                client_connection.sendall(b"Au revoir\n")
                                break
                            try:
                                # Transmission du traitement au Worker
                                fifo_dw.write(cmd + "\n")
                                fifo_dw.flush()
                                reply = fifo_wd.readline()
                                if not reply:
                                    raise RuntimeError("Worker ne répond plus")
                                # Transmission de la réponse du Worker au Client
                                client_connection.sendall((reply.strip() + "\n").encode())
                            except (OSError, BrokenPipeError) as e:
                                print(f"{ERROR}[Dispatcher] - ERREUR : Communication worker impossible : {e}{RESET}")
                                break
                            except Exception as e:
                                print(f"{ERROR}[Dispatcher] - ERREUR : Réponse worker invalide : {e}{RESET}")

                except (ConnectionResetError, BrokenPipeError):
                    print(f"{WARNING}[Dispatcher] WARNING : Client déconnecté prématurément{RESET}")
                except Exception as error:
                    print(f"{ERROR}[Dispatcher] ERREUR lors de l'échange client : {error}{RESET}")
                finally:
                    close_resource(client_connection, "Socket du Client")
                    client_connection = None

            except socket.timeout:
                pass
            except OSError as error:
                if not shutdown_requested:
                    print(f"{ERROR}[Dispatcher] - ERREUR : Erreur critique accept métier : {error}{RESET}")
            except Exception as error:
                print(f"{ERROR}[Dispatcher] ERREUR fatale de la boucle principale : {error}{RESET}")
                break

    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur inattendue : {exception}{RESET}")
        return 1

    finally:
        # Fermeture de la connexion au Watchdog
        if watchdog_connection:
            try:
                watchdog_connection.close()
            except Exception:
                pass

        # Nettoyage des ressources
        cleanup_resources(
            shm_segment,
            dispatcher_socket,
            health_socket,
            fifo_wd=fifo_wd,
            fifo_dw=fifo_dw,
            worker_process=worker_process,
        )

    print(f"{SUCCESS}[Dispatcher] - INFO : Dispatcher arrêté correctement{RESET}")
    return 0

if __name__ == "__main__":
    # Programme principal
    sys.exit(main())
