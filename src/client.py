#!/usr/bin/env python3
import socket

HOST = "127.0.0.1"
PORT = 2222

# Constantes affichage des logs
ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

print("[CLIENT] : Connexion au dispatcher...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

try:
    sock.connect((HOST, PORT))
    print(f"{SUCCESS}[CLIENT] : Connecté au dispatcher.{RESET}")

    while True:
        try:
            cmd = input("[CLIENT] : Commande client ('QUIT' pour sortir) : ")

            if not cmd:
                continue

            sock.sendall((cmd + "\n").encode())

            if cmd == "QUIT":
                reply = sock.recv(1024).decode().strip()
                print(f"{WARNING}[CLIENT] : Fermeture du client...{RESET}")
                break

            data = sock.recv(1024)
            if not data:
                print(f"{WARNING}[CLIENT] : Le serveur a fermé la connexion.{RESET}")
                break

            dispatcher_response = data.decode().strip()
            print("[CLIENT] : Réponse du dispatcher :", dispatcher_response)

        except (BrokenPipeError, ConnectionResetError):
            print(f"{ERROR}[CLIENT] : Connexion perdue avec le dispatcher.{RESET}")
            break

except ConnectionRefusedError:
    print(f"{ERROR}[CLIENT] : Impossible de se connecter (le dispatcher est-il lancé ?)")
except KeyboardInterrupt:
    print("[CLIENT] : Arrêt demandé par l'utilisateur.")

finally:
    sock.close()
    print(f"{SUCCESS}[CLIENT] : Client fermé.")
