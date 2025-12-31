"""
MCP (Model Context Protocol) Server for Radio Automation
Implements the Anthropic MCP Streamable HTTP Transport (2025-03-26)
with OAuth 2.1 Authorization support

Transport specification:
- POST /mcp - Receives JSON-RPC messages, returns JSON or SSE
- GET /mcp - Opens SSE stream for server-initiated messages (optional)
- Session management via Mcp-Session-Id header

OAuth 2.1 endpoints:
- GET /.well-known/oauth-authorization-server - Metadata discovery
- POST /oauth/token - Token endpoint (client_credentials grant)
- POST /oauth/register - Dynamic client registration
"""
import json
import logging
import secrets
import threading
import queue
import time
import hashlib
from functools import wraps
from flask import Blueprint, request, Response, jsonify, url_for

logger = logging.getLogger(__name__)

# MCP Protocol Constants
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "radio-automation"
MCP_SERVER_VERSION = "2.0.6"

# Create Blueprint
mcp_bp = Blueprint('mcp', __name__)

# Session storage: session_id -> {"queue": Queue, "active": bool, "initialized": bool}
_sessions = {}
_sessions_lock = threading.Lock()

# OAuth token storage: access_token -> {"client_id": str, "expires_at": float, "scope": str}
_oauth_tokens = {}
_oauth_tokens_lock = threading.Lock()

# Registered OAuth clients: client_id -> {"client_secret": str, "client_name": str}
_oauth_clients = {}
_oauth_clients_lock = threading.Lock()


def get_server_base_url():
    """Get the base URL of the server from the current request"""
    return f"{request.scheme}://{request.host}"


def is_auth_required():
    """Check if authentication is required (API key is configured)"""
    from app.models import StreamSettings
    settings = StreamSettings.get_settings()
    return bool(settings.mcp_api_key)


def get_api_key_from_request():
    """Extract API key from Authorization header"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return None


def validate_api_key(api_key):
    """Validate the API key against stored settings"""
    if not api_key:
        return False
    from app.models import StreamSettings
    settings = StreamSettings.get_settings()
    return settings.validate_mcp_api_key(api_key)


def validate_oauth_token(token):
    """Validate an OAuth access token"""
    with _oauth_tokens_lock:
        token_data = _oauth_tokens.get(token)
        if not token_data:
            return False
        # Check expiration
        if time.time() > token_data.get('expires_at', 0):
            del _oauth_tokens[token]
            return False
        return True


def validate_request_auth():
    """
    Validate request authentication.
    Returns (is_valid, error_response)
    """
    # If no API key configured, allow all requests (authless mode)
    if not is_auth_required():
        return True, None

    # Check for Bearer token
    token = get_api_key_from_request()
    if not token:
        return False, None

    # First check if it's a direct API key
    if validate_api_key(token):
        return True, None

    # Then check if it's an OAuth token
    if validate_oauth_token(token):
        return True, None

    return False, None


def generate_session_id():
    """Generate a cryptographically secure session ID"""
    return secrets.token_hex(32)


def generate_access_token():
    """Generate a cryptographically secure access token"""
    return secrets.token_urlsafe(32)


def generate_client_credentials():
    """Generate client_id and client_secret for OAuth"""
    client_id = secrets.token_urlsafe(16)
    client_secret = secrets.token_urlsafe(32)
    return client_id, client_secret


def get_tool_definitions():
    """Return the list of available MCP tools with their schemas"""
    return [
        {
            "name": "list_files",
            "description": "List audio files in a category folder. Categories: music, promos, jingles, ads, random-moderation, planned-moderation, musicbeds, misc",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category folder name",
                        "enum": ["music", "promos", "jingles", "ads", "random-moderation", "planned-moderation", "musicbeds", "misc"]
                    }
                },
                "required": ["category"]
            }
        },
        {
            "name": "search_song",
            "description": "Search for songs by title or artist name",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for title or artist"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "add_to_queue",
            "description": "Add an audio file to the playback queue",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "Database ID of the audio file"
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full file path (alternative to file_id)"
                    }
                }
            }
        },
        {
            "name": "get_queue",
            "description": "Get the current playback queue contents",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "upload_file",
            "description": "Upload an audio file to a category folder",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Target category folder"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Filename for the uploaded file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Base64-encoded file content"
                    }
                },
                "required": ["category", "filename", "content"]
            }
        },
        {
            "name": "generate_moderation",
            "description": "Generate AI voice moderation using text-to-speech with configured Minimax settings",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to convert to speech"
                    },
                    "target_folder": {
                        "type": "string",
                        "description": "Target folder: random-moderation, planned-moderation, or misc",
                        "default": "random-moderation"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional custom filename (without extension)"
                    }
                },
                "required": ["text"]
            }
        },
        {
            "name": "queue_moderation",
            "description": "Add a moderation file to the priority moderation queue",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Full path to the moderation audio file"
                    }
                },
                "required": ["filepath"]
            }
        },
        {
            "name": "get_upcoming_shows",
            "description": "Get the next scheduled shows",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of upcoming shows to return (default: 5)",
                        "default": 5
                    }
                }
            }
        },
        {
            "name": "get_current_time",
            "description": "Get the current time in the configured station timezone",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "list_rotation_rules",
            "description": "List all rotation rules configured in the system",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "active_only": {
                        "type": "boolean",
                        "description": "Only return active rules",
                        "default": False
                    }
                }
            }
        },
        {
            "name": "toggle_rotation_rule",
            "description": "Enable or disable a rotation rule by ID or name",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "rule_id": {
                        "type": "integer",
                        "description": "ID of the rotation rule"
                    },
                    "rule_name": {
                        "type": "string",
                        "description": "Name of the rotation rule (alternative to rule_id)"
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Set to true to enable, false to disable"
                    }
                },
                "required": ["enabled"]
            }
        }
    ]


def handle_initialize(params):
    """Handle the initialize method"""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION
        }
    }


def handle_tools_list(params):
    """Handle the tools/list method"""
    return {
        "tools": get_tool_definitions()
    }


def handle_tools_call(params):
    """Handle the tools/call method"""
    from app.mcp_tools import execute_tool

    tool_name = params.get('name')
    arguments = params.get('arguments', {})

    if not tool_name:
        return {
            "content": [{
                "type": "text",
                "text": "Error: No tool name specified"
            }],
            "isError": True
        }

    # Execute the tool
    try:
        result = execute_tool(tool_name, arguments)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2)
            }],
            "isError": result.get('error') is not None
        }
    except Exception as e:
        logger.error(f"Tool execution error: {e}")
        return {
            "content": [{
                "type": "text",
                "text": f"Error executing tool: {str(e)}"
            }],
            "isError": True
        }


def process_jsonrpc_message(data):
    """Process a JSON-RPC message and return the response"""
    # Validate JSON-RPC format
    if data.get('jsonrpc') != '2.0':
        return {
            "jsonrpc": "2.0",
            "id": data.get('id'),
            "error": {
                "code": -32600,
                "message": "Invalid Request: jsonrpc must be '2.0'"
            }
        }

    message_id = data.get('id')
    method = data.get('method')
    params = data.get('params', {})

    if not method:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {
                "code": -32600,
                "message": "Invalid Request: method is required"
            }
        }

    # Route to appropriate handler
    handlers = {
        'initialize': handle_initialize,
        'notifications/initialized': lambda p: None,  # Notification, no response needed
        'ping': lambda p: {},  # Ping/pong - return empty result
        'tools/list': handle_tools_list,
        'tools/call': handle_tools_call
    }

    handler = handlers.get(method)
    if not handler:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

    try:
        result = handler(params)
        # Notifications don't get responses
        if result is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": result
        }
    except Exception as e:
        logger.error(f"Handler error for {method}: {e}")
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }


def add_cors_headers(response, include_protocol_version=False):
    """Add CORS headers to response"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID'
    response.headers['Access-Control-Expose-Headers'] = 'Mcp-Session-Id, MCP-Protocol-Version, WWW-Authenticate'
    if include_protocol_version:
        response.headers['MCP-Protocol-Version'] = MCP_PROTOCOL_VERSION
    return response


# ============================================================================
# OAuth 2.1 Endpoints
# ============================================================================

@mcp_bp.route('/.well-known/oauth-authorization-server', methods=['GET', 'OPTIONS'])
def oauth_metadata():
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414)
    Returns server capabilities and endpoint URLs
    """
    if request.method == 'OPTIONS':
        response = Response()
        return add_cors_headers(response)

    base_url = get_server_base_url()

    metadata = {
        "issuer": base_url,
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic"
        ],
        "grant_types_supported": [
            "client_credentials"
        ],
        "response_types_supported": ["token"],
        "scopes_supported": ["mcp:tools", "mcp:read", "mcp:write"],
        "service_documentation": f"{base_url}/docs",
        "code_challenge_methods_supported": ["S256"]
    }

    response = jsonify(metadata)
    return add_cors_headers(response)


@mcp_bp.route('/oauth/register', methods=['POST', 'OPTIONS'])
def oauth_register():
    """
    OAuth 2.0 Dynamic Client Registration (RFC 7591)
    Allows clients to register and obtain credentials
    """
    if request.method == 'OPTIONS':
        response = Response()
        return add_cors_headers(response)

    try:
        data = request.get_json() or {}
    except Exception:
        data = {}

    client_name = data.get('client_name', 'MCP Client')
    redirect_uris = data.get('redirect_uris', [])

    # Generate credentials
    client_id, client_secret = generate_client_credentials()

    # Store client
    with _oauth_clients_lock:
        _oauth_clients[client_id] = {
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "created_at": time.time()
        }

    logger.info(f"OAuth client registered: {client_name} ({client_id})")

    response = jsonify({
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": client_name,
        "token_endpoint_auth_method": "client_secret_post",
        "grant_types": ["client_credentials"],
        "redirect_uris": redirect_uris
    })
    response.status_code = 201
    return add_cors_headers(response)


@mcp_bp.route('/oauth/token', methods=['POST', 'OPTIONS'])
def oauth_token():
    """
    OAuth 2.0 Token Endpoint
    Supports client_credentials grant type
    """
    if request.method == 'OPTIONS':
        response = Response()
        return add_cors_headers(response)

    # Parse request - support both form data and JSON
    if request.content_type and 'application/json' in request.content_type:
        try:
            data = request.get_json() or {}
        except Exception:
            data = {}
    else:
        data = request.form.to_dict()

    grant_type = data.get('grant_type')
    client_id = data.get('client_id')
    client_secret = data.get('client_secret')
    scope = data.get('scope', 'mcp:tools')

    # Also check Basic auth header
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Basic '):
        import base64
        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            if ':' in decoded:
                client_id, client_secret = decoded.split(':', 1)
        except Exception:
            pass

    # Validate grant type
    if grant_type != 'client_credentials':
        response = jsonify({
            "error": "unsupported_grant_type",
            "error_description": "Only client_credentials grant is supported"
        })
        response.status_code = 400
        return add_cors_headers(response)

    # Validate client credentials
    valid_client = False

    # Check against registered OAuth clients
    with _oauth_clients_lock:
        client_data = _oauth_clients.get(client_id)
        if client_data and secrets.compare_digest(client_data.get('client_secret', ''), client_secret or ''):
            valid_client = True

    # Also accept the configured MCP API key as client_secret
    if not valid_client and client_secret:
        if validate_api_key(client_secret):
            valid_client = True

    if not valid_client:
        response = jsonify({
            "error": "invalid_client",
            "error_description": "Invalid client credentials"
        })
        response.status_code = 401
        response.headers['WWW-Authenticate'] = 'Basic realm="MCP"'
        return add_cors_headers(response)

    # Generate access token
    access_token = generate_access_token()
    expires_in = 3600  # 1 hour

    # Store token
    with _oauth_tokens_lock:
        _oauth_tokens[access_token] = {
            "client_id": client_id,
            "expires_at": time.time() + expires_in,
            "scope": scope
        }

    logger.info(f"OAuth token issued for client: {client_id}")

    response = jsonify({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": scope
    })
    return add_cors_headers(response)


# ============================================================================
# MCP Endpoints
# ============================================================================

@mcp_bp.route('/mcp', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
def mcp_endpoint():
    """
    Streamable HTTP MCP endpoint (2025-06-18 protocol).

    POST: Receives JSON-RPC messages from client, returns JSON or SSE
    GET: Opens SSE stream for server-initiated messages
    DELETE: Terminates a session
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = Response()
        return add_cors_headers(response, include_protocol_version=True)

    # Validate authentication
    is_valid, error_response = validate_request_auth()
    if not is_valid:
        # Return 401 with WWW-Authenticate header to trigger OAuth flow
        base_url = get_server_base_url()
        response = jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": "Unauthorized"
            }
        })
        response.status_code = 401
        response.headers['WWW-Authenticate'] = f'Bearer realm="MCP", resource="{base_url}/.well-known/oauth-authorization-server"'
        return add_cors_headers(response, include_protocol_version=True)

    # Get session ID from header
    session_id = request.headers.get('Mcp-Session-Id')

    # Handle DELETE - session termination
    if request.method == 'DELETE':
        if session_id:
            with _sessions_lock:
                if session_id in _sessions:
                    _sessions[session_id]["active"] = False
                    del _sessions[session_id]
                    logger.info(f"MCP session terminated: {session_id}")
            response = Response('', status=204)
            return add_cors_headers(response, include_protocol_version=True)
        response = Response('', status=400)
        return add_cors_headers(response, include_protocol_version=True)

    # Handle GET - SSE stream for server-initiated messages
    if request.method == 'GET':
        accept = request.headers.get('Accept', '')
        if 'text/event-stream' not in accept:
            response = Response('', status=405)
            return add_cors_headers(response, include_protocol_version=True)

        # Validate session exists
        if session_id:
            with _sessions_lock:
                if session_id not in _sessions:
                    response = jsonify({"error": "Session not found"})
                    response.status_code = 404
                    return add_cors_headers(response, include_protocol_version=True)
                session = _sessions[session_id]
                message_queue = session["queue"]
        else:
            # Create a temporary queue for this connection
            message_queue = queue.Queue()

        def generate_sse():
            try:
                while True:
                    try:
                        msg = message_queue.get(timeout=30)
                        if msg is None:
                            break
                        yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            except GeneratorExit:
                pass

        response = Response(
            generate_sse(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
                'MCP-Protocol-Version': MCP_PROTOCOL_VERSION
            }
        )
        return add_cors_headers(response, include_protocol_version=True)

    # Handle POST - JSON-RPC messages
    if request.method == 'POST':
        # Parse JSON-RPC request
        try:
            data = request.get_json()
        except Exception as e:
            response = jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
            })
            response.status_code = 400
            return add_cors_headers(response, include_protocol_version=True)

        if not data:
            response = jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: Empty request body"}
            })
            response.status_code = 400
            return add_cors_headers(response, include_protocol_version=True)

        # Handle batch requests
        is_batch = isinstance(data, list)
        messages = data if is_batch else [data]

        # Check if this is an initialize request
        is_initialize = any(
            msg.get('method') == 'initialize' for msg in messages
            if isinstance(msg, dict)
        )

        # Validate session for non-initialize requests
        if not is_initialize and session_id:
            with _sessions_lock:
                if session_id not in _sessions:
                    response = jsonify({
                        "jsonrpc": "2.0",
                        "id": messages[0].get('id') if messages else None,
                        "error": {"code": -32600, "message": "Session not found or expired"}
                    })
                    response.status_code = 404
                    return add_cors_headers(response, include_protocol_version=True)

        # Process messages
        responses = []
        new_session_id = None

        for msg in messages:
            if not isinstance(msg, dict):
                responses.append({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request: not an object"}
                })
                continue

            result = process_jsonrpc_message(msg)

            # Handle initialize - create session
            if msg.get('method') == 'initialize' and result and 'result' in result:
                new_session_id = generate_session_id()
                with _sessions_lock:
                    _sessions[new_session_id] = {
                        "queue": queue.Queue(),
                        "active": True,
                        "initialized": True
                    }
                logger.info(f"MCP session created: {new_session_id}")

            if result is not None:
                responses.append(result)

        # Determine response format based on Accept header
        accept = request.headers.get('Accept', '')
        wants_sse = 'text/event-stream' in accept

        # For notifications only (no responses), return 202 Accepted
        if not responses:
            response = Response('', status=202)
            if new_session_id:
                response.headers['Mcp-Session-Id'] = new_session_id
            return add_cors_headers(response, include_protocol_version=True)

        # Single response
        response_data = responses if is_batch else responses[0]

        # Return as SSE if client prefers it
        if wants_sse:
            def generate_sse():
                if is_batch:
                    for resp in responses:
                        yield f"event: message\ndata: {json.dumps(resp)}\n\n"
                else:
                    yield f"event: message\ndata: {json.dumps(response_data)}\n\n"

            response = Response(
                generate_sse(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no',
                    'MCP-Protocol-Version': MCP_PROTOCOL_VERSION
                }
            )
        else:
            response = jsonify(response_data)

        if new_session_id:
            response.headers['Mcp-Session-Id'] = new_session_id

        return add_cors_headers(response, include_protocol_version=True)


# ============================================================================
# Legacy endpoints for backwards compatibility with 2024-11-05 protocol
# ============================================================================

@mcp_bp.route('/mcp/sse', methods=['GET', 'OPTIONS'])
def mcp_sse_endpoint_legacy():
    """
    Legacy SSE endpoint for 2024-11-05 protocol.
    """
    if request.method == 'OPTIONS':
        response = Response()
        return add_cors_headers(response)

    # Validate authentication
    is_valid, _ = validate_request_auth()
    if not is_valid:
        return jsonify({"error": "Invalid or missing API key"}), 401

    # Create session
    session_id = generate_session_id()
    message_queue = queue.Queue()

    with _sessions_lock:
        _sessions[session_id] = {
            "queue": message_queue,
            "active": True,
            "initialized": False
        }

    logger.info(f"MCP SSE connection (legacy) established: {session_id}")

    def generate():
        try:
            # Send endpoint event with the POST URL for this session (legacy format)
            endpoint_url = f"/mcp/messages?session_id={session_id}"
            yield f"event: endpoint\ndata: {endpoint_url}\n\n"

            # Keep connection alive and send messages from queue
            while True:
                try:
                    msg = message_queue.get(timeout=30)
                    if msg is None:
                        break
                    yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"

                with _sessions_lock:
                    if session_id not in _sessions or not _sessions[session_id]["active"]:
                        break
        except GeneratorExit:
            pass
        finally:
            with _sessions_lock:
                if session_id in _sessions:
                    _sessions[session_id]["active"] = False
                    del _sessions[session_id]
            logger.info(f"MCP SSE connection (legacy) closed: {session_id}")

    response = Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )
    return add_cors_headers(response)


@mcp_bp.route('/mcp/messages', methods=['POST', 'OPTIONS'])
def mcp_messages_endpoint_legacy():
    """
    Legacy POST endpoint for 2024-11-05 protocol.
    """
    if request.method == 'OPTIONS':
        response = Response()
        return add_cors_headers(response)

    # Validate authentication
    is_valid, _ = validate_request_auth()
    if not is_valid:
        return jsonify({"error": "Invalid or missing API key"}), 401

    # Get session ID from query parameter (legacy)
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "Missing session_id parameter"}), 400

    # Find session
    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session or not session["active"]:
            return jsonify({"error": "Session not found or expired"}), 404
        message_queue = session["queue"]

    # Parse JSON-RPC message
    try:
        data = request.get_json()
    except Exception as e:
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
        }), 400

    if not data:
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error: Empty request body"}
        }), 400

    # Process message
    response = process_jsonrpc_message(data)

    # Send response through SSE stream if there is one
    if response is not None:
        message_queue.put(response)

    # Return accepted status
    return jsonify({"status": "accepted"}), 202
