import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model

# --- FUNZIONE DEL SOLVER ---
def calcola_turni(is_pasqua, assenze):
    model = cp_model.CpModel()
    
    dipendenti = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    
    # [ID, Nome, Ore, is_M, is_P, is_Spezzato, inizia_6]
    turni = [
        (0, "RIPOSO", 0, 0, 0, 0, 0),
        (1, "06:00-13:00", 7, 1, 0, 0, 1),
        (2, "07:00-14:00", 7, 1, 0, 0, 0),
        (3, "08:00-15:00", 7, 1, 0, 0, 0),
        (4, "06:00-14:00", 8, 1, 0, 0, 1),
        (5, "07:00-15:00", 8, 1, 0, 0, 0),
        (6, "13:00-20:00", 7, 0, 1, 0, 0),
        (7, "12:00-20:00", 8, 0, 1, 0, 0),
        (8, "06-11 / 16-20", 9, 1, 1, 1, 1),
        (9, "08:00-13:00", 5, 1, 0, 0, 0),
        (10, "14:00-20:00", 6, 0, 1, 0, 0)
    ]

    x = {}
    for d in dipendenti:
        for g_idx in range(7):
            for t in turni:
                x[(d, g_idx, t[0])] = model.NewBoolVar(f'x_{d}_{g_idx}_{t[0]}')

    # --- VINCOLI BASE ---
    for d in dipendenti:
        for g_idx in range(7):
            model.AddExactlyOne(x[(d, g_idx, t[0])] for t in turni)

        ore_target = 44 if d == "Carmen" else 42
        model.Add(sum(x[(d, g_idx, t[0])] * t[2] for g_idx in range(7) for t in turni) == ore_target)

        # Spezzato consentito solo Ven(4) e Sab(5)
        for g_idx in [0, 1, 2, 3, 6]: 
            model.Add(x[(d, g_idx, 8)] == 0)

    # --- INTEGRAZIONE INPUT UTENTE (ASSENZE) ---
    # Per ogni assenza selezionata nell'interfaccia, forziamo l'ID 0 (RIPOSO)
    for assenza in assenze:
        dipendente_assente = assenza['dipendente']
        giorno_assente_idx = giorni.index(assenza['giorno'])
        model.Add(x[(dipendente_assente, giorno_assente_idx, 0)] == 1)

    # --- GESTIONE DOMENICA E RIPOSI ---
    if is_pasqua:
        for d in dipendenti:
            model.Add(x[(d, 6, 0)] == 1)
            model.Add(sum(x[(d, g, 0)] for g in range(6)) == 0)
    else:
        for d in dipendenti:
            model.Add(sum(x[(d, g_idx, 0)] for g_idx in range(7)) == 1)
        model.Add(sum(x[(d, 6, 0)] for d in dipendenti) == 3)

    # --- COPERTURE ---
    for g_idx in range(7):
        if is_pasqua and g_idx == 6: continue

        if g_idx in [4, 5]:
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) == 4)
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[3] == 1) >= 4)
        else:
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) >= 3)
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[3] == 1) >= 4)

        model.Add(sum(x[("Monia", g_idx, t[0])] + x[("Sara T", g_idx, t[0])] + x[("Carmen", g_idx, t[0])] for t in turni if t[6] == 1) >= 1)
        model.Add(sum(x[("Nicola", g_idx, t[0])] + x[("Giovanna", g_idx, t[0])] for t in turni if t[3] == 1) >= 1)

    # --- RISOLUZIONE ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        dati_tabella = []
        for d in dipendenti:
            riga = {"Dipendente": d}
            for g_idx, giorno in enumerate(giorni):
                turno_ass = "RIPOSO"
                if not (is_pasqua and g_idx == 6):
                    for t in turni:
                        if solver.Value(x[(d, g_idx, t[0])]):
                            if t[0] != 0:
                                turno_ass = f"{t[1]}"
                            break
                riga[giorno] = turno_ass
            dati_tabella.append(riga)
        return pd.DataFrame(dati_tabella), None
    else:
        return None, "Impossibile trovare una soluzione. Troppi assenti o vincoli in conflitto. Riduci le assenze."

# --- INTERFACCIA WEB (STREAMLIT) ---
st.set_page_config(layout="wide")
st.title("Generatore Turni Automatico")

# Controlli a sinistra
with st.sidebar:
    st.header("Impostazioni")
    is_pasqua = st.checkbox("Settimana di Pasqua (Domenica chiusi)", value=True)
    
    st.divider()
    st.header("Assenze / Malattie")
    
    dipendenti_list = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni_list = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    
    # UI per inserire malattie
    num_assenze = st.number_input("Numero di persone assenti", min_value=0, max_value=5, value=0)
    assenze_registrate = []
    
    for i in range(int(num_assenze)):
        col1, col2 = st.columns(2)
        with col1:
            dip = st.selectbox(f"Dipendente {i+1}", dipendenti_list, key=f"dip_{i}")
        with col2:
            giorno = st.selectbox(f"Giorno {i+1}", giorni_list, key=f"gio_{i}")
        assenze_registrate.append({"dipendente": dip, "giorno": giorno})

    st.divider()
    avvia = st.button("Genera Turni", type="primary", use_container_width=True)

# Schermata principale
if avvia:
    with st.spinner("Calcolo delle combinazioni in corso..."):
        df, errore = calcola_turni(is_pasqua, assenze_registrate)
        
        if errore:
            st.error(errore)
        else:
            st.success("Turni generati con successo!")
            st.dataframe(df, use_container_width=True)
            
            # Tasto per scaricare Excel
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Scarica Tabella (CSV)",
                data=csv,
                file_name='Turni.csv',
                mime='text/csv',
            )