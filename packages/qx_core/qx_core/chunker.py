from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(
    text: str,
    chunk_size: int = 1200,
    chunk_overlap: int = 200
):

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )

    chunks = splitter.split_text(text)

    return chunks


if __name__ == "__main__":

    sample_text = """
    AI眼镜行业正在快速发展。
    """ * 1000

    chunks = chunk_text(sample_text)

    print(f"Total chunks: {len(chunks)}")

    print("\n========== FIRST CHUNK ==========\n")

    print(chunks[0])