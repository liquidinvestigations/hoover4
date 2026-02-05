"""RAG Chain implementation with Milvus retriever, reranker, and chat history support."""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableAssign, RunnableParallel, Runnable
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from hoover4_ai_clients import (
    Hoover4MilvusVectorStore, 
    Hoover4MilvusRetriever,
    Hoover4EmbeddingsClient,
    Hoover4NERClient,
    Hoover4RerankClient
)

logger = logging.getLogger(__name__)


def build_hoover4_rag_chain(
        # Vector store configuration
        collection_name: str = "rag_chunks",
        milvus_host: str = "http://localhost",
        milvus_port: int = 19530,
        embedding_dim: int = 1024,
        
        # AI service configuration
        embeddings_base_url: str = "http://localhost:8000/v1",
        ner_base_url: str = "http://localhost:8000/v1",
        reranker_base_url: str = "http://localhost:8000/v1",
        
        # LLM configuration (OpenAI)
        llm_api_key: Optional[str] = None,
        llm_model: str = "gpt-3.5-turbo",
        llm_temperature: float = 0.7,
        llm_base_url: Optional[str] = None,
        
        # Retrieval configuration
        initial_retrieval_k: int = 120,  # Documents retrieved before reranking
        final_retrieval_k: int = 10,     # Documents after reranking
        search_mode: str = "hybrid",     # "semantic" or "hybrid"
        
        # System prompt
        system_prompt: Optional[str] = None,
) -> Runnable:
    """
    Build a RAG Chain with Milvus retriever and reranker.
    
    Features:
    - Retrieves documents before reranking
    - Uses reranker to get top most relevant documents
    - Integrates NER for entity-aware retrieval
    - Uses OpenAI LLM for chat completion
        
        Args:
            collection_name: Name of the Milvus collection
            milvus_host: Milvus server host
            milvus_port: Milvus server port
            embedding_dim: Dimension of embeddings
            embeddings_base_url: Base URL for embeddings service
            ner_base_url: Base URL for NER service
            reranker_base_url: Base URL for reranker service
            llm_api_key: LLM API key (for OpenAI, Anthropic, etc.)
            llm_model: LLM model to use (e.g., gpt-3.5-turbo, claude-3-sonnet)
            llm_temperature: Temperature for LLM generation
            llm_base_url: Custom base URL for LLM API (optional)
            initial_retrieval_k: Number of documents to retrieve before reranking
            final_retrieval_k: Number of documents to keep after reranking
            search_mode: Search mode ("semantic" or "hybrid")
            system_prompt: Custom system prompt for the chat
        
    Returns:
        A LangChain Runnable chain that can be used with invoke, stream, batch, etc.
    """
        
        # Initialize AI service clients
    embeddings_client = Hoover4EmbeddingsClient(
        base_url=embeddings_base_url, 
        task_description="Given a question or statement, return the most relevant documents that match the question or statement."
    )
    ner_client = Hoover4NERClient(base_url=ner_base_url)
    reranker_client = Hoover4RerankClient(base_url=reranker_base_url)
    
    # Initialize OpenAI LLM
    llm_kwargs = {
        "model": llm_model,
        "temperature": llm_temperature,
    }
    
    if llm_api_key:
        llm_kwargs["api_key"] = llm_api_key
    
    if llm_base_url:
        llm_kwargs["base_url"] = llm_base_url
        
    llm = ChatOpenAI(**llm_kwargs)
    
    # Initialize vector store
    vector_store = Hoover4MilvusVectorStore(
        collection_name=collection_name,
        host=milvus_host,
        port=milvus_port,
        embedding_dim=embedding_dim,
        embedding=embeddings_client,
        search_mode=search_mode,
        ner_client=ner_client,
        use_ner_for_entities=True,
    )
    
    # Configure retriever with reranking
    retriever = Hoover4MilvusRetriever(
        vectorstore=vector_store,
        search_type=search_mode,
        search_kwargs={
            "k": initial_retrieval_k,
            "mode": search_mode,
            "include_entities_sparse": True,
        },
        reranker_client=reranker_client
    )
    
    # System prompt
    if system_prompt is None:
        system_prompt = """You are a helpful AI assistant that answers questions based on the provided context documents. 

Instructions:
1. Use the provided context documents to answer the user's question
2. If the answer cannot be found in the context, say so clearly
3. Cite specific information from the documents when possible
4. Be concise but comprehensive in your responses
5. If asked about something not in the context, politely explain that you don't have that information

Context documents:
{context}"""
    
        # Create the prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
            ("human", "{question}")
        ])
        
    def format_documents(documents: List[Document]) -> str:
        """Format retrieved documents for the prompt."""
        if not documents:
            return "No relevant documents found."
        
        formatted_docs = []
        for i, doc in enumerate(documents[:final_retrieval_k], 1):
            # Extract metadata for context
            metadata_info = []
            if doc.metadata:
                if doc.metadata.get("source_collection"):
                    metadata_info.append(f"Source: {doc.metadata['source_collection']}")
                if doc.metadata.get("source_file_hash"):
                    metadata_info.append(f"File: {doc.metadata['source_file_hash'][:8]}...")
                if doc.metadata.get("chunk_index") is not None:
                    metadata_info.append(f"Chunk: {doc.metadata['chunk_index']}")
            
            metadata_str = f" ({', '.join(metadata_info)})" if metadata_info else ""
            
            formatted_docs.append(f"Document {i}{metadata_str}:\n{doc.page_content}")
        
        return "\n\n".join(formatted_docs)
    
    chain = (
        RunnableParallel({
            "question": RunnablePassthrough(),  # Pass the question string through
            "documents": retriever  # Get documents from retriever using question
        }) |
        RunnableAssign({
            "context": lambda x: format_documents(x["documents"]),
        }) |
        RunnableAssign({
            "response": prompt | llm | StrOutputParser(),
        })
    )
    
    logger.info(
        f"Built Hoover4RAG chain with {search_mode} search using Hoover4MilvusRetriever, "
        f"{initial_retrieval_k}→{final_retrieval_k} retrieval with reranking"
    )
    
    return chain


