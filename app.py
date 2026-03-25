import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model

# --- FUNZIONE DEL SOLVER ---
def calcola_turni(assenze, richieste):
    model = cp_model.CpModel()
    
    dipendenti = ["Carmen", "Cinzia", "Monia", "Debora", "Sara T", "Monica", "Alessia", "Nicola", "Giovanna"]
    giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    
    # [ID, Nome, Ore, is_M, is_P, is_Spezzato, inizia_6]
    # N.B. Nessun turno sotto le 6 ore. Eliminato il turno delle 12:00.
    turni = [
        (0, "RIPOSO", 0, 0, 0, 0, 0),
        (1, "06:00-13:00", 7, 1, 0, 0, 1),
        (2, "07:00-14:00", 7, 1, 0, 0, 0),
        (3, "08:00-14:00", 6, 1, 0, 0, 0),
        (4, "06:00-14:00", 8, 1, 0, 0, 1),
        (5, "07:00-15:00", 8, 1, 0, 0, 0),
        (6, "13:00-20:00", 7, 0, 1, 0, 0),
        (7, "14:00-20:00", 6, 0, 1, 0, 0),
        (8, "06-11 / 16-20", 9, 1, 1, 1, 1) # Spezzato
    ]

    x = {}
    for d in dipendenti:
        for g_idx in range(7):
            for t in turni:
                x[(d, g_idx, t[0])] = model.NewBoolVar(f'x_{d}_{g_idx}_{t[0]}')

    # --- 1. VINCOLI BASE E MONTE ORE ---
    for d in dipendenti:
        # Esattamente un turno al giorno
        for g_idx in range(7):
            model.AddExactlyOne(x[(d, g_idx, t[0])] for t in turni)

        # Monte ore esatto
        ore_target = 44 if d == "Carmen" else 42
        model.Add(sum(x[(d, g_idx, t[0])] * t[2] for g_idx in range(7) for t in turni) == ore_target)

        # Spezzato consentito solo Ven(4) e Sab(5)
        for g_idx in [0, 1, 2, 3, 6]: 
            model.Add(x[(d, g_idx, 8)] == 0)

        # Esattamente 1 giorno di riposo a settimana per ogni dipendente
        model.Add(sum(x[(d, g_idx, 0)] for g_idx in range(7)) == 1)

    # --- 2. GESTIONE DOMENICA E RIPOSI GIORNALIERI ---
    # Domenica: 3 a riposo (e 6 lavorano)
    model.Add(sum(x[(d, 6, 0)] for d in dipendenti) == 3)
    # Lunedì - Sabato: Esattamente 1 persona a riposo al giorno (per far tornare i conti di 8 presenti al giorno)
    for g_idx in range(6):
        model.Add(sum(x[(d, g_idx, 0)] for d in dipendenti) == 1)

    # --- 3. COPERTURE RIGIDE (HARD CONSTRAINTS) ---
    for g_idx in range(7):
        if g_idx == 0: # Lunedì (Giornata di punta)
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) == 3) # Esatti 3 Pome (Quindi 5 Mattina)
        elif g_idx in [1, 2, 3]: # Mar, Mer, Gio
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) == 4) # Esatti 4 Pome (Quindi 4 Mattina)
        elif g_idx in [4, 5]: # Ven, Sab
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) == 4) # Esatti 4 Pome (Spezzati inclusi)
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[3] == 1) >= 4) # Minimo 4 Mattina
        elif g_idx == 6: # Domenica
            model.Add(sum(x[(d, g_idx, t[0])] for d in dipendenti for t in turni if t[4] == 1) == 3) # Esatti 3 Pome, 3 Mattina

    # --- 4. REGOLE CUCINA (NICOLA E GIOVANNA) ---
    for g_idx in range(7):
        # Almeno uno dei due DEVE fare l'apertura delle 06:00
        model.Add(sum(x[("Nicola", g_idx, t[0])] + x[("Giovanna", g_idx, t[0])] for t in turni if t[6] == 1) >= 1)

    for d in ["Nicola", "Giovanna"]:
        # Obbligo di fare almeno 1 turno puramente pomeridiano a settimana
        model.Add(sum(x[(d, g_idx, t[0])] for g_idx in range(7) for t in turni if t[4] == 1 and t[3] == 0) >= 1)

    # --- 5. INPUT DA INTERFACCIA (MALATTIE E RICHIESTE FISSE) ---
    # Malattie (Forza il Riposo)
    for ass in assenze:
        g_idx = giorni.index(ass['giorno'])
        model.Add(x[(ass['dipendente'], g_idx, 0)] == 1)

    # Richieste fisse
    for req in richieste:
        g_idx = giorni.index(req['giorno'])
        t_id = next(t[0] for t in turni if t[1] == req['turno'])
        model.Add(x[(req['dipendente'], g_idx, t_id)] == 1)

    # --- 6. OTTIMIZZAZIONE (SOFT CONSTRAINTS) ---
    # 6A. Minimizzare i pomeriggi di Carmen (Punteggio di penalità altissimo)
    carmen_pomeriggi = sum(x[("Carmen", g_idx, t[0])] for g_idx in range(7) for t in turni if t[4] == 1 and t[3] == 0)
    
    # 6B. Massimizzare i giorni in cui Nicola e Giovanna sono ENTRAMBI di mattina
    giorni_cucina_insieme = []
    for g_idx in range(7):
        entrambi = model.NewBoolVar(f'cucina_{g_idx}')
        nicola_m = sum(x[("Nicola", g_idx, t[0])] for t in turni if t[3] == 1)
        giovanna_m = sum(x[("Giovanna", g_idx, t[0])] for t in turni if t[3] == 1)
        model.Add(nicola_m + giovanna_m == 2).OnlyEnforceIf(entrambi)
        model.Add(nicola_m + giovanna_m < 2).OnlyEnforceIf(entrambi.Not())
        giorni_cucina_insieme.append(entrambi)

    # Il solver cercherà di abbassare i pomeriggi di Carmen e alzare le mattine condivise in cucina
    model.Minimize((carmen_pomeriggi * 50) - sum(giorni_cucina_insieme))

    # --- 7. RISOLUZIONE ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0 # Diamo 20 secondi per combinazioni complesse
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
            
            # Aggiunge la colonna di controllo finale
            riga["Totale Ore"] = totale_ore
            dati_tabella.append(riga)
            
        return pd.DataFrame(dati_tabella), None
    else:
        return None, "ERRORE: Le richieste inserite (malattie/turni fissi) rendono matematicamente impossibile coprire il negozio rispettando le ore di tutti. Riduci i vincoli."

# --- INTERFACCIA WEB (STREAMLIT) ---
st.set_page_config(layout="wide")
st.title("Generatore Turni Automatico")

# Menu Laterale
with st.sidebar:
    st.header("Imprevisti (Malattie / Ferie)")
    st.caption("Forza un dipendente a RIPOSO in un giorno specifico.")
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
    
    st.header("Richieste Turni Fissi")
    st.caption("Assegna un orario intoccabile a un dipendente.")
    num_richieste = st.number_input("Numero di richieste", min_value=0, max_value=10, value=0)
    richieste_registrate = []
    for i in range(int(num_richieste)):
        col1, col2, col3 = st.columns([1.5, 1, 1.5])
        with col1: dip = st.selectbox("Dip", dipendenti_list, key=f"req_dip_{i}", label_visibility="collapsed")
        with col2: gio = st.selectbox("Gio", giorni_list, key=f"req_gio_{i}", label_visibility="collapsed")
        with col3: tur = st.selectbox("Turno", turni_nomi, key=f"req_tur_{i}", label_visibility="collapsed")
        richieste_registrate.append({"dipendente": dip, "giorno": gio, "turno": tur})

    st.divider()
    avvia = st.button("Genera Turni Settimanali", type="primary", use_container_width=True)

# Schermata Principale
if avvia:
    with st.spinner("Il motore matematico sta calcolando la soluzione ottimale... (potrebbe volerci qualche secondo)"):
        df, errore = calcola_turni(assenze_registrate, richieste_registrate)
        
        if errore:
            st.error(errore)
        else:
            st.success("Turni generati con successo! Tutti i vincoli sono stati rispettati.")
            
            # Mostra la tabella formattata
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Bottone per scaricare in CSV per Excel
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Scarica Tabella (File CSV)",
                data=csv,
                file_name='Turni_Settimana.csv',
                mime='text/csv',
            )
