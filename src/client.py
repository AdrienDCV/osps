#!/usr/bin/env python3
import socket

HOST = "127.0.0.1"
PORT = 2222

print("Connexion au dispatcher...")

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((HOST, PORT))

print("Connecté au dispatcher.")

try:
    while True:
        cmd = input("Commande client ('QUIT' pour sortir) : ")

        sock.sendall((cmd + "\n").encode())

        if cmd == "QUIT":
            print("Fermeture du client...")
            break

        reply = sock.recv(1024).decode().strip()
        print("Réponse du dispatcher :", reply)

except KeyboardInterrupt:
    pass

sock.close()
