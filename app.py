import streamlit as st
import pandas as pd
import json
import os
from ortools.sat.python import cp_model

DB_FILE = 'storico_turni.json'

# --- FUNZIONI DATABASE ---
def carica_storico():
    """Legge l'ultimo orario salvato per applicare le regole di continuità."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {}

def salva_storico(df):
    """Salva i turni della Domenica per la settimana successiva."""
    storico = {}
    for index, row in df.iterrows():
        storico[row['Dipendente']] = row['Domenica']
    with open(DB_FILE, 'w') as f:
        json.dump(storico, f)

# --- FUNZIONE DEL SOLVER ---
def calcola_turni(assenze, richieste, storico_domenica_scorsa):
    model = cp_model.CpModel()
    
    dipendenti = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    
    # [ID, Nome, Ore, is_M, is_P, is_Spezzato, inizia_06, finisce_20]
    turni = [
        (0, "RIPOSO", 0, 0, 0, 0, 0, 0),
        (1, "06:00-13:00", 7, 1, 0, 0, 1, 0),
        (2, "07:00-14:00", 7, 1, 0, 0, 0, 0),
        (3, "08:00-14:00", 6, 1, 0, 0, 0, 0),
        (4, "06:00-14:00", 8, 1, 0, 0, 1, 0),
        (5, "07:00-15:00", 8, 1, 0, 0, 0, 0),
        (6, "13:00-20:00", 7, 0, 1, 0, 0, 1),
        (7, "14:00-20:00", 6, 0, 1, 0, 0, 1),
        (8, "06-11 / 16-20", 9, 1, 1, 1, 1, 1) # Lo spezzato inizia alle 6 e finisce alle 20
    ]

    x = {}
    for d in dipendenti:
        for g_idx in range(7):
            for t in turni:
                x[(d, g_idx, t[0])] = model.NewBoolVar(f'x_{d}_{g_idx}_{t[0]}')

    # --- 1. VINCOLI BASE E MONTE ORE FLESSIBILE (PER ASSENZE) ---
    totale_assenti_settimana = len(assenze)
    
    for d in dipendenti:
        for g_idx in range(7):
            model.AddExactlyOne(x[(d, g_idx, t[0])] for t in turni)

        ore_target = 44 if d == "Carmen" else 42
        ore_lavorate = sum(x[(d, g_idx, t[0])] * t[2] for g_idx in range(7) for t in turni)
        
        # Se ci sono malati, autorizziamo fino a 1 ora di straordinario a testa per coprire
        if totale_assenti_settimana > 0:
            model.Add(ore_lavorate >= ore_target)
            model.Add(ore_lavorate <= ore_target + 1)
        else:
            model.Add(ore_lavorate == ore_target)

        # Spezzato solo Ven/Sab
        for g_idx in [0, 1, 2, 3, 6]: 
            model.Add(x[(d, g_idx, 8)] == 0)

        # Salto del riposo autorizzato solo in emergenza
        riposi_settimanali = sum(x[(d, g_idx, 0)] for g_idx in range(7))
        if totale_assenti_settimana > 1:
            model.Add(riposi_settimanali >= 0) # Si può lavorare 7 giorni
        else:
            model.Add(riposi_settimanali == 1)

    # --- 2. COPERTURE DINAMICHE ---
    for g_idx in range(7):
        assenti_oggi = sum(1 for a in assenze if a['giorno'] == giorni[g_idx])
        # Riduciamo il quorum di 1 se manca qualcuno oggi
        tolleranza = 1 if assenti_oggi > 0 else 0 

        if g_idx == 0: # Lunedì
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= 3 - tolleranza) 
        elif g_idx in [1, 2, 3]: # Mar, Mer, Gio
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= 4 - tolleranza)
        elif g_idx in [4, 5]: # Ven, Sab
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= 4 - tolleranza)
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[3] == 1) >= 4 - tolleranza)
        elif g_idx == 6: # Domenica
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= 3 - tolleranza)

    # --- 3. RIPOSO LEGALE 11 ORE ("NO SMONTO-MONTO") ---
    # Controllo infrasettimanale
    for d in dipendenti:
        for g_idx in range(6): # Da Lunedì a Venerdì (controlla il giorno dopo)
            chiude_oggi = sum(x[(d, g_idx, t[0])] for t in turni if t[7] == 1) # Finisce alle 20
            apre_domani = sum(x[(d, g_idx+1, t[0])] for t in turni if t[6] == 1) # Inizia alle 06
            model.Add(chiude_oggi + apre_domani <= 1) # Mutuamente esclusivi
            
    # Controllo storico (Domenica scorsa -> Lunedì attuale)
    if storico_domenica_scorsa:
        for d in dipendenti:
            if d in storico_domenica_scorsa:
                turno_domenica_scorsa = storico_domenica_scorsa[d]
                # Se la stringa del turno conteneva "20:00"
                if "20:00" in turno_domenica_scorsa or "16-20" in turno_domenica_scorsa:
                    apre_lunedi = sum(x[(d, 0, t[0])] for t in turni if t[6] == 1)
                    model.Add(apre_lunedi == 0) # Non può aprire il Lunedì

    # --- 4. REGOLE CUCINA E PROTOCOLLO EMERGENZA ---
    for d in ["Nicola", "Giovanna"]:
        model.Add(x[(d, 0, 0)] == 0) # Mai riposo Lunedì
        model.Add(x[(d, 3, 0)] == 0) # Mai riposo Giovedì

    for g_idx in range(7):
        nicola_assente = any(a['dipendente'] == "Nicola" and a['giorno'] == giorni[g_idx] for a in assenze)
        giovanna_assente = any(a['dipendente'] == "Giovanna" and a['giorno'] == giorni[g_idx] for a in assenze)

        if nicola_assente and giovanna_assente:
            # PROTOCOLLO EMERGENZA: Entrambi i cuochi KO. Carmen forzata all'apertura delle 06:00
            model.Add(sum(x[("Carmen", g_idx, t[0])] for t in turni if t[6] == 1) == 1)
        else:
            # Regola standard: Uno dei due cuochi apre
            model.Add(sum(x[("Nicola", g_idx, t[0])] + x[("Giovanna", g_idx, t[0])] for t in turni if t[6] == 1) >= 1)

    # --- 5. INPUT DA INTERFACCIA ---
    for ass in assenze:
        g_idx = giorni.index(ass['giorno'])
        model.Add(x[(ass['dipendente'], g_idx, 0)] == 1)

    for req in richieste:
        g_idx = giorni.index(req['giorno'])
        t_id = next(t[0] for t in turni if t[1] == req['turno'])
        model.Add(x[(req['dipendente'], g_idx, t_id)] == 1)

    # --- 6. OTTIMIZZAZIONE ---
    carmen_pomeriggi = sum(x[("Carmen", g_idx, t[0])] for g_idx in range(7) for t in turni if t[4] == 1 and t[3] == 0)
    model.Minimize(carmen_pomeriggi)

    # --- 7. RISOLUZIONE ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        dati_tabella = []
        for d in dipendenti:
            riga = {"Dipendente": d}
            totale_ore = 0
            for g_idx, giorno in enumerate(giorni):
                turno_ass = "RIPOSO"
                for t in turni:
                    if solver.Value(x[(d, g_idx, t[0])]):
                        if t[0] != 0:
                            turno_ass = f"{t[1]} ({t[2]}h)"
                            totale_ore += t[2]
                        break
                riga[giorno] = turno_ass
            riga["Totale Ore"] = totale_ore
            dati_tabella.append(riga)
        return pd.DataFrame(dati_tabella), None
    else:
        return None, "ERRORE: I vincoli sono troppo rigidi (troppi malati o turni incompatibili). Impossibile trovare una soluzione."

# --- INTERFACCIA WEB (STREAMLIT) ---
st.set_page_config(layout="wide")
st.title("Gestione Turni Avanzata (Con Memoria)")

# Carica il database all'avvio
storico = carica_storico()
if storico:
    st.info("📦 Database attivo: Il sistema si ricorda gli orari della domenica scorsa per garantire il riposo di 11 ore il lunedì.")

# Gestione Stato per mantenere la tabella a schermo
if 'df_generato' not in st.session_state:
    st.session_state.df_generato = None

with st.sidebar:
    st.header("Gestione Assenze")
    dipendenti_list = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni_list = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    turni_nomi = ["06:00-13:00", "07:00-14:00", "08:00-14:00", "06:00-14:00", "07:00-15:00", "13:00-20:00", "14:00-20:00", "06-11 / 16-20"]
    
    num_assenze = st.number_input("Numero di assenze", min_value=0, max_value=5, value=0)
    assenze_registrate = []
    for i in range(int(num_assenze)):
        col1, col2 = st.columns(2)
        with col1: dip = st.selectbox(f"Assente {i+1}", dipendenti_list, key=f"ass_dip_{i}")
        with col2: gio = st.selectbox(f"Giorno {i+1}", giorni_list, key=f"ass_gio_{i}")
        assenze_registrate.append({"dipendente": dip, "giorno": gio})

    st.divider()
    
    st.header("Forzature Turni")
    num_richieste = st.number_input("Turni da bloccare", min_value=0, max_value=10, value=0)
    richieste_registrate = []
    for i in range(int(num_richieste)):
        col1, col2, col3 = st.columns([1.5, 1, 1.5])
        with col1: dip = st.selectbox("Dip", dipendenti_list, key=f"req_dip_{i}", label_visibility="collapsed")
        with col2: gio = st.selectbox("Gio",
