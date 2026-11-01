import ast
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set

class ParsedSymbol:
    def __init__(
        self,
        name: str,
        qualified_name: str,
        symbol_type: str,
        start_line: int,
        end_line: int,
        signature: str,
        docstring: Optional[str] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        return_type: Optional[str] = None,
        complexity_score: int = 1,
        is_exported: bool = True,
        calls: Optional[List[str]] = None,
    ):
        self.name = name
        self.qualified_name = qualified_name
        self.symbol_type = symbol_type
        self.start_line = start_line
        self.end_line = end_line
        self.signature = signature
        self.docstring = docstring
        self.parameters = parameters or []
        self.return_type = return_type
        self.complexity_score = complexity_score
        self.is_exported = is_exported
        self.calls = calls or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "symbol_type": self.symbol_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "complexity_score": self.complexity_score,
            "is_exported": self.is_exported,
        }

class ParsedImport:
    def __init__(
        self,
        module_name: str,
        imported_symbols: List[str],
        line_number: int,
        is_standard_lib: bool = False,
        is_third_party: bool = True,
    ):
        self.module_name = module_name
        self.imported_symbols = imported_symbols
        self.line_number = line_number
        self.is_standard_lib = is_standard_lib
        self.is_third_party = is_third_party

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_name": self.module_name,
            "imported_symbols": self.imported_symbols,
            "line_number": self.line_number,
            "is_standard_lib": self.is_standard_lib,
            "is_third_party": self.is_third_party,
        }

# Python Standard Library Detection Set
PYTHON_STDLIB_MODULES = {
    "os", "sys", "re", "json", "math", "time", "datetime", "pathlib", "typing",
    "collections", "itertools", "functools", "copy", "uuid", "hashlib", "logging",
    "asyncio", "threading", "subprocess", "socket", "http", "urllib", "shutil",
    "unittest", "doctest", "abc", "contextlib", "dataclasses", "enum", "inspect"
}

def is_python_stdlib(mod_name: str) -> bool:
    base = mod_name.split(".")[0]
    return base in PYTHON_STDLIB_MODULES

class PythonAstVisitor(ast.NodeVisitor):
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.lines = source_code.splitlines()
        self.symbols: List[ParsedSymbol] = []
        self.imports: List[ParsedImport] = []
        self.relationships: List[Dict[str, Any]] = []
        self.current_class: Optional[str] = None

    def _get_signature_from_lines(self, start_line: int, end_line: int) -> str:
        idx = max(0, start_line - 1)
        sig_lines = []
        while idx < min(len(self.lines), end_line):
            line = self.lines[idx].strip()
            sig_lines.append(line)
            if line.endswith(":") or line.endswith("{"):
                break
            idx += 1
        return " ".join(sig_lines)

    def _calculate_complexity(self, node: ast.AST) -> int:
        score = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler, ast.With)):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
        return score

    def _extract_calls(self, node: ast.AST) -> List[str]:
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
        return list(set(calls))

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            is_std = is_python_stdlib(alias.name)
            self.imports.append(
                ParsedImport(
                    module_name=alias.name,
                    imported_symbols=[alias.asname or alias.name],
                    line_number=node.lineno,
                    is_standard_lib=is_std,
                    is_third_party=not is_std,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        symbols = [alias.name for alias in node.names]
        is_std = is_python_stdlib(mod)
        self.imports.append(
            ParsedImport(
                module_name=mod,
                imported_symbols=symbols,
                line_number=node.lineno,
                is_standard_lib=is_std,
                is_third_party=not is_std and not mod.startswith("."),
            )
        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        prev_class = self.current_class
        self.current_class = node.name

        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)

        symbol_type = "class"
        # Database model detection (SQLAlchemy, Pydantic, Tortoise, etc.)
        if any(b in ("Base", "Model", "DeclarativeBase", "Document") for b in base_names):
            symbol_type = "db_model"
        elif any(b in ("BaseModel", "Schema") for b in base_names):
            symbol_type = "schema_model"

        end_line = getattr(node, "end_lineno", node.lineno)
        docstring = ast.get_docstring(node)
        sig = self._get_signature_from_lines(node.lineno, end_line)

        # Track inheritance relationships
        for base_name in base_names:
            self.relationships.append({
                "source_name": node.name,
                "target_name": base_name,
                "relationship_type": "inherits",
                "evidence_line": node.lineno,
                "evidence_text": sig,
            })

        class_symbol = ParsedSymbol(
            name=node.name,
            qualified_name=node.name,
            symbol_type=symbol_type,
            start_line=node.lineno,
            end_line=end_line,
            signature=sig,
            docstring=docstring,
            complexity_score=self._calculate_complexity(node),
            is_exported=not node.name.startswith("_"),
        )
        self.symbols.append(class_symbol)

        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._process_function(node, is_async=True)

    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool):
        qname = f"{self.current_class}.{node.name}" if self.current_class else node.name
        symbol_type = "method" if self.current_class else "function"

        # Route / API endpoint detection
        is_route = False
        for dec in node.decorator_list:
            dec_str = ""
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Attribute):
                    dec_str = dec.func.attr
                elif isinstance(dec.func, ast.Name):
                    dec_str = dec.func.id
            elif isinstance(dec, ast.Attribute):
                dec_str = dec.attr
            elif isinstance(dec, ast.Name):
                dec_str = dec.id

            if dec_str.lower() in ("get", "post", "put", "delete", "patch", "options", "head", "api_route", "route"):
                symbol_type = "api_route"
                is_route = True
                break

        # Extract parameters
        params = []
        for arg in node.args.args:
            arg_type = None
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    arg_type = arg.annotation.id
                elif isinstance(arg.annotation, ast.Attribute):
                    arg_type = arg.annotation.attr
                else:
                    arg_type = "Any"
            params.append({"name": arg.arg, "type": arg_type})

        # Return type
        return_type = None
        if node.returns:
            if isinstance(node.returns, ast.Name):
                return_type = node.returns.id
            elif isinstance(node.returns, ast.Attribute):
                return_type = node.returns.attr
            else:
                return_type = "Any"

        end_line = getattr(node, "end_lineno", node.lineno)
        docstring = ast.get_docstring(node)
        sig = self._get_signature_from_lines(node.lineno, end_line)
        calls = self._extract_calls(node)

        # Track call relationships
        for called in calls:
            self.relationships.append({
                "source_name": qname,
                "target_name": called,
                "relationship_type": "calls",
                "evidence_line": node.lineno,
                "evidence_text": f"{qname} invokes {called}()",
            })

        self.symbols.append(
            ParsedSymbol(
                name=node.name,
                qualified_name=qname,
                symbol_type=symbol_type,
                start_line=node.lineno,
                end_line=end_line,
                signature=sig,
                docstring=docstring,
                parameters=params,
                return_type=return_type,
                complexity_score=self._calculate_complexity(node),
                is_exported=not node.name.startswith("_"),
                calls=calls,
            )
        )
        self.generic_visit(node)

def parse_python_file(content: str) -> Dict[str, Any]:
    try:
        tree = ast.parse(content)
        visitor = PythonAstVisitor(content)
        visitor.visit(tree)
        return {
            "symbols": [s.to_dict() for s in visitor.symbols],
            "raw_symbols": visitor.symbols,
            "imports": [i.to_dict() for i in visitor.imports],
            "relationships": visitor.relationships,
            "ast_parsed": True,
        }
    except Exception:
        # Fallback to regex parser if code has syntax errors or unsupported features
        return parse_polyglot_file(content, "python")

def parse_javascript_typescript(content: str, lang: str = "typescript") -> Dict[str, Any]:
    symbols: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    lines = content.splitlines()

    # Import statements: import { a, b } from 'c' or import x from 'y'
    import_re = re.compile(r'import\s+(?:(?:\*\s+as\s+\w+|\w+|(?:\{[^}]*\}))\s+from\s+)?[\'"]([^\'"]+)[\'"]')
    for i, line in enumerate(lines, start=1):
        match = import_re.search(line)
        if match:
            mod_path = match.group(1)
            is_third_party = not mod_path.startswith(".") and not mod_path.startswith("/")
            imports.append({
                "module_name": mod_path,
                "imported_symbols": [s.strip() for s in re.findall(r'[\w]+', line.split("from")[0]) if s not in ("import", "as", "default")],
                "line_number": i,
                "is_standard_lib": False,
                "is_third_party": is_third_party,
            })

    # Classes: class Foo extends Bar
    class_re = re.compile(r'(?:export\s+)?(?:default\s+)?class\s+([A-Za-z0-9_$]+)(?:\s+extends\s+([A-Za-z0-9_$]+))?')
    # Functions: function foo(params) or const foo = (...) =>
    func_re = re.compile(r'(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(([^)]*)\)')
    arrow_re = re.compile(r'(?:export\s+)?const\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*([A-Za-z0-9_<>[\]]+))?\s*=>')
    # Interfaces and types
    type_re = re.compile(r'(?:export\s+)?(?:interface|type)\s+([A-Za-z0-9_$]+)')
    # API route handlers in Express / Next: app.get('/api', ...) or router.post(...)
    route_re = re.compile(r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]')

    for i, line in enumerate(lines, start=1):
        trimmed = line.strip()

        # Check route
        route_match = route_re.search(trimmed)
        if route_match:
            method, route_path = route_match.groups()
            symbols.append({
                "name": f"{method.upper()} {route_path}",
                "qualified_name": f"{method.upper()} {route_path}",
                "symbol_type": "api_route",
                "start_line": i,
                "end_line": i,
                "signature": trimmed[:120],
                "docstring": None,
                "parameters": [{"name": "req"}, {"name": "res"}],
                "return_type": None,
                "complexity_score": 1,
                "is_exported": True,
            })
            continue

        # Check class
        class_match = class_re.search(trimmed)
        if class_match:
            cls_name = class_match.group(1)
            parent_name = class_match.group(2)
            symbols.append({
                "name": cls_name,
                "qualified_name": cls_name,
                "symbol_type": "class",
                "start_line": i,
                "end_line": i,
                "signature": trimmed[:120],
                "docstring": None,
                "parameters": [],
                "return_type": None,
                "complexity_score": 1,
                "is_exported": "export" in trimmed,
            })
            if parent_name:
                relationships.append({
                    "source_name": cls_name,
                    "target_name": parent_name,
                    "relationship_type": "inherits",
                    "evidence_line": i,
                    "evidence_text": trimmed,
                })
            continue

        # Check function
        func_match = func_re.search(trimmed)
        if func_match:
            fname, raw_params = func_match.groups()
            symbols.append({
                "name": fname,
                "qualified_name": fname,
                "symbol_type": "function",
                "start_line": i,
                "end_line": i,
                "signature": trimmed[:120],
                "docstring": None,
                "parameters": [{"name": p.strip().split(":")[0]} for p in raw_params.split(",") if p.strip()],
                "return_type": None,
                "complexity_score": 1,
                "is_exported": "export" in trimmed,
            })
            continue

        # Check arrow function
        arrow_match = arrow_re.search(trimmed)
        if arrow_match:
            fname, raw_params, ret_type = arrow_match.groups()
            symbols.append({
                "name": fname,
                "qualified_name": fname,
                "symbol_type": "function",
                "start_line": i,
                "end_line": i,
                "signature": trimmed[:120],
                "docstring": None,
                "parameters": [{"name": p.strip().split(":")[0]} for p in raw_params.split(",") if p.strip()],
                "return_type": ret_type,
                "complexity_score": 1,
                "is_exported": "export" in trimmed,
            })
            continue

        # Check type/interface
        type_match = type_re.search(trimmed)
        if type_match:
            tname = type_match.group(1)
            symbols.append({
                "name": tname,
                "qualified_name": tname,
                "symbol_type": "interface",
                "start_line": i,
                "end_line": i,
                "signature": trimmed[:120],
                "docstring": None,
                "parameters": [],
                "return_type": None,
                "complexity_score": 1,
                "is_exported": "export" in trimmed,
            })

    return {
        "symbols": symbols,
        "imports": imports,
        "relationships": relationships,
        "ast_parsed": True,
    }

def parse_polyglot_file(content: str, language: str) -> Dict[str, Any]:
    if language == "python":
        return parse_python_file(content)
    elif language in ("javascript", "typescript"):
        return parse_javascript_typescript(content, language)
    else:
        # Fallback generic syntax recognizer for Go, Java, Rust, C++
        symbols: List[Dict[str, Any]] = []
        lines = content.splitlines()
        for i, line in enumerate(lines, start=1):
            trimmed = line.strip()
            # Match Go func, Rust fn, Java/C++ method
            if trimmed.startswith("func ") or trimmed.startswith("pub fn ") or trimmed.startswith("fn "):
                m = re.search(r'(?:func|fn)\s+([A-Za-z0-9_]+)', trimmed)
                if m:
                    symbols.append({
                        "name": m.group(1),
                        "qualified_name": m.group(1),
                        "symbol_type": "function",
                        "start_line": i,
                        "end_line": i,
                        "signature": trimmed[:120],
                        "docstring": None,
                        "parameters": [],
                        "return_type": None,
                        "complexity_score": 1,
                        "is_exported": True,
                    })
        return {
            "symbols": symbols,
            "imports": [],
            "relationships": [],
            "ast_parsed": len(symbols) > 0,
        }
