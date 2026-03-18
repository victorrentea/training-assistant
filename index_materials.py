import os
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

# Use a local embeddings model (sentence-transformers) for speed and 0 cost
# Alternatively, we could use Anthropic/OpenAI if we wanted, but the user requested local FAISS.
EMBEDDINGS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_DB_PATH = "faiss_index"

def index_materials(materials_dir: str = "materials"):
    materials_path = Path(materials_dir)
    if not materials_path.exists():
        print(f"Directory {materials_dir} does not exist.")
        return

    print(f"Loading documents from {materials_dir}...")
    
    # Support for PDF and TXT/MD
    loaders = {
        ".pdf": PyPDFLoader,
        ".txt": TextLoader,
        ".md": TextLoader,
    }

    documents = []
    for ext, loader_cls in loaders.items():
        loader = DirectoryLoader(materials_dir, glob=f"**/*{ext}", loader_cls=loader_cls)
        documents.extend(loader.load())

    if not documents:
        print("No documents found for indexing.")
        return

    print(f"Found {len(documents)} documents. Splitting...")
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = text_splitter.split_documents(documents)
    
    print(f"Generated {len(chunks)} chunks. Calculating embeddings and creating FAISS index...")
    
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDINGS_MODEL)
    vectorstore = FAISS.from_documents(chunks, embeddings)
    
    vectorstore.save_local(VECTOR_DB_PATH)
    print(f"Index has been saved to {VECTOR_DB_PATH}")

if __name__ == "__main__":
    index_materials()
