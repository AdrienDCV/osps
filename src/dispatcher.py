#! /usr/bin/env python3
# _*_ coding: utf8 _*_

import os
from multiprocessing import shared_memory, Process
import subprocess

def f():
    # Lancer directement worker.py (doit être exécutable)
    subprocess.call(['./worker.py'])

if __name__ == "__main__":
    print('Début processus 1')

    # Créer ou se connecter au segment mémoire partagé
    try:
        shm_segment1 = shared_memory.SharedMemory(name='012345', create=True, size=10)
    except FileExistsError:
        shm_segment1 = shared_memory.SharedMemory(name='012345', create=False)

    print('Nom du segment mémoire partagée :', shm_segment1.name)
    print('Taille du segment mémoire partagée en octets via premier accès :', len(shm_segment1.buf))

    # Écrire les 10 octets initiaux
    data = bytearray([74, 73, 72, 71, 70, 69, 68, 67, 66, 65])
    shm_segment1.buf[:10] = data

    # Lancer le worker dans un autre processus
    p = Process(target=f)
    p.start()
    print("Processus 1 : va se mettre en attente...\n")
    p.join()
    print("Processus 1 : fin d'attente.\n")

    # Nettoyer le segment mémoire
    shm_segment1.close()
    shm_segment1.unlink()

    print('Fin processus 1')
