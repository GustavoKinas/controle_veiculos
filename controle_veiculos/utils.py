def normalizar_texto(texto : str) -> str:
    if not texto:
        return ""
    
    return "".join(texto.lower().split())