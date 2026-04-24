import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
from pathlib import Path
from datetime import datetime
import sys

st.set_page_config(page_title="Monitoring Signaux", page_icon="📡", layout="wide")

if not st.session_state.get('admin_auth'):
    st.warning("Connectez-vous depuis la page d'accueil")
    st.stop()

MONITOR_DIR = Path(__file__).parent.parent.parent / 'data' / 'monitoring'

st.title("📡 Monitoring des Signaux")
st.markdown("---")

# Re-entrainement
col1, col2 = st.columns([3, 1])
with col2:
    if st.button("🔄 Re-entrainer", type="primary"):
        with st.spinner("Extraction MT5 + analyse en cours..."):
            try:
                sys.path.append(str(Path(__file__).parent.parent))
                from retrain_pipeline import run_retrain
                results = run_retrain(verbose=False)
                st.success("Termine !")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur: {e}")

# Select index
selected = st.selectbox("Indice", ['Crash 1000 Index', 'Crash 900 Index', 'Crash 500 Index'])

safe = selected.replace(' ', '_')
fpath = MONITOR_DIR / f'{safe}_history.json'

if not fpath.exists():
    st.warning(f"Pas de donnees pour {selected}. Lancez le re-entrainement.")
    st.stop()

with open(fpath) as f:
    history = json.load(f)

if not history:
    st.stop()

latest = history[-1]
signals = latest.get('signals', {})
meta = signals.get('_meta', {})

# ============================================================
# KPIs
# ============================================================
st.markdown(f"### {selected} - Etat Actuel")

signal_names = ['post_crash_recovery', 'rsi_oversold_bounce', 'squeeze_uptrend',
                'ema_cross', 'rsi_momentum']
labels = ['Post-Crash', 'RSI Oversold', 'Squeeze+Up', 'EMA Cross', 'RSI Momentum']

cols = st.columns(len(signal_names) + 1)
for i, (sig, label) in enumerate(zip(signal_names, labels)):
    with cols[i]:
        if sig in signals:
            rate = signals[sig]['rate']
            n = signals[sig]['n']
            status = signals[sig]['status']
            icon = '🟢' if status == 'STRONG' else '🟡' if status == 'OK' else '🔴'

            st.metric(f"{icon} {label}", f"{rate:.1f}%", delta=f"N={n}")
        else:
            st.metric(f"⚪ {label}", "N/A")

with cols[-1]:
    if meta:
        h = meta.get('hurst', 0.5)
        icon = '🟢' if h > 0.6 else '🟡' if h > 0.55 else '🔴'
        st.metric(f"{icon} Hurst", f"{h:.3f}")

# Market state
if meta:
    st.markdown("### Etat du Marche")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Volatilite", f"{meta.get('volatility', 0):.5f}")
    c2.metric("% UP", f"{meta.get('pct_up', 50):.1f}%")
    c3.metric("Spikes/1000", f"{meta.get('spike_rate_per_1000', 0):.1f}")
    c4.metric("Candles analysees", meta.get('candles', 0))

# ============================================================
# Evolution
# ============================================================
if len(history) > 1:
    st.markdown("### Evolution dans le Temps")

    timeline = []
    for entry in history:
        ts = entry.get('timestamp', '')
        sigs = entry.get('signals', {})
        for sig in signal_names:
            if sig in sigs:
                timeline.append({'date': ts, 'signal': sig, 'rate': sigs[sig]['rate']})

    if timeline:
        tdf = pd.DataFrame(timeline)
        fig = go.Figure()
        colors = {'post_crash_recovery': '#ff6b6b', 'rsi_oversold_bounce': '#4ecdc4',
                  'squeeze_uptrend': '#45b7d1', 'ema_cross': '#f9ca24', 'rsi_momentum': '#a29bfe'}

        for sig in signal_names:
            sdf = tdf[tdf['signal'] == sig]
            if len(sdf) > 0:
                fig.add_trace(go.Scatter(x=sdf['date'], y=sdf['rate'], name=sig,
                                        mode='lines+markers', line=dict(color=colors.get(sig, '#fff'))))

        fig.add_hline(y=55, line_dash="dash", line_color="green", annotation_text="STRONG")
        fig.add_hline(y=50, line_dash="dash", line_color="orange", annotation_text="OK")
        fig.add_hline(y=45, line_dash="dash", line_color="red", annotation_text="WEAK")
        fig.update_layout(height=400, yaxis_title="Win Rate %")
        st.plotly_chart(fig, use_container_width=True)

    # Hurst evolution
    hurst_data = [{'date': e.get('timestamp', ''), 'hurst': e['signals']['_meta']['hurst']}
                  for e in history if '_meta' in e.get('signals', {})]
    if hurst_data:
        hdf = pd.DataFrame(hurst_data)
        fig_h = go.Figure()
        fig_h.add_trace(go.Scatter(x=hdf['date'], y=hdf['hurst'], mode='lines+markers',
                                    line=dict(color='#00d4aa')))
        fig_h.add_hline(y=0.55, line_dash="dash", line_color="red")
        fig_h.update_layout(title="Hurst Exponent", height=300)
        st.plotly_chart(fig_h, use_container_width=True)

# ============================================================
# Recommendations
# ============================================================
st.markdown("### Recommandations")

recs = []
for sig in signal_names:
    if sig in signals:
        rate = signals[sig]['rate']
        if rate < 45:
            recs.append(f"🔴 **Desactiver `{sig}`** dans l'EA ({rate:.1f}%)")
        elif rate < 50:
            recs.append(f"🟡 **Surveiller `{sig}`** ({rate:.1f}%)")

if meta and meta.get('hurst', 0.5) < 0.55:
    recs.append(f"🟡 **Hurst bas ({meta['hurst']:.3f})** - marche moins trending")

if not recs:
    st.success("Tous les signaux sont sains. Aucune action requise.")
else:
    for r in recs:
        st.markdown(r)

st.markdown("---")
st.markdown(f"*Derniere mise a jour: {latest.get('timestamp', 'N/A')}*")
