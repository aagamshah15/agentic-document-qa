import os
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException
from api.models import QueryRequest, QueryResponse
from services.document_processor import process_pdf
from services.vector_store import add_documents_to_store
from services.agent import get_agent_executor

router = APIRouter()

# Directory to temporarily store uploaded files
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    try:
        # Save uploaded file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process PDF and split into chunks
        chunks = process_pdf(file_path)
        
        # Add chunks to vector store
        add_documents_to_store(chunks)
        
        return {"message": f"Successfully processed {file.filename} and added {len(chunks)} chunks to the database."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query", response_model=QueryResponse)
async def query_agent(request: QueryRequest):
    try:
        agent_executor = get_agent_executor()
        
        # Execute the agent
        response = agent_executor.invoke({"input": request.query})
        
        return QueryResponse(answer=response["output"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
