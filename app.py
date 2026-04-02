import streamlit as st
import pandas as pd
import json
import os
from ortools.sat.python import cp_model

DB_FILE = 'storico_turni.json'

def carica_storico():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {}

def salva_storico(df):
    storico = {}
    for index, row in df.iterrows():
        storico[row['Dipendente']] = row['Domenica']
    with open(DB_FILE, 'w') as f:
        json.dump(storico, f)

def calcola_turni(assenze, richieste, storico_domenica_scorsa, modalita_speciale):
    model = cp_model.CpModel()
    
    dipendenti = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    
    turni = [
        (0, "RIPOSO", 0, 0, 0, 0, 0, 0),
        (1, "06:00-13:00", 7, 1, 0, 0, 1, 0),
        (2, "07:00-14:00", 7, 1, 0, 0, 0, 0),
        (3, "08:00-14:00", 6, 1, 0, 0, 0, 0),
        (4, "06:00-14:00", 8, 1, 0, 0, 1, 0),
        (5, "07:00-15:00", 8, 1, 0, 0, 0, 0),
        (6, "13:00-20:00", 7, 0, 1, 0, 0, 1),
        (7, "14:00-20:00", 6, 0, 1, 0, 0, 1),
        (8, "06-11 / 16-20", 9, 1, 1, 1, 1, 1) 
    ]

    x = {}
    for d in dipendenti:
        for g_idx in range(7):
            for t in turni:
                x[(d, g_idx, t[0])] = model.NewBoolVar(f'x_{d}_{g_idx}_{t[0]}')

    totale_assenti_settimana = len(assenze)
    
    for d in dipendenti:
        for g_idx in range(7):
            model.AddExactlyOne(x[(d, g_idx, t[0])] for t in turni)

        ore_target = 44 if d == "Carmen" else 42
        ore_lavorate = sum(x[(d, g_idx, t[0])] * t[2] for g_idx in range(7) for t in turni)
        
        # --- LOGICA SETTIMANA SPECIALE (PASQUA) ---
        if modalita_speciale:
            model.Add(ore_lavorate <= ore_target) # Lavorano fino al massimo, ma se fanno meno va bene. Niente minimi.
        elif totale_assenti_settimana > 0:
            model.Add(ore_lavorate >= ore_target)
            model.Add(ore_lavorate <= ore_target + 1)
        else:
            model.Add(ore_lavorate == ore_target)

        # Spezzato solo Ven/Sab
        for g_idx in [0, 1, 2, 3, 6]: 
            model.Add(x[(d, g_idx, 8)] == 0)

        # Riposi
        riposi_settimanali = sum(x[(d, g_idx, 0)] for g_idx in range(7))
        if modalita_speciale:
            pass # Zero regole sui riposi. Se forzi 3 giorni di riposo, il solver li accetta.
        elif totale_assenti_settimana > 1:
            model.Add(riposi_settimanali >= 0) 
        else:
            model.Add(riposi_settimanali == 1)

    # --- COPERTURE ---
    for g_idx in range(7):
        assenti_oggi = sum(1 for a in assenze if a['giorno'] == giorni[g_idx])
        
        # Se è una settimana speciale, abbassiamo drasticamente le difese (tolleranza = 2 persone in meno)
        if modalita_speciale:
            tolleranza = 2
        else:
            tolleranza = 1 if assenti_oggi > 0 else 0 

        if g_idx == 0: 
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= max(0, 3 - tolleranza)) 
        elif g_idx in [1, 2, 3]: 
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= max(0, 4 - tolleranza))
        elif g_idx in [4, 5]: 
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= max(0, 4 - tolleranza))
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[3] == 1) >= max(0, 4 - tolleranza))
        elif g_idx == 6: 
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= max(0, 3 - tolleranza))

    # --- RIPOSO LEGALE 11 ORE ---
    for d in dipendenti:
        for g_idx in range(6): 
            chiude_oggi = sum(x[(d, g_idx, t[0])] for t in turni if t[7] == 1) 
            apre_domani = sum(x[(d, g_idx+1, t[0])] for t in turni if t[6] == 1) 
            model.Add(chiude_oggi + apre_domani <= 1) 
            
    if storico_domenica_scorsa:
        for d in dipendenti:
            if d in storico_domenica_scorsa:
                turno_domenica_scorsa = storico_domenica_scorsa[d]
                if "20:00" in turno_domenica_scorsa or "16-20" in turno_domenica_scorsa:
                    apre_lunedi = sum(x[(d, 0, t[0])] for t in turni if t[6] == 1)
                    model.Add(apre_lunedi == 0) 

    # --- REGOLE CUCINA E EMERGENZA ---
    for d in ["Nicola", "Giovanna"]:
        if not modalita_speciale: # In Pasqua/Ferie possono riposare lunedì e giovedì
            model.Add(x[(d, 0, 0)] == 0) 
            model.Add(x[(d, 3, 0)] == 0) 

    for g_idx in range(7):
        nicola_assente = any(a['dipendente'] == "Nicola" and a['giorno'] == giorni[g_idx] for a in assenze)
        giovanna_assente = any(a['dipendente'] == "Giovanna" and a['giorno'] == giorni[g_idx] for a in assenze)

        if nicola_assente and giovanna_assente:
            model.Add(sum(x[("Carmen", g_idx, t[0])] for t in turni if t[6] == 1) == 1)
        else:
            model.Add(sum(x[("Nicola", g_idx, t[0])] + x[("Giovanna", g_idx, t[0])] for t in turni if t[6] == 1) >= 1)

    # --- INPUT DA INTERFACCIA ---
    for ass in assenze:
        g_idx = giorni.index(ass['giorno'])
        model.Add(x[(ass['dipendente'], g_idx, 0)] == 1)

    for req in richieste:
        g_idx = giorni.index(req['giorno'])
        t_id = next(t[0] for t in turni if t[1] == req['turno'])
        model.Add(x[(req['dipendente'], g_idx, t_id)] == 1)

    # --- OTTIMIZZAZIONE ---
    carmen_pomeriggi = sum(x[("Carmen", g_idx, t[0])] for g_idx in range(7) for t in turni if t[4] == 1 and t[3] == 0)
    model.Minimize(carmen_pomeriggi)

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
        return None, "ERRORE: I vincoli sono troppo rigidi. Controlla le malattie e le richieste, oppure attiva la Modalità Speciale."

# --- INTERFACCIA WEB (STREAMLIT) ---
st.set_page_config(layout="wide")
st.title("Gestione Turni Avanzata")

storico = carica_storico()
if storico:
    st.info("📦 Database attivo: regole storiche Domenica-Lunedì applicate.")

if 'df_generato' not in st.session_state:
    st.session_state.df_generato = None

with st.sidebar:
    st.header("Impostazioni Generali")
    # NUOVO INTERRUTTORE
    modalita_speciale = st.checkbox("⚠️ Modalità Settimana Speciale (Pasqua/Ferie)", help="Disattiva i limiti minimi di ore e permette riposi multipli o assenze di massa senza bloccarsi.")
    st.divider()

    st.header("Assenze (Riposi forzati)")
    dipendenti_list = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni_list = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    turni_nomi = ["06:00-13:00", "07:00-14:00", "08:00-14:00", "06:00-14:00", "07:00-15:00", "13:00-20:00", "14:00-20:00", "06-11 / 16-20"]
    
    num_assenze = st.number_input("Giorni di assenza", min_value=0, max_value=10, value=0)
    assenze_registrate = []
    for i in range(int(num_assenze)):
        col1, col2 = st.columns(2)
        with col1: dip = st.selectbox(f"Assente {i+1}", dipendenti_list, key=f"ass_dip_{i}")
        with col2: gio = st.selectbox(f"Giorno {i+1}", giorni_list, key=f"ass_gio_{i}")
        assenze_registrate.append({"dipendente": dip, "giorno": gio})

    st.divider()
    
    st.header("Forzature Turni (Richieste)")
    num_richieste = st.number_input("Turni da bloccare", min_value=0, max_value=10, value=0)
    richieste_registrate = []
    for i in range(int(num_richieste)):
        col1, col2, col3 = st.columns([1.5, 1, 1.5])
        with col1: dip = st.selectbox("Dip", dipendenti_list, key=f"req_dip_{i}", label_visibility="collapsed")
        with col2: gio = st.selectbox("Gio", giorni_list, key=f"req_gio_{i}", label_visibility="collapsed")
        with col3: tur = st.selectbox("Turno", turni_nomi, key=f"req_tur_{i}", label_visibility="collapsed")
        richieste_registrate.append({"dipendente": dip, "giorno": gio, "turno": tur})

    st.divider()
    avvia = st.button("Genera Algoritmo", type="primary", use_container_width=True)

if avvia:
    with st.spinner("Calcolo ottimizzazione in corso..."):
        df, errore = calcola_turni(assenze_registrate, richieste_registrate, storico, modalita_speciale)
        if errore:
