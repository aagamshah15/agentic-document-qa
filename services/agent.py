from langchain_ollama import ChatOllama
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

from core.config import settings
from services.vector_store import get_retriever

def get_agent_executor():
    """
    Creates and returns a LangChain AgentExecutor equipped with the document retriever.
    """
    retriever = get_retriever()
    
    # Create the retriever tool
    llm = ChatOllama(model="llama3", temperature=0)

    # Define a simple system prompt that handles both context and general knowledge
    system_prompt = (
        "You are a helpful Q&A assistant. "
        "Use the following pieces of retrieved context to answer the user's question. "
        "If the context doesn't contain the answer, you can use your general knowledge to answer. "
        "If you don't know the answer, just say that you don't know. "
        "Keep your answer concise and helpful.\n\n"
        "Context:\n{context}"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])

    # Create the document chain
    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    
    # Create the retrieval chain
    rag_chain = create_retrieval_chain(retriever, question_answer_chain)
    
    # Return a wrapper that mimics the executor's invoke method so api/routes.py doesn't break
    class ChainWrapper:
        def invoke(self, inputs):
            result = rag_chain.invoke({"input": inputs["input"]})
            return {"output": result["answer"]}
            
    return ChainWrapper()
