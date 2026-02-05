#!/usr/bin/env python3
"""
Embedding server using FastAPI and sentence-transformers
This provides an OpenAI-compatible embedding API for the multilingual-e5-large-instruct model
"""

import os
import time
import logging
from typing import List, Optional, Union
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import torch
from sentence_transformers import SentenceTransformer, CrossEncoder
import numpy as np
import uvicorn

# Try to import tiktoken for token decoding (for LangChain compatibility)
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    print("Warning: tiktoken not available. LangChain OpenAI wrapper may not work correctly.")

# Import transformers for NER (Named Entity Recognition) - required
try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    print("Error: transformers not available. NER functionality requires transformers library.")

# Import re for text processing utilities
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Multilingual E5 Embedding, Reranking & NER Server",
    version="1.0.0",
    description="OpenAI-compatible embedding API with reranking and metadata expansion capabilities."
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model variables
model = None
reranker = None
ner_model = None
model_name = "intfloat/multilingual-e5-large-instruct"
reranker_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
ner_model_name = "FacebookAI/xlm-roberta-large-finetuned-conll03-english"

# Performance optimization settings
OPTIMAL_BATCH_SIZE = int(os.getenv("OPTIMAL_BATCH_SIZE", "32"))  # Configurable batch size
MAX_SEQUENCE_LENGTH = int(os.getenv("MAX_SEQUENCE_LENGTH", "512"))  # Max tokens per sequence
ENABLE_HALF_PRECISION = os.getenv("ENABLE_HALF_PRECISION", "true").lower() == "true"
ENABLE_TORCH_COMPILE = os.getenv("ENABLE_TORCH_COMPILE", "true").lower() == "true"  # PyTorch 2.0+

class EmbeddingRequest(BaseModel):
    input: Union[str, List[str], List[List[int]]] = Field(..., description="Text, list of texts, or list of token arrays to embed")
    model: Optional[str] = Field(default=model_name, description="Model to use for embeddings")
    encoding_format: Optional[str] = Field(default="float", description="Encoding format for embeddings")
    user: Optional[str] = Field(default=None, description="User identifier")
    task_description: Optional[str] = Field(default="Given a web search query, retrieve relevant passages that answer the query", description="Task description for the embedding model")

class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int

class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: dict

class RerankRequest(BaseModel):
    query: str = Field(..., description="The search query to rerank documents against")
    documents: List[str] = Field(..., description="List of document texts to rerank")
    model: Optional[str] = Field(default=reranker_model_name, description="Reranking model to use")
    top_k: Optional[int] = Field(default=None, description="Number of top documents to return (returns all if not specified)")
    return_documents: Optional[bool] = Field(default=True, description="Whether to return document texts in response")

class RerankResult(BaseModel):
    index: int = Field(..., description="Index of the document in the original list")
    relevance_score: float = Field(..., description="Relevance score between query and document")
    document: Optional[str] = Field(default=None, description="Document text (if return_documents=True)")

class RerankResponse(BaseModel):
    object: str = "list"
    data: List[RerankResult]
    model: str
    usage: dict

class EntityInfo(BaseModel):
    text: str = Field(..., description="The text span of the entity")
    label: str = Field(..., description="The entity type (e.g., PERSON, ORG, GPE)")
    start: int = Field(..., description="Start character position in the text")
    end: int = Field(..., description="End character position in the text")
    confidence: Optional[float] = Field(default=None, description="Confidence score for the entity")
    text_index: Optional[int] = Field(default=None, description="Index of the input text this entity was extracted from (for multi-text requests)")

class NERRequest(BaseModel):
    input: Union[str, List[str]] = Field(..., description="Text or list of texts to extract entities from")
    model: Optional[str] = Field(default=ner_model_name, description="NER model to use")
    include_confidence: Optional[bool] = Field(default=True, description="Include confidence scores")
    entity_types: Optional[List[str]] = Field(default=None, description="Filter by specific entity types (e.g., ['PERSON', 'ORG'])")

class NERResponse(BaseModel):
    object: str = "list"
    data: List[EntityInfo]
    model: str
    usage: dict


def get_detailed_instruct(task_description: str, query: str) -> str:
    """Format query with instruction as required by the model"""
    return f'Instruct: {task_description}\nQuery: {query}'

def process_texts_in_batches(texts: List[str], batch_size: int = OPTIMAL_BATCH_SIZE):
    """Process texts in optimized batches for better GPU utilization"""
    for i in range(0, len(texts), batch_size):
        yield texts[i:i + batch_size]

def optimize_model_for_inference(model_instance):
    """Apply inference optimizations to model"""
    if hasattr(model_instance, 'eval'):
        model_instance.eval()
    
    # Enable half precision if supported and requested
    if ENABLE_HALF_PRECISION and torch.cuda.is_available():
        try:
            if hasattr(model_instance, 'half'):
                model_instance.half()
                logger.info("Enabled half precision (FP16) for faster inference")
        except Exception as e:
            logger.warning(f"Could not enable half precision: {e}")
    
    # Enable torch.compile for PyTorch 2.0+ (significant speedup)
    if ENABLE_TORCH_COMPILE:
        try:
            if hasattr(torch, 'compile'):
                if hasattr(model_instance, '_modules'):
                    model_instance = torch.compile(model_instance)
                    logger.info("Enabled torch.compile optimization")
        except Exception as e:
            logger.warning(f"Could not enable torch.compile: {e}")
    
    return model_instance

def decode_tokens_to_text(tokens: List[int], encoding_name: str = "cl100k_base") -> str:
    """Decode a list of tokens back to text using tiktoken"""
    if not TIKTOKEN_AVAILABLE:
        raise HTTPException(status_code=400, detail="tiktoken not available for token decoding")
    
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return encoding.decode(tokens)
    except Exception as e:
        logger.error(f"Error decoding tokens: {e}")
        raise HTTPException(status_code=400, detail=f"Error decoding tokens: {str(e)}")

def is_token_array(input_item) -> bool:
    """Check if input item is a list of integers (tokens)"""
    return (isinstance(input_item, list) and 
            len(input_item) > 0 and 
            all(isinstance(x, int) for x in input_item))


@app.on_event("startup")
async def load_models():
    """Load the embedding, reranking, and NER models on startup"""
    global model, reranker, ner_model
    logger.info("Loading models...")
    
    try:
        # Check if CUDA is available
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {device}")
        
        # Load the embedding model
        logger.info(f"Loading embedding model: {model_name}")
        model = SentenceTransformer(model_name, device=device)
        
        # Apply inference optimizations
        model = optimize_model_for_inference(model)
        
        # Set optimal batch size for embeddings
        if hasattr(model, 'encode'):
            # Configure for optimal batch processing
            model.max_seq_length = MAX_SEQUENCE_LENGTH
        
        logger.info(f"Embedding model loaded and optimized (batch_size: {OPTIMAL_BATCH_SIZE})")
        
        # Load the reranking model
        logger.info(f"Loading reranking model: {reranker_model_name}")
        reranker = CrossEncoder(reranker_model_name, device=device)
        reranker = optimize_model_for_inference(reranker)
        logger.info("Reranking model loaded and optimized successfully!")
        
        # Load the NER model
        if TRANSFORMERS_AVAILABLE:
            logger.info(f"Loading NER model: {ner_model_name}")
            try:
                ner_model = pipeline(
                    "ner", 
                    model=ner_model_name,
                    tokenizer=ner_model_name,
                    aggregation_strategy="simple",
                    device=0 if device == "cuda" else -1,
                    # Optimization: process multiple texts efficiently
                    batch_size=OPTIMAL_BATCH_SIZE,
                    # Enable model optimizations
                    torch_dtype=torch.float16 if ENABLE_HALF_PRECISION and device == "cuda" else torch.float32
                )
                logger.info("Hugging Face NER model loaded successfully!")
            except Exception as e:
                logger.error(f"Could not load {ner_model_name}: {e}")
                raise e
        else:
            logger.error("transformers not available. NER functionality requires transformers library.")
            raise ImportError("transformers library is required for NER functionality")
        
        # Print GPU memory info if available
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
            logger.info(f"GPU Memory: {gpu_memory:.1f} GB")
            
    except Exception as e:
        logger.error(f"Error loading models: {e}")
        raise e

@app.get("/")
async def root():
    """Root endpoint with server information"""
    return {
        "message": "Multilingual E5 Embedding, Reranking & FacebookAI XLM-RoBERTa NER Server", 
        "embedding_model": model_name,
        "reranking_model": reranker_model_name,
        "ner_model": ner_model_name if ner_model is not None else "disabled",
        "endpoints": [
            "/v1/embeddings",
            "/v1/rerank",
            "/v1/extract-entities",
            "/v1/models",
            "/health",
            "/performance-stats"
        ]
    }

@app.get("/v1/models")
async def list_models():
    """List available models (OpenAI compatible)"""
    return {
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "intfloat"
            }
        ]
    }

@app.post("/v1/embeddings")
async def create_embeddings(request: EmbeddingRequest):
    """Create embeddings (OpenAI compatible API)"""
    global model
    
    if model is None:
        logger.error("Model not loaded when embeddings requested")
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Handle different input types: string, list of strings, or list of token arrays
        if isinstance(request.input, str):
            texts = [request.input]
        elif isinstance(request.input, list):
            if len(request.input) == 0:
                raise HTTPException(status_code=400, detail="Input cannot be empty")
            
            # Check if this is a list of token arrays (for LangChain compatibility)
            if all(is_token_array(item) for item in request.input):
                logger.info(f"Detected tokenized input from LangChain, decoding {len(request.input)} token arrays")
                texts = []
                for token_array in request.input:
                    decoded_text = decode_tokens_to_text(token_array)
                    texts.append(decoded_text)
                    logger.debug(f"Decoded tokens {token_array[:10]}... -> '{decoded_text[:50]}...'")
            else:
                # Regular list of strings
                texts = request.input
        else:
            raise HTTPException(status_code=400, detail="Input must be string or list of strings/tokens")
        
        # Validate final texts
        if not texts or len(texts) == 0:
            raise HTTPException(status_code=400, detail="Input cannot be empty")
        
        # Check for empty strings
        if any(not str(text).strip() for text in texts):
            raise HTTPException(status_code=400, detail="Input texts cannot be empty")
        
        logger.info(f"Processing {len(texts)} text(s) for embeddings")
        
        # Use the task description from the request
        task_description = request.task_description
        
        # Process texts - add instruction for queries if needed
        processed_texts = []
        for text in texts:
            if len(text.strip()) > 0:
                processed_texts.append(get_detailed_instruct(task_description, text))
            else:
                processed_texts.append(text)
        
        # Generate embeddings with optimized batch processing
        with torch.no_grad():  # Disable gradient computation for inference
            embeddings = model.encode(
                processed_texts,
                batch_size=min(OPTIMAL_BATCH_SIZE, len(processed_texts)),
                convert_to_tensor=False,
                normalize_embeddings=True,
                show_progress_bar=False,
                device=model.device  # Ensure consistent device usage
            )
        
        # Convert to list format
        if isinstance(embeddings, np.ndarray):
            embeddings = embeddings.tolist()
        
        # Format response
        data = []
        for i, embedding in enumerate(embeddings):
            data.append(EmbeddingData(
                embedding=embedding,
                index=i
            ))
        
        # Calculate token usage (approximate)
        total_tokens = sum(len(text.split()) for text in texts)
        
        response = EmbeddingResponse(
            data=data,
            model=request.model or model_name,
            usage={
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens
            }
        )
        
        logger.info(f"Successfully generated embeddings for {len(texts)} text(s) with task: '{task_description}'")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating embeddings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating embeddings: {str(e)}")

@app.post("/v1/rerank")
async def rerank_documents(request: RerankRequest):
    """Rerank documents based on relevance to query"""
    global reranker
    
    if reranker is None:
        logger.error("Reranker model not loaded when rerank requested")
        raise HTTPException(status_code=503, detail="Reranker model not loaded")
    
    try:
        # Validate input
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")
        
        if not request.documents or len(request.documents) == 0:
            raise HTTPException(status_code=400, detail="Documents list cannot be empty")
        
        # Check for empty documents
        if any(not str(doc).strip() for doc in request.documents):
            raise HTTPException(status_code=400, detail="Documents cannot be empty")
        
        logger.info(f"Reranking {len(request.documents)} documents for query: '{request.query[:50]}...'")
        
        # Create query-document pairs for the cross-encoder
        pairs = [[request.query, doc] for doc in request.documents]
        
        # Get relevance scores with optimized batch processing
        with torch.no_grad():  # Disable gradient computation for inference
            scores = reranker.predict(
                pairs, 
                batch_size=min(OPTIMAL_BATCH_SIZE, len(pairs)),
                show_progress_bar=False
            )
        
        # Convert scores to float (in case they're numpy arrays)
        if isinstance(scores, np.ndarray):
            scores = scores.tolist()
        elif not isinstance(scores, list):
            scores = [float(scores)]
        
        # Create indexed results
        indexed_results = []
        for i, (doc, score) in enumerate(zip(request.documents, scores)):
            result = RerankResult(
                index=i,
                relevance_score=float(score),
                document=doc if request.return_documents else None
            )
            indexed_results.append(result)
        
        # Sort by relevance score (highest first)
        sorted_results = sorted(indexed_results, key=lambda x: x.relevance_score, reverse=True)
        
        # Apply top_k limit if specified
        if request.top_k is not None and request.top_k > 0:
            sorted_results = sorted_results[:request.top_k]
        
        # Calculate usage (approximate)
        total_tokens = len(request.query.split()) + sum(len(doc.split()) for doc in request.documents)
        
        response = RerankResponse(
            data=sorted_results,
            model=request.model or reranker_model_name,
            usage={
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens
            }
        )
        
        logger.info(f"Successfully reranked {len(request.documents)} documents, returning top {len(sorted_results)}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reranking documents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error reranking documents: {str(e)}")

@app.post("/v1/extract-entities")
async def extract_entities(request: NERRequest):
    """Extract named entities from text or list of texts using Hugging Face NER"""
    global ner_model
    
    if ner_model is None:
        raise HTTPException(status_code=503, detail="NER model not available")
    
    try:
        # Handle different input types: string or list of strings
        if isinstance(request.input, str):
            texts = [request.input]
        elif isinstance(request.input, list):
            if len(request.input) == 0:
                raise HTTPException(status_code=400, detail="Input cannot be empty")
            texts = request.input
        else:
            raise HTTPException(status_code=400, detail="Input must be string or list of strings")
        
        # Validate texts
        if not texts or len(texts) == 0:
            raise HTTPException(status_code=400, detail="Input cannot be empty")
        
        # Check for empty strings
        if any(not str(text).strip() for text in texts):
            raise HTTPException(status_code=400, detail="Input texts cannot be empty")
        
        logger.info(f"Extracting entities from {len(texts)} text(s)")
        
        model_used = request.model or ner_model_name
        all_entities = []
        total_tokens = 0
        
        # Optimized batch processing for NER
        if len(texts) == 1:
            # Single text - process directly
            ner_results = ner_model(texts[0])
            text_results = [ner_results] if isinstance(ner_results, list) else [[ner_results]]
        else:
            # Multiple texts - use batch processing for better efficiency
            try:
                # Process all texts in a single batch call
                ner_results = ner_model(texts)
                # Ensure results are properly structured
                if isinstance(ner_results[0], dict):
                    # Single result per text
                    text_results = [[result] for result in ner_results]
                else:
                    # Multiple results per text (already batched)
                    text_results = ner_results
            except Exception as e:
                logger.warning(f"Batch NER processing failed, falling back to sequential: {e}")
                # Fallback to sequential processing
                text_results = []
                for text in texts:
                    result = ner_model(text)
                    text_results.append(result if isinstance(result, list) else [result])
        
        # Process results from all texts
        for text_idx, text_ner_results in enumerate(text_results):
            if not isinstance(text_ner_results, list):
                text_ner_results = [text_ner_results]
                
            logger.debug(f"Processing results for text {text_idx + 1}/{len(texts)}")
            
            # Extract entities for this text
            for ent in text_ner_results:
                if not isinstance(ent, dict):
                    continue
                    
                # Convert entity label to standard format
                entity_label = ent.get('entity_group', ent.get('label', 'UNKNOWN'))
                # Remove B- and I- prefixes if present
                if entity_label.startswith(('B-', 'I-')):
                    entity_label = entity_label[2:]
                
                # Filter by entity types if specified
                if request.entity_types and entity_label not in request.entity_types:
                    continue
                
                entity_info = EntityInfo(
                    text=ent.get('word', ''),
                    label=entity_label,
                    start=ent.get('start', 0),
                    end=ent.get('end', 0),
                    confidence=ent.get('score') if request.include_confidence else None,
                    text_index=text_idx if len(texts) > 1 else None
                )
                all_entities.append(entity_info)
            
            # Calculate tokens for this text
            if text_idx < len(texts):
                total_tokens += len(texts[text_idx].split())
        
        response = NERResponse(
            data=all_entities,
            model=model_used,
            usage={
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens
            }
        )
        
        logger.info(f"Successfully extracted {len(all_entities)} entities from {len(texts)} text(s) using {model_used}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting entities: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error extracting entities: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    global model, reranker, ner_model
    core_models_loaded = model is not None and reranker is not None
    
    gpu_info = {}
    if torch.cuda.is_available():
        gpu_info = {
            "gpu_memory_total": torch.cuda.get_device_properties(0).total_memory / 1e9,
            "gpu_memory_allocated": torch.cuda.memory_allocated(0) / 1e9,
            "gpu_memory_cached": torch.cuda.memory_reserved(0) / 1e9
        }
    
    return {
        "status": "healthy" if core_models_loaded else "unhealthy",
        "embedding_model_loaded": model is not None,
        "reranker_model_loaded": reranker is not None,
        "ner_model_loaded": ner_model is not None,
        "embedding_model": model_name,
        "reranker_model": reranker_model_name,
        "ner_model": ner_model_name if ner_model is not None else "disabled",
        "transformers_available": TRANSFORMERS_AVAILABLE,
        "cuda_available": torch.cuda.is_available(),
        "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        **gpu_info,
        "performance_config": {
            "optimal_batch_size": OPTIMAL_BATCH_SIZE,
            "max_sequence_length": MAX_SEQUENCE_LENGTH,
            "half_precision_enabled": ENABLE_HALF_PRECISION,
            "torch_compile_enabled": ENABLE_TORCH_COMPILE
        }
    }

@app.get("/performance-stats")
async def performance_stats():
    """Performance statistics and optimization info"""
    global model, reranker, ner_model
    
    stats = {
        "configuration": {
            "optimal_batch_size": OPTIMAL_BATCH_SIZE,
            "max_sequence_length": MAX_SEQUENCE_LENGTH,
            "half_precision": ENABLE_HALF_PRECISION,
            "torch_compile": ENABLE_TORCH_COMPILE
        },
        "models": {
            "embedding_model": model_name,
            "reranker_model": reranker_model_name,
            "ner_model": ner_model_name
        },
        "hardware": {
            "cuda_available": torch.cuda.is_available(),
            "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0
        }
    }
    
    if torch.cuda.is_available():
        stats["gpu_memory"] = {
            "total_gb": torch.cuda.get_device_properties(0).total_memory / 1e9,
            "allocated_gb": torch.cuda.memory_allocated(0) / 1e9,
            "cached_gb": torch.cuda.memory_reserved(0) / 1e9,
            "utilization_percent": (torch.cuda.memory_allocated(0) / torch.cuda.get_device_properties(0).total_memory) * 100
        }
    
    # Recommendations based on current setup
    recommendations = []
    if torch.cuda.is_available():
        if not ENABLE_HALF_PRECISION:
            recommendations.append("Enable half precision (FP16) with ENABLE_HALF_PRECISION=true for 2x speed boost")
        if not ENABLE_TORCH_COMPILE:
            recommendations.append("Enable torch.compile with ENABLE_TORCH_COMPILE=true for additional 20-30% speedup")
        if OPTIMAL_BATCH_SIZE < 16:
            recommendations.append(f"Consider increasing batch size from {OPTIMAL_BATCH_SIZE} to 32-64 for better GPU utilization")
    else:
        recommendations.append("Consider using GPU for 10-50x speed improvement")
        if OPTIMAL_BATCH_SIZE > 8:
            recommendations.append(f"Consider reducing batch size from {OPTIMAL_BATCH_SIZE} to 4-8 for CPU processing")
    
    stats["recommendations"] = recommendations
    return stats

def main():
    """Main function to start the server"""
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "hoover4_ai_server:app",
        host=host,
        port=port,
        workers=1,  # Single worker for GPU usage
        reload=False
    )

if __name__ == "__main__":
    main()
