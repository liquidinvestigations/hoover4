#!/usr/bin/env python3
"""
CLI interface for the Hoover4 RAG Chain.

This script provides a command-line interface for interacting with the RAG system,
including querying and configuration management.
"""

import argparse
import json
import logging
import os
import sys
from typing import Optional

# Add the parent directory to the path to import hoover4_rag modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hoover4_rag.chains.rag import build_hoover4_rag_chain
from langchain_core.runnables import Runnable
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RAGCLI:
    """Command-line interface for the RAG chain."""
    
    def __init__(self):
        """Initialize the CLI."""
        self.rag_chain: Optional[Runnable] = None
    
    def initialize_rag_chain(self, args: argparse.Namespace) -> Runnable:
        """Initialize the RAG chain with configuration from args."""
        config = {
            # Vector store configuration
            "collection_name": args.collection_name,
            "milvus_host": args.milvus_host,
            "milvus_port": args.milvus_port,
            "embedding_dim": args.embedding_dim,
            
            # AI service configuration
            "embeddings_base_url": args.embeddings_url,
            "ner_base_url": args.ner_url,
            "reranker_base_url": args.reranker_url,
            
            # LLM configuration (LiteLLM)
            "llm_api_key": args.llm_api_key,
            "llm_model": args.llm_model,
            "llm_temperature": args.temperature,
            "llm_base_url": args.llm_base_url,
            
            # Retrieval configuration
            "initial_retrieval_k": args.initial_k,
            "final_retrieval_k": args.final_k,
            "search_mode": args.search_mode,
            
        }
        
        # Remove None values
        config = {k: v for k, v in config.items() if v is not None}
        
        return build_hoover4_rag_chain(**config)
    
    def cmd_query(self, args: argparse.Namespace):
        """Handle the query command."""
        try:
            if not self.rag_chain:
                self.rag_chain = self.initialize_rag_chain(args)
            
            # Single query
            if args.question:
                if args.stream:
                    self._handle_streaming_query(args)
                else:
                    self._handle_single_query(args)
            
            # Interactive mode
            else:
                print("\n" + "="*80)
                print("HOOVER4 RAG CHAT INTERFACE")
                print("="*80)
                print("Commands: 'help' (show help)")
                print("Type 'exit' or press Ctrl+C to end the conversation")
                print("="*80)
                
                while True:
                    try:
                        # Get user input with >>> prompt
                        question = input("\n>>> ").strip()
                        
                        # Handle special commands
                        if question.lower() in ['exit', 'quit', 'bye']:
                            print("\nGoodbye!")
                            break
                        elif question.lower() == 'help':
                            print("\nCommands:")
                            print("- 'exit', 'quit', 'bye': End conversation")
                            print("- 'help': Show this help")
                            continue
                        elif not question:
                            continue
                        
                        # Process the question and get response
                        if args.stream:
                            self._handle_interactive_streaming(question, args)
                        else:
                            response = self.rag_chain.invoke(question)
                            
                            # Print response on new line
                            print(f"\n{response['response']}")
                            
                            # Show verbose info if requested
                            if args.verbose:
                                print(f"\n[Retrieved {len(response['documents'])} documents]")
                    
                    except KeyboardInterrupt:
                        print("\n\nGoodbye!")
                        break
                    except Exception as e:
                        print(f"\nError: {e}")
                        logger.error(f"Error in interactive mode: {e}")
        
        except Exception as e:
            logger.error(f"Error in query command: {e}")
            print(f"Error: {e}")
            sys.exit(1)
    
    def _handle_single_query(self, args: argparse.Namespace):
        """Handle a single non-streaming query."""
        response = self.rag_chain.invoke(args.question)
        
        print("\n" + "="*80)
        print("ANSWER:")
        print("="*80)
        print(response["response"])
        
        if args.verbose:
            print("\n" + "="*80)
            print("METADATA:")
            print("="*80)
            print(f"Question: {response['question']}")
            print(f"Documents Retrieved: {len(response['documents'])}")
            from datetime import datetime
            print(f"Timestamp: {datetime.now().isoformat()}")
            
            if args.show_documents:
                print("\n" + "="*80)
                print("RETRIEVED DOCUMENTS:")
                print("="*80)
                for i, doc in enumerate(response["documents"], 1):
                    print(f"\nDocument {i}:")
                    print(f"ID: {doc.id}")
                    if doc.metadata:
                        print(f"Metadata: {json.dumps(doc.metadata, indent=2)}")
                    print(f"Content: {doc.page_content[:200]}...")
    
    def _handle_streaming_query(self, args: argparse.Namespace):
        """Handle a single streaming query."""
        print("\n" + "="*80)
        print("ANSWER:")
        print("="*80)
        
        # Flush output to ensure prompt appears immediately
        sys.stdout.flush()
        
        full_answer = ""
        documents = []
        question = args.question
        
        try:
            for chunk in self.rag_chain.stream(args.question):
                # Extract response content from the chunk
                if "response" in chunk and hasattr(chunk["response"], 'content'):
                    content = chunk["response"].content
                    if content:
                        print(content, end="", flush=True)
                        full_answer += content
                
                # Store documents from first chunk that has them
                if "documents" in chunk and not documents:
                    documents = chunk["documents"]
                    question = chunk.get("question", args.question)
            
            print()  # New line after streaming
            
            if args.verbose:
                print("\n" + "="*80)
                print("METADATA:")
                print("="*80)
                print(f"Question: {question}")
                print(f"Documents Retrieved: {len(documents)}")
                from datetime import datetime
                print(f"Timestamp: {datetime.now().isoformat()}")
                
                if args.show_documents:
                    print("\n" + "="*80)
                    print("RETRIEVED DOCUMENTS:")
                    print("="*80)
                    for i, doc in enumerate(documents, 1):
                        print(f"\nDocument {i}:")
                        if hasattr(doc, 'metadata') and doc.metadata:
                            print(f"Metadata: {json.dumps(doc.metadata, indent=2)}")
                        print(f"Content: {doc.page_content[:200]}...")
                        
        except KeyboardInterrupt:
            print("\n\nStreaming interrupted by user.")
    
    def _handle_interactive_streaming(self, question: str, args: argparse.Namespace):
        """Handle streaming in interactive mode."""
        print()  # New line before response
        
        full_answer = ""
        documents = []
        
        try:
            for chunk in self.rag_chain.stream(question):
                # Extract response content from the chunk
                if "response" in chunk:
                    content = chunk["response"]
                    if content:
                        print(content, end="", flush=True)
                        full_answer += content
                
                # Store documents from first chunk that has them
                if "documents" in chunk and not documents:
                    documents = chunk["documents"]
            
            print()  # New line after streaming
            
            if args.verbose:
                print(f"\n[Retrieved {len(documents)} documents]")
                
        except KeyboardInterrupt:
            print("\n\nStreaming interrupted by user.")
    
    def cmd_config(self, args: argparse.Namespace):
        """Handle the config command."""
        try:
            if not self.rag_chain:
                self.rag_chain = self.initialize_rag_chain(args)
            
            print("Current RAG Chain Configuration:")
            print("="*50)
            print(f"Collection Name: {self.rag_chain.vector_store.collection_name}")
            print(f"Milvus Host: {self.rag_chain.vector_store.host}:{self.rag_chain.vector_store.port}")
            print(f"Embedding Dimension: {self.rag_chain.vector_store.embedding_dim}")
            print(f"Search Mode: {self.rag_chain.search_mode}")
            print(f"Initial Retrieval K: {self.rag_chain.initial_retrieval_k}")
            print(f"Final Retrieval K: {self.rag_chain.final_retrieval_k}")
            
            print(f"LLM Model: {self.rag_chain.llm.model}")
            print(f"LLM Temperature: {self.rag_chain.llm.temperature}")
            
            print("\nService URLs:")
            print(f"Embeddings: {self.rag_chain.embeddings_client.base_url}")
            print(f"NER: {self.rag_chain.ner_client.base_url}")
            print(f"Reranker: {self.rag_chain.reranker_client.base_url}")
        
        except Exception as e:
            logger.error(f"Error in config command: {e}")
            print(f"Error: {e}")
            sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Hoover4 RAG Chain CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single query
  python rag_cli.py query "What is machine learning?"
  
  # Interactive chat (terminal-based with >>> prompt)
  python rag_cli.py query
  
  # Show configuration
  python rag_cli.py config
  
  # Verbose query with document details
  python rag_cli.py query "Tell me about AI" --verbose --show-documents
  
  # Streaming query
  python rag_cli.py query "Tell me about AI" --stream
  
  # Interactive chat with streaming
  python rag_cli.py query --stream
  
        """
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query the RAG system')
    query_parser.add_argument(
        'question', 
        nargs='?', 
        help='Question to ask (if not provided, starts interactive mode)'
    )
    query_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )
    query_parser.add_argument(
        '--show-documents', '-d',
        action='store_true',
        help='Show retrieved documents (requires --verbose)'
    )
    query_parser.add_argument(
        '--stream', '-s',
        action='store_true',
        help='Stream the response in real-time'
    )
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Show current configuration')
    
    # Global options
    for subparser in [query_parser, config_parser]:
        # Vector store options
        subparser.add_argument(
            '--collection-name',
            default=os.getenv('MILVUS_COLLECTION_NAME', 'rag_chunks'),
            help='Milvus collection name (default: rag_chunks)'
        )
        subparser.add_argument(
            '--milvus-host',
            default=os.getenv('MILVUS_HOST', 'localhost'),
            help='Milvus host (default: localhost)'
        )
        subparser.add_argument(
            '--milvus-port',
            type=int,
            default=int(os.getenv('MILVUS_PORT', '19530')),
            help='Milvus port (default: 19530)'
        )
        subparser.add_argument(
            '--embedding-dim',
            type=int,
            default=1024,
            help='Embedding dimension (default: 1024)'
        )
        
        # AI service options
        subparser.add_argument(
            '--embeddings-url',
            default=os.getenv('EMBEDDING_SERVER_URL', 'http://localhost:8000/v1'),
            help='Embeddings service URL (default: http://localhost:8000/v1)'
        )
        subparser.add_argument(
            '--ner-url',
            default=os.getenv('NER_SERVER_URL', 'http://localhost:8000/v1'),
            help='NER service URL (default: http://localhost:8000/v1)'
        )
        subparser.add_argument(
            '--reranker-url',
            default=os.getenv('RERANKER_SERVER_URL', 'http://localhost:8000/v1'),
            help='Reranker service URL (default: http://localhost:8000/v1)'
        )
        
        # LLM options (LiteLLM)
        subparser.add_argument(
            '--llm-api-key',
            default=os.getenv('LLM_API_KEY'),
            help='LLM API key (can also use LLM_API_KEY env var)'
        )
        subparser.add_argument(
            '--llm-model',
            default=os.getenv('LLM_MODEL', 'gpt-3.5-turbo'),
            help='LLM model (default: gpt-3.5-turbo). Examples: gpt-3.5-turbo, gpt-4, claude-3-sonnet, claude-3-haiku'
        )
        subparser.add_argument(
            '--llm-base-url',
            default=os.getenv('LLM_BASE_URL'),
            help='Custom base URL for LLM API (optional)'
        )
        subparser.add_argument(
            '--temperature',
            type=float,
            default=float(os.getenv('LLM_TEMPERATURE', '0.7')),
            help='LLM temperature (default: 0.7)'
        )
        
        # Retrieval options
        subparser.add_argument(
            '--initial-k',
            type=int,
            default=int(os.getenv('RAG_INITIAL_K', '120')),
            help='Initial retrieval count (default: 120)'
        )
        subparser.add_argument(
            '--final-k',
            type=int,
            default=int(os.getenv('RAG_FINAL_K', '10')),
            help='Final retrieval count after reranking (default: 10)'
        )
        subparser.add_argument(
            '--search-mode',
            choices=['semantic', 'hybrid'],
            default=os.getenv('RAG_SEARCH_MODE', 'hybrid'),
            help='Search mode (default: hybrid)'
        )
        
    
    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    cli = RAGCLI()
    
    try:
        if args.command == 'query':
            cli.cmd_query(args)
        elif args.command == 'config':
            cli.cmd_config(args)
        else:
            parser.print_help()
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
