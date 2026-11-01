from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional


@dataclass
class BaseEntity:
    repository_id: str
    file_path: str
    symbol_name: str
    symbol_type: str
    start_line: int
    end_line: int
    source_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            field_name.name: getattr(self, field_name.name)
            for field_name in fields(self)
            if field_name.name != "metadata"
        }
        data.update(self.metadata)
        return data


@dataclass
class CodeFile(BaseEntity):
    language: str = ""
    size_bytes: int = 0
    is_test: bool = False
    is_config: bool = False
    is_documentation: bool = False


@dataclass
class CodeClass(BaseEntity):
    is_abstract: bool = False
    bases: List[str] = field(default_factory=list)
    docstring: Optional[str] = None


@dataclass
class CodeFunction(BaseEntity):
    signature: str = ""
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None


@dataclass
class CodeMethod(CodeFunction):
    enclosing_class: Optional[str] = None


@dataclass
class CodeImport(BaseEntity):
    module_name: str = ""
    imported_names: List[str] = field(default_factory=list)
    is_standard_library: bool = False
    is_third_party: bool = False


@dataclass
class CodeDependency(BaseEntity):
    package_name: str = ""
    version: str = ""
    ecosystem: str = ""
    manifest_file: Optional[str] = None


@dataclass
class ApiEndpoint(BaseEntity):
    method: str = "GET"
    path: str = ""
    handler: Optional[str] = None


@dataclass
class DatabaseModel(BaseEntity):
    table_name: Optional[str] = None
    base_class: Optional[str] = None


@dataclass
class CodeComment(BaseEntity):
    comment_text: str = ""


@dataclass
class CodeDocstring(BaseEntity):
    value: str = ""


__all__ = [
    "BaseEntity",
    "CodeFile",
    "CodeClass",
    "CodeFunction",
    "CodeMethod",
    "CodeImport",
    "CodeDependency",
    "ApiEndpoint",
    "DatabaseModel",
    "CodeComment",
    "CodeDocstring",
]
