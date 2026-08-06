"""文档加载和分割 - 用于 RAG 知识库入库

参考 exchange_rag_agent/document_util.py 实现。
支持 txt、md、pdf、docx、csv 格式。
"""

import os
from pathlib import Path
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    CSVLoader,
    Docx2txtLoader,
    PyMuPDFLoader,
    TextLoader,
)
from langchain_core.documents import Document


# 后缀名 → Loader 映射
LOADER_MAP = {
    ".txt": TextLoader,
    ".md": TextLoader,
    ".pdf": PyMuPDFLoader,
    ".docx": Docx2txtLoader,
    ".csv": CSVLoader,
}
# 支持的格式
SUPPORTED_FORMATS = set(LOADER_MAP.keys())


def _get_loader(filepath: str):
    """根据文件后缀名返回对应的 Loader 类"""
    suffix = Path(filepath).suffix.lower()
    if suffix not in LOADER_MAP:
        raise ValueError(f"不支持的文档格式: {suffix}，支持: {SUPPORTED_FORMATS}")
    return LOADER_MAP[suffix]


def load_documents(filepath: str) -> List[Document]:
    """加载单个文件"""
    loader_cls = _get_loader(filepath)
    suffix = Path(filepath).suffix.lower()
    if suffix in (".txt", ".md", ".csv"):
        loader = loader_cls(file_path=filepath, encoding="utf-8")
    else:
        loader = loader_cls(file_path=filepath)
    return loader.load()


def load_documents_from_dir(dir_path: str) -> List[Document]:
    """遍历目录，加载所有支持的文档"""
    all_docs = []
    for root, _, files in os.walk(dir_path):
        for file in files:
            filepath = os.path.join(root, file)
            suffix = Path(filepath).suffix.lower()
            if suffix in SUPPORTED_FORMATS:
                docs = load_documents(filepath)
                all_docs.extend(docs)
    return all_docs


def split_documents(docs: List[Document]) -> List[Document]:
    """文档分割

    Args:
        docs: 原始文档列表

    Returns:
        分割后的文档片段列表
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=200,
        chunk_overlap=20,
        separators=["\n\n", "\n", "。", "，", " ", "！", "？"],
    )
    return splitter.split_documents(docs)


def create_index(file_path: str):
    """将单个文档入库到 ChromaDB"""
    from src.tools.rag_tool import _get_vector_store

    docs = load_documents(file_path)
    chunks = split_documents(docs)

    vector_store = _get_vector_store()
    vector_store.add_documents(chunks)
    return vector_store


def create_index_from_dir(dir_path: str = None):
    """遍历知识库目录，加载所有文档并入库"""
    from src.tools.rag_tool import _get_vector_store

    if dir_path is None:
        dir_path = str(Path(__file__).resolve().parent.parent.parent / "knowledge_base")

    docs = load_documents_from_dir(dir_path)
    if not docs:
        print("知识库目录为空，无文档可入库")
        return None

    chunks = split_documents(docs)
    print(f"共加载 {len(docs)} 个文档，分割为 {len(chunks)} 个片段")

    vector_store = _get_vector_store()
    vector_store.add_documents(chunks)
    print("入库完成")
    return vector_store


if __name__ == "__main__":
    create_index_from_dir()
