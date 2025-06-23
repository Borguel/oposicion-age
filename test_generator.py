# 💣 COMPROBACIÓN DE DEPLOY v3.1
import random
import os
import json
from collections import defaultdict
from openai import OpenAI
from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import validar_pregunta

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    print("🚨 ¡¡ENTRANDO EN generar_test_avanzado!!")
    print(f"🧾 Temas recibidos: {temas} | N° preguntas: {num_preguntas}")
    return {"test": []}  # Forzado para asegurar que se imprime aunque no haga nada más
