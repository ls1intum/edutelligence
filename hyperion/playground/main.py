import streamlit as st

from langchain_core.messages import AIMessage, ToolMessage, HumanMessage

from hyperion.steps.draft_problem_statement.generate import generate_chat_response

st.set_page_config(layout="wide")

st.title("1. Create Problem Statement")

canvas, chat = st.columns(2)

# Initialize problem statement
if "problem_statement" not in st.session_state:
    st.session_state.problem_statement = ""

st.session_state.problem_statement = canvas.text_area("Problem Statement", value=st.session_state.problem_statement, placeholder="Write your problem statement here...", height=700, label_visibility="collapsed")

with chat.container():
    messages_container = st.container(height=700)
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        if isinstance(message, AIMessage) or isinstance(message, ToolMessage):
            with messages_container.chat_message("AI") as msg:
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with messages_container.chat_message("Human"):
                st.markdown(message.content)

    # React to user input
    if input_query := st.chat_input("Ask anything"):
        with messages_container.chat_message("Human") as msg:
            st.markdown(input_query)
        st.session_state.messages.append(HumanMessage(input_query))

        with messages_container.chat_message("AI"):
            response = generate_chat_response(
                messages=st.session_state.messages, 
                input_query=input_query, 
                draft_problem_statement=st.session_state.problem_statement
            )
            
            if isinstance(response, ToolMessage):
                st.session_state.problem_statement = response.artifact
                # Convert to AIMessage :shrug:
                response = AIMessage(response.content)                
            st.markdown(response.content)
        
        st.session_state.messages.append(response)
        st.rerun()  # To update problem_statement