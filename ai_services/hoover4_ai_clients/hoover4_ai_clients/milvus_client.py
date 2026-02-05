"""Milvus vector store client with LangChain interface."""

import logging
from collections.abc import Sequence
from typing import Any, Optional, Dict, List, Tuple, Literal

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore, VectorStoreRetriever
from pydantic import Field

from pymilvus import MilvusClient, AnnSearchRequest, DataType, Function, FunctionType
from pymilvus import RRFRanker

from .ner_client import Hoover4NERClient
from .reranker_client import Hoover4RerankClient

logger = logging.getLogger(__name__)


SearchMode = Literal["semantic", "hybrid"]


class Hoover4MilvusVectorStore(VectorStore):
    """
    Milvus vector store client implementing LangChain-style VectorStore interface.

    This client wraps the official PyMilvus MilvusClient and provides a LangChain-compatible
    interface for working with Milvus while maintaining the specific functionality needed
    for our RAG system.

    NER Integration:
        The vector store can optionally use the Hoover NER client to extract entities from
        search queries and use them as targeted queries for specific sparse fields. This
        enables more precise entity-based searching.
        
        - When use_ner_for_entities=True and ner_client is provided, the NER client extracts entities from queries
        - Extracted entities are mapped to appropriate sparse fields:
          * PER (persons) -> entities_persons_sparse
          * ORG (organizations) -> entities_organizations_sparse  
          * LOC (locations) -> entities_locations_sparse
          * MISC (miscellaneous) -> no sparse field (fallback to original query)
        - If no entities are found, the original query is used for all sparse fields

    RRF (Reciprocal Rank Fusion) Configuration:
        The rrf_k parameter controls the rank cutoff threshold for Reciprocal Rank Fusion
        in hybrid search. This parameter determines how many top results from each individual
        search method (dense vector search, sparse/BM25 search) are considered for fusion.
        
        - Higher k values (e.g., 100): Consider more results from each search method,
          potentially improving recall but may include less relevant results
        - Lower k values (e.g., 20): Consider fewer results from each search method,
          potentially improving precision but may miss some relevant results
        - Default k=60: Balanced approach that works well for most use cases
        
        The RRF algorithm combines results by computing reciprocal rank scores:
        1/(rank + k) for each result, then summing these scores across all search methods.
    """

    def __init__(
        self,
        collection_name: str = "rag_chunks",
        host: str = "http://localhost",
        port: int = 19530,
        embedding_dim: int = 1024,
        embedding: Optional[Embeddings] = None,
        # -------- NEW: search config --------
        search_mode: SearchMode = "semantic",
        include_text_sparse: bool = True,
        include_entities_sparse: bool = True,
        # optional hardcoded sparse fields override; if None, we auto-discover
        sparse_fields: Optional[List[str]] = None,
        dense_weight: float = 1.0,
        entities_sparse_weight: float = 0.8,
        default_dense_params: Optional[dict] = None,     # e.g., {"nprobe": 10}
        default_sparse_params: Optional[dict] = None,    # e.g., {"drop_ratio_search": 0.2}
        # RRF ranker configuration
        rrf_k: int = 60,  # Rank cutoff for Reciprocal Rank Fusion
        # NER client configuration
        ner_client: Optional[Hoover4NERClient] = None,
        use_ner_for_entities: bool = True,
        # ------------------------------------
        **kwargs
    ):
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.embedding_dim = embedding_dim
        self._embedding = embedding

        # NEW: store hybrid config
        self.search_mode: SearchMode = search_mode
        self.include_text_sparse = include_text_sparse
        self.include_entities_sparse = include_entities_sparse
        self._user_sparse_fields = sparse_fields or []
        self.dense_weight = dense_weight
        self.entities_sparse_weight = entities_sparse_weight
        self.default_dense_params = default_dense_params or {"nprobe": 10}
        self.default_sparse_params = default_sparse_params or {"drop_ratio_search": 0.2}
        self.rrf_k = rrf_k
        
        # NER client configuration
        self.use_ner_for_entities = use_ner_for_entities
        self.ner_client = ner_client if use_ner_for_entities else None

        # Initialize the official MilvusClient
        self.client = MilvusClient(
            uri=f"{host}:{port}",
            **kwargs
        )

        logger.info(
            f"Initialized Milvus vector store for collection '{collection_name}' "
            f"using MilvusClient (mode={self.search_mode})"
        )

    @property
    def embeddings(self) -> Optional[Embeddings]:
        """Access the query embedding object if available."""
        return self._embedding

    def connect(self) -> bool:
        """Connect to Milvus database (connection is handled by MilvusClient)."""
        try:
            self.client.list_collections()
            logger.info("Connected to Milvus via MilvusClient")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            return False

    def disconnect(self) -> bool:
        """Disconnect from Milvus database."""
        try:
            self.client.close()
            logger.info("Disconnected from Milvus via MilvusClient")
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect from Milvus: {e}")
            return False

    def create_collection(self, embedding_dim: Optional[int] = None) -> bool:
        """Create the collection with appropriate schema using MilvusClient."""
        if embedding_dim:
            self.embedding_dim = embedding_dim

        try:
            if self.client.has_collection(self.collection_name):
                logger.info(f"Collection '{self.collection_name}' already exists")
                return True

            # Create schema with dynamic fields enabled (no auto_id since we'll use document ID as primary key)
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
            
            # Primary key - use document ID as the primary key (matches LangChain Document.id)
            schema.add_field("id", DataType.VARCHAR, max_length=512, is_primary=True)
            
            # Main text with analyzer for BM25
            schema.add_field("text", DataType.VARCHAR, max_length=65535, enable_analyzer=True)
            
            # Dense vector
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.embedding_dim)
            
            # Entities as plain text (for FTS) + sparse fields
            for name in ["persons", "organizations", "locations"]:
                schema.add_field(f"entities_{name}", DataType.VARCHAR, max_length=2048, enable_analyzer=True)
                schema.add_field(f"entities_{name}_sparse", DataType.SPARSE_FLOAT_VECTOR)
            
            # Add miscellaneous entity field without sparse vector
            schema.add_field("entities_miscellaneous", DataType.VARCHAR, max_length=2048)
            
            # Other scalar fields
            schema.add_field("source_collection", DataType.VARCHAR, max_length=512)
            schema.add_field("source_file_hash", DataType.VARCHAR, max_length=512)
            schema.add_field("source_page_id", DataType.INT64)
            schema.add_field("source_extracted_by", DataType.VARCHAR, max_length=512)
            schema.add_field("chunk_index", DataType.INT64)
            schema.add_field("start_char", DataType.INT64)
            schema.add_field("end_char", DataType.INT64)

            # Add BM25 functions (auto-generate sparse from text)
            # BM25 for each entities field
            for name in ["persons", "organizations", "locations"]:
                schema.add_function(Function(
                    name=f"ent_{name}_bm25",
                    input_field_names=[f"entities_{name}"],
                    output_field_names=[f"entities_{name}_sparse"],
                    function_type=FunctionType.BM25
                ))

            # Prepare index parameters
            index_params = self.client.prepare_index_params()

            # Dense vector index
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 1024}
            )

            # Sparse (BM25) vector indexes
            for f in ["entities_persons_sparse", "entities_organizations_sparse",
                      "entities_locations_sparse"]:
                index_params.add_index(
                    field_name=f,
                    index_type="SPARSE_INVERTED_INDEX",
                    metric_type="BM25"
                )

            # Helpful scalar inverted indexes
            index_params.add_index("source_collection", index_type="INVERTED")

            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
                metric_type="COSINE",
                vector_field_name="embedding",
                consistency_level="Strong"
            )

            logger.info(
                f"Created collection '{self.collection_name}' with {self.embedding_dim}-dimensional embeddings, BM25 functions, and hybrid search schema"
            )
            return True

        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return False

    def load_collection(self) -> bool:
        """Load existing collection using MilvusClient."""
        try:
            if not self.client.has_collection(self.collection_name):
                logger.error(f"Collection '{self.collection_name}' does not exist")
                return False

            self.client.load_collection(self.collection_name)
            logger.info(f"Loaded collection '{self.collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Error loading collection: {e}")
            return False

    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        """
        Add documents to the vector store (LangChain interface).
        Optimized for throughput using batch processing for embeddings and NER extraction.
        """
        try:
            if not documents:
                return []

            doc_ids = []
            texts = []
            docs_needing_embeddings = []
            docs_needing_ner = []

            # First pass: collect all texts and identify what needs processing
            for i, doc in enumerate(documents):
                doc_id = doc.id
                doc_ids.append(doc_id)
                texts.append(doc.page_content)

                # Check if embedding is needed
                if doc.metadata.get('embedding') is None and self._embedding:
                    docs_needing_embeddings.append((i, doc))

                # Check if NER extraction is needed
                if (self.use_ner_for_entities and self.ner_client and 
                    not any(doc.metadata.get(f'entities_{entity_type}') for entity_type in 
                           ['persons', 'organizations', 'locations', 'miscellaneous'])):
                    docs_needing_ner.append((i, doc))

            # Batch process embeddings if needed
            if docs_needing_embeddings and self._embedding:
                logger.info(f"Batch processing embeddings for {len(docs_needing_embeddings)} documents")
                texts_for_embedding = [doc.page_content for _, doc in docs_needing_embeddings]
                embeddings = self._embedding.embed_documents(texts_for_embedding)
                
                # Update document metadata with embeddings
                for (doc_idx, doc), embedding in zip(docs_needing_embeddings, embeddings):
                    if 'embedding' not in doc.metadata:
                        doc.metadata['embedding'] = embedding

            # Batch process NER extraction if needed
            if docs_needing_ner and self.use_ner_for_entities and self.ner_client:
                logger.info(f"Batch processing NER extraction for {len(docs_needing_ner)} documents")
                texts_for_ner = [doc.page_content for _, doc in docs_needing_ner]
                ner_results = self.ner_client.extract_entities(texts_for_ner)
                
                # Update document metadata with NER results
                for (doc_idx, doc), entities in zip(docs_needing_ner, ner_results):
                    # Only update if entities are not already present
                    if not any(doc.metadata.get(f'entities_{entity_type}') for entity_type in 
                             ['persons', 'organizations', 'locations', 'miscellaneous']):
                        doc.metadata['entities_persons'] = ' '.join(entities.get('PER', []))
                        doc.metadata['entities_organizations'] = ' '.join(entities.get('ORG', []))
                        doc.metadata['entities_locations'] = ' '.join(entities.get('LOC', []))
                        doc.metadata['entities_miscellaneous'] = ' '.join(entities.get('MISC', []))

            # Prepare data for batch insertion
            data = []
            for i, doc in enumerate(documents):
                doc_id = doc_ids[i]
                
                # Get embedding (either from metadata or raise error if still missing)
                embedding = doc.metadata.get('embedding')
                if embedding is None:
                    raise ValueError(f"No embedding provided for document {doc_id}")

                # Prepare data for insertion
                doc_data = {
                    "id": doc_id,
                    "text": doc.page_content,
                    "embedding": embedding,
                    "source_collection": doc.metadata.get('source_collection', ''),
                    "source_file_hash": doc.metadata.get('source_file_hash', ''),
                    "source_page_id": doc.metadata.get('source_page_id', 0),
                    "source_extracted_by": doc.metadata.get('source_extracted_by', ''),
                    "chunk_index": doc.metadata.get('chunk_index', 0),
                    "start_char": doc.metadata.get('start_char', 0),
                    "end_char": doc.metadata.get('end_char', 0),
                    "entities_persons": doc.metadata.get('entities_persons', ''),
                    "entities_organizations": doc.metadata.get('entities_organizations', ''),
                    "entities_locations": doc.metadata.get('entities_locations', ''),
                    "entities_miscellaneous": doc.metadata.get('entities_miscellaneous', ''),
                }
                
                data.append(doc_data)

            # Batch insert to Milvus
            self.client.insert(self.collection_name, data)
            logger.info(f"Successfully added {len(data)} documents to Milvus using batch processing")
            return doc_ids

        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            raise

    # ------------------------- SEARCH HELPERS (NEW) -------------------------

    def _extract_entities_from_query(self, query: str) -> Dict[str, List[str]]:
        """
        Extract entities from query text using the NER client.
        
        Args:
            query: The search query text
            
        Returns:
            Dictionary mapping entity types to lists of entity texts
        """
        if not self.use_ner_for_entities or not self.ner_client:
            return {"PER": [], "ORG": [], "LOC": [], "MISC": []}
        
        try:
            # Extract entities from the query
            entities_results = self.ner_client.extract_entities([query])
            if entities_results:
                return entities_results[0]  # Return entities for the single query
            return {"PER": [], "ORG": [], "LOC": [], "MISC": []}
        except Exception as e:
            logger.warning(f"Failed to extract entities from query '{query}': {e}")
            return {"PER": [], "ORG": [], "LOC": [], "MISC": []}

    def _get_entity_sparse_field_mapping(self) -> Dict[str, str]:
        """
        Get mapping from entity types to sparse field names.
        
        Returns:
            Dictionary mapping entity types to sparse field names
        """
        return {
            "PER": "entities_persons_sparse",
            "ORG": "entities_organizations_sparse", 
            "LOC": "entities_locations_sparse",
            "MISC": None  # Miscellaneous entities don't have a sparse field
        }

    def _default_output_fields(self) -> List[str]:
        return [
            "id", "text", "source_collection", "source_file_hash",
            "source_page_id", "source_extracted_by", "chunk_index",
            "start_char", "end_char", "entities_persons", "entities_organizations",
            "entities_locations", "entities_miscellaneous"
        ]

    def _discover_sparse_fields(
        self,
        include_text_sparse: bool,
        include_entities_sparse: bool,
        user_sparse_fields: Optional[List[str]] = None,
    ) -> List[str]:
        """Return the list of sparse fields to use for BM25/sparse search."""
        # honor user-specified list if provided
        if user_sparse_fields:
            return user_sparse_fields

        candidates = []
        if include_entities_sparse:
            candidates.extend([
                "entities_persons_sparse",
                "entities_organizations_sparse",
                "entities_locations_sparse",
            ])

        # Keep only existing fields (avoid runtime errors if schema not updated yet)
        try:
            desc = self.client.describe_collection(self.collection_name)
            existing = {f["name"] for f in desc.get("schema", {}).get("fields", [])}
            return [f for f in candidates if f in existing]
        except Exception:
            # If describe fails, return candidates and let Milvus raise on missing fields
            return candidates

    def _hit_to_document(self, hit: Dict[str, Any]) -> Document:
        metadata = {
            "source_collection": hit.get("source_collection"),
            "source_file_hash": hit.get("source_file_hash"),
            "source_page_id": hit.get("source_page_id"),
            "source_extracted_by": hit.get("source_extracted_by"),
            "chunk_index": hit.get("chunk_index"),
            "start_char": hit.get("start_char"),
            "end_char": hit.get("end_char"),
            "entities_persons": hit.get("entities_persons"),
            "entities_organizations": hit.get("entities_organizations"),
            "entities_locations": hit.get("entities_locations"),
            "entities_miscellaneous": hit.get("entities_miscellaneous"),
        }
        return Document(
            id=hit.get("id"),  # Use the "id" field which is now the primary key
            page_content=hit.get("text"),
            metadata=metadata
        )

    # ------------------------- PUBLIC SEARCH METHODS -------------------------

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        *,
        # NEW: optional per-call override
        mode: Optional[SearchMode] = None,
        include_text_sparse: Optional[bool] = None,
        include_entities_sparse: Optional[bool] = None,
        dense_weight: Optional[float] = None,
        entities_sparse_weight: Optional[float] = None,
        dense_params: Optional[dict] = None,
        sparse_params: Optional[dict] = None,
        sparse_fields: Optional[List[str]] = None,
        output_fields: Optional[List[str]] = None,
        rrf_k: Optional[int] = None,  # Override RRF rank cutoff
        **kwargs
    ) -> list[Document]:
        results = self.similarity_search_with_score(
            query=query,
            k=k,
            mode=mode,
            include_text_sparse=include_text_sparse,
            include_entities_sparse=include_entities_sparse,
            dense_weight=dense_weight,
            entities_sparse_weight=entities_sparse_weight,
            dense_params=dense_params,
            sparse_params=sparse_params,
            sparse_fields=sparse_fields,
            output_fields=output_fields,
            rrf_k=rrf_k,
            **kwargs
        )
        return [doc for doc, _ in results]

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        *,
        # NEW: optional per-call override
        mode: Optional[SearchMode] = None,
        include_text_sparse: Optional[bool] = None,
        include_entities_sparse: Optional[bool] = None,
        dense_weight: Optional[float] = None,
        entities_sparse_weight: Optional[float] = None,
        dense_params: Optional[dict] = None,
        sparse_params: Optional[dict] = None,
        sparse_fields: Optional[List[str]] = None,
        output_fields: Optional[List[str]] = None,
        rrf_k: Optional[int] = None,  # Override RRF rank cutoff
        **kwargs
    ) -> list[tuple[Document, float]]:
        """
        Search for similar documents with scores (LangChain interface).
        Supports 'semantic' (dense only) or 'hybrid' (dense + sparse/BM25).
        """
        try:
            if not self.client.has_collection(self.collection_name):
                raise ValueError(f"Collection '{self.collection_name}' does not exist")

            # Resolve config (constructor defaults → per-call overrides)
            eff_mode = (mode or self.search_mode)
            eff_include_text_sparse = self.include_text_sparse if include_text_sparse is None else include_text_sparse
            eff_include_entities_sparse = (
                self.include_entities_sparse if include_entities_sparse is None else include_entities_sparse
            )
            eff_dense_weight = self.dense_weight if dense_weight is None else dense_weight
            eff_entities_sparse_weight = (
                self.entities_sparse_weight if entities_sparse_weight is None else entities_sparse_weight
            )
            eff_dense_params = self.default_dense_params if dense_params is None else dense_params
            eff_sparse_params = self.default_sparse_params if sparse_params is None else sparse_params
            eff_output_fields = output_fields or self._default_output_fields()
            eff_sparse_fields = sparse_fields or self._user_sparse_fields
            eff_rrf_k = self.rrf_k if rrf_k is None else rrf_k

            if eff_mode == "hybrid":
                return self._hybrid_search_internal(
                    query=query,
                    k=k,
                    include_text_sparse=eff_include_text_sparse,
                    include_entities_sparse=eff_include_entities_sparse,
                    dense_weight=eff_dense_weight,
                    entities_sparse_weight=eff_entities_sparse_weight,
                    dense_params=eff_dense_params,
                    sparse_params=eff_sparse_params,
                    output_fields=eff_output_fields,
                    user_sparse_fields=eff_sparse_fields,
                    rrf_k=eff_rrf_k,
                )
            # else: semantic
            return self._dense_search_internal(
                query=query,
                k=k,
                dense_params=eff_dense_params,
                output_fields=eff_output_fields
            )

        except Exception as e:
            logger.error(f"Error in similarity search: {e}")
            raise

    def similarity_search_by_vector(
        self,
        embedding: list[float],
        k: int = 4,
        *,
        # NEW: accept mode but ignore for vector-based (dense only)
        mode: Optional[SearchMode] = None,
        dense_params: Optional[dict] = None,
        output_fields: Optional[List[str]] = None,
        **kwargs
    ) -> list[Document]:
        """
        Return docs most similar to embedding vector (dense only).
        """
        try:
            if not self.client.has_collection(self.collection_name):
                raise ValueError(f"Collection '{self.collection_name}' does not exist")

            search_params = {
                "metric_type": "COSINE",
                "params": dense_params or self.default_dense_params
            }

            results = self.client.search(
                collection_name=self.collection_name,
                data=[embedding],
                anns_field="embedding",
                search_params=search_params,
                limit=k,
                output_fields=output_fields or self._default_output_fields()
            )

            documents = []
            for hit in results[0]:
                documents.append(self._hit_to_document(hit))

            logger.debug(f"Found {len(documents)} similar documents by vector")
            return documents

        except Exception as e:
            logger.error(f"Error in similarity search by vector: {e}")
            raise

    # ------------------------- INTERNAL SEARCH ENGINES (NEW) -------------------------

    def _dense_search_internal(
        self,
        query: str,
        k: int,
        dense_params: dict,
        output_fields: List[str],
    ) -> List[Tuple[Document, float]]:
        if self._embedding is None:
            raise ValueError("No embedding function provided")

        embedding = self._embedding.embed_query(query)
        search_params = {"metric_type": "COSINE", "params": dense_params}

        results = self.client.search(
            collection_name=self.collection_name,
            data=[embedding],
            anns_field="embedding",
            search_params=search_params,
            limit=k,
            output_fields=output_fields
        )

        documents_with_scores: List[Tuple[Document, float]] = []
        for hit in results[0]:
            # Convert distance to similarity in [0,1] for cosine
            distance = float(hit.get("distance", 0.0))
            similarity = max(0.0, min(1.0, 1.0 - distance))
            documents_with_scores.append((self._hit_to_document(hit), similarity))
        return documents_with_scores

    def _hybrid_search_internal(
        self,
        query: str,
        k: int,
        include_text_sparse: bool,
        include_entities_sparse: bool,
        dense_weight: float,
        entities_sparse_weight: float,
        dense_params: dict,
        sparse_params: dict,
        output_fields: List[str],
        user_sparse_fields: Optional[List[str]] = None,
        rrf_k: int = 60,
    ) -> List[Tuple[Document, float]]:
        if self._embedding is None:
            raise ValueError("No embedding function provided for dense part of hybrid search.")

        # Build sparse vector field list
        sparse_fields = self._discover_sparse_fields(
            include_text_sparse=include_text_sparse,
            include_entities_sparse=include_entities_sparse,
            user_sparse_fields=user_sparse_fields,
        )

        requests: List[AnnSearchRequest] = []

        # Dense request
        dense_vec = self._embedding.embed_query(query)
        requests.append(AnnSearchRequest(
            data=[dense_vec],
            anns_field="embedding",
            param=dense_params,
            limit=k,
        ))

        # Sparse requests (BM25) for each selected sparse field
        # Extract entities from query if NER is enabled
        extracted_entities = self._extract_entities_from_query(query) if self.use_ner_for_entities else {}
        entity_mapping = self._get_entity_sparse_field_mapping()
        
        for sf in sparse_fields:
            # Determine the appropriate query for this sparse field
            query_for_field = query  # Default to original query
            
            # If this is an entity sparse field, try to use extracted entities
            if self.use_ner_for_entities and extracted_entities:
                # Find which entity type this sparse field corresponds to
                for entity_type, sparse_field_name in entity_mapping.items():
                    if sparse_field_name == sf and entity_type in extracted_entities:
                        entities = extracted_entities[entity_type]
                        if entities:
                            # Use extracted entities as the query for this field
                            query_for_field = " ".join(entities)
                            logger.debug(f"Using extracted {entity_type} entities '{query_for_field}' for sparse field {sf}")
                        break
            
            requests.append(AnnSearchRequest(
                data=[query_for_field],  # Use entity-specific query or original query
                anns_field=sf,
                param=sparse_params,
                limit=k
            ))

        # Build weights aligned with requests order (first is dense)
        weights: List[float] = [dense_weight]
        for sf in sparse_fields:
            weights.append(entities_sparse_weight)

        # Call hybrid_search; pass weights via a common 'rerank' shape if supported
        results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=requests,
            limit=k,
            output_fields=output_fields,
            ranker=RRFRanker(k=rrf_k)
        )

        docs_with_scores: List[Tuple[Document, float]] = []
        for hit in results[0]:  # single query
            # Prefer 'score' (already fused). If only 'distance', convert (heuristic).
            score = hit.get("score", None)
            if score is None:
                dist = float(hit.get("distance", 0.0))
                score = max(0.0, min(1.0, 1.0 - dist))
            docs_with_scores.append((self._hit_to_document(hit), float(score)))
        return docs_with_scores

    def hybrid_search(
        self, 
        query: str, 
        k: int = 4, 
        use_entities: bool = True, 
        weights: Optional[List[float]] = None,
        rrf_k: Optional[int] = None,
        **kwargs
    ) -> List[Tuple[Document, float]]:
        """
        Dedicated hybrid search method using new AnnSearchRequest format.
        
        Args:
            query: Search query text
            k: Number of results to return
            use_entities: Whether to include entity-based searches
            weights: Optional custom weights for fusion (default: auto-generated)
            rrf_k: Rank cutoff for Reciprocal Rank Fusion (default: uses constructor value)
            **kwargs: Additional search parameters
        """
        if self._embedding is None:
            raise ValueError("No embedding function provided")

        dense_q = self._embedding.embed_query(query)
        reqs = []

        # Dense semantic over main text
        reqs.append(AnnSearchRequest(
            data=[dense_q],
            anns_field="embedding",
            param={"nprobe": 10},
            limit=k
        ))

        if use_entities:
            # Extract entities from query if NER is enabled
            extracted_entities = self._extract_entities_from_query(query) if self.use_ner_for_entities else {}
            entity_mapping = self._get_entity_sparse_field_mapping()
            
            # Sparse BM25 over entities
            for f in ["entities_persons_sparse", "entities_organizations_sparse",
                      "entities_locations_sparse"]:
                # Determine the appropriate query for this sparse field
                query_for_field = query  # Default to original query
                
                # If this is an entity sparse field, try to use extracted entities
                if self.use_ner_for_entities and extracted_entities:
                    # Find which entity type this sparse field corresponds to
                    for entity_type, sparse_field_name in entity_mapping.items():
                        if sparse_field_name == f and entity_type in extracted_entities:
                            entities = extracted_entities[entity_type]
                            if entities:
                                # Use extracted entities as the query for this field
                                query_for_field = " ".join(entities)
                                logger.debug(f"Using extracted {entity_type} entities '{query_for_field}' for sparse field {f}")
                            break
                
                reqs.append(AnnSearchRequest(
                    data=[query_for_field],  # Use entity-specific query or original query
                    anns_field=f,
                    param={"drop_ratio_search": 0.2},
                    limit=k
                ))

        # Auto-generate weights if not provided
        if weights is None:
            weights = [1.0]  # dense weight
            if use_entities:
                weights.extend([1.0] * 3)  # entity sparse weights

        # Resolve rrf_k parameter
        eff_rrf_k = self.rrf_k if rrf_k is None else rrf_k

        # Run hybrid search (Milvus fuses the requests)
        try:
            results = self.client.hybrid_search(
                collection_name=self.collection_name,
                reqs=reqs,
                limit=k,
                ranker=RRFRanker(k=eff_rrf_k),
                output_fields=self._default_output_fields()
            )
            
            docs_with_scores: List[Tuple[Document, float]] = []
            for hit in results[0]:  # single query
                score = hit.get("score", hit.get("distance", 0.0))
                docs_with_scores.append((self._hit_to_document(hit), float(score)))
            return docs_with_scores
            
        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            raise

    # ------------------------- ADMIN / MISC -------------------------

    def delete(self, ids: Optional[list[str]] = None, **kwargs: Any) -> Optional[bool]:
        """
        Delete by vector ID or other criteria.
        """
        try:
            if not self.client.has_collection(self.collection_name):
                logger.error(f"Collection '{self.collection_name}' does not exist")
                return False

            if ids is None:
                expr = "id != ''"
            else:
                id_list = "', '".join(ids)
                expr = f"id in ['{id_list}']"

            self.client.delete(self.collection_name, filter=expr)
            logger.info(f"Deleted documents with expression: {expr}")
            return True

        except Exception as e:
            logger.error(f"Error deleting documents: {e}")
            return False

    def get_by_ids(self, ids: Sequence[str]) -> list[Document]:
        """
        Get documents by their IDs.
        """
        try:
            if not self.client.has_collection(self.collection_name):
                logger.error(f"Collection '{self.collection_name}' does not exist")
                return []

            id_list = "', '".join(ids)
            expr = f"id in ['{id_list}']"

            results = self.client.query(
                collection_name=self.collection_name,
                filter=expr,
                output_fields=self._default_output_fields()
            )

            documents = []
            for result in results:
                documents.append(self._hit_to_document(result))

            logger.debug(f"Retrieved {len(documents)} documents by IDs")
            return documents

        except Exception as e:
            logger.error(f"Error getting documents by IDs: {e}")
            return []

    def _select_relevance_score_fn(self):
        """The 'correct' relevance function for cosine similarity."""
        return self._cosine_relevance_score_fn

    def as_retriever(self, **kwargs: Any) -> "Hoover4MilvusRetriever":
        """
        Return Hoover4MilvusRetriever initialized from this VectorStore.
        
        Args:
            **kwargs: Keyword arguments to pass to the retriever.
                Can include:
                - reranker_client: Optional Hoover4RerankClient for document reranking
                - search_type: Type of search ("similarity", "hybrid", "similarity_score_threshold")
                - search_kwargs: Additional search parameters
                - All other parameters supported by Hoover4MilvusRetriever
        
        Returns:
            Hoover4MilvusRetriever: Retriever instance for this VectorStore
        """
        return Hoover4MilvusRetriever(vectorstore=self, **kwargs)

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Embeddings,
        metadatas: Optional[list[dict]] = None,
        *,
        ids: Optional[list[str]] = None,
        collection_name: str = "rag_chunks",
        host: str = "localhost",
        port: int = 19530,
        embedding_dim: int = 1024,
        ner_client: Optional[Hoover4NERClient] = None,
        **kwargs: Any,
    ) -> "Hoover4MilvusVectorStore":
        """
        Return VectorStore initialized from texts and embeddings.
        """
        vectorstore = cls(
            collection_name=collection_name,
            host=host,
            port=port,
            embedding_dim=embedding_dim,
            embedding=embedding,
            ner_client=ner_client,
            **kwargs
        )

        vectorstore.connect()
        vectorstore.create_collection()

        documents = []
        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas and i < len(metadatas) else {}
            doc_id = ids[i] if ids and i < len(ids) else None

            documents.append(Document(id=doc_id, page_content=text, metadata=metadata))

        vectorstore.add_documents(documents)
        vectorstore.load_collection()
        return vectorstore

    def get_collection_stats(self) -> Dict[str, Any]:
        try:
            return self.client.get_collection_stats(self.collection_name)
        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            return {}

    def describe_collection(self) -> Dict[str, Any]:
        try:
            return self.client.describe_collection(self.collection_name)
        except Exception as e:
            logger.error(f"Error describing collection: {e}")
            return {}

    def drop_collection(self) -> bool:
        try:
            self.client.drop_collection(self.collection_name)
            logger.info(f"Dropped collection '{self.collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Error dropping collection: {e}")
            return False

    def flush_collection(self) -> bool:
        try:
            self.client.flush(self.collection_name)
            logger.info(f"Flushed collection '{self.collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Error flushing collection: {e}")
            return False


class Hoover4MilvusRetriever(VectorStoreRetriever):
    """
    Hoover4 Milvus retriever with optional reranker integration.
    
    This retriever extends the standard VectorStoreRetriever to provide additional
    functionality specific to the Hoover4 Milvus vector store, including:
    - Optional document reranking using Hoover4RerankClient
    - Support for hybrid search modes
    - Entity-aware search capabilities
    """
    
    vectorstore: Hoover4MilvusVectorStore
    """The Hoover4 Milvus vector store to use for retrieval."""
    
    reranker_client: Optional[Hoover4RerankClient] = None
    """Optional reranker client for document reranking."""
    
    search_type: str = "similarity"
    """Type of search to perform. Can be 'similarity', 'hybrid', or 'similarity_score_threshold'."""
    
    search_kwargs: dict = Field(default_factory=dict)
    """Keyword arguments to pass to the search function."""
    
    # Extended allowed search types to include hybrid
    allowed_search_types = (
        "similarity",
        "similarity_score_threshold", 
        "hybrid"
    )
    
    def __init__(self, **kwargs):
        # Extract search_type for validation
        search_type = kwargs.get('search_type', 'similarity')
        if search_type not in self.allowed_search_types:
            raise ValueError(f"search_type of {search_type} not allowed. Valid values are: {self.allowed_search_types}")
        super().__init__(**kwargs)
    
    def _get_relevant_documents(
        self, 
        query: str, 
        *, 
        run_manager: Any = None, 
        **kwargs: Any
    ) -> list[Document]:
        """
        Get documents relevant to a query.
        
        Args:
            query: The query string
            run_manager: Optional callback manager
            **kwargs: Additional search parameters
            
        Returns:
            List of relevant documents
        """
        # Merge search_kwargs with any additional kwargs
        search_params = {**self.search_kwargs, **kwargs}
        
        if self.search_type == "similarity":
            docs = self.vectorstore.similarity_search(query, **search_params)
        elif self.search_type == "hybrid":
            # Use hybrid search with scores, then extract documents
            docs_with_scores = self.vectorstore.hybrid_search(
                query, **search_params
            )
            docs = [doc for doc, _ in docs_with_scores]
        elif self.search_type == "similarity_score_threshold":
            docs_and_similarities = (
                self.vectorstore.similarity_search_with_score(
                    query, **search_params
                )
            )
            docs = [doc for doc, _ in docs_and_similarities]
        else:
            raise ValueError(f"search_type of {self.search_type} not allowed.")
        
        # Apply reranking if reranker client is available
        if self.reranker_client and docs:
            docs = self._rerank_documents(query, docs)
        
        return docs
    
    async def _aget_relevant_documents(
        self, 
        query: str, 
        *, 
        run_manager: Any = None, 
        **kwargs: Any
    ) -> list[Document]:
        """
        Async get documents relevant to a query.
        
        Args:
            query: The query string
            run_manager: Optional callback manager
            **kwargs: Additional search parameters
            
        Returns:
            List of relevant documents
        """
        # For now, use the sync version since the vectorstore doesn't have async methods
        # In the future, this could be enhanced with proper async support
        return self._get_relevant_documents(query, run_manager=run_manager, **kwargs)
    
    def _rerank_documents(self, query: str, documents: list[Document]) -> list[Document]:
        """
        Rerank documents using the reranker client.
        
        Args:
            query: The search query
            documents: List of documents to rerank
            
        Returns:
            List of reranked documents
        """
        if not self.reranker_client or not documents:
            return documents
        
        try:
            # Extract document texts for reranking
            doc_texts = [doc.page_content for doc in documents]
            
            # Get reranking results
            rerank_results = self.reranker_client.rerank_documents(
                query=query,
                documents=doc_texts,
                return_documents=False  # We don't need the text back, just the order
            )
            
            # Sort documents by reranking results
            reranked_docs = []
            for original_index, relevance_score, _ in rerank_results:
                if original_index < len(documents):
                    doc = documents[original_index]
                    # Add reranking score to metadata for transparency
                    if hasattr(doc, 'metadata') and doc.metadata is not None:
                        doc.metadata['rerank_score'] = relevance_score
                    reranked_docs.append(doc)
            
            logger.debug(f"Reranked {len(documents)} documents using reranker client")
            return reranked_docs
            
        except Exception as e:
            logger.warning(f"Failed to rerank documents: {e}. Returning original order.")
            return documents
    
    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        """
        Add documents to the vectorstore.
        
        Args:
            documents: Documents to add to the vectorstore
            **kwargs: Additional keyword arguments
            
        Returns:
            List of IDs of the added documents
        """
        return self.vectorstore.add_documents(documents, **kwargs)
    
    async def aadd_documents(
        self, documents: list[Document], **kwargs: Any
    ) -> list[str]:
        """
        Async add documents to the vectorstore.
        
        Args:
            documents: Documents to add to the vectorstore
            **kwargs: Additional keyword arguments
            
        Returns:
            List of IDs of the added documents
        """
        return await self.vectorstore.aadd_documents(documents, **kwargs)

