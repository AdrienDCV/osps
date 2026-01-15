import os
import signal
import socket
import sys
import time
import subprocess

# Constantes pour l'affichage coloré des logs
ERROR = '\033[91m'    # Rouge pour les erreurs
SUCCESS = '\033[92m'  # Vert pour les succès
WARNING = '\033[93m'  # Jaune pour les avertissements
RESET = '\033[0m'     # Réinitialisation de la couleur

# Configuration réseau
HOST = '127.0.0.1'
DISPATCHER_PORT = 2224  # Port health du dispatcher
WORKER_PORT = 2225      # Port health du worker

# Intervalle de vérification
HEALTH_CHECK_INTERVAL = 10  # secondes
CHECK_SPACING = 5           # secondes entre dispatcher et worker

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

def handle_sigint(signum, frame):
    """
    Gestionnaire pour SIGINT / SIGTERM
    """
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[WATCHDOG] - INFO : Signal d'arrêt reçu, arrêt en cours...{RESET}")
        shutdown_requested = True

signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def close_socket(sock, name):
    """
    Ferme proprement une socket
    """
    if sock:
        try:
            sock.close()
            print(f'{WARNING}[WATCHDOG] - INFO : Connexion {name} fermée{RESET}')
        except Exception as error:
            print(f'{ERROR}[WATCHDOG] - ERROR : Erreur fermeture {name}: {type(error).__name__} {error}{RESET}')

def connect_to_dispatcher():
    """
    Tente de se connecter au dispatcher via TCP
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((HOST, DISPATCHER_PORT))
        process_status["dispatcher"] = True
        print(f'{SUCCESS}[WATCHDOG] - INFO  : Connexion au dispatcher établie.{RESET}')
        return s
    except OSError as error:
        process_status["dispatcher"] = False
        print(f'{ERROR}[WATCHDOG] - ERROR : Impossible de se connecter au dispatcher : {type(error).__name__} {error}{RESET}')
        return None

def connect_to_worker():
    """
    Tente de se connecter au worker via TCP
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((HOST, WORKER_PORT))
        process_status["worker"] = True
        print(f'{SUCCESS}[WATCHDOG] - INFO  : Connexion au worker établie.{RESET}')
        return s
    except OSError as error:
        process_status["worker"] = False
        print(f'{ERROR}[WATCHDOG] - ERROR : Impossible de se connecter au worker : {type(error).__name__} {error}{RESET}')
        return None

def get_pid_from_file(name):
    """
    Lit le PID du processus depuis un fichier
    """
    filename = f"/tmp/{name.lower()}.pid"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return int(f.read().strip())
    except ValueError as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : le fichier PID {filename} est vide ou invalide : {type(error).__name__} {error}{RESET}')
        return None
    except Exception as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : Erreur lecture PID {filename} : {type(error).__name__} {error}{RESET}')
        return None
    return None

def restart_process(name):
    """
    Relance le processus (dispatcher ou worker) de manière totalement détachée
    """
    pid = get_pid_from_file(name)
    script_target = "dispatcher.py" if name == "Dispatcher" else "worker.py"

    # Arrêt du processus existant
    if pid:
        try:
            print(f'{WARNING}[WATCHDOG] - INFO  : Envoi du signal SIGTERM au PID {pid} ({name})...{RESET}')
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
        except OSError as e:
            print(f'{WARNING}[WATCHDOG] - WARNING : Impossible d\'arrêter {name} (PID {pid}) : {type(e).__name__} {e}{RESET}')

    # Lancer le nouveau processus complètement détaché
    try:
        print(f'{SUCCESS}[WATCHDOG] - ACTION : Relance de {script_target} en arrière-plan...{RESET}')
        with open(os.devnull, 'w') as devnull:
            subprocess.Popen(
                [sys.executable, script_target],
                start_new_session=True,  # détache du terminal et évite SIGINT partagé
                stdout=devnull,          # Redirection vers l'objet fichier ouvert
                stderr=devnull           # Redirection vers l'objet fichier ouvert
            )
        print(f'{SUCCESS}[WATCHDOG] - INFO  : {name} a été détaché du Watchdog.{RESET}')
    except Exception as e:
        print(f'{ERROR}[WATCHDOG] - CRITICAL : Impossible de relancer {name} : {type(e).__name__} {e}{RESET}')

def check_health(sock, name, retry=False):
    """
    Envoie un message de health check et attend une réponse.
    Une seule tentative de retry est autorisée en cas de timeout.
    """
    try:
        sock.settimeout(5.0)

        # Envoi du message watchdog
        try:
            sock.sendall(b'watchdog-health-test')
        except (BrokenPipeError, ConnectionResetError, OSError) as error:
            print(f'{ERROR}[WATCHDOG] - ERROR : Erreur d\'envoi vers {name} : {type(error).__name__} {error}{RESET}')
            return False

        # Lecture de la réponse
        response = sock.recv(1024)
        if response:
            print(f'{SUCCESS}[WATCHDOG] - INFO  : {name} a répondu : {response!r}{RESET}')
            process_status[name.lower()] = True
            return True
        else:
            print(f'{ERROR}[WATCHDOG] - ERROR : {name} a fermé la connexion{RESET}')
            process_status[name.lower()] = False
            return False

    except socket.timeout:
        if not retry:
            print(f'{WARNING}[WATCHDOG] - WARNING : Timeout 5s pour {name}. Nouvelle tentative...{RESET}')
            return check_health(sock, name, retry=True)
        print(f'{ERROR}[WATCHDOG] - ERROR : Deuxième timeout pour {name}. Le service semble figé.{RESET}')
        process_status[name.lower()] = False
        return False
    except OSError as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : {name} ne répond pas : {type(error).__name__} {error}{RESET}')
        process_status[name.lower()] = False
        return False
    except Exception as error:
        print(f'{ERROR}[WATCHDOG] - CRITICAL : Exception inattendue lors du check de {name} : {type(error).__name__} {error}{RESET}')
        process_status[name.lower()] = False
        return False

def main():
    """
    Programme principal
    """
    global dispatcher_socket, worker_socket, shutdown_requested
    exit_code = 0

    print(f'{SUCCESS}[WATCHDOG] - INFO : Watchdog démarré.{RESET}')
    print(f'{SUCCESS}[WATCHDOG] - INFO : Vérification toutes les {HEALTH_CHECK_INTERVAL}s (espacement {CHECK_SPACING}s entre services){RESET}')

    dispatcher_socket = connect_to_dispatcher()
    time.sleep(1)
    worker_socket = connect_to_worker()

    try:
        while not shutdown_requested:
            # Vérification de l'état du Dispatcher
            if dispatcher_socket is None:
                print(f'{WARNING}[WATCHDOG] - INFO : Tentative de reconnexion au Dispatcher...{RESET}')
                dispatcher_socket = connect_to_dispatcher()

            if dispatcher_socket:
                if not check_health(dispatcher_socket, "Dispatcher"):
                    # Si le Dispatcher ne répond pas, le Watchdog le relance en veillant à bien terminer le processus précédent
                    print(f'{WARNING}[WATCHDOG] - INFO : Dispatcher défaillant, relance en cours...{RESET}')
                    close_socket(dispatcher_socket, "dispatcher")
                    dispatcher_socket = None
                    if worker_socket:
                        close_socket(worker_socket, "worker")
                        worker_socket = None
                    restart_process("Dispatcher")
                    time.sleep(2)
                    continue

            if shutdown_requested:
                break
            time.sleep(CHECK_SPACING)

            # Vérification de l'état du Worker
            if worker_socket is None:
                print(f'{WARNING}[WATCHDOG] - INFO : Tentative de reconnexion au Worker...{RESET}')
                worker_socket = connect_to_worker()

            if worker_socket:
                if not check_health(worker_socket, "Worker"):
                    # Si le Worker ne répond pas, le Watchdog le relance en veillant à bien terminer le processus précédent
                    print(f'{WARNING}[WATCHDOG] - INFO : Worker défaillant, relance du bloc complet...{RESET}')
                    close_socket(worker_socket, "worker")
                    worker_socket = None
                    if dispatcher_socket:
                        close_socket(dispatcher_socket, "dispatcher")
                        dispatcher_socket = None
                    restart_process("Dispatcher")

            remaining_time = HEALTH_CHECK_INTERVAL - CHECK_SPACING
            for _ in range(int(remaining_time)):
                if shutdown_requested:
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        print(f'\n{WARNING}[WATCHDOG] - INFO : Interruption clavier détectée{RESET}')
        exit_code = 0
    except Exception as error:
        print(f'\n{ERROR}[WATCHDOG] - ERROR : Erreur inattendue dans la boucle principale : {type(error).__name__} {error}{RESET}')
        exit_code = 1
    finally:
        if dispatcher_socket:
            close_socket(dispatcher_socket, "dispatcher")
        if worker_socket:
            close_socket(worker_socket, "worker")
        print(f'{SUCCESS}[WATCHDOG] - INFO : Watchdog arrêté{RESET}')

    return exit_code

if __name__ == "__main__":
    sys.exit(main())