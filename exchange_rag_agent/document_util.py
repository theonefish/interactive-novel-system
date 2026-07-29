"""
第一阶段的文档加载和文档分割
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

# 后缀名 → Loader 映射表
LOADER_MAP = {
    ".txt": TextLoader,
    ".md": TextLoader,
    ".pdf": PyMuPDFLoader,
    ".docx": Docx2txtLoader,
    ".csv": CSVLoader,
}

# 支持的文档格式
SUPPORTED_FORMATS = set(LOADER_MAP.keys())


def _get_loader(filepath: str):
    """根据文件后缀名返回对应的 Loader 类"""
    suffix = Path(filepath).suffix.lower()
    if suffix not in LOADER_MAP:
        raise ValueError(f"不支持的文档格式: {suffix}，支持: {SUPPORTED_FORMATS}")
    return LOADER_MAP[suffix]


def load_documents(filepath: str):
    loader_cls = _get_loader(filepath)
    suffix = Path(filepath).suffix.lower()
    # 只有 TextLoader 和 CSVLoader 需要指定 encoding
    if suffix in (".txt", ".md", ".csv"):
        loader = loader_cls(file_path=filepath, encoding="utf-8")
    else:
        loader = loader_cls(file_path=filepath)
    docs = loader.load()
    return docs


def load_documents_from_dir(dir_path: str):
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


# 文档分割
# chunk_size: 分割文档最大token数
# chunk_overlap: 分割文档重叠token数
# separators: 分割文档的分隔符
# 优先级 separators > chunk_size > chunk_overlap
def split_documents(docs: List[Document]):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=200,
        chunk_overlap=20,
        separators=["\n\n", "\n", "。", "，", " ", "！", "？"]
    )
    chunks = splitter.split_documents(docs)
    return chunks