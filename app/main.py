"""FastAPI app for xtream-vodfs Sprint 3

CDN direct URL exposure, scanner detection, content-type normalization, performance improvements,
streaming reliability, rate limiting, and head_mode caching.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, Response, HTTPException, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from app.tree import VirtualTree
from app.httpfs import HTTPFilesystem
from app.config import Config, ConfigManager, get_config_manager, get_active_providers, load_config, save_config
from app.cache import Cache, get_cache
from app.metadata_cache import MetadataCache, get_metadata_cache
from app.xtream import XtreamClient, validate_credentials
from app.proxy import stream_vod_from_node, get_rate_limiter
from app.warmer import MetadataWarmer
from app.models import NodeType, XtreamCredentials


app = FastAPI(title="xtream-vodfs", description="Local HTTP virtual filesystem for Xtream Codes VOD and Series", version="0.3.0 (Sprint 3)")

BASE_DIR = Path(__file__).parent.parent
MEDIA_DIR = BASE_DIR / "sample_media"

# Global instances
config_manager: Optional[ConfigManager] = None
config: Optional[Config] = None
cache: Optional[Cache] = None
tree: Optional[VirtualTree] = None
httpfs: Optional[HTTPFilesystem] = None
metadata_cache: Optional[MetadataCache] = None
warmer: Optional[MetadataWarmer] = None


class ConfigForm(BaseModel):
    """Form data for config submission"""
    base_url: str
    username: str
    password: str
    enable_vod: bool = True
    movies_include_all: bool = True
    movies_include_categories: bool = True


@app.on_event("startup")
async def startup_event():
    """Initialize app components on startup"""
    global config_manager, config, cache, tree, httpfs, metadata_cache, warmer

    config_manager = get_config_manager()
    config = config_manager.load()

    cache = get_cache()

    # Try to load cache from disk
    cache_loaded = cache.load_from_disk()
    if cache_loaded:
        print(f"Loaded cache from disk: {len(cache.vod_categories)} categories, {len(cache.vod_streams)} streams")

    # Load metadata cache
    metadata_cache = get_metadata_cache()
    metadata_cache_loaded = metadata_cache.load_from_disk()
    if metadata_cache_loaded:
        print(f"Loaded metadata cache from disk: {metadata_cache.count()} entries")

    # Build tree
    active_providers = get_active_providers(config)
    if active_providers:
        # Multi-provider mode: try to refresh to get full data
        if cache_loaded:
            try:
                await refresh_vod_cache()
            except Exception as e:
                logger.warning(f"Failed to refresh cache on startup: {e}")
                # Fall back to single-provider mode with existing cache
                tree = VirtualTree(cache=cache if not cache.is_empty else None, config=config)
        else:
            tree = VirtualTree(cache=None, config=config)
    else:
        # Single-provider mode or not configured
        tree = VirtualTree(cache=cache if not cache.is_empty else None, config=config)

    httpfs = HTTPFilesystem(tree, str(MEDIA_DIR), metadata_cache=metadata_cache)
    _apply_httpfs_config()


def _apply_httpfs_config():
    """Apply HTTP filesystem settings from current config"""
    global httpfs, config
    if httpfs and config:
        httpfs.enable_scanner_detection = config.httpfs.enable_scanner_detection
        httpfs.cache_content_type = config.httpfs.cache_content_type
        httpfs.dir_listing_cache_ttl = config.httpfs.dir_listing_cache_ttl


async def refresh_vod_cache():
    """Refresh VOD cache for all configured providers."""
    global config, cache, tree, httpfs, metadata_cache, warmer

    if not config or not config_manager:
        raise HTTPException(status_code=400, detail="Config not loaded")

    active_providers = get_active_providers(config)
    if not active_providers:
        raise HTTPException(status_code=400, detail="No Xtream providers configured")

    try:
        all_categories = []
        all_streams = []
        providers_data = []          # For warmer: (name, creds, streams)
        providers_tree_data = []     # For tree: (name, categories, streams)

        # Fetch data from each provider
        for creds in active_providers:
            async with XtreamClient(creds, timeout=30.0) as client:
                # Validate credentials
                await client.validate_account()

                # Fetch categories and streams
                categories = await client.get_vod_categories()
                streams = await client.get_vod_streams()

                all_categories.extend(categories)
                all_streams.extend(streams)

                # Store for tree building (needs categories + streams)
                providers_tree_data.append((creds.provider_name, categories, streams))
                # Store for warming (needs credentials)
                providers_data.append((creds.provider_name, creds, streams))

                logger.info(
                    f"Fetched {len(categories)} categories and {len(streams)} streams "
                    f"from provider {creds.provider_name}"
                )

        # Update cache with all data
        if cache:
            cache.refresh(all_categories, all_streams)
            cache.save_to_disk()

        # Build tree with multi-provider data
        tree = VirtualTree(
            cache=cache if cache and not cache.is_empty else None,
            config=config,
            providers=providers_tree_data
        )
        httpfs = HTTPFilesystem(tree, str(MEDIA_DIR), metadata_cache=metadata_cache)
        _apply_httpfs_config()

        # Start warmer in background
        if config.metadata_warmer.enabled and metadata_cache:
            global warmer
            warmer = MetadataWarmer(metadata_cache, providers_data, config.metadata_warmer)
            asyncio.create_task(warmer.start())

        return sum(len(cats) for _, cats, _ in providers_tree_data), sum(len(streams) for _, _, streams in providers_tree_data)

    except Exception as e:
        # Sanitize error message
        error_msg = str(e)
        if config:
            for creds in get_active_providers(config):
                error_msg = error_msg.replace(creds.username, "USERNAME")
                error_msg = error_msg.replace(creds.password, "PASSWORD")
        raise HTTPException(status_code=500, detail=f"Failed to refresh VOD cache: {error_msg}")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Main status and configuration page"""
    is_configured = config_manager.is_configured() if config_manager else False
    vod_categories = len(cache.vod_categories) if cache else 0
    vod_streams = len(cache.vod_streams) if cache else 0
    last_refresh = cache.last_refresh.isoformat() if cache and cache.last_refresh else "Never"

    html = f"""<!doctype html>
<html>
<head>
    <title>xtream-vodfs - Sprint 3</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif;max-width:900px;margin:40px auto;padding:20px;line-height:1.6}}
        h1 {{color:#333;border-bottom:2px solid #007bff;padding-bottom:10px}}
        .status {{background:#d4edda;color:#155724;padding:15px;border-radius:5px;margin:20px 0}}
        .status.not-configured {{background:#fff3cd;color:#856404}}
        .info {{background:#f8f9fa;padding:15px;border-radius:5px;margin:20px 0;border:1px solid #dee2e6}}
        .links {{margin:20px 0}}
        .links a {{display:block;margin:8px 0;color:#0066cc;text-decoration:none}}
        .links a:hover {{text-decoration:underline}}
        .stats {{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin:20px 0}}
        .stat {{background:#e9ecef;padding:15px;border-radius:5px;text-align:center}}
        .stat-value {{font-size:2em;font-weight:bold;color:#007bff}}
        .stat-label {{color:#666;font-size:0.9em}}

        /* Provider Management Styles */
        .section-header {{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px}}
        .provider-count {{font-size:0.82rem;font-weight:600;color:#6c757d;background:#e9ecef;padding:3px 10px;border-radius:999px}}
        .provider-list {{display:flex;flex-direction:column;gap:12px;margin-bottom:16px}}
        .provider-card {{background:#fff;border:1px solid #dee2e6;border-radius:8px;padding:14px 16px;display:flex;align-items:center;gap:14px;transition:box-shadow 0.2s,border-color 0.2s,opacity 0.2s;position:relative}}
        .provider-card:hover {{box-shadow:0 4px 12px rgba(0,0,0,0.1);border-color:#007bff}}
        .provider-card.disabled {{opacity:0.65}}
        .provider-card.editing {{border-color:#52b34b;box-shadow:0 0 0 3px rgba(82,181,75,0.1)}}
        .provider-card.confirm-delete {{border-color:#dc3545;background:#fff5f5}}
        .provider-icon {{width:40px;height:40px;border-radius:6px;background:#e8f5e9;color:#52b34b;display:flex;align-items:center;justify-content:center;font-size:1.1rem;font-weight:700;flex-shrink:0;text-transform:uppercase}}
        .provider-info {{flex:1;min-width:0}}
        .provider-name {{font-size:0.95rem;font-weight:700;color:#212529;margin:0 0 2px;display:flex;align-items:center;gap:8px}}
        .provider-url {{font-size:0.82rem;color:#6c757d;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
        .provider-status-dot {{width:8px;height:8px;border-radius:50%;display:inline-block}}
        .provider-status-dot.active {{background:#52b34b}}
        .provider-status-dot.inactive {{background:#6c757d}}
        .provider-meta {{display:flex;align-items:center;gap:12px;flex-shrink:0;flex-wrap:wrap}}
        .toggle-switch {{position:relative;display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-size:0.82rem;font-weight:600;color:#495057;user-select:none}}
        .toggle-switch input {{position:absolute;opacity:0;width:0;height:0}}
        .toggle-slider {{width:36px;height:20px;background:#6c757d;border-radius:999px;position:relative;transition:background 0.2s;flex-shrink:0}}
        .toggle-slider::after {{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;background:#fff;border-radius:50%;transition:transform 0.2s;box-shadow:0 1px 3px rgba(0,0,0,0.2)}}
        .toggle-switch input:checked + .toggle-slider {{background:#52b34b}}
        .toggle-switch input:checked + .toggle-slider::after {{transform:translateX(16px)}}
        .card-actions {{display:flex;align-items:center;gap:6px}}
        .btn {{background:#007bff;color:#fff;padding:8px 16px;border:none;border-radius:4px;cursor:pointer;font-size:14px}}
        .btn:hover {{background:#0056b3}}
        .btn:disabled {{background:#6c757d;cursor:not-allowed}}
        .btn-primary {{background:#007bff}}
        .btn-secondary {{background:#6c757d}}
        .btn-secondary:hover {{background:#545b62}}
        .btn-danger {{background:#dc3545}}
        .btn-danger:hover {{background:#c82333}}
        .btn-icon {{padding:6px 10px}}
        .delete-confirm-text {{font-size:0.88rem;font-weight:700;color:#dc3545;margin-right:8px}}
        .empty-state {{text-align:center;padding:40px 20px;color:#6c757d}}
        .empty-state-icon {{font-size:3rem;margin-bottom:16px}}
        .empty-state-title {{font-size:1.1rem;font-weight:700;color:#212529;margin-bottom:8px}}
        .provider-form-wrap {{animation:fadeIn 0.25s ease;margin-top:4px}}
        .provider-form-card {{background:#fff;border:1px solid #dee2e6;border-radius:8px;padding:18px 20px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
        .form-card-title {{margin:0 0 18px;font-size:1rem;font-weight:700}}
        .form-group {{margin-bottom:15px}}
        .form-row {{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
        @media (max-width: 600px) {{.form-row {{grid-template-columns:1fr;gap:0}}}}
        label {{display:block;margin-bottom:5px;font-weight:600;color:#495057}}
        input[type="text"], input[type="password"] {{width:100%;padding:8px;border:1px solid #dee2e6;border-radius:4px;box-sizing:border-box}}
        .form-hint {{font-size:0.82rem;color:#6c757d;margin-top:4px}}
        .form-error {{font-size:0.82rem;color:#dc3545;margin-top:6px;min-height:1.2em;font-weight:600}}
        .form-error:empty {{display:none}}
        .required {{color:#dc3545;font-weight:700}}
        .form-actions {{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:4px}}
        .form-actions-right {{display:flex;align-items:center;gap:10px}}
        .add-provider-trigger {{margin-top:4px}}
        .test-result {{margin-top:12px;padding:10px;border-radius:4px;font-size:0.9em}}
        .test-result.success {{background:#d4edda;color:#155724}}
        .test-result.error {{background:#f8d7da;color:#721c24}}
        @keyframes fadeIn {{from {{opacity:0}} to {{opacity:1}}}}
        .spinner {{display:inline-block;width:12px;height:12px;border:2px solid #fff;border-radius:50%;border-top-color:transparent;animation:spin 0.6s linear infinite;vertical-align:middle;margin-right:6px}}
        .spinner {{display:none}}
        .btn.loading .spinner {{display:inline-block}}
        @keyframes spin {{to {{transform:rotate(360deg)}}}}
    </style>
</head>
<body>
<h1>xtream-vodfs - Sprint 3</h1>
<div class="status {'not-configured' if not is_configured else ''}">
    <strong>Status:</strong> {'' if is_configured else 'Not '}Configured
</div>
<div class="stats">
    <div class="stat">
        <div class="stat-value">{vod_categories}</div>
        <div class="stat-label">VOD Categories</div>
    </div>
    <div class="stat">
        <div class="stat-value">{vod_streams}</div>
        <div class="stat-label">VOD Streams</div>
    </div>
</div>
<div class="info">
    <h3>Xtream Providers</h3>
    <div class="section-header">
        <span class="provider-count" id="providerCount">Loading...</span>
    </div>
    <div id="providerList" class="provider-list">
        <div style="text-align:center;color:#6c757d;padding:20px;">Loading providers...</div>
    </div>
    <div id="providerEmpty" class="empty-state" style="display:none;">
        <div class="empty-state-icon">&#128225;</div>
        <div class="empty-state-title">No providers configured</div>
        <p>Add your first Xtream provider to start building the virtual filesystem.</p>
    </div>
    <div id="providerFormWrap" class="provider-form-wrap" style="display:none;">
        <div class="provider-form-card">
            <h3 class="form-card-title" id="formTitle">Add Provider</h3>
            <form id="providerForm" onsubmit="return false;" novalidate>
                <div class="form-group">
                    <label for="p_provider_name">Provider Name <span class="required">*</span></label>
                    <input id="p_provider_name" name="provider_name" type="text" placeholder="e.g. super-iptv" autocomplete="off">
                    <div class="form-hint">Used in filesystem paths. Lowercase letters, numbers, hyphens, underscores only.</div>
                    <div class="form-error" id="err_provider_name"></div>
                </div>
                <div class="form-group">
                    <label for="p_base_url">Server URL <span class="required">*</span></label>
                    <input id="p_base_url" name="base_url" type="text" placeholder="http://example.com:8080" autocomplete="off">
                    <div class="form-hint">Base URL without trailing slash.</div>
                    <div class="form-error" id="err_base_url"></div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label for="p_username">Username <span class="required">*</span></label>
                        <input id="p_username" name="username" type="text" autocomplete="off">
                        <div class="form-error" id="err_username"></div>
                    </div>
                    <div class="form-group">
                        <label for="p_password">Password <span class="required">*</span></label>
                        <input id="p_password" name="password" type="password" autocomplete="off">
                        <div class="form-error" id="err_password"></div>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" id="btnTestProvider" class="btn btn-secondary" onclick="testProviderConnection()">
                        <span class="spinner"></span>
                        <span class="btn-text">Test Connection</span>
                    </button>
                    <div class="form-actions-right">
                        <button type="button" class="btn btn-secondary" onclick="cancelProviderForm()">Cancel</button>
                        <button type="button" id="btnSaveProvider" class="btn btn-primary" onclick="saveProvider()">
                            <span class="spinner"></span>
                            <span class="btn-text">Save Provider</span>
                        </button>
                    </div>
                </div>
                <div id="providerTestResult"></div>
            </form>
        </div>
    </div>
    <div id="addProviderTrigger" class="add-provider-trigger">
        <button type="button" class="btn btn-primary" onclick="showAddProviderForm()">
            <span style="font-size:1.1em;line-height:1;">+</span>
            <span>Add Provider</span>
        </button>
    </div>
    <form method="post" action="/refresh" style="margin-top: 20px;">
        <button type="submit" class="btn btn-secondary" {'disabled' if not is_configured else ''}>Refresh VOD Cache</button>
    </form>
    <p style="margin-top: 15px; color: #666; font-size: 0.9em;">
        Last refresh: {last_refresh}
    </p>
</div>
<div class="links">
    <h3>Virtual Filesystem:</h3>
    <a href="/fs/">/fs/</a> - Virtual filesystem root
    <a href="/fs/movies/">/fs/movies/</a> - Movies (requires Xtream config)
    <a href="/fs/series/">/fs/series/</a> - Series (Sprint 4)
    <a href="/fs/samples/">/fs/samples/</a> - Sample files
</div>
<div class="info">
    <h3>Health Check:</h3>
    <p><a href="/healthz">/healthz</a> - JSON status</p>
</div>
<script>
var providers = [];
var editingProviderName = null;
var API = {{list: '/api/providers', create: '/api/providers', update: function(name) {{ return '/api/providers/' + encodeURIComponent(name); }}, remove: function(name) {{ return '/api/providers/' + encodeURIComponent(name); }}, test: null}};

function escapeHtml(s) {{ return s.replace(/&/g, '&amp;amp;').replace(/</g, '&amp;lt;').replace(/>/g, '&amp;gt;').replace(/"/g, '&amp;quot;').replace(/'/g, '&#x27;'); }}

function loadProviders() {{
    var xhr = new XMLHttpRequest();
    xhr.open('GET', API.list, true);
    xhr.onload = function() {{
        if (xhr.status >= 200 &amp;&amp; xhr.status < 300) {{
            try {{ providers = JSON.parse(xhr.responseText); }} catch(e) {{ providers = []; }}
            renderProviderList();
        }} else {{ document.getElementById('providerList').innerHTML = '<div style="text-align:center;color:#dc3545;padding:20px;">Failed to load providers</div>'; }}
    }};
    xhr.onerror = function() {{ document.getElementById('providerList').innerHTML = '<div style="text-align:center;color:#dc3545;padding:20px;">Failed to load providers</div>'; }};
    xhr.send();
}}

function renderProviderList() {{
    var listEl = document.getElementById('providerList');
    var emptyEl = document.getElementById('providerEmpty');
    var countEl = document.getElementById('providerCount');
    listEl.innerHTML = '';
    countEl.textContent = providers.length + ' configured';
    if (providers.length === 0) {{
        emptyEl.style.display = 'block';
        return;
    }}
    emptyEl.style.display = 'none';
    providers.forEach(function(p) {{
        var card = document.createElement('div');
        card.className = 'provider-card' + (p.enabled === false ? ' disabled' : '');
        if (editingProviderName === p.provider_name) card.classList.add('editing');
        var initials = (p.provider_name || '?').substring(0, 2);
        card.innerHTML =
            '<div class="provider-icon">' + escapeHtml(initials) + '</div>' +
            '<div class="provider-info">' +
                '<p class="provider-name">' +
                    '<span class="provider-status-dot ' + (p.enabled !== false ? 'active' : 'inactive') + '"></span> ' +
                    escapeHtml(p.provider_name) +
                '</p>' +
                '<p class="provider-url">' + escapeHtml(p.base_url || '') + '</p>' +
            '</div>' +
            '<div class="provider-meta">' +
                '<label class="toggle-switch" title="Enable or disable this provider">' +
                    '<input type="checkbox" ' + (p.enabled !== false ? 'checked' : '') + ' onchange="toggleProviderEnabled(\\'' + escapeHtml(p.provider_name) + '\\', this.checked)">' +
                    '<span class="toggle-slider"></span>' +
                    '<span>' + (p.enabled !== false ? 'Enabled' : 'Disabled') + '</span>' +
                '</label>' +
                '<div class="card-actions">' +
                    '<button type="button" class="btn btn-secondary btn-icon" title="Edit" onclick="editProvider(\\'' + escapeHtml(p.provider_name) + \\')">&#9998;</button>' +
                    '<button type="button" class="btn btn-danger btn-icon" title="Delete" onclick="promptDeleteProvider(this, \\'' + escapeHtml(p.provider_name) + \\')">&#128465;</button>' +
                '</div>' +
            '</div>';
        listEl.appendChild(card);
    }});
}}

function showAddProviderForm() {{
    editingProviderName = null;
    clearProviderForm();
    document.getElementById('formTitle').textContent = 'Add Provider';
    document.getElementById('providerFormWrap').style.display = 'block';
    document.getElementById('addProviderTrigger').style.display = 'none';
    clearResult('providerTestResult');
    renderProviderList();
}}

function editProvider(name) {{
    var p = providers.find(function(x) {{ return x.provider_name === name; }});
    if (!p) return;
    editingProviderName = name;
    document.getElementById('p_provider_name').value = p.provider_name || '';
    document.getElementById('p_base_url').value = p.base_url || '';
    document.getElementById('p_username').value = p.username || '';
    document.getElementById('p_password').value = p.password || '';
    document.getElementById('formTitle').textContent = 'Edit Provider';
    document.getElementById('providerFormWrap').style.display = 'block';
    document.getElementById('addProviderTrigger').style.display = 'none';
    clearAllProviderErrors();
    clearResult('providerTestResult');
    renderProviderList();
}}

function cancelProviderForm() {{
    document.getElementById('providerFormWrap').style.display = 'none';
    document.getElementById('addProviderTrigger').style.display = 'block';
    editingProviderName = null;
    renderProviderList();
}}

function clearProviderForm() {{
    document.getElementById('p_provider_name').value = '';
    document.getElementById('p_base_url').value = '';
    document.getElementById('p_username').value = '';
    document.getElementById('p_password').value = '';
    clearAllProviderErrors();
}}

function clearAllProviderErrors() {{
    ['err_provider_name','err_base_url','err_username','err_password'].forEach(function(id) {{ document.getElementById(id).textContent = ''; }});
}}

function validateProviderForm() {{
    clearAllProviderErrors();
    var valid = true;
    var name = document.getElementById('p_provider_name').value.trim();
    var url = document.getElementById('p_base_url').value.trim();
    var username = document.getElementById('p_username').value.trim();
    var password = document.getElementById('p_password').value;
    if (!name) {{ document.getElementById('err_provider_name').textContent = 'Provider name is required.'; valid = false; }}
    else if (!/^[a-z0-9_-]+$/.test(name)) {{ document.getElementById('err_provider_name').textContent = 'Use lowercase letters, numbers, hyphens, underscores only.'; valid = false; }}
    else if (!editingProviderName &amp;&amp; providers.some(function(p){{ return p.provider_name === name; }})) {{ document.getElementById('err_provider_name').textContent = 'A provider with this name already exists.'; valid = false; }}
    if (!url) {{ document.getElementById('err_base_url').textContent = 'Server URL is required.'; valid = false; }}
    else if (!/^https?:\\/\\/.+/.test(url)) {{ document.getElementById('err_base_url').textContent = 'Enter a valid URL starting with http:// or https://.'; valid = false; }}
    if (!username) {{ document.getElementById('err_username').textContent = 'Username is required.'; valid = false; }}
    if (!password) {{ document.getElementById('err_password').textContent = 'Password is required.'; valid = false; }}
    return valid ? {{ provider_name: name, base_url: url.replace(/\\/+$/, ''), username: username, password: password, enabled: true }} : null;
}}

function setButtonLoading(btnId, loading) {{
    var btn = document.getElementById(btnId);
    if (loading) btn.classList.add('loading');
    else btn.classList.remove('loading');
}}

function clearResult(id) {{ var el = document.getElementById(id); el.innerHTML = ''; el.className = ''; }}

function showResult(id, type, msg) {{ var el = document.getElementById(id); el.innerHTML = msg; el.className = 'test-result ' + type; }}

function saveProvider() {{
    var payload = validateProviderForm();
    if (!payload) return;
    setButtonLoading('btnSaveProvider', true);
    clearResult('providerTestResult');
    var xhr = new XMLHttpRequest();
    var isEdit = editingProviderName !== null;
    var url = isEdit ? API.update(editingProviderName) : API.create;
    xhr.open(isEdit ? 'PUT' : 'POST', url, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {{
        setButtonLoading('btnSaveProvider', false);
        if (xhr.status >= 200 &amp;&amp; xhr.status < 300) {{
            cancelProviderForm();
            loadProviders();
        }} else {{ var err = 'Save failed.'; try {{ var d = JSON.parse(xhr.responseText); if (d.detail) err = d.detail; }} catch(e) {{}} showResult('providerTestResult', 'error', err); }}
    }};
    xhr.onerror = function() {{ setButtonLoading('btnSaveProvider', false); showResult('providerTestResult', 'error', 'Request failed. Check server logs.'); }};
    xhr.send(JSON.stringify(payload));
}}

function promptDeleteProvider(btn, name) {{
    var card = btn.closest('.provider-card');
    if (card.classList.contains('confirm-delete')) {{ doDeleteProvider(name); }}
    else {{
        card.classList.add('confirm-delete');
        var actions = card.querySelector('.card-actions');
        actions.innerHTML =
            '<span class="delete-confirm-text">Delete?</span>' +
            '<button type="button" class="btn btn-danger btn-icon" onclick="doDeleteProvider(\\'' + escapeHtml(name) + \\')">Yes</button>' +
            '<button type="button" class="btn btn-secondary btn-icon" onclick="cancelDeleteProvider(this)">No</button>';
    }}
}}

function cancelDeleteProvider(btn) {{
    var card = btn.closest('.provider-card');
    card.classList.remove('confirm-delete');
    var actions = card.querySelector('.card-actions');
    actions.innerHTML =
        '<button type="button" class="btn btn-secondary btn-icon" title="Edit" onclick="editProvider(\\'' + escapeHtml(card.querySelector('.provider-name').textContent.trim()) + \\')">&#9998;</button>' +
        '<button type="button" class="btn btn-danger btn-icon" title="Delete" onclick="promptDeleteProvider(this, \\'' + escapeHtml(card.querySelector('.provider-name').textContent.trim()) + \\')">&#128465;</button>';
}}

function doDeleteProvider(name) {{
    var xhr = new XMLHttpRequest();
    xhr.open('DELETE', API.remove(name), true);
    xhr.onload = function() {{
        if (xhr.status >= 200 &amp;&amp; xhr.status < 300) loadProviders();
    }};
    xhr.send();
}}

function toggleProviderEnabled(name, enabled) {{
    var p = providers.find(function(x) {{ return x.provider_name === name; }});
    if (!p) return;
    p.enabled = enabled;
    var xhr = new XMLHttpRequest();
    xhr.open('PUT', API.update(name), true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {{ if (xhr.status >= 200 &amp;&amp; xhr.status < 300) loadProviders(); else loadProviders(); }};
    xhr.onerror = function() {{ loadProviders(); }};
    xhr.send(JSON.stringify(p));
}}

function testProviderConnection() {{
    clearResult('providerTestResult');
    var url = document.getElementById('p_base_url').value.trim().replace(/\\/+$/, '');
    var username = document.getElementById('p_username').value.trim();
    var password = document.getElementById('p_password').value;
    if (!url || !username || !password) {{ showResult('providerTestResult', 'error', 'Fill in URL, Username, and Password to test.'); return; }}
    setButtonLoading('btnTestProvider', true);
    var testUrl = url + '/player_api.php?username=' + encodeURIComponent(username) + '&amp;password=' + encodeURIComponent(password);
    var xhr = new XMLHttpRequest();
    xhr.open('GET', testUrl, true);
    xhr.timeout = 12000;
    xhr.onload = function() {{
        setButtonLoading('btnTestProvider', false);
        if (xhr.status >= 200 &amp;&amp; xhr.status < 300) {{
            try {{ var resp = JSON.parse(xhr.responseText); if (resp.user_info) {{ var status = resp.user_info.status || 'unknown'; var msg = 'Connected — status: ' + escapeHtml(status); if (resp.user_info.active_cons !== undefined) {{ msg += ', ' + resp.user_info.active_cons; if (resp.user_info.max_connections !== undefined) msg += '/' + resp.user_info.max_connections; msg += ' active streams'; }} showResult('providerTestResult', 'success', msg); }} else {{ showResult('providerTestResult', 'success', 'Connection successful!'); }} }} catch(e) {{ showResult('providerTestResult', 'success', 'Connection successful (non-JSON response).'); }}
        }} else if (xhr.status === 401) {{ showResult('providerTestResult', 'error', 'Authentication failed (401). Check credentials.'); }}
        else if (xhr.status === 404) {{ showResult('providerTestResult', 'error', 'API endpoint not found (404). Check base URL.'); }}
        else {{ showResult('providerTestResult', 'error', 'Connection failed (HTTP ' + xhr.status + ').'); }}
    }};
    xhr.onerror = function() {{ setButtonLoading('btnTestProvider', false); showResult('providerTestResult', 'error', 'Connection failed. Check URL and ensure server is reachable.'); }};
    xhr.ontimeout = function() {{ setButtonLoading('btnTestProvider', false); showResult('providerTestResult', 'error', 'Connection timed out after 12 seconds.'); }};
    xhr.send();
}}

document.addEventListener('DOMContentLoaded', function() {{ loadProviders(); }});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/config", response_class=HTMLResponse)
async def save_config_route(
    base_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    enable_vod: bool = Form(True),
    movies_include_all: bool = Form(True),
    movies_include_categories: bool = Form(True)
):
    """Save Xtream credentials and validate (legacy route for backward compatibility)"""
    global config

    try:
        # Validate credentials
        success, message = await validate_credentials(base_url, username, password)

        if success:
            # Update config
            if config is None:
                config = Config()

            # Migrate to providers list format
            provider_name = "default-provider"
            if not any(p.provider_name == provider_name for p in config.providers):
                # Create new provider with default name
                new_provider = XtreamCredentials(
                    provider_name=provider_name,
                    base_url=base_url,
                    username=username,
                    password=password,
                    enabled=True
                )
                config.providers.append(new_provider)
            else:
                # Update existing default provider
                for p in config.providers:
                    if p.provider_name == provider_name:
                        p.base_url = base_url
                        p.username = username
                        p.password = password
                        p.enabled = True
                        break

            config.library.enable_vod = enable_vod
            config.library.movies_include_all = movies_include_all
            config.library.movies_include_categories = movies_include_categories

            save_config(config)

            # Auto-refresh cache on successful config
            try:
                await refresh_vod_cache()
            except Exception as e:
                # Don't fail config save if cache refresh fails
                pass

        return RedirectResponse(url=f"/?{'success' if success else 'error'}", status_code=303)

    except Exception as e:
        # Sanitize error
        error_msg = str(e).replace(username, "USERNAME").replace(password, "PASSWORD")
        return RedirectResponse(url=f"/?error={error_msg}", status_code=303)


@app.post("/refresh", response_class=HTMLResponse)
async def refresh_route():
    """Refresh VOD cache"""
    try:
        await refresh_vod_cache()
        return RedirectResponse(url="/?success=refresh", status_code=303)
    except HTTPException as e:
        return RedirectResponse(url=f"/?error={e.detail}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/?error=Unexpected error", status_code=303)


@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    is_configured = config_manager.is_configured() if config_manager else False
    return {
        "status": "ok",
        "sprint": 3,
        "xtream_configured": is_configured,
        "vod_categories": len(cache.vod_categories) if cache else 0,
        "vod_streams": len(cache.vod_streams) if cache else 0
    }


# ===== Provider Management API =====

@app.get("/api/providers")
async def api_list_providers():
    """List all configured providers"""
    cfg = config_manager.load() if config_manager else Config()
    return [p.dict() for p in cfg.providers]


@app.post("/api/providers")
async def api_create_provider(provider: XtreamCredentials):
    """Create a new provider"""
    global config
    if not config:
        config = Config()

    # Check for duplicate name
    if any(p.provider_name == provider.provider_name for p in config.providers):
        raise HTTPException(status_code=409, detail="Provider name already exists")

    config.providers.append(provider)
    save_config(config)
    return provider


@app.put("/api/providers/{name}")
async def api_update_provider(name: str, provider: XtreamCredentials):
    """Update an existing provider"""
    global config
    if not config:
        config = Config()

    for i, p in enumerate(config.providers):
        if p.provider_name == name:
            config.providers[i] = provider
            save_config(config)
            return provider

    raise HTTPException(status_code=404, detail="Provider not found")


@app.delete("/api/providers/{name}")
async def api_delete_provider(name: str):
    """Delete a provider"""
    global config
    if not config:
        config = Config()

    config.providers = [p for p in config.providers if p.provider_name != name]
    save_config(config)
    return {"ok": True}


# ===== Filesystem Routes =====

@app.get("/fs/", response_class=HTMLResponse)
@app.get("/fs/{path:path}", response_class=HTMLResponse)
async def get_fs(request: Request, path: str = ""):
    """Handle GET requests for filesystem paths"""
    if tree is None:
        raise HTTPException(status_code=503, detail="Server not ready")

    if not path.startswith("/"):
        path = "/" + path
    node = tree.resolve(path)
    if node is None:
        raise HTTPException(status_code=404, detail="Not found")
    if node.is_directory():
        if not path.endswith("/") and path != "":
            return RedirectResponse(url=f"/fs{path.rstrip('/')}/", status_code=301)
        listing_html = httpfs.get_directory_listing(path, request=request) if httpfs else ""
        return HTMLResponse(content=listing_html)

    # Handle file requests
    if node.type == NodeType.XTREAM_VOD_FILE:
        # Rate limiting check
        client_ip = request.client.host if request.client else "unknown"
        rate_limiter = get_rate_limiter()
        if not rate_limiter.check(client_ip):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Stream from Xtream proxy
        upstream_url = node.upstream_url
        if not upstream_url:
            # Build URL from credentials
            if config and config_manager and config_manager.is_configured():
                upstream_url = f"{config.xtream.base_url}/movie/{config.xtream.username}/{config.xtream.password}/{node.stream_id}.{node.container_extension}"
            else:
                raise HTTPException(status_code=503, detail="Xtream credentials not configured")

        # Get Range header
        range_header = request.headers.get("range")

        # Return streaming response
        return await stream_vod_from_node(node, range_header=range_header)

    return httpfs.serve_file(path) if httpfs else Response(status_code=503, content="Server not ready")


@app.head("/fs/")
@app.head("/fs/{path:path}")
def head_fs(request: Request, path: str = ""):
    """Handle HEAD requests - lightweight, no upstream calls"""
    if tree is None:
        raise HTTPException(status_code=503, detail="Server not ready")

    if not path.startswith("/"):
        path = "/" + path
    node = tree.resolve(path)
    if node is None:
        raise HTTPException(status_code=404, detail="Not found")
    if node.is_directory():
        if httpfs:
            httpfs._track_scanner_access(request)
        return httpfs.head_directory(path, has_trailing_slash=path.endswith("/")) if httpfs else Response(status_code=503, content="Server not ready")
    else:
        # For Xtream VOD files, trigger lazy fetch if metadata missing
        if node.type == NodeType.XTREAM_VOD_FILE and node.provider_name and node.stream_id and warmer and metadata_cache:
            if not metadata_cache.has(node.provider_name, node.stream_id):
                # Fire-and-forget lazy fetch - does not block HEAD response
                asyncio.create_task(warmer.request_single(node.provider_name, node.stream_id))

        return httpfs.head_file(path) if httpfs else Response(status_code=503, content="Server not ready")


@app.get("/cdn/{path:path}")
async def get_cdn_redirect(path: str):
    """Redirect to direct CDN/upstream URL for a VOD file.

    Bypasses the local proxy and redirects directly to the upstream Xtream URL.
    Only works when enable_cdn_direct is True in config.
    HEAD requests remain local for metadata without hitting CDN.

    Note: This exposes the upstream URL (including credentials) to the client.
    Use with caution - only enable in trusted networks.
    """
    if tree is None:
        raise HTTPException(status_code=503, detail="Server not ready")

    if not config or not config.httpfs.enable_cdn_direct:
        raise HTTPException(status_code=404, detail="CDN direct mode is disabled")

    if not path.startswith("/"):
        path = "/" + path

    node = tree.resolve(path)
    if node is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not node.is_file() or node.type != NodeType.XTREAM_VOD_FILE:
        raise HTTPException(status_code=400, detail="CDN redirect only available for VOD files")

    if not node.upstream_url:
        raise HTTPException(status_code=503, detail="No upstream URL available")

    logger = __import__('logging').getLogger(__name__)
    logger.info(f"CDN redirect: {node.name} -> {node.upstream_url}")

    return RedirectResponse(
        url=node.upstream_url,
        status_code=302,
        headers={"X-Cdn-Url": node.upstream_url}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
