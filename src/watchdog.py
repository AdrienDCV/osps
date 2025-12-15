# --- Constantes ---
# Couleurs pour les messages
import os
import signal
import socket
import sys
import time

ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Configuration réseau
HOST = '127.0.0.1'
DISPATCHER_PORT = 2224  # Port health du dispatcher
WORKER_PORT = 2225      # Port health du worker

# Intervalle de vérification
HEALTH_CHECK_INTERVAL = 30  # secondes
CHECK_SPACING = 5  # secondes entre dispatcher et worker

# Sockets du dispatcher et du worker
dispatcher_socket = None
worker_socket = None

# Variable globale pour gérer l'arrêt propre
shutdown_requested = False

# Variable globale pour le statut des processus
process_status = {
    "dispatcher": False,
    "worker": False
}

def handle_sigint(sig, frame):
    """Gestionnaire pour SIGINT (Ctrl+C)"""
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[WATCHDOG] - INFO : Signal d'arrêt reçu, arrêt en cours...{RESET}")
        shutdown_requested = True

signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def close_socket(sock, name):
    """Ferme proprement une socket"""
    if sock:
        try:
            sock.close()
            print(f'{WARNING}[WATCHDOG] - INFO : Connexion {name} fermée{RESET}')
        except Exception as e:
            print(f'{ERROR}[WATCHDOG] - ERROR : Erreur fermeture {name}: {e}{RESET}')

def connect_to_dispatcher():
    """
    Tente d'établir une connexion avec le dispatcher.
    Retourne la socket connectée (ou None en cas d'erreur).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, DISPATCHER_PORT))
        process_status["dispatcher"] = True
        print(f'{SUCCESS}[WATCHDOG] - INFO  : Connexion au dispatcher établie.{RESET}')
        return s
    except OSError as error:
        process_status["dispatcher"] = False
        print(f'{ERROR}[WATCHDOG] - ERROR : Impossible de se connecter au dispatcher : {error}{RESET}')
        return None

def connect_to_worker():
    """
    Tente d'établir une connexion avec le worker.
    Retourne la socket connectée (ou None en cas d'erreur).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, WORKER_PORT))
        process_status["worker"] = True
        print(f'{SUCCESS}[WATCHDOG] - INFO  : Connexion au worker établie.{RESET}')
        return s
    except OSError as error:
        process_status["worker"] = False
        print(f'{ERROR}[WATCHDOG] - ERROR : Impossible de se connecter au worker : {error}{RESET}')
        return None

def check_health(sock, name):
    """
    Vérifie l'état d'un processus via sa socket.
    Retourne True si le processus répond correctement, False sinon.
    """
    try:
        # Configurer un timeout de 5 secondes pour la réception
        sock.settimeout(5.0)

        # Envoyer le message de santé
        sock.send(b'watchdog-health-test')

        # Attendre une réponse (n'importe quelle donnée)
        response = sock.recv(1024)

        if response:
            print(f'{SUCCESS}[WATCHDOG] - INFO  : {name} a répondu : {response!r}{RESET}')
            if name == "Dispatcher":
                process_status["dispatcher"] = True
            else:
                process_status["worker"] = True
            return True
        else:
            # Connexion fermée proprement par le serveur
            print(f'{ERROR}[WATCHDOG] - ERROR : {name} a fermé la connexion{RESET}')
            if name == "Dispatcher":
                process_status["dispatcher"] = False
            else:
                process_status["worker"] = False
            return False

    except socket.timeout:
        print(f'{ERROR}[WATCHDOG] - ERROR : Aucun message reçu de {name} dans la limite des 5 secondes (timeout){RESET}')
        if name == "Dispatcher":
            process_status["dispatcher"] = False
        else:
            process_status["worker"] = False
        return False
    except OSError as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : {name} ne répond pas : {error}{RESET}')
        if name == "Dispatcher":
            process_status["dispatcher"] = False
        else:
            process_status["worker"] = False
        return False

def main():
    global dispatcher_socket, worker_socket, shutdown_requested
    exit_code = 0

    print(f'{SUCCESS}[WATCHDOG] - INFO : Watchdog démarré.{RESET}')
    print(f'{SUCCESS}[WATCHDOG] - INFO : Vérification toutes les {HEALTH_CHECK_INTERVAL}s (espacement de {CHECK_SPACING}s entre services){RESET}')

    # Établir les connexions initiales
    dispatcher_socket = connect_to_dispatcher()
    time.sleep(1)  # Petit délai entre les connexions
    worker_socket = connect_to_worker()

    try:
        while not shutdown_requested:
            # Vérifier le dispatcher
            if dispatcher_socket is None:
                print(f'{WARNING}[WATCHDOG] - INFO : Tentative de reconnexion au Dispatcher...{RESET}')
                dispatcher_socket = connect_to_dispatcher()

            if dispatcher_socket:
                if not check_health(dispatcher_socket, "Dispatcher"):
                    print(f'{WARNING}[WATCHDOG] - INFO : Dispatcher défaillant, fermeture de la connexion{RESET}')
                    close_socket(dispatcher_socket, "dispatcher")
                    dispatcher_socket = None

            # Attendre avant de vérifier le worker
            if shutdown_requested:
                break
            time.sleep(CHECK_SPACING)

            # Vérifier le worker
            if worker_socket is None:
                print(f'{WARNING}[WATCHDOG] - INFO : Tentative de reconnexion au Worker...{RESET}')
                worker_socket = connect_to_worker()

            if worker_socket:
                if not check_health(worker_socket, "Worker"):
                    print(f'{WARNING}[WATCHDOG] - INFO : Worker défaillant, fermeture de la connexion{RESET}')
                    close_socket(worker_socket, "worker")
                    worker_socket = None

            # Attendre avant le prochain cycle de vérification
            remaining_time = HEALTH_CHECK_INTERVAL - CHECK_SPACING
            for _ in range(int(remaining_time)):
                if shutdown_requested:
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        print(f'\n{WARNING}[WATCHDOG] - INFO : Interruption clavier détectée{RESET}')
        exit_code = 0
    except Exception as e:
        print(f'\n{ERROR}[WATCHDOG] - ERROR : Erreur inattendue : {e}{RESET}')
        exit_code = 1

    finally:
        # Fermeture propre
        if dispatcher_socket:
            try:
                dispatcher_socket.close()
                print(f'{SUCCESS}[WATCHDOG] - SUCCESS : Connexion avec le Dispatcher correctement fermée.{RESET}')
            except Exception as e:
                print(f'{ERROR}[WATCHDOG] - ERROR : Erreur lors de la fermeture du Dispatcher : {e}{RESET}')

        if worker_socket:
            try:
                worker_socket.close()
                print(f'{SUCCESS}[WATCHDOG] - SUCCESS : Connexion avec le Worker correctement fermée.{RESET}')
            except Exception as e:
                print(f'{ERROR}[WATCHDOG] - ERROR : Erreur lors de la fermeture du Worker : {e}{RESET}')

        print(f'{SUCCESS}[WATCHDOG] - INFO : Watchdog arrêté{RESET}')
        return exit_code

if __name__ == "__main__":
    sys.exit(main())