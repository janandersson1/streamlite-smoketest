import streamlit as st

st.set_page_config(page_title="Smoketest", page_icon="✅", layout="centered")
st.title("It works ✅")
namn = st.text_input("Vad heter du?")
if st.button("Säg hej"):
    st.success(f"Hej {namn or 'okänd spelare'}!")