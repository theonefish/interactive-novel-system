"""通过Chroma数据库进行文档片段向量化并入库"""
import os
import sys
from pathlib import Path
from exchange_rag_agent.document_util import load_documents, split_documents

from models.llm import embeddings

# 将项目根目录添加到 sys.path，确保模块导入正常
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_chroma import Chroma

def create_index(file_path: str):
    if not os.path.isabs(file_path):
        file_path = str(PROJECT_ROOT / file_path)

    docs = load_documents(file_path)
    chunks = split_documents(docs)

    vector_store = Chroma(
        host="localhost",
        port=8081,
        collection_name="default",
        embedding_function=embeddings,
    )
    vector_store.add_documents(chunks)
    return vector_store


def create_index_from_dir(dir_path: str = None):
    """遍历知识库目录，加载所有文档并入库"""
    if dir_path is None:
        dir_path = str(PROJECT_ROOT / "knowledge_base")

    from document_util import load_documents_from_dir

    docs = load_documents_from_dir(dir_path)
    if not docs:
        print("知识库目录为空，无文档可入库")
        return None

    chunks = split_documents(docs)
    print(f"共加载 {len(docs)} 个文档，分割为 {len(chunks)} 个片段")

    vector_store = Chroma(
        host="localhost",
        port=8081,
        collection_name="default",
        embedding_function=embeddings,
    )
    vector_store.add_documents(chunks)
    print(f"入库完成，向量库路径: {PROJECT_ROOT / 'data' / 'chroma_index'}")
    return vector_store


if __name__ == "__main__":
    create_index_from_dir()