from dotenv import load_dotenv
load_dotenv(verbose=True)

from markitdown import MarkItDown
import io
from typing import BinaryIO, Any
import camelot
import tempfile
from markitdown.converters import PdfConverter
from markitdown.converters._pdf_converter import _dependency_exc_info
from markitdown._stream_info import StreamInfo
from markitdown._base_converter import DocumentConverterResult
from markitdown._exceptions import MissingDependencyException, MISSING_DEPENDENCY_MESSAGE
import pdfminer
import pdfminer.high_level

from src.logger import logger


def read_tables_from_stream(file_stream):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as temp_pdf:
        temp_pdf.write(file_stream.read())
        temp_pdf.flush()
        tables = camelot.read_pdf(temp_pdf.name, flavor="lattice")
        return tables

class PdfWithTableConverter(PdfConverter):
    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        # Check the dependencies
        if _dependency_exc_info is not None:
            raise MissingDependencyException(
                MISSING_DEPENDENCY_MESSAGE.format(
                    converter=type(self).__name__,
                    extension=".pdf",
                    feature="pdf",
                )
            ) from _dependency_exc_info[
                1
            ].with_traceback(  # type: ignore[union-attr]
                _dependency_exc_info[2]
            )

        assert isinstance(file_stream, io.IOBase)  # for mypy

        tables = read_tables_from_stream(file_stream)
        num_tables = tables.n
        if num_tables == 0:
            return DocumentConverterResult(
                markdown=pdfminer.high_level.extract_text(file_stream),
            )
        else:
            markdown_content = pdfminer.high_level.extract_text(file_stream)
            table_content = ""
            for i in range(num_tables):
                table = tables[i].df
                table_content += f"Table {i + 1}:\n" + table.to_markdown(index=False) + "\n\n"
            markdown_content += "\n\n" + table_content
            return DocumentConverterResult(
                markdown=markdown_content,
            )

class MarkitdownConverter():
    def __init__(self, timeout: int = 30):

        self.timeout = timeout
        
        self.client = MarkItDown(
            enable_plugins=True,
            llm_model="gpt-4.1",
            llm_prompt="Please describe the content of the image in as much detail as possible."
        )

        removed_converters = [PdfConverter]

        self.client._converters = [
            converter for converter in self.client._converters
            if not isinstance(converter.converter, tuple(removed_converters))
        ]
        self.client.register_converter(PdfWithTableConverter())

    def convert(self, source: str, **kwargs: Any):
        try:
            result = self.client.convert(
                source,
                **kwargs)
            return result
        except Exception as e:
            logger.error(f"Error during conversion: {e}")
            return None
