import tempfile
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from rishikesh_urban import Config, run_pipeline

st.set_page_config(page_title="Rishikesh Urban Intelligence", layout="wide")
st.title("🏔️ Rishikesh Urban Intelligence")

up = st.file_uploader("Upload your GeoPackage", type=["gpkg"])
lang = st.radio("Language", ["English", "Hinglish"], horizontal=True)
heat_col = st.text_input("Heat column name (leave blank to use Landsat)")
use_ndvi = st.checkbox("Compute greenery from Landsat (uses lots of memory)", False)

if up and st.button("Run analysis"):
    work = Path(tempfile.mkdtemp())
    gp = work / "input.gpkg"
    gp.write_bytes(up.getbuffer())
    out = work / "out"
    with st.spinner("Running analysis... this can take a few minutes"):
        run_pipeline(Config(gpkg=str(gp), language=lang, out_dir=str(out),
                            heat_column=heat_col, use_ndvi=use_ndvi))
    html = (out / "Rishikesh_Dashboard.html").read_text(encoding="utf-8")
    st.download_button("Download dashboard", html, "Rishikesh_Dashboard.html", "text/html")
    components.html(html, height=900, scrolling=True)
