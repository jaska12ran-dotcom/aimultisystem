import pytest
from app.services.parser.polyglot_parser import parse_python_file, parse_polyglot_file

PYTHON_SAMPLE = """
from typing import List, Optional
import os
import requests

class UserModel(Base):
    '''Represents a user in the database.'''
    id: int
    name: str

class AuthController:
    def __init__(self, token: str):
        self.token = token

    @router.get("/users/me")
    async def get_current_user(self, user_id: int) -> UserModel:
        '''Fetch the authenticated user profile.'''
        if not user_id:
            return None
        return self._lookup(user_id)

    def _lookup(self, uid: int):
        return UserModel()
"""

TS_SAMPLE = """
import { useState, useEffect } from 'react';
import axios from 'axios';

export interface UserProfile {
    id: string;
    username: string;
}

export class AuthService extends BaseService {
    authenticate() {
        return true;
    }
}

app.get('/api/v1/status', (req, res) => {
    res.json({ ok: true });
});
"""

def test_python_ast_parser_symbols():
    result = parse_python_file(PYTHON_SAMPLE)
    assert result["ast_parsed"] is True
    symbols = result["symbols"]
    symbol_names = [s["name"] for s in symbols]
    
    assert "UserModel" in symbol_names
    assert "AuthController" in symbol_names
    assert "get_current_user" in symbol_names
    assert "_lookup" in symbol_names

    # Verify db_model detection
    user_model = next(s for s in symbols if s["name"] == "UserModel")
    assert user_model["symbol_type"] == "db_model"
    assert "Represents a user" in user_model["docstring"]

    # Verify API route detection
    route_sym = next(s for s in symbols if s["name"] == "get_current_user")
    assert route_sym["symbol_type"] == "api_route"
    assert route_sym["start_line"] > 0
    assert route_sym["end_line"] >= route_sym["start_line"]
    assert "Fetch the authenticated user profile." in route_sym["docstring"]

    # Verify imports
    imports = result["imports"]
    modules = [i["module_name"] for i in imports]
    assert "os" in modules
    assert "requests" in modules
    assert "typing" in modules

    # Verify call relationships
    relationships = result["relationships"]
    calls = [r for r in relationships if r["relationship_type"] == "calls"]
    assert any("lookup" in r["target_name"] for r in calls)

def test_typescript_parser():
    result = parse_polyglot_file(TS_SAMPLE, "typescript")
    assert result["ast_parsed"] is True
    symbols = result["symbols"]
    names = [s["name"] for s in symbols]
    
    assert "UserProfile" in names
    assert "AuthService" in names
    assert any("GET /api/v1/status" in s["name"] for s in symbols)

    # Check inheritance relationship
    rels = result["relationships"]
    assert any(r["source_name"] == "AuthService" and r["target_name"] == "BaseService" for r in rels)
