import streamlit as st

st.set_page_config(
    page_title="DynoAd",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ----- REMOVE STREAMLIT DEFAULT UI -----
st.markdown("""
<style>

#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
header {visibility:hidden;}

.block-container{
padding-top:0rem;
}

.stApp{
background-image:url("https://images.freecreatives.com/wp-content/uploads/2016/04/Abstract-Website-Background.jpg");
background-size:cover;
background-position:center;
background-attachment:fixed;
}

.title{
text-align:center;
font-size:70px;
font-weight:bold;
color:white;
margin-top:120px;
}

.subtitle{
text-align:center;
font-size:24px;
color:white;
margin-bottom:40px;
}

.center-box{
background:rgba(0,0,0,0.65);
padding:40px;
border-radius:15px;
width:420px;
margin:auto;
}

.mode-text{
color:white;
font-size:18px;
margin-bottom:10px;
}

</style>
""", unsafe_allow_html=True)


# ----- TITLE -----
st.markdown('<div class="title">DYNOAD</div>', unsafe_allow_html=True)

st.markdown(
'<div class="subtitle">AI Powered Dynamic Advertisement Generator</div>',
unsafe_allow_html=True
)

# ----- CENTER BOX -----
st.markdown('<div class="center-box">', unsafe_allow_html=True)

st.markdown(
'<div class="mode-text">Select Advertisement Mode</div>',
unsafe_allow_html=True
)

mode = st.radio(
"",
["Single Image Advertisement", "Multi Image Advertisement"]
)

if st.button("Launch Generator", use_container_width=True):

    if mode == "Single Image Advertisement":
        st.markdown(
        '<meta http-equiv="refresh" content="0; url=http://localhost:8502">',
        unsafe_allow_html=True
        )

    if mode == "Multi Image Advertisement":
        st.markdown(
        '<meta http-equiv="refresh" content="0; url=http://localhost:8501">',
        unsafe_allow_html=True
        )

st.markdown('</div>', unsafe_allow_html=True)